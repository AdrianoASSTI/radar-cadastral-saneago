"""
Fila priorizada, ordens de vistoria e laudos (Human-in-the-Loop).

Fluxo:
  1. ANALISTA consulta a fila (ordenada por Ganho Esperado) e gera ordens RADAR;
     também gera ordens de grupo controle (METODO_ATUAL) e amostra aleatória (recall).
  2. FISCAL registra o laudo em campo. O fiscal NÃO decide a reclassificação:
     irregularidade confirmada vai para ENCAMINHAR_ANALISE.
  3. SUPERVISOR (pessoa diferente do fiscal) decide RECLASSIFICAR ou MANTER,
     o que registra a notificação prévia e abre o prazo de contestação.
  4. SUPERVISOR aplica a reclassificação após o prazo (função do banco, garantia G1).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb

from ..db import conexao
from ..schemas import DecisaoIn, FaixaRenda, LaudoIn, OrdemPatch, OrdensControleIn, OrdensRadarIn
from ..seguranca import CAMPO, LEITURA_GESTAO, OPERACAO, Usuario, exigir
from .ucs import links_externos

router = APIRouter(tags=["fiscalização"])


# ------------------------------------------------------------------------ fila
@router.get("/fila", summary="Fila priorizada de vistoria (ordenada por Ganho Esperado)")
async def fila(limite: int = Query(50, le=1000), offset: int = 0,
               probabilidade_minima: float = Query(0.0, ge=0, le=1),
               faixa_renda: FaixaRenda | None = None, bairro: str | None = None,
               categoria_sugerida: str | None = None,
               _: Usuario = Depends(exigir(*LEITURA_GESTAO)), conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT *, count(*) OVER () AS total FROM fiscalizacao.vw_fila_priorizada
        WHERE probabilidade_irregularidade >= %(p)s
          AND (%(f)s::text IS NULL OR faixa_renda::text = %(f)s)
          AND (%(b)s::text IS NULL OR bairro = %(b)s)
          AND (%(c)s::text IS NULL OR categoria_sugerida::text = %(c)s)
        ORDER BY posicao LIMIT %(l)s OFFSET %(o)s""",
        {"p": probabilidade_minima, "f": faixa_renda, "b": bairro, "c": categoria_sugerida,
         "l": limite, "o": offset})
    linhas = await cur.fetchall()
    for r in linhas:
        r["links"] = links_externos(r["latitude"], r["longitude"])
    return {"total": linhas[0]["total"] if linhas else 0,
            "itens": [{k: v for k, v in r.items() if k != "total"} for r in linhas]}


@router.post("/fila/ordens", status_code=201, summary="Gerar ordens de vistoria a partir da fila (origem RADAR)")
async def gerar_ordens_radar(dados: OrdensRadarIn, u: Usuario = Depends(exigir(*OPERACAO)),
                             conn=Depends(conexao)):
    if not dados.quantidade and not dados.resultado_analise_ids:
        raise HTTPException(422, "Informe `quantidade` ou `resultado_analise_ids`")
    cur = await conn.execute("""
        INSERT INTO fiscalizacao.ordem_vistoria
          (uc_id, resultado_analise_id, origem, posicao_ranking, fiscal_matricula, criada_por)
        SELECT f.uc_id, f.resultado_analise_id, 'RADAR', f.posicao, %(fiscal)s, %(por)s
        FROM fiscalizacao.vw_fila_priorizada f
        WHERE f.probabilidade_irregularidade >= %(p)s
          AND (%(ids)s::uuid[] IS NULL OR f.resultado_analise_id = ANY(%(ids)s))
        ORDER BY f.posicao
        LIMIT %(n)s
        ON CONFLICT DO NOTHING
        RETURNING id, uc_id, posicao_ranking""",
        {"fiscal": dados.fiscal_matricula, "por": u.login, "p": dados.probabilidade_minima,
         "ids": dados.resultado_analise_ids, "n": dados.quantidade})
    criadas = await cur.fetchall()
    return {"ordens_criadas": len(criadas), "ordens": criadas}


@router.post("/ordens/controle", status_code=201,
             summary="Gerar ordens de grupo controle (método atual) ou amostra aleatória (recall)")
async def gerar_ordens_controle(dados: OrdensControleIn, u: Usuario = Depends(exigir(*OPERACAO)),
                                conn=Depends(conexao)):
    cur = await conn.execute("""
        INSERT INTO fiscalizacao.ordem_vistoria (uc_id, origem, fiscal_matricula, criada_por)
        SELECT uc.id, %(origem)s, %(fiscal)s, %(por)s
        FROM cadastro.unidade_consumidora uc
        WHERE uc.ligacao_ativa AND uc.categoria_atual IN ('RESIDENCIAL_NORMAL','RESIDENCIAL_SOCIAL')
          AND NOT EXISTS (SELECT 1 FROM fiscalizacao.ordem_vistoria o
                          WHERE o.uc_id = uc.id AND o.status IN ('AGUARDANDO','EM_CAMPO'))
        ORDER BY md5(uc.id::text || %(semente)s::text)          -- sorteio reprodutível
        LIMIT %(n)s
        ON CONFLICT DO NOTHING
        RETURNING id, uc_id""",
        {"origem": dados.origem, "fiscal": dados.fiscal_matricula, "por": u.login,
         "semente": dados.semente, "n": dados.quantidade})
    criadas = await cur.fetchall()
    return {"origem": dados.origem, "semente": dados.semente, "ordens_criadas": len(criadas), "ordens": criadas}


# ------------------------------------------------------------------------ ordens
@router.get("/ordens", summary="Listar ordens (o fiscal vê as suas e as não atribuídas)")
async def listar_ordens(status: str | None = None, origem: str | None = None,
                        limite: int = Query(100, le=1000),
                        u: Usuario = Depends(exigir(*LEITURA_GESTAO, "FISCAL")), conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT o.id, o.uc_id, uc.matricula, uc.logradouro, uc.numero, b.nome AS bairro,
               ST_Y(uc.geom) AS latitude, ST_X(uc.geom) AS longitude,
               o.origem::text, o.status::text, o.posicao_ranking, o.fiscal_matricula, o.criada_em,
               ra.probabilidade_irregularidade, ra.categoria_sugerida::text, ra.ganho_esperado_anual,
               l.id AS laudo_id, l.resultado::text, l.decisao::text
        FROM fiscalizacao.ordem_vistoria o
        JOIN cadastro.unidade_consumidora uc ON uc.id = o.uc_id
        JOIN cadastro.bairro b ON b.id = uc.bairro_id
        LEFT JOIN analise.resultado_analise ra ON ra.id = o.resultado_analise_id
        LEFT JOIN fiscalizacao.laudo_vistoria l ON l.ordem_id = o.id
        WHERE (%(s)s::text IS NULL OR o.status::text = %(s)s)
          AND (%(o)s::text IS NULL OR o.origem::text = %(o)s)
          AND (%(fiscal)s::text IS NULL OR o.fiscal_matricula IS NULL OR o.fiscal_matricula = %(fiscal)s)
        ORDER BY o.criada_em DESC, o.posicao_ranking NULLS LAST LIMIT %(l)s""",
        {"s": status, "o": origem, "l": limite, "fiscal": u.matricula if u.perfil == "FISCAL" else None})
    return await cur.fetchall()


@router.patch("/ordens/{ordem_id}", summary="Atribuir fiscal / mudar status da ordem")
async def atualizar_ordem(ordem_id: UUID, dados: OrdemPatch, u: Usuario = Depends(exigir(*OPERACAO, "FISCAL")),
                          conn=Depends(conexao)):
    if u.perfil == "FISCAL" and dados.fiscal_matricula not in (None, u.matricula):
        raise HTTPException(403, "Fiscal só pode atribuir a ordem a si mesmo")
    cur = await conn.execute("""
        UPDATE fiscalizacao.ordem_vistoria
           SET fiscal_matricula = coalesce(%s, fiscal_matricula), status = coalesce(%s::fiscalizacao.status_ordem, status)
         WHERE id = %s AND status IN ('AGUARDANDO','EM_CAMPO') RETURNING id, status::text, fiscal_matricula""",
        (dados.fiscal_matricula, dados.status, ordem_id))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(409, "Ordem inexistente ou já encerrada")
    return r


# ------------------------------------------------------------------------ laudos
@router.post("/ordens/{ordem_id}/laudo", status_code=201, summary="Registrar laudo de vistoria (fiscal)")
async def registrar_laudo(ordem_id: UUID, dados: LaudoIn, u: Usuario = Depends(exigir(*CAMPO)),
                          conn=Depends(conexao)):
    cur = await conn.execute("""SELECT id, uc_id, status::text FROM fiscalizacao.ordem_vistoria
                                WHERE id = %s FOR UPDATE""", (ordem_id,))
    ordem = await cur.fetchone()
    if not ordem:
        raise HTTPException(404, "Ordem não encontrada")
    if ordem["status"] not in ("AGUARDANDO", "EM_CAMPO"):
        raise HTTPException(409, f"Ordem com status {ordem['status']}")
    if dados.resultado == "IRREGULARIDADE_CONFIRMADA" and not dados.categoria_constatada:
        raise HTTPException(422, "Informe a categoria constatada")
    decisao = "ENCAMINHAR_ANALISE" if dados.resultado in ("IRREGULARIDADE_CONFIRMADA", "INCONCLUSIVO",
                                                          "IMOVEL_FECHADO") else "MANTER"
    cur = await conn.execute("""
        INSERT INTO fiscalizacao.laudo_vistoria
          (ordem_id, uc_id, fiscal_matricula, realizada_em, resultado, categoria_constatada,
           atividade_observada, evidencias, observacoes, decisao)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, decisao::text""",
        (ordem_id, ordem["uc_id"], u.matricula, dados.realizada_em or datetime.now(timezone.utc),
         dados.resultado, dados.categoria_constatada, dados.atividade_observada,
         Jsonb(dados.evidencias), dados.observacoes, decisao))
    laudo = await cur.fetchone()
    await conn.execute("UPDATE fiscalizacao.ordem_vistoria SET status = 'CONCLUIDA' WHERE id = %s", (ordem_id,))
    return {"laudo_id": laudo["id"], "decisao": laudo["decisao"],
            "proximo_passo": "decisão do supervisor" if laudo["decisao"] == "ENCAMINHAR_ANALISE" else "encerrado"}


@router.get("/laudos", summary="Listar laudos")
async def listar_laudos(decisao: str | None = None, pendentes_aplicacao: bool = False,
                        limite: int = Query(100, le=1000),
                        _: Usuario = Depends(exigir(*LEITURA_GESTAO)), conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT l.id, l.ordem_id, l.uc_id, uc.matricula, o.origem::text, l.fiscal_matricula, l.realizada_em,
               l.resultado::text, uc.categoria_atual::text, l.categoria_constatada::text, l.atividade_observada,
               l.decisao::text, l.aprovado_por, l.aprovado_em, l.notificacao_previa_em,
               l.prazo_contestacao_ate, l.aplicado_em
        FROM fiscalizacao.laudo_vistoria l
        JOIN fiscalizacao.ordem_vistoria o ON o.id = l.ordem_id
        JOIN cadastro.unidade_consumidora uc ON uc.id = l.uc_id
        WHERE (%(d)s::text IS NULL OR l.decisao::text = %(d)s)
          AND (NOT %(p)s OR (l.decisao = 'RECLASSIFICAR' AND l.aplicado_em IS NULL))
        ORDER BY l.realizada_em DESC LIMIT %(l)s""", {"d": decisao, "p": pendentes_aplicacao, "l": limite})
    return await cur.fetchall()


@router.post("/laudos/{laudo_id}/decisao", summary="Decisão do supervisor (RECLASSIFICAR ou MANTER)")
async def decidir(laudo_id: UUID, dados: DecisaoIn, u: Usuario = Depends(exigir("SUPERVISOR")),
                  conn=Depends(conexao)):
    cur = await conn.execute("""SELECT id, fiscal_matricula, resultado::text, decisao::text, aplicado_em
                                FROM fiscalizacao.laudo_vistoria WHERE id = %s FOR UPDATE""", (laudo_id,))
    l = await cur.fetchone()
    if not l:
        raise HTTPException(404, "Laudo não encontrado")
    if l["aplicado_em"]:
        raise HTTPException(409, "Reclassificação já aplicada")
    if l["fiscal_matricula"] == u.matricula:
        raise HTTPException(409, "Segregação de funções: o aprovador não pode ser o fiscal do laudo")
    if dados.decisao == "RECLASSIFICAR" and l["resultado"] != "IRREGULARIDADE_CONFIRMADA":
        raise HTTPException(422, "Só é possível reclassificar com irregularidade confirmada")

    agora = datetime.now(timezone.utc)
    if dados.decisao == "RECLASSIFICAR":
        prazo = date.today() + timedelta(days=dados.prazo_contestacao_dias)
        await conn.execute("""
            UPDATE fiscalizacao.laudo_vistoria
               SET decisao = 'RECLASSIFICAR', aprovado_por = %s, aprovado_em = %s,
                   notificacao_previa_em = %s, prazo_contestacao_ate = %s,
                   observacoes = coalesce(observacoes || E'\\n', '') || coalesce(%s, '')
             WHERE id = %s""", (u.matricula, agora, agora, prazo, dados.observacoes, laudo_id))
        return {"laudo_id": laudo_id, "decisao": "RECLASSIFICAR", "notificacao_previa_em": agora,
                "prazo_contestacao_ate": prazo,
                "proximo_passo": "aplicar após o prazo: POST /laudos/{id}/aplicar"}
    await conn.execute("""UPDATE fiscalizacao.laudo_vistoria SET decisao = 'MANTER', aprovado_por = %s, aprovado_em = %s
                          WHERE id = %s""", (u.matricula, agora, laudo_id))
    return {"laudo_id": laudo_id, "decisao": "MANTER"}


@router.post("/laudos/{laudo_id}/aplicar", summary="Aplicar a reclassificação (após o prazo de contestação)")
async def aplicar(laudo_id: UUID, _: Usuario = Depends(exigir("SUPERVISOR")), conn=Depends(conexao)):
    cur = await conn.execute("SELECT * FROM fiscalizacao.aplicar_reclassificacao(%s)", (laudo_id,))
    h = await cur.fetchone()
    return {"aplicado": True, "historico": h}
