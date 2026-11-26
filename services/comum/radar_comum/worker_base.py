"""
Base comum dos workers (coletor e IA): consumo AMQP com confirmação manual,
retentativas limitadas e dead-letter.

Semântica de entrega: at-least-once. Cada worker consome a fila paralela E a fila
sequencial (.seq, x-single-active-consumer) da sua etapa. Uma mensagem só é
confirmada (ack) depois que o efeito foi gravado no banco. Em erro, é republicada
com `tentativa + 1`; após MAX_TENTATIVAS vai para a DLQ e a UC é contada como falha
do lote (sem perda silenciosa).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket

import aio_pika

from . import topologia

log = logging.getLogger("radar.worker")


class WorkerBase:
    nome = "worker"
    filas: tuple[str, ...] = ()

    def __init__(self):
        self.worker_id = f"{self.nome}@{socket.gethostname()}:{os.getpid()}"
        self.prefetch = int(os.getenv("PREFETCH_COUNT", "1"))
        self.url = os.getenv("RABBITMQ_URL", "amqp://radar:radar_dev@localhost:5672/radar")
        self.conexao = None
        self.canal = None
        self.exchange = None
        self._parar = asyncio.Event()

    # ------------------------------------------------------------ a implementar
    async def preparar(self) -> None:
        """Abre pools, carrega modelos etc."""

    async def processar(self, dados: dict) -> None:
        raise NotImplementedError

    async def ao_falhar(self, dados: dict, erro: str) -> None:
        """Chamado quando a mensagem esgota as tentativas."""

    async def encerrar(self) -> None:
        pass

    # ------------------------------------------------------------ infraestrutura
    async def publicar(self, routing_key: str, corpo: bytes, tipo: str, message_id: str | None = None,
                       correlation_id: str | None = None) -> None:
        await self.exchange.publish(
            aio_pika.Message(body=corpo, content_type="application/json", type=tipo,
                             delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                             message_id=message_id, correlation_id=correlation_id),
            routing_key=routing_key)

    async def _ao_receber(self, msg: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            dados = json.loads(msg.body)
        except json.JSONDecodeError:
            log.error("mensagem inválida descartada para a DLQ")
            await msg.reject(requeue=False)
            return
        try:
            await self.processar(dados)
            await msg.ack()
        except Exception as e:  # noqa: BLE001
            tentativa = int(dados.get("tentativa", 0)) + 1
            if tentativa < topologia.MAX_TENTATIVAS:
                log.warning("UC %s falhou (tentativa %d): %s", dados.get("uc_id"), tentativa, e)
                dados["tentativa"] = tentativa
                await self.publicar(msg.routing_key, json.dumps(dados, default=str).encode(),
                                    msg.type or "", msg.message_id, msg.correlation_id)
                await msg.ack()
            else:
                log.exception("UC %s esgotou as tentativas; enviada à DLQ", dados.get("uc_id"))
                try:
                    await self.ao_falhar(dados, f"{e.__class__.__name__}: {e}")
                finally:
                    await msg.reject(requeue=False)

    async def _conectar(self) -> None:
        espera = 2
        while True:
            try:
                self.conexao = await aio_pika.connect_robust(self.url)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("RabbitMQ indisponível (%s); nova tentativa em %ss", e.__class__.__name__, espera)
                await asyncio.sleep(espera)
                espera = min(espera * 2, 30)
        self.canal = await self.conexao.channel(publisher_confirms=True)
        await self.canal.set_qos(prefetch_count=self.prefetch)
        filas = await topologia.declarar_topologia(self.canal)
        self.exchange = await self.canal.get_exchange(topologia.EXCHANGE)
        for nome in self.filas:
            await filas[nome].consume(self._ao_receber)
        log.info("%s consumindo %s (prefetch=%d)", self.worker_id, ", ".join(self.filas), self.prefetch)

    async def executar(self) -> None:
        logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, self._parar.set)
            except NotImplementedError:
                pass
        await self.preparar()
        await self._conectar()
        await self._parar.wait()
        log.info("encerrando %s", self.worker_id)
        await self.conexao.close()
        await self.encerrar()
