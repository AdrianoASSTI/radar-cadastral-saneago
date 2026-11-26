"""
Indicadores de impacto sociotécnico I1–I5 (Entrega 04; formalização em docs/03 e docs/04).

Todos são calculados dinamicamente a partir do que o sistema registra (laudos,
histórico de categoria, análises, cadastro). Período: [inicio, fim).

I1  Taxa de acerto das vistorias, por origem (Radar × método atual), com IC de Wilson.
        I1_g = confirmadas_g / conclusivas_g ;  razão = I1_RADAR / I1_METODO_ATUAL (meta ≥ 3)
I2  Receita recuperada por real investido.
        I2 = Σ_i max(0, F_nova,i(v̄_i) − F_antiga,i(v̄_i)) · 12  /  custo da solução no período
I3  Cobertura da Tarifa Social (ICTS): economias Residencial Social / famílias elegíveis (meta 100%).
I4  Precisão@k (k = 10% do ranking) e recall (amostra aleatória vistoriada).
I5  Equidade territorial: taxa de falsos positivos entre indicados (FDR) por faixa de renda;
        razão = max_g FDR_g / min_g FDR_g ; revisão do modelo se razão > 1,25.
    + taxa de indicação por faixa (paridade de seleção), auditável antes das vistorias.

"Conclusiva" = vistoria com resultado IRREGULARIDADE_CONFIRMADA ou CADASTRO_CORRETO
(imóvel fechado e inconclusivo entram no total realizado, não no denominador da taxa).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from radar_comum.tarifa_social import SQL_COBERTURA

from .estatistica import razao, wilson
from .tarifas import parametros, tabela_vigente

CONCLUSIVAS = ("IRREGULARIDADE_CONFIRMADA", "CADASTRO_CORRETO")


def _periodo(inicio: datetime | None, fim: datetime | None, padrao_dias: int | None = None):
    fim = fim or datetime.now(timezone.utc)
    if inicio is None and padrao_dias:
        inicio = fim - timedelta(days=padrao_dias)
    return inicio, fim


# --------------------------------------------------------------------------- I1
async def i1(conn, inicio=None, fim=None) -> dict:
    inicio, fim = _periodo(inicio, fim)
    cur = await conn.execute("""
        SELECT o.origem::text AS origem,
               count(*) AS realizadas,
               count(*) FILTER (WHERE l.resultado IN ('IRREGULARIDADE_CONFIRMADA','CADASTRO_CORRETO')) AS conclusivas,
               count(*) FILTER (WHERE l.resultado = 'IRREGULARIDADE_CONFIRMADA') AS confirmadas
        FROM fiscalizacao.laudo_vistoria l
        JOIN fiscalizacao.ordem_vistoria o ON o.id = l.ordem_id
        WHERE l.realizada_em >= coalesce(%(ini)s::timestamptz, '-infinity') AND l.realizada_em < %(fim)s
        GROUP BY 1""", {"ini": inicio, "fim": fim})
    por = {r["origem"]: r for r in await cur.fetchall()}
    p = await parametros(conn)
    grupos = {}
    for g in ("RADAR", "METODO_ATUAL", "AMOSTRA_ALEATORIA"):
        r = por.get(g, {"realizadas": 0, "conclusivas": 0, "confirmadas": 0})
        grupos[g] = {"realizadas": r["realizadas"], **wilson(r["confirmadas"], r["conclusivas"])}
    rz = razao(grupos["RADAR"]["valor"], grupos["METODO_ATUAL"]["valor"])
    meta = p.get("i1_meta_razao_controle", 3.0)
    return {
        "indicador": "I1", "nome": "Taxa de acerto das vistorias",
        "definicao": "confirmadas / vistorias conclusivas, por origem da ordem; IC 95% de Wilson",
        "periodo": {"inicio": inicio, "fim": fim},
        "grupos": grupos,
        "razao_radar_controle": rz, "meta_razao": meta,
        "atingiu_meta": None if rz is None else rz >= meta,
    }


# --------------------------------------------------------------------------- I2
async def i2(conn, inicio=None, fim=None, incluir_implantacao: bool = True) -> dict:
    inicio, fim = _periodo(inicio, fim, padrao_dias=365)
    tab = await tabela_vigente(conn)
    p = await parametros(conn)
    cur = await conn.execute("""
        SELECT h.uc_id, h.categoria_anterior::text AS ant, h.categoria_nova::text AS nova, h.alterado_em,
               o.origem::text AS origem, uc.economias, uc.possui_esgoto,
               (SELECT avg(volume_m3) FROM (
                    SELECT volume_m3 FROM cadastro.consumo_mensal c
                    WHERE c.uc_id = h.uc_id AND c.competencia <= h.alterado_em
                    ORDER BY c.competencia DESC LIMIT 6) s) AS v_ref
        FROM cadastro.historico_categoria h
        JOIN fiscalizacao.laudo_vistoria l ON l.id = h.laudo_id
        JOIN fiscalizacao.ordem_vistoria o ON o.id = l.ordem_id
        JOIN cadastro.unidade_consumidora uc ON uc.id = h.uc_id
        WHERE h.alterado_em >= %(ini)s AND h.alterado_em < %(fim)s""", {"ini": inicio, "fim": fim})
    itens, receita, reducoes = [], Decimal(0), Decimal(0)
    por_origem: dict[str, Decimal] = {}
    for r in await cur.fetchall():
        v = float(r["v_ref"] or 0)
        delta = (tab.fatura_mensal(r["nova"], v, r["economias"], r["possui_esgoto"])
                 - tab.fatura_mensal(r["ant"], v, r["economias"], r["possui_esgoto"])) * 12
        if delta >= 0:
            receita += delta
            por_origem[r["origem"]] = por_origem.get(r["origem"], Decimal(0)) + delta
        else:
            reducoes += delta
        itens.append({"uc_id": r["uc_id"], "de": r["ant"], "para": r["nova"], "origem": r["origem"],
                      "volume_ref_m3": round(v, 2), "delta_anual": float(delta), "alterado_em": r["alterado_em"]})

    cur = await conn.execute("""SELECT coalesce(sum(valor), 0) AS total, count(*) AS n FROM fiscalizacao.custo_solucao
                                WHERE competencia >= date_trunc('month', %(ini)s::timestamptz)
                                  AND competencia < %(fim)s""", {"ini": inicio, "fim": fim})
    c = await cur.fetchone()
    if c["n"] > 0:
        custo, origem_custo = Decimal(c["total"]), "fiscalizacao.custo_solucao (registrado)"
    else:
        cur = await conn.execute("SELECT count(*) AS n FROM cadastro.unidade_consumidora WHERE ligacao_ativa")
        n_ucs = (await cur.fetchone())["n"]
        meses = max(1, math.ceil((fim - inicio).days / 30.4375))
        custo = (Decimal(str(p["custo_solucao_por_imovel_mes"])) * n_ucs * meses
                 + (Decimal(str(p["custo_implantacao"])) if incluir_implantacao else Decimal(0)))
        origem_custo = (f"premissa: R$ {p['custo_solucao_por_imovel_mes']}/imóvel/mês × {n_ucs} UCs × {meses} meses"
                        + (f" + implantação R$ {p['custo_implantacao']:.2f}" if incluir_implantacao else ""))
    valor = float(receita / custo) if custo > 0 else None
    return {
        "indicador": "I2", "nome": "Receita recuperada por real investido",
        "definicao": "Σ max(0, F_nova − F_antiga)(v̄ últimos 6 meses) × 12 / custo da solução; > 1 = a solução se paga",
        "periodo": {"inicio": inicio, "fim": fim},
        "receita_recuperada_anual": float(receita), "reducoes_anuais": float(reducoes),
        "receita_por_origem": {k: float(v) for k, v in por_origem.items()},
        "custo": float(custo), "origem_custo": origem_custo,
        "valor": None if valor is None else round(valor, 4),
        "roi_percentual": None if valor is None else round((valor - 1) * 100, 2),
        "reclassificacoes": itens,
    }


# --------------------------------------------------------------------------- I3
async def i3(conn_social) -> dict:
    """Recebe conexão do papel radar_social; devolve apenas contagens agregadas."""
    cur = await conn_social.execute(SQL_COBERTURA)
    r = await cur.fetchone()
    eleg = r["familias_elegiveis"]
    valor = round(r["economias_social"] / eleg, 4) if eleg else None
    return {
        "indicador": "I3", "nome": "Cobertura da Tarifa Social (ICTS)",
        "definicao": "economias na Residencial Social / famílias elegíveis no CadÚnico (≤ ½ SM per capita ou BPC); meta 100%",
        "valor": valor, "meta": 1.0,
        "economias_residencial_social": r["economias_social"], "familias_elegiveis": eleg,
        "familias_vinculadas_a_uc": r["familias_vinculadas"], "alertas_abertos": r["alertas_abertos"],
        "familias_incluidas_pelo_sistema": r["familias_incluidas_pelo_sistema"],
        "fonte_normativa": "Lei 14.898/2024; AGR — Relatório de AIR nº 17/2026",
    }


# ------------------------------------------------------- ranking de referência
SQL_RANKING = """
WITH ua AS (   -- última análise de cada UC feita enquanto ela era residencial (snapshot)
  SELECT DISTINCT ON (uc_id) uc_id, probabilidade_irregularidade AS p, score_prioridade, criado_em
  FROM analise.resultado_analise
  WHERE categoria_atual IN ('RESIDENCIAL_NORMAL','RESIDENCIAL_SOCIAL')
  ORDER BY uc_id, criado_em DESC
),
rk AS (
  SELECT ua.*, row_number() OVER (ORDER BY score_prioridade DESC, p DESC) AS pos, count(*) OVER () AS n
  FROM ua
),
lv AS (        -- rótulo: laudo conclusivo mais recente, realizado APÓS a análise
  SELECT DISTINCT ON (l.uc_id) l.uc_id, l.resultado::text AS resultado, o.origem::text AS origem, l.realizada_em
  FROM fiscalizacao.laudo_vistoria l
  JOIN fiscalizacao.ordem_vistoria o ON o.id = l.ordem_id
  WHERE l.resultado IN ('IRREGULARIDADE_CONFIRMADA','CADASTRO_CORRETO')
    AND l.realizada_em >= coalesce(%(ini)s::timestamptz, '-infinity') AND l.realizada_em < %(fim)s
  ORDER BY l.uc_id, l.realizada_em DESC
)
SELECT rk.uc_id, rk.pos, rk.n, rk.p, b.faixa_renda::text AS faixa,
       CASE WHEN lv.realizada_em >= rk.criado_em THEN lv.resultado END AS rotulo,
       CASE WHEN lv.realizada_em >= rk.criado_em THEN lv.origem END AS origem_rotulo
FROM rk
JOIN cadastro.unidade_consumidora uc ON uc.id = rk.uc_id
JOIN cadastro.bairro b ON b.id = uc.bairro_id
LEFT JOIN lv ON lv.uc_id = rk.uc_id
"""


async def _ranking(conn, inicio, fim) -> list[dict]:
    cur = await conn.execute(SQL_RANKING, {"ini": inicio, "fim": fim})
    return await cur.fetchall()


# --------------------------------------------------------------------------- I4
async def i4(conn, inicio=None, fim=None, fracao_k: float = 0.10, limiar: float = 0.5) -> dict:
    inicio, fim = _periodo(inicio, fim)
    rk = await _ranking(conn, inicio, fim)
    n = len(rk)
    k = max(1, math.ceil(fracao_k * n)) if n else 0
    topo = [r for r in rk if r["pos"] <= k]
    rot_topo = [r for r in topo if r["rotulo"]]
    prec = wilson(sum(r["rotulo"] == "IRREGULARIDADE_CONFIRMADA" for r in rot_topo), len(rot_topo))

    aleat_pos = [r for r in rk if r["origem_rotulo"] == "AMOSTRA_ALEATORIA" and r["rotulo"] == "IRREGULARIDADE_CONFIRMADA"]
    rec_k = wilson(sum(r["pos"] <= k for r in aleat_pos), len(aleat_pos))
    rec_lim = wilson(sum(float(r["p"]) >= limiar for r in aleat_pos), len(aleat_pos))
    f1 = None
    if prec["valor"] is not None and rec_k["valor"] is not None and (prec["valor"] + rec_k["valor"]) > 0:
        f1 = round(2 * prec["valor"] * rec_k["valor"] / (prec["valor"] + rec_k["valor"]), 4)

    # Matriz de confusão na amostra rotulada (atenção: amostra enviesada pela seleção do próprio ranking)
    mc = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for r in rk:
        if not r["rotulo"]:
            continue
        pred = float(r["p"]) >= limiar
        real = r["rotulo"] == "IRREGULARIDADE_CONFIRMADA"
        mc["tp" if pred and real else "fp" if pred else "fn" if real else "tn"] += 1
    return {
        "indicador": "I4", "nome": "Precisão e recall do modelo",
        "definicao": "precisão@k nos k = ⌈fração·N⌉ primeiros do ranking (vistoriados após a análise); "
                     "recall estimado na amostra ALEATÓRIA vistoriada",
        "periodo": {"inicio": inicio, "fim": fim},
        "ucs_ranqueadas": n, "k": k, "fracao_k": fracao_k, "limiar_probabilidade": limiar,
        "precisao_at_k": prec, "cobertura_rotulos_top_k": round(len(rot_topo) / k, 4) if k else None,
        "recall_at_k": rec_k, "recall_no_limiar": rec_lim, "f1_operacional": f1,
        "matriz_confusao_amostra_rotulada": mc,
        "aviso": "A matriz usa só UCs vistoriadas, que não são uma amostra aleatória; "
                 "use a amostra aleatória (origem AMOSTRA_ALEATORIA) para estimativas não viesadas.",
    }


# --------------------------------------------------------------------------- I5
async def i5(conn, inicio=None, fim=None, fracao_k: float = 0.10, amostra_minima: int = 5) -> dict:
    inicio, fim = _periodo(inicio, fim)
    p = await parametros(conn)
    limite = p.get("i5_limite_razao_fpr", 1.25)
    cur = await conn.execute("""
        SELECT b.faixa_renda::text AS faixa,
               count(*) AS conclusivas,
               count(*) FILTER (WHERE l.resultado = 'CADASTRO_CORRETO') AS falsos_positivos
        FROM fiscalizacao.laudo_vistoria l
        JOIN fiscalizacao.ordem_vistoria o ON o.id = l.ordem_id
        JOIN cadastro.unidade_consumidora uc ON uc.id = l.uc_id
        JOIN cadastro.bairro b ON b.id = uc.bairro_id
        WHERE o.origem = 'RADAR' AND l.resultado IN ('IRREGULARIDADE_CONFIRMADA','CADASTRO_CORRETO')
          AND l.realizada_em >= coalesce(%(ini)s::timestamptz, '-infinity') AND l.realizada_em < %(fim)s
        GROUP BY 1""", {"ini": inicio, "fim": fim})
    fdr = {r["faixa"]: wilson(r["falsos_positivos"], r["conclusivas"]) for r in await cur.fetchall()}

    rk = await _ranking(conn, inicio, fim)
    n = len(rk)
    k = max(1, math.ceil(fracao_k * n)) if n else 0
    selecao = {}
    for faixa in ("ALTA", "MEDIA_ALTA", "MEDIA", "BAIXA"):
        da_faixa = [r for r in rk if r["faixa"] == faixa]
        indicados = sum(r["pos"] <= k for r in da_faixa)
        selecao[faixa] = {"ucs": len(da_faixa), "indicadas_top_k": indicados,
                          "taxa_indicacao": round(indicados / len(da_faixa), 4) if da_faixa else None}

    validas = {f: v["valor"] for f, v in fdr.items() if v["n"] >= amostra_minima}
    rz, situacao = None, "amostra_insuficiente"
    if len(validas) >= 2:
        mx, mn = max(validas.values()), min(validas.values())
        if mn > 0:
            rz = round(mx / mn, 3)
            situacao = "revisar_modelo" if rz > limite else "dentro_do_limite"
        else:
            situacao = "revisar_modelo" if mx > 0 else "dentro_do_limite"   # razão infinita (min = 0)
    taxas_sel = [v["taxa_indicacao"] for v in selecao.values() if v["taxa_indicacao"] is not None]
    return {
        "indicador": "I5", "nome": "Diferença de erro entre faixas de renda",
        "definicao": "FDR_g = falsos positivos / indicados vistoriados (origem RADAR) na faixa g; "
                     "razão = max/min entre faixas com n ≥ amostra mínima; revisão se razão > limite",
        "periodo": {"inicio": inicio, "fim": fim},
        "fdr_por_faixa": fdr, "amostra_minima": amostra_minima,
        "razao_max_min": rz, "limite": limite, "situacao": situacao,
        "alerta": situacao == "revisar_modelo",
        "paridade_de_selecao": {"k": k, "fracao_k": fracao_k, "por_faixa": selecao,
                                "razao_max_min_taxa_indicacao": razao(max(taxas_sel), min(taxas_sel))
                                if len(taxas_sel) >= 2 else None,
                                "faixas_sem_indicacao": [f for f, v in selecao.items()
                                                         if v["ucs"] and not v["indicadas_top_k"]]},
    }
