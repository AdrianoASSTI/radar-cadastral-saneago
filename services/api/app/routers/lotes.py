"""
Lotes de análise: seleciona UCs, registra o lote e publica uma mensagem por UC.

Ordem das operações (evita condição de corrida com os workers):
  1. INSERT do lote e COMMIT  → workers sempre encontram o lote ao consumir;
  2. publicação com publisher confirms;
  3. UPDATE do lote para EM_PROCESSAMENTO (ou FALHOU se o broker recusar).
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from radar_comum.mensagens import MensagemColeta

from ..db import conexao
from ..schemas import LoteIn
from ..seguranca import LEITURA_GESTAO, OPERACAO, Usuario, exigir

router = APIRouter(prefix="/lotes", tags=["lotes de análise"])


@router.post("", status_code=202, summary="Criar lote e enviar UCs para coleta/análise (assíncrono)")
async def criar_lote(dados: LoteIn, request: Request, u: Usuario = Depends(exigir(*OPERACAO)),
                     conn=Depends(conexao)):
    mens = request.app.state.mensageria
    if not mens.conectado:
        raise HTTPException(503, "RabbitMQ indisponível; tente novamente em instantes")

    cur = await conn.execute("""
        SELECT uc.id, uc.matricula, ST_Y(uc.geom) AS lat, ST_X(uc.geom) AS lon,
               uc.logradouro || coalesce(', ' || uc.numero, '') || ' - ' || b.nome AS endereco
        FROM cadastro.unidade_consumidora uc JOIN cadastro.bairro b ON b.id = uc.bairro_id
        WHERE uc.ligacao_ativa
          AND (%(ids)s::bigint[] IS NULL OR uc.id = ANY(%(ids)s))
          AND (%(bairros)s::int[] IS NULL OR uc.bairro_id = ANY(%(bairros)s))
          AND uc.categoria_atual::text = ANY(%(cats)s)
        ORDER BY uc.id
        LIMIT %(lim)s""",
        {"ids": dados.uc_ids, "bairros": dados.bairro_ids, "cats": list(dados.categorias), "lim": dados.limite})
    ucs = await cur.fetchall()
    if not ucs:
        raise HTTPException(422, "Nenhuma UC atende aos filtros")

    cur = await conn.execute("""
        INSERT INTO analise.lote_processamento (status, modo, total_ucs, parametros, solicitado_por)
        VALUES ('PENDENTE', %s, %s, %s::jsonb, %s) RETURNING id""",
        (dados.modo, len(ucs), json.dumps(dados.model_dump()), u.login))
    lote_id = (await cur.fetchone())["id"]
    await conn.commit()

    msgs = [MensagemColeta(lote_id=lote_id, uc_id=r["id"], matricula=r["matricula"], latitude=r["lat"],
                           longitude=r["lon"], endereco=r["endereco"], modo=dados.modo) for r in ucs]
    try:
        enviados = await mens.publicar_coleta(msgs)
    except Exception as e:  # noqa: BLE001
        await conn.execute("UPDATE analise.lote_processamento SET status = 'FALHOU' WHERE id = %s", (lote_id,))
        raise HTTPException(503, f"Falha ao publicar no broker: {e}") from e
    await conn.execute("""UPDATE analise.lote_processamento SET status = 'EM_PROCESSAMENTO', iniciado_em = now()
                          WHERE id = %s""", (lote_id,))
    return {"lote_id": lote_id, "ucs": len(ucs), "mensagens_publicadas": enviados, "modo": dados.modo,
            "fila": "radar.coleta.seq" if dados.modo == "SEQUENCIAL" else "radar.coleta"}


@router.get("", summary="Listar lotes")
async def listar(limite: int = Query(50, le=500), _: Usuario = Depends(exigir(*LEITURA_GESTAO)),
                 conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT id, criado_em, iniciado_em, concluido_em, status::text, modo::text, n_workers,
               total_ucs, processadas, falhas, solicitado_por,
               round(100.0 * (processadas + falhas) / nullif(total_ucs, 0), 1) AS progresso_pct,
               extract(epoch FROM (coalesce(concluido_em, now()) - iniciado_em)) AS duracao_s,
               parametros->>'etiqueta' AS etiqueta
        FROM analise.lote_processamento ORDER BY criado_em DESC LIMIT %s""", (limite,))
    return await cur.fetchall()


@router.get("/{lote_id}", summary="Situação do lote")
async def obter(lote_id: UUID, request: Request, _: Usuario = Depends(exigir(*LEITURA_GESTAO)),
                conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT *, round(100.0 * (processadas + falhas) / nullif(total_ucs, 0), 1) AS progresso_pct,
               extract(epoch FROM (coalesce(concluido_em, now()) - iniciado_em)) AS duracao_s,
               (processadas + falhas) / nullif(extract(epoch FROM (coalesce(concluido_em, now()) - iniciado_em)), 0)
                 AS vazao_ucs_por_s
        FROM analise.lote_processamento WHERE id = %s""", (lote_id,))
    lote = await cur.fetchone()
    if not lote:
        raise HTTPException(404, "Lote não encontrado")
    lote["telemetria_broker"] = request.app.state.mensageria.resumo_telemetria(str(lote_id))
    return lote
