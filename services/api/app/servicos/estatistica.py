"""Estatística auxiliar para os indicadores (intervalos de confiança)."""

from __future__ import annotations

import math


def wilson(sucessos: int, n: int, z: float = 1.96) -> dict:
    """
    Proporção com intervalo de Wilson (95% por padrão). Preferido ao intervalo de
    Wald por manter cobertura adequada com n pequeno e p perto de 0 ou 1 — o caso
    típico das taxas de acerto de vistoria.

        p̂ = s/n,  centro = (p̂ + z²/2n)/(1 + z²/n),
        semi = z·sqrt(p̂(1−p̂)/n + z²/4n²)/(1 + z²/n)
    """
    if n <= 0:
        return {"valor": None, "ic95": None, "n": 0, "sucessos": sucessos}
    p = sucessos / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    semi = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"valor": round(p, 4), "ic95": [round(max(0.0, centro - semi), 4), round(min(1.0, centro + semi), 4)],
            "n": n, "sucessos": sucessos}


def razao(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(a / b, 3)
