#!/usr/bin/env python3
"""
Baseline por regras (sem visão computacional) — Radar Cadastral SANEAGO.

Papel no projeto:
  1. Enquanto o worker de IA (Etapa 3) não existe, popula `analise.resultado_analise`
     para que a fila, o fluxo de vistoria e os indicadores possam ser exercitados.
  2. No artigo, serve de LINHA DE BASE: o modelo completo (imagem + consumo + bases)
     precisa superá-lo em Precisão@10% e no I5 (docs/04).

Usa apenas dados permitidos à fiscalização (consumo, CNPJ, alvará, zoneamento).
Não lê CadÚnico nem o gabarito sintético. Roda com o login do worker de IA:

  docker compose run --rm -e DATABASE_URL=postgresql://usr_ia:ia_dev@db:5432/radar \
      api python -m scripts.baseline_regras

Modelo: regressão logística com pesos FIXOS definidos por especialista
    z = β₀ + Σ_j β_j·x_j ,  p = σ(z) = 1/(1+e^(−z))
A explicação de cada UC é a decomposição aditiva do logit (contribuição β_j·x_j).
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar_comum.ganho import ganho_esperado, volume_referencia  # noqa: E402
from radar_comum.tarifas import TabelaTarifaria  # noqa: E402

VERSAO = "baseline-regras-v1"
BETA0 = -3.0
PESOS = {
    "cnpj_ativo_nao_mei":  (2.0, "CNPJ ativo (ME/EPP/Demais) a até 30 m do endereço"),
    "cnpj_ativo_mei":      (0.5, "MEI ativo no endereço (peso baixo: muitos MEIs não atendem no local)"),
    "alvara_vigente":      (1.2, "Alvará de funcionamento vigente no endereço"),
    "salto_consumo":       (1.6, "Aumento do consumo: (média últimos 6 / primeiros 6 meses) − 1,3, limitado a [0, 2]"),
    "consumo_excedente":   (0.03, "m³ acima de 20 m³/mês no regime atual"),
    "zona_nao_residencial": (0.5, "Zona mista, comercial/serviços ou industrial"),
}

SQL_UCS = """
SELECT uc.id, uc.categoria_atual::text AS categoria_atual, uc.economias, uc.possui_esgoto,
       array_agg(c.volume_m3::float ORDER BY c.competencia) AS serie,
       (SELECT count(*) FROM publico.estabelecimento_cnpj e
         WHERE e.situacao = 'ATIVA' AND e.porte <> 'MEI'
           AND ST_DWithin(e.geom::geography, uc.geom::geography, 30)) AS cnpj_nao_mei,
       (SELECT count(*) FROM publico.estabelecimento_cnpj e
         WHERE e.situacao = 'ATIVA' AND e.porte = 'MEI'
           AND ST_DWithin(e.geom::geography, uc.geom::geography, 30)) AS cnpj_mei,
       (SELECT count(*) FROM publico.alvara_funcionamento a
         WHERE a.data_validade >= current_date AND ST_DWithin(a.geom::geography, uc.geom::geography, 30)) AS alvaras,
       (SELECT z.uso::text FROM publico.zona_urbana z WHERE ST_Contains(z.geom, uc.geom) LIMIT 1) AS zona
FROM cadastro.unidade_consumidora uc
JOIN cadastro.consumo_mensal c ON c.uc_id = uc.id
WHERE uc.ligacao_ativa AND uc.categoria_atual IN ('RESIDENCIAL_NORMAL', 'RESIDENCIAL_SOCIAL')
GROUP BY uc.id
"""


def atributos(r: dict) -> dict:
    s = r["serie"]
    ini = sum(s[:6]) / max(len(s[:6]), 1)
    fim = volume_referencia(s, 6)
    razao = fim / max(ini, 1.0)
    return {
        "cnpj_ativo_nao_mei": 1.0 if r["cnpj_nao_mei"] else 0.0,
        "cnpj_ativo_mei": 1.0 if (r["cnpj_mei"] and not r["cnpj_nao_mei"]) else 0.0,
        "alvara_vigente": 1.0 if r["alvaras"] else 0.0,
        "salto_consumo": min(max(razao - 1.3, 0.0), 2.0),
        "consumo_excedente": max(fim - 20.0, 0.0),
        "zona_nao_residencial": 1.0 if r["zona"] in ("MISTO", "COMERCIAL_SERVICOS", "INDUSTRIAL") else 0.0,
        "_volume_ref": fim, "_razao_consumo": razao, "_zona": r["zona"],
    }


def categoria_provavel(x: dict) -> str:
    if x["_volume_ref"] >= 55 and (x["_razao_consumo"] > 2.5 or x["_zona"] == "INDUSTRIAL"):
        return "INDUSTRIAL"
    if x["_volume_ref"] <= 10:
        return "COMERCIAL_II"
    return "COMERCIAL_I"


def main() -> None:
    url = os.getenv("DATABASE_URL", "postgresql://usr_ia:ia_dev@localhost:5432/radar")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        cur = conn.execute("SELECT categoria::text, valor_mensal FROM regulatorio.tarifa_basica")
        basicas = cur.fetchall()
        faixas = conn.execute("SELECT * FROM regulatorio.tarifa_faixa").fetchall()
        for f in faixas:
            f["categoria"] = str(f["categoria"])
        params = {r["chave"]: r["v"] for r in conn.execute(
            "SELECT chave, coalesce(valor_num::text, valor_texto) AS v FROM regulatorio.parametro")}
        tab = TabelaTarifaria.de_linhas(basicas, faixas, params)

        ucs = conn.execute(SQL_UCS).fetchall()
        n = 0
        for r in ucs:
            t0 = time.perf_counter()
            x = atributos(r)
            contrib = {k: PESOS[k][0] * x[k] for k in PESOS}
            z = BETA0 + sum(contrib.values())
            p = 1 / (1 + math.exp(-z))
            cat = categoria_provavel(x)
            probs = {cat: p, r["categoria_atual"]: 1 - p}
            g = ganho_esperado(tab, r["categoria_atual"], probs, x["_volume_ref"], r["economias"], r["possui_esgoto"])
            fatores = sorted(
                ({"fator": k, "descricao": PESOS[k][1], "valor": round(x[k], 3), "peso": PESOS[k][0],
                  "contribuicao_logit": round(contrib[k], 3)} for k in PESOS),
                key=lambda f: -abs(f["contribuicao_logit"]))
            explic = {
                "metodo": "baseline por regras — decomposição aditiva do logit",
                "intercepto": BETA0, "logit": round(z, 3),
                "fatores": fatores,
                "resumo": [f["descricao"] for f in fatores if f["contribuicao_logit"] > 0.2][:3],
                "categoria_provavel_regra": cat,
                "aviso": "Recomendação para vistoria; a decisão é sempre humana.",
            }
            conn.execute("""
                INSERT INTO analise.resultado_analise
                  (uc_id, modelo_versao, categoria_atual, probabilidade_irregularidade, categoria_sugerida,
                   probabilidades_categoria, fatura_atual_mensal, fatura_sugerida_mensal, ganho_esperado_anual,
                   score_prioridade, explicabilidade, features, imagem_desatualizada, tempo_inferencia_ms, worker_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s)""",
                (r["id"], VERSAO, r["categoria_atual"], round(g.probabilidade_irregularidade, 4),
                 g.categoria_sugerida if g.probabilidade_irregularidade >= 0.5 else r["categoria_atual"],
                 Jsonb({k: round(v, 4) for k, v in probs.items()}),
                 g.fatura_atual_mensal, g.fatura_sugerida_mensal, g.ganho_esperado_anual, g.score_prioridade,
                 Jsonb(explic), Jsonb({k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()}),
                 int((time.perf_counter() - t0) * 1000), "baseline-regras"))
            n += 1
        conn.commit()
    print(f"[baseline] {n} UCs analisadas com {VERSAO}")


if __name__ == "__main__":
    main()
