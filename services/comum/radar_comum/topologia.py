"""
Topologia RabbitMQ do Radar Cadastral (declaração idempotente por todos os serviços).

  exchange `radar` (direct, durável)
    ├─ radar.coleta        rk=coleta         modo PARALELO   (N coletores competindo)
    ├─ radar.coleta.seq    rk=coleta.seq     modo SEQUENCIAL (x-single-active-consumer)
    ├─ radar.analise       rk=analise        modo PARALELO   (M workers de IA competindo)
    ├─ radar.analise.seq   rk=analise.seq    modo SEQUENCIAL (x-single-active-consumer)
    └─ radar.resultados    rk=resultado      progresso/telemetria (consumido pela API)

  exchange `radar.dlx` (direct) → filas `<fila>.dlq` para mensagens rejeitadas
  após o número máximo de tentativas (análise forense, sem perda silenciosa).

O modo SEQUENCIAL usa `x-single-active-consumer`: mesmo com vários workers no
ar, o broker entrega a fila a apenas UM consumidor por vez. Assim o baseline
sequencial do experimento de speedup roda na MESMA infraestrutura do paralelo,
isolando a variável "grau de paralelismo" (docs/04).
"""

from __future__ import annotations

import os

EXCHANGE = "radar"
EXCHANGE_DLX = "radar.dlx"

FILA_COLETA = os.getenv("FILA_COLETA", "radar.coleta")
FILA_ANALISE = os.getenv("FILA_ANALISE", "radar.analise")
FILA_RESULTADOS = os.getenv("FILA_RESULTADOS", "radar.resultados")

# routing keys
RK_COLETA, RK_COLETA_SEQ = "coleta", "coleta.seq"
RK_ANALISE, RK_ANALISE_SEQ = "analise", "analise.seq"
RK_RESULTADO = "resultado"

MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "3"))

FILAS: dict[str, dict] = {
    FILA_COLETA: {"rk": RK_COLETA, "args": {}},
    f"{FILA_COLETA}.seq": {"rk": RK_COLETA_SEQ, "args": {"x-single-active-consumer": True}},
    FILA_ANALISE: {"rk": RK_ANALISE, "args": {}},
    f"{FILA_ANALISE}.seq": {"rk": RK_ANALISE_SEQ, "args": {"x-single-active-consumer": True}},
    FILA_RESULTADOS: {"rk": RK_RESULTADO, "args": {}},
}


def rk_coleta(modo: str) -> str:
    return RK_COLETA_SEQ if modo == "SEQUENCIAL" else RK_COLETA


def rk_analise(modo: str) -> str:
    return RK_ANALISE_SEQ if modo == "SEQUENCIAL" else RK_ANALISE


async def declarar_topologia(canal) -> dict:
    """Declara exchanges, filas, DLQs e bindings. Retorna {nome_fila: objeto_fila}."""
    import aio_pika  # import tardio: o pacote comum não exige aio-pika para usar tarifas

    ex = await canal.declare_exchange(EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
    dlx = await canal.declare_exchange(EXCHANGE_DLX, aio_pika.ExchangeType.DIRECT, durable=True)
    filas = {}
    for nome, cfg in FILAS.items():
        dlq = await canal.declare_queue(f"{nome}.dlq", durable=True)
        await dlq.bind(dlx, routing_key=nome)
        args = {"x-dead-letter-exchange": EXCHANGE_DLX, "x-dead-letter-routing-key": nome, **cfg["args"]}
        q = await canal.declare_queue(nome, durable=True, arguments=args)
        await q.bind(ex, routing_key=cfg["rk"])
        filas[nome] = q
    return filas
