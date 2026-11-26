"""Carrega a tabela tarifária vigente do banco (fonte única de verdade) com cache."""

from __future__ import annotations

import time

from radar_comum.tarifas import TabelaTarifaria

_cache: dict = {"tabela": None, "em": 0.0}
TTL_S = 600


async def tabela_vigente(conn) -> TabelaTarifaria:
    if _cache["tabela"] is not None and time.monotonic() - _cache["em"] < TTL_S:
        return _cache["tabela"]
    cur = await conn.execute("""
        SELECT categoria::text, valor_mensal FROM regulatorio.tarifa_basica b
        WHERE vigencia_inicio = (SELECT max(vigencia_inicio) FROM regulatorio.tarifa_basica
                                 WHERE vigencia_inicio <= current_date AND categoria = b.categoria)""")
    basicas = await cur.fetchall()
    cur = await conn.execute("""
        SELECT vigencia_inicio, categoria::text, faixa_min_m3, faixa_max_m3, agua_m3, esgoto_coleta_m3, esgoto_tratam_m3
        FROM regulatorio.tarifa_faixa f
        WHERE vigencia_inicio = (SELECT max(vigencia_inicio) FROM regulatorio.tarifa_faixa
                                 WHERE vigencia_inicio <= current_date AND categoria = f.categoria)""")
    faixas = await cur.fetchall()
    cur = await conn.execute("SELECT chave, coalesce(valor_num::text, valor_texto) AS v FROM regulatorio.parametro")
    params = {r["chave"]: r["v"] for r in await cur.fetchall()}
    tab = TabelaTarifaria.de_linhas(basicas, faixas, params)
    _cache.update(tabela=tab, em=time.monotonic())
    return tab


async def parametros(conn) -> dict:
    cur = await conn.execute("SELECT chave, valor_num, valor_texto FROM regulatorio.parametro")
    return {r["chave"]: (float(r["valor_num"]) if r["valor_num"] is not None else r["valor_texto"])
            for r in await cur.fetchall()}
