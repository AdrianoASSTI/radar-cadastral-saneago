"""
Ganho Esperado e score de priorização da fila de vistoria.

Formulação (docs/02_METODOLOGIA_IA_E_DATA_MINING.md):

  Seja c₀ a categoria atual da UC, v̄ o volume de referência (média dos últimos
  `janela` meses, para refletir o regime de uso ATUAL) e P(c | x) a probabilidade,
  dada pelo modelo, de a categoria real ser c. Considerando apenas a direção do
  subfaturamento (ganho de receita), o ganho esperado anual é

      E[G] = M · Σ_c  P(c | x) · max(0, F_c(v̄) − F_{c₀}(v̄))

  com M = 12 meses. A probabilidade de irregularidade é p = Σ_{c ∈ C⁺} P(c | x),
  em que C⁺ são as categorias de tarifa maior que a atual.

  O score de prioridade é o próprio E[G] (R$/ano): ordenar por E[G] maximiza a
  receita esperada por vistoria (problema da mochila com custo unitário). Um
  pequeno termo de desempate α·p evita empates em E[G] = 0 (ex.: Comercial II).

A IA sugere; a reclassificação é sempre decidida por um servidor (G1 no banco).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from .tarifas import CATEGORIAS, TabelaTarifaria

CATEGORIAS_SUBFATURAMENTO = ("COMERCIAL_I", "COMERCIAL_II", "INDUSTRIAL")


def volume_referencia(serie_m3: Sequence[float], janela: int = 6) -> float:
    """Média dos últimos `janela` meses (série ordenada do mais antigo ao mais recente)."""
    if not serie_m3:
        return 0.0
    ult = list(serie_m3)[-janela:]
    return float(sum(ult) / len(ult))


@dataclass(frozen=True)
class ResultadoGanho:
    categoria_atual: str
    categoria_sugerida: str
    volume_referencia_m3: float
    probabilidade_irregularidade: float
    fatura_atual_mensal: Decimal
    fatura_sugerida_mensal: Decimal
    ganho_se_confirmado_anual: Decimal      # (F_sug − F_atual) · M
    ganho_esperado_anual: Decimal           # E[G]
    score_prioridade: float
    delta_por_categoria: dict[str, Decimal]

    def como_dict(self) -> dict:
        d = self.__dict__.copy()
        for k, v in list(d.items()):
            if isinstance(v, Decimal):
                d[k] = float(v)
        d["delta_por_categoria"] = {k: float(v) for k, v in self.delta_por_categoria.items()}
        return d


def ganho_esperado(
    tabela: TabelaTarifaria,
    categoria_atual: str,
    probabilidades: Mapping[str, float],
    volume_m3: float,
    economias: int = 1,
    esgoto: bool = True,
    meses: int = 12,
    alfa_desempate: float = 1.0,
) -> ResultadoGanho:
    """Calcula E[G], a categoria sugerida e o score de prioridade de uma UC."""
    soma = sum(probabilidades.values())
    if soma <= 0:
        raise ValueError("probabilidades vazias")
    probs = {c: float(probabilidades.get(c, 0.0)) / soma for c in CATEGORIAS}

    f_atual = tabela.fatura_mensal(categoria_atual, volume_m3, economias, esgoto)
    delta: dict[str, Decimal] = {}
    eg = Decimal(0)
    p_irreg = 0.0
    for c in CATEGORIAS:
        d = tabela.fatura_mensal(c, volume_m3, economias, esgoto) - f_atual
        delta[c] = d
        if c in CATEGORIAS_SUBFATURAMENTO and c != categoria_atual and d > 0:
            eg += Decimal(str(probs[c])) * d
        if c in CATEGORIAS_SUBFATURAMENTO and c != categoria_atual:
            p_irreg += probs[c]
    eg = (eg * meses).quantize(Decimal("0.01"))

    sugerida = max(probs, key=probs.get)
    f_sug = tabela.fatura_mensal(sugerida, volume_m3, economias, esgoto)
    ganho_conf = ((f_sug - f_atual) * meses).quantize(Decimal("0.01"))

    return ResultadoGanho(
        categoria_atual=categoria_atual,
        categoria_sugerida=sugerida,
        volume_referencia_m3=round(float(volume_m3), 2),
        probabilidade_irregularidade=round(p_irreg, 4),
        fatura_atual_mensal=f_atual,
        fatura_sugerida_mensal=f_sug,
        ganho_se_confirmado_anual=ganho_conf,
        ganho_esperado_anual=eg,
        score_prioridade=round(float(eg) + alfa_desempate * p_irreg, 4),
        delta_por_categoria=delta,
    )
