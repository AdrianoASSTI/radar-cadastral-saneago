"""Indicadores I1–I5 (cálculo dinâmico) e painel executivo consolidado."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request

from ..db import conexao
from ..seguranca import LEITURA_GESTAO, Usuario, exigir
from ..servicos import indicadores as ind

router = APIRouter(prefix="/indicadores", tags=["indicadores"])
LEITORES = (*LEITURA_GESTAO,)


async def _i3(request: Request, usuario: Usuario) -> dict:
    # Conexão do papel radar_social usada EXCLUSIVAMENTE para contagens agregadas (sem dado pessoal).
    async with request.app.state.pool_social.connection() as c:
        await c.execute("SELECT set_config('radar.usuario', %s, true)", (usuario.login,))
        return await ind.i3(c)


@router.get("", summary="Painel executivo: I1 a I5")
async def todos(request: Request, inicio: datetime | None = None, fim: datetime | None = None,
                fracao_k: float = Query(0.10, gt=0, le=1),
                u: Usuario = Depends(exigir(*LEITORES)), conn=Depends(conexao)):
    return {
        "gerado_em": datetime.now(timezone.utc),
        "I1": await ind.i1(conn, inicio, fim),
        "I2": await ind.i2(conn, inicio, fim),
        "I3": await _i3(request, u),
        "I4": await ind.i4(conn, inicio, fim, fracao_k),
        "I5": await ind.i5(conn, inicio, fim, fracao_k),
    }


@router.get("/i1", summary="I1 — taxa de acerto (Radar × método atual)")
async def i1(inicio: datetime | None = None, fim: datetime | None = None,
             _: Usuario = Depends(exigir(*LEITORES)), conn=Depends(conexao)):
    return await ind.i1(conn, inicio, fim)


@router.get("/i2", summary="I2 — receita recuperada por real investido")
async def i2(inicio: datetime | None = None, fim: datetime | None = None, incluir_implantacao: bool = True,
             _: Usuario = Depends(exigir(*LEITORES)), conn=Depends(conexao)):
    return await ind.i2(conn, inicio, fim, incluir_implantacao)


@router.get("/i3", summary="I3 — cobertura da Tarifa Social (agregado)")
async def i3(request: Request, u: Usuario = Depends(exigir(*LEITORES, "ASSISTENTE_SOCIAL"))):
    return await _i3(request, u)


@router.get("/i4", summary="I4 — precisão@k e recall")
async def i4(inicio: datetime | None = None, fim: datetime | None = None,
             fracao_k: float = Query(0.10, gt=0, le=1), limiar: float = Query(0.5, ge=0, le=1),
             _: Usuario = Depends(exigir(*LEITORES)), conn=Depends(conexao)):
    return await ind.i4(conn, inicio, fim, fracao_k, limiar)


@router.get("/i5", summary="I5 — equidade territorial (FDR por faixa de renda + paridade de seleção)")
async def i5(inicio: datetime | None = None, fim: datetime | None = None,
             fracao_k: float = Query(0.10, gt=0, le=1), amostra_minima: int = Query(5, ge=1),
             _: Usuario = Depends(exigir(*LEITORES)), conn=Depends(conexao)):
    return await ind.i5(conn, inicio, fim, fracao_k, amostra_minima)
