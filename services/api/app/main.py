"""
Radar Cadastral SANEAGO — API REST (FastAPI).

Documentação interativa: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import errors as pgerr

from .config import settings
from .db import criar_pools
from .mensageria import Mensageria
from .routers import basicos, fiscalizacao, indicadores, lotes, tarifa_social, ucs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("radar.api")

DESCRICAO = """
Sistema de apoio à atualização cadastral de imóveis (SANEAGO).

**Regra de ouro:** a IA nunca altera a categoria tarifária. Ela gera uma fila priorizada
por Ganho Esperado; a mudança exige laudo de vistoria e decisão de um supervisor
(garantida pelo banco de dados). O módulo Tarifa Social usa conexão e perfil próprios.

Usuários de demonstração: `analista`, `fiscal`, `supervisor`, `social`, `gestor`
(senha = login + `123`). Use o botão **Authorize**.
"""


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    app.state.pool, app.state.pool_social = criar_pools()
    await app.state.pool.open(wait=False)
    await app.state.pool_social.open(wait=False)
    app.state.mensageria = Mensageria(settings().rabbitmq_url)
    await app.state.mensageria.iniciar()
    log.info("API iniciada")
    yield
    await app.state.mensageria.encerrar()
    await app.state.pool.close()
    await app.state.pool_social.close()


app = FastAPI(title="Radar Cadastral SANEAGO — API", version="0.2.0", description=DESCRICAO,
              lifespan=ciclo_de_vida)
app.add_middleware(CORSMiddleware, allow_origins=settings().origens_cors, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

for r in (basicos.router, ucs.router, lotes.router, fiscalizacao.router, indicadores.router, tarifa_social.router):
    app.include_router(r)


# ----------------------------------------------------- erros do banco → HTTP
MAPA_ERROS = [
    (pgerr.InsufficientPrivilege, 403),   # inclui o bloqueio da garantia G1
    (pgerr.UniqueViolation, 409),
    (pgerr.CheckViolation, 422),
    (pgerr.ForeignKeyViolation, 422),
    (pgerr.InvalidTextRepresentation, 422),
    (pgerr.RaiseException, 409),          # regras de negócio em funções PL/pgSQL
]


@app.exception_handler(psycopg.Error)
async def erro_banco(_: Request, e: psycopg.Error):
    status = next((s for cls, s in MAPA_ERROS if isinstance(e, cls)), 500)
    diag = getattr(e, "diag", None)
    msg = (diag.message_primary if diag and diag.message_primary else str(e)).strip()
    if status == 500:
        log.exception("Erro de banco não mapeado")
    return JSONResponse(status_code=status, content={"detail": msg, "constraint": getattr(diag, "constraint_name", None)})


@app.get("/", include_in_schema=False)
async def raiz():
    return {"servico": "Radar Cadastral SANEAGO — API", "docs": "/docs", "saude": "/saude"}
