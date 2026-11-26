#!/usr/bin/env python3
"""
Gera o ACERVO SIMULADO de fotos de fachada das UCs do banco (modo MODO_FONTES=simulado).

Emula o que chegaria das fontes reais: a maior parte das fotos vem dos leituristas
(70%) e o restante do Mapillary (30%), com datas de captura variadas (algumas com
mais de 18 meses → "imagem desatualizada"). UCs do cenário IMAGEM_DESATUALIZADA
ficam sem foto. Layout: <acervo>/<fonte>/<matricula>.jpg + <matricula>.json

Lê o gabarito sintético (só o papel radar_experimento pode) para desenhar os
elementos reais de cada imóvel. O coletor e a IA NÃO têm acesso ao gabarito:
para eles o acervo é uma fonte externa como outra qualquer.

  docker compose --profile experimentos run --rm experiments python gerar_acervo.py
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from radar_exp import mundo
from radar_exp.fachadas import renderizar


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--acervo", default=os.getenv("ACERVO_PATH", "/data/acervo"))
    ap.add_argument("--semente", type=int, default=20261125)
    ap.add_argument("--limpar", action="store_true", help="apaga o acervo antes de gerar")
    a = ap.parse_args()

    raiz = Path(a.acervo)
    if a.limpar:
        for sub in ("leiturista", "mapillary", "geo360"):
            shutil.rmtree(raiz / sub, ignore_errors=True)
    for sub in ("leiturista", "mapillary"):
        (raiz / sub).mkdir(parents=True, exist_ok=True)

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        ucs = conn.execute("""
            SELECT uc.id, uc.matricula, g.cenario, g.elementos_visuais, g.imagem_disponivel
            FROM cadastro.unidade_consumidora uc
            JOIN experimento.gabarito_sintetico g ON g.uc_id = uc.id
            ORDER BY uc.id""").fetchall()

    n_fotos = n_antigas = 0
    for u in ucs:
        rng = random.Random(a.semente * 1_000_003 + u["id"])
        perfil = mundo.perfil_imagem(u["cenario"], rng)
        if not (u["imagem_disponivel"] and perfil["disponivel"]):
            continue
        fonte, pasta = ("LEITURISTA", "leiturista") if rng.random() < 0.7 else ("MAPILLARY", "mapillary")
        img, _ = renderizar(u["elementos_visuais"], random.Random(rng.randint(0, 2**31)),
                            banner_pequeno=u["cenario"] == "HOME_SERVICE")
        img.save(raiz / pasta / f"{u['matricula']}.jpg", quality=88)
        (raiz / pasta / f"{u['matricula']}.json").write_text(json.dumps({
            "fonte": fonte, "capturada_em": mundo.capturada_em(perfil["idade_dias"]).isoformat(),
            "referencia": f"{pasta}:sim-{u['id']}", "sintetica": True}))
        n_fotos += 1
        n_antigas += perfil["idade_dias"] > mundo.DIAS_DESATUALIZADA
    print(f"[acervo] {len(ucs)} UCs · {n_fotos} fotos geradas ({n_antigas} com mais de 18 meses) em {raiz}")


if __name__ == "__main__":
    main()
