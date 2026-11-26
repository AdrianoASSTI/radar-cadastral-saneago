"""
Módulo Tarifa Social — inclusão proativa (Lei 14.898/2024).

Usa EXCLUSIVAMENTE a conexão `usr_api_social` e exige o perfil ASSISTENTE_SOCIAL.
Nenhum dado daqui é exposto a fiscais, analistas ou ao modelo de fiscalização.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from radar_comum import tarifa_social as ts

from ..db import conexao_social
from ..schemas import AlertaPatch
from ..servicos import indicadores as ind

router = APIRouter(prefix="/tarifa-social", tags=["tarifa social"])


@router.post("/processar", summary="Vincular famílias do CadÚnico às UCs e gerar alertas de elegibilidade")
async def processar(raio_m: int = Query(ts.RAIO_VINCULO_M, ge=10, le=500),
                    confianca_minima: float = Query(ts.CONFIANCA_MINIMA, ge=0, le=1),
                    conn=Depends(conexao_social)):
    return await ts.processar(conn, raio_m, confianca_minima)


@router.get("/alertas", summary="Alertas de famílias elegíveis fora da Tarifa Social")
async def alertas(status: str | None = None, limite: int = Query(100, le=1000), conn=Depends(conexao_social)):
    cur = await conn.execute("""
        SELECT a.id, a.uc_id, uc.matricula, uc.logradouro, uc.numero, b.nome AS bairro, b.faixa_renda::text,
               uc.categoria_atual::text, a.criterio::text, a.status::text, a.evidencia,
               a.criado_em, a.atualizado_em, a.responsavel, a.observacao, a.aplicado_em
        FROM social.alerta_tarifa_social a
        JOIN cadastro.unidade_consumidora uc ON uc.id = a.uc_id
        JOIN cadastro.bairro b ON b.id = uc.bairro_id
        WHERE (%(s)s::text IS NULL OR a.status::text = %(s)s)
        ORDER BY a.criado_em DESC LIMIT %(l)s""", {"s": status, "l": limite})
    return await cur.fetchall()


@router.patch("/alertas/{alerta_id}", summary="Atualizar o andamento do alerta (contato, inclusão, recusa)")
async def atualizar(alerta_id: UUID, dados: AlertaPatch, conn=Depends(conexao_social)):
    cur = await conn.execute("""
        UPDATE social.alerta_tarifa_social
           SET status = %s, observacao = coalesce(%s, observacao), atualizado_em = now(),
               responsavel = current_setting('radar.usuario', true)
         WHERE id = %s RETURNING id, status::text, atualizado_em""", (dados.status, dados.observacao, alerta_id))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, "Alerta não encontrado")
    return r


@router.post("/alertas/{alerta_id}/aplicar-inclusao",
             summary="Aplicar a inclusão na Residencial Social (alerta INCLUIDA; elegibilidade reconferida)")
async def aplicar_inclusao(alerta_id: UUID, conn=Depends(conexao_social)):
    cur = await conn.execute("SELECT * FROM social.aplicar_inclusao_tarifa_social(%s)", (alerta_id,))
    return {"aplicado": True, "historico": await cur.fetchone()}


@router.get("/cobertura", summary="I3 detalhado")
async def cobertura(conn=Depends(conexao_social)):
    return await ind.i3(conn)
