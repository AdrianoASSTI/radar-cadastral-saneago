"""
"Mundo sintético" em memória para treino e avaliação offline.

Reaproveita EXATAMENTE os geradores do seed (db/seed) — mesmos cenários, mesmas
probabilidades por estrato de renda, mesmas séries de consumo — e produz para cada
UC o mesmo contrato de evidência que o coletor monta em produção. Assim o modelo
treinado aqui é servido sem divergência treino/serviço.

Também define a política de disponibilidade de imagem, usada igualmente pelo
gerador do acervo (gerar_acervo.py) e pelo mundo em memória.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "db" / "seed"))
import dados_referencia as ref  # noqa: E402
import seed as gerador  # noqa: E402

from radar_comum.features import ROTULOS  # noqa: E402

DIAS_DESATUALIZADA = 540          # imagem com mais de 18 meses = desatualizada
DATA_REFERENCIA = date.fromisoformat(os.getenv("DATA_REFERENCIA", date.today().isoformat()))


def rotulo(categoria_real: str) -> str:
    return "RESIDENCIAL" if categoria_real.startswith("RESIDENCIAL") else categoria_real


def perfil_imagem(cenario: str, rng: random.Random) -> dict:
    """Disponibilidade e idade da foto de fachada (mesma regra no acervo e no mundo)."""
    if cenario == "IMAGEM_DESATUALIZADA":
        return {"disponivel": False, "idade_dias": None}
    u = rng.random()
    if u < 0.04:
        return {"disponivel": False, "idade_dias": None}                 # sem foto em nenhuma fonte
    if u < 0.10:
        return {"disponivel": True, "idade_dias": rng.randint(DIAS_DESATUALIZADA + 1, 1200)}  # foto antiga
    return {"disponivel": True, "idade_dias": rng.randint(5, 330)}


def capturada_em(idade_dias: int) -> datetime:
    return datetime.combine(DATA_REFERENCIA, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=idade_dias)


def evidencia(spec: dict, zona_uso: str | None, rng: random.Random, img: dict) -> dict:
    cnpjs = []
    if spec.get("cnpj"):
        c = spec["cnpj"]
        cnpjs.append({"porte": c["porte"], "situacao": c["situacao"], "cnae": c["cnae"],
                      "distancia_m": round(rng.uniform(0, 15), 1)})
    alvaras = []
    if spec.get("alvara"):
        alvaras.append({"vigente": date.fromisoformat(spec["alvara"]["validade"]) >= DATA_REFERENCIA})
    return {"cnpjs": cnpjs, "alvaras": alvaras, "zona_uso": zona_uso,
            "imagem": {"disponivel": img["disponivel"],
                       "desatualizada": (not img["disponivel"]) or img["idade_dias"] > DIAS_DESATUALIZADA}}


def gerar(n: int, semente: int, incluir_curadas: bool = False) -> list[dict]:
    """Gera n UCs procedurais (e, opcionalmente, as 30 curadas) com rótulos e evidências."""
    rng = random.Random(semente)
    specs = gerador.especificar_ucs(rng, n)
    if not incluir_curadas:
        specs = specs[len(ref.UCS):]
    estrato = {b[0]: b[2] for b in ref.BAIRROS}
    uso = {b[0]: b[6] for b in ref.BAIRROS}
    meses = gerador.competencias()
    mundo = []
    for sp in specs:
        cen = ref.CENARIOS[sp["cenario"]]
        serie = gerador.gerar_serie_consumo(sp.get("consumo", cen["consumo"]), meses, rng, cen.get("teto_m3"))
        img = perfil_imagem(sp["cenario"], rng)
        mundo.append({
            "n": sp["n"], "cenario": sp["cenario"], "origem": sp["origem"],
            "bairro": sp["bairro"], "faixa_renda": estrato[sp["bairro"]],
            "categoria_atual": cen["cat_atual"], "categoria_real": cen["cat_real"],
            "rotulo": rotulo(cen["cat_real"]), "rotulo_idx": ROTULOS.index(rotulo(cen["cat_real"])),
            "irregular": cen["cat_real"] in ref.CATEGORIAS_SUBFATURAMENTO and cen["cat_real"] != cen["cat_atual"],
            "armadilha": cen["armadilha"],
            "serie": [v for _, v, _ in serie], "estimadas": sum(t == "ESTIMADA" for *_, t in serie),
            "economias": sp.get("economias", 1),
            "evidencia": evidencia(sp, uso[sp["bairro"]], rng, img),
            "imagem": img,
            "elementos": sp.get("visuais", cen["visuais"]),
            "banner_pequeno": sp["cenario"] == "HOME_SERVICE",
            "semente_imagem": rng.randint(0, 2**31 - 1),
        })
    return mundo
