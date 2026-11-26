"""
Pools de conexão PostgreSQL.

Dois pools, dois papéis de banco (segregação por finalidade, LGPD):
  * `pool`        → usr_api        (fiscalização; SEM acesso ao schema social)
  * `pool_social` → usr_api_social (Tarifa Social; único com acesso ao CadÚnico)

Cada requisição roda numa transação e registra o usuário da aplicação em
`radar.usuario` (lido pelos triggers de auditoria do banco).
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Request
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
from .seguranca import SOCIAL, Usuario, exigir, usuario_atual


def criar_pools() -> tuple[AsyncConnectionPool, AsyncConnectionPool]:
    s = settings()
    kw = {"row_factory": dict_row}
    pool = AsyncConnectionPool(s.database_url, min_size=s.pool_min, max_size=s.pool_max,
                               kwargs=kw, open=False, name="radar_api")
    pool_social = AsyncConnectionPool(s.database_url_social, min_size=1, max_size=max(2, s.pool_max // 4),
                                      kwargs=kw, open=False, name="radar_api_social")
    return pool, pool_social


async def _conexao(pool: AsyncConnectionPool, usuario: Usuario) -> AsyncIterator:
    async with pool.connection() as conn:          # commit no sucesso, rollback na exceção
        await conn.execute("SELECT set_config('radar.usuario', %s, true)", (usuario.login,))
        yield conn


async def conexao(request: Request, usuario: Usuario = Depends(usuario_atual)) -> AsyncIterator:
    async for c in _conexao(request.app.state.pool, usuario):
        yield c


async def conexao_social(request: Request, usuario: Usuario = Depends(exigir(*SOCIAL))) -> AsyncIterator:
    """Conexão do módulo Tarifa Social — exige perfil ASSISTENTE_SOCIAL (falha segura)."""
    async for c in _conexao(request.app.state.pool_social, usuario):
        yield c
