"""
Baseline por regras de especialista (linha de base do artigo).

Regressão logística com pesos FIXOS (não treinados):
    z = β₀ + Σ_j β_j·x_j ,  p = σ(z)
Usa apenas consumo e bases públicas — sem visão computacional e sem aprendizado.
A explicação é a decomposição aditiva do logit (β_j·x_j).
"""

from __future__ import annotations

import math
from typing import Sequence

from .ganho import volume_referencia

VERSAO = "baseline-regras-v1"
BETA0 = -3.0
PESOS = {
    "cnpj_ativo_nao_mei":   (2.0, "CNPJ ativo (ME/EPP/Demais) no endereço"),
    "cnpj_ativo_mei":       (0.5, "MEI ativo no endereço (peso baixo: muitos MEIs não atendem no local)"),
    "alvara_vigente":       (1.2, "Alvará de funcionamento vigente no endereço"),
    "salto_consumo":        (1.6, "Aumento do consumo: (média últimos 6 / primeiros 6 meses) − 1,3, limitado a [0, 2]"),
    "consumo_excedente":    (0.03, "m³ acima de 20 m³/mês no regime atual"),
    "zona_nao_residencial": (0.5, "Zona mista, comercial/serviços ou industrial"),
}


def atributos(serie: Sequence[float], evidencia: dict) -> dict:
    s = list(serie)
    ini = sum(s[:6]) / max(len(s[:6]), 1)
    fim = volume_referencia(s, 6)
    razao = fim / max(ini, 1.0)
    ativos = [c for c in evidencia.get("cnpjs", []) if c.get("situacao") == "ATIVA"]
    nao_mei = any(c.get("porte") != "MEI" for c in ativos)
    return {
        "cnpj_ativo_nao_mei": 1.0 if nao_mei else 0.0,
        "cnpj_ativo_mei": 1.0 if (not nao_mei and any(c.get("porte") == "MEI" for c in ativos)) else 0.0,
        "alvara_vigente": 1.0 if any(a.get("vigente") for a in evidencia.get("alvaras", [])) else 0.0,
        "salto_consumo": min(max(razao - 1.3, 0.0), 2.0),
        "consumo_excedente": max(fim - 20.0, 0.0),
        "zona_nao_residencial": 1.0 if evidencia.get("zona_uso") in ("MISTO", "COMERCIAL_SERVICOS", "INDUSTRIAL") else 0.0,
        "_volume_ref": fim, "_razao_consumo": razao, "_zona": evidencia.get("zona_uso"),
    }


def categoria_provavel(x: dict) -> str:
    if x["_volume_ref"] >= 55 and (x["_razao_consumo"] > 2.5 or x["_zona"] == "INDUSTRIAL"):
        return "INDUSTRIAL"
    if x["_volume_ref"] <= 10:
        return "COMERCIAL_II"
    return "COMERCIAL_I"


def prever(serie: Sequence[float], evidencia: dict) -> tuple[float, str, dict, dict]:
    """Retorna (p_irregular, categoria_provavel, atributos, explicação)."""
    x = atributos(serie, evidencia)
    contrib = {k: PESOS[k][0] * x[k] for k in PESOS}
    z = BETA0 + sum(contrib.values())
    p = 1 / (1 + math.exp(-z))
    cat = categoria_provavel(x)
    fatores = sorted(({"fator": k, "descricao": PESOS[k][1], "valor": round(x[k], 3), "peso": PESOS[k][0],
                       "contribuicao": round(contrib[k], 3)} for k in PESOS), key=lambda f: -abs(f["contribuicao"]))
    explic = {"metodo": "baseline por regras — decomposição aditiva do logit", "intercepto": BETA0,
              "logit": round(z, 3), "fatores": fatores, "classe_explicada": cat,
              "resumo_a_favor": [f["descricao"] for f in fatores if f["contribuicao"] > 0.2][:3],
              "aviso": "Recomendação para vistoria; a decisão é sempre humana."}
    return p, cat, x, explic
