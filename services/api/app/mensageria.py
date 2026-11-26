"""
Integração da API com o RabbitMQ.

* Publicador: envia uma mensagem COLETAR_UC por UC do lote (persistente, com
  confirmação do broker — publisher confirms), na fila paralela ou sequencial.
* Monitor de resultados: consome `radar.resultados` e mantém telemetria em
  memória por lote (vazão, latência), exposta em GET /lotes/{id}/telemetria.

A API sobe mesmo sem o broker (modo degradado); a conexão é refeita sozinha
(`connect_robust`) e /saude informa o estado.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import aio_pika
from radar_comum import topologia
from radar_comum.mensagens import MensagemColeta, MensagemResultado

log = logging.getLogger("radar.mensageria")


class Mensageria:
    def __init__(self, url: str):
        self.url = url
        self.conexao: aio_pika.abc.AbstractRobustConnection | None = None
        self.canal = None
        self.exchange = None
        self.telemetria: dict[str, dict] = defaultdict(
            lambda: {"sucessos": 0, "falhas": 0, "tempo_ms_total": 0, "workers": set(),
                     "primeira": None, "ultima": None})
        self._tarefa_conexao: asyncio.Task | None = None

    @property
    def conectado(self) -> bool:
        return bool(self.conexao and not self.conexao.is_closed and self.exchange)

    async def iniciar(self) -> None:
        """Tenta conectar em segundo plano, sem bloquear a subida da API."""
        self._tarefa_conexao = asyncio.create_task(self._conectar_com_retentativa())

    async def _conectar_com_retentativa(self) -> None:
        espera = 2
        while True:
            try:
                await self._conectar()
                return
            except Exception as e:  # noqa: BLE001
                log.warning("RabbitMQ indisponível (%s); nova tentativa em %ss", e.__class__.__name__, espera)
                await asyncio.sleep(espera)
                espera = min(espera * 2, 30)

    async def _conectar(self) -> None:
        self.conexao = await aio_pika.connect_robust(self.url)
        self.canal = await self.conexao.channel(publisher_confirms=True)
        await self.canal.set_qos(prefetch_count=50)
        filas = await topologia.declarar_topologia(self.canal)
        self.exchange = await self.canal.get_exchange(topologia.EXCHANGE)
        await filas[topologia.FILA_RESULTADOS].consume(self._ao_receber_resultado)
        log.info("RabbitMQ conectado; topologia declarada")

    async def encerrar(self) -> None:
        if self._tarefa_conexao and not self._tarefa_conexao.done():
            self._tarefa_conexao.cancel()
        if self.conexao:
            await self.conexao.close()

    async def publicar_coleta(self, msgs: list[MensagemColeta]) -> int:
        if not self.conectado:
            raise RuntimeError("RabbitMQ indisponível")
        enviados = 0
        for m in msgs:
            await self.exchange.publish(
                aio_pika.Message(
                    body=m.model_dump_json().encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=str(m.mensagem_id),
                    correlation_id=str(m.lote_id),
                    type=m.tipo,
                    headers={"versao": m.versao, "modo": m.modo},
                ),
                routing_key=topologia.rk_coleta(m.modo),
            )
            enviados += 1
        return enviados

    async def contagem_filas(self) -> dict[str, int]:
        if not self.conectado:
            return {}
        out = {}
        for nome in topologia.FILAS:
            q = await self.canal.declare_queue(nome, passive=True)
            out[nome] = q.declaration_result.message_count
        return out

    async def _ao_receber_resultado(self, msg: aio_pika.abc.AbstractIncomingMessage) -> None:
        async with msg.process(requeue=False):
            try:
                r = MensagemResultado.model_validate(json.loads(msg.body))
            except Exception:  # noqa: BLE001 — mensagem malformada vai para a DLQ
                raise
            t = self.telemetria[str(r.lote_id)]
            t["sucessos" if r.sucesso else "falhas"] += 1
            t["tempo_ms_total"] += r.tempo_ms or 0
            if r.worker_id:
                t["workers"].add(r.worker_id)
            agora = datetime.now(timezone.utc)
            t["primeira"] = t["primeira"] or agora
            t["ultima"] = agora

    def resumo_telemetria(self, lote_id: str) -> dict:
        t = self.telemetria.get(lote_id)
        if not t:
            return {"mensagens": 0}
        n = t["sucessos"] + t["falhas"]
        dur = (t["ultima"] - t["primeira"]).total_seconds() if t["primeira"] else 0
        return {
            "mensagens": n, "sucessos": t["sucessos"], "falhas": t["falhas"],
            "workers_distintos": len(t["workers"]),
            "latencia_media_ms": round(t["tempo_ms_total"] / n, 1) if n else None,
            "vazao_ucs_por_s": round(n / dur, 3) if dur > 0 else None,
            "janela_s": round(dur, 3),
        }
