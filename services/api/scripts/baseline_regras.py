#!/usr/bin/env python3
"""
Baseline por regras (sem visão computacional) — Radar Cadastral SANEAGO.

Papel no projeto:
  1. Popula `analise.resultado_analise` sem depender do worker de IA (útil para
     demonstrar a fila e os indicadores sem os workers no ar).
  2. No artigo, é a LINHA DE BASE: o modelo completo precisa superá-lo (docs/04).

A regra está em radar_comum.baseline e as evidências vêm da MESMA consulta usada
pelo coletor (radar_comum.evidencia). Não lê CadÚnico nem o gabarito sintético.

  docker compose --profile ferramentas run --rm baseline
"""

from __future__ import annotations

import os
import time

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from radar_comum import baseline
from radar_comum.evidencia import SQL_EVIDENCIA
from radar_comum.ganho import ganho_esperado
from radar_comum.tarifas import TabelaTarifaria


def main() -> None:
    url = os.getenv("DATABASE_URL", "postgresql://usr_ia:ia_dev@localhost:5432/radar")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        bas = conn.execute("SELECT categoria::text, valor_mensal FROM regulatorio.tarifa_basica").fetchall()
        fx = conn.execute("SELECT vigencia_inicio, categoria::text, faixa_min_m3, faixa_max_m3, agua_m3, "
                          "esgoto_coleta_m3, esgoto_tratam_m3 FROM regulatorio.tarifa_faixa").fetchall()
        par = {r["chave"]: r["v"] for r in conn.execute(
            "SELECT chave, coalesce(valor_num::text, valor_texto) AS v FROM regulatorio.parametro")}
        tab = TabelaTarifaria.de_linhas(bas, fx, par)

        ucs = conn.execute("""
            SELECT uc.id, uc.categoria_atual::text AS categoria_atual, uc.economias, uc.possui_esgoto,
                   array_agg(c.volume_m3::float ORDER BY c.competencia) AS serie
            FROM cadastro.unidade_consumidora uc JOIN cadastro.consumo_mensal c ON c.uc_id = uc.id
            WHERE uc.ligacao_ativa AND uc.categoria_atual IN ('RESIDENCIAL_NORMAL', 'RESIDENCIAL_SOCIAL')
            GROUP BY uc.id""").fetchall()
        for r in ucs:
            t0 = time.perf_counter()
            ev = conn.execute(SQL_EVIDENCIA, {"uc": r["id"]}).fetchone()
            p, cat, x, explic = baseline.prever(r["serie"], ev)
            g = ganho_esperado(tab, r["categoria_atual"], {cat: p, r["categoria_atual"]: 1 - p},
                               x["_volume_ref"], r["economias"], r["possui_esgoto"])
            conn.execute("""
                INSERT INTO analise.resultado_analise
                  (uc_id, modelo_versao, categoria_atual, probabilidade_irregularidade, categoria_sugerida,
                   probabilidades_categoria, fatura_atual_mensal, fatura_sugerida_mensal, ganho_esperado_anual,
                   score_prioridade, explicabilidade, features, imagem_desatualizada, tempo_inferencia_ms, worker_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s)""",
                (r["id"], baseline.VERSAO, r["categoria_atual"], round(g.probabilidade_irregularidade, 4),
                 g.categoria_sugerida, Jsonb({cat: round(p, 4), r["categoria_atual"]: round(1 - p, 4)}),
                 g.fatura_atual_mensal, g.fatura_sugerida_mensal, g.ganho_esperado_anual, g.score_prioridade,
                 Jsonb(explic), Jsonb({k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()}),
                 int((time.perf_counter() - t0) * 1000), "baseline-regras"))
        conn.commit()
    print(f"[baseline] {len(ucs)} UCs analisadas com {baseline.VERSAO}")


if __name__ == "__main__":
    main()
