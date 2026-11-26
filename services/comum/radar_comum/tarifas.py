"""
Cálculo tarifário SANEAGO (água + esgoto) — implementação de referência em Python.

Regra (Resolução Conjunta AGR/ARM nº 1/2026, Anexo Único, vigência 01/04/2026):

    F_c(v) = n_e · [ B_c + Σ_k  q_k(v/n_e) · (a_k + e_k^col + e_k^trat) ]

  onde n_e é o número de economias, B_c a tarifa básica (custo mínimo fixo) da
  categoria c, e q_k(x) = max(0, min(x, s_k) − (i_k − 1)) o volume que cai na faixa
  k = [i_k, s_k] (faixas progressivas). Sem esgoto, e_k^col = e_k^trat = 0.

Premissas parametrizadas (marcadas `premissa=true` em regulatorio.parametro):
  * Comercial II só tem faixa até 10 m³; acima disso aplica-se Comercial I.
  * Residencial Social acima de 20 m³: excedente pelas faixas da Residencial Normal.

Esta função é espelhada por `regulatorio.fatura_mensal` no banco; os testes
garantem que as duas implementações produzem valores idênticos (oráculo duplo).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Mapping

CATEGORIAS = (
    "RESIDENCIAL_SOCIAL",
    "RESIDENCIAL_NORMAL",
    "COMERCIAL_I",
    "COMERCIAL_II",
    "INDUSTRIAL",
    "PUBLICA",
)
CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class Faixa:
    min_m3: int
    max_m3: int | None          # None = sem teto
    agua: Decimal
    esgoto_coleta: Decimal
    esgoto_tratamento: Decimal

    def preco_m3(self, esgoto: bool) -> Decimal:
        return self.agua + (self.esgoto_coleta + self.esgoto_tratamento if esgoto else Decimal(0))


@dataclass(frozen=True)
class TabelaTarifaria:
    vigencia: date
    basica: Mapping[str, Decimal]
    faixas: Mapping[str, tuple[Faixa, ...]]
    limite_comercial_ii_m3: Decimal = Decimal(10)
    categoria_transbordo_social: str = "RESIDENCIAL_NORMAL"
    fonte: str = "Res. Conjunta AGR/ARM 1/2026"

    # ------------------------------------------------------------------ fábrica
    @classmethod
    def de_linhas(cls, basicas: Iterable[Mapping], faixas: Iterable[Mapping],
                  parametros: Mapping[str, object] | None = None) -> "TabelaTarifaria":
        """Monta a tabela a partir das linhas de regulatorio.tarifa_basica/tarifa_faixa."""
        parametros = parametros or {}
        b = {r["categoria"]: Decimal(str(r["valor_mensal"])) for r in basicas}
        f: dict[str, list[Faixa]] = {}
        vig = None
        for r in faixas:
            vig = r.get("vigencia_inicio", vig)
            f.setdefault(r["categoria"], []).append(Faixa(
                int(r["faixa_min_m3"]),
                None if r["faixa_max_m3"] is None else int(r["faixa_max_m3"]),
                Decimal(str(r["agua_m3"])), Decimal(str(r["esgoto_coleta_m3"])),
                Decimal(str(r["esgoto_tratam_m3"]))))
        return cls(
            vigencia=vig or date(2026, 4, 1),
            basica=b,
            faixas={k: tuple(sorted(v, key=lambda x: x.min_m3)) for k, v in f.items()},
            limite_comercial_ii_m3=Decimal(str(parametros.get("comercial_ii_limite_m3", 10))),
            categoria_transbordo_social=str(parametros.get("residencial_social_transbordo", "RESIDENCIAL_NORMAL")),
        )

    @classmethod
    def padrao_2026(cls) -> "TabelaTarifaria":
        """Tabela embutida (idêntica ao 01_init.sql) — para testes e uso offline."""
        D = Decimal
        bas = {"RESIDENCIAL_SOCIAL": D("8.73"), "RESIDENCIAL_NORMAL": D("17.46"), "COMERCIAL_I": D("17.46"),
               "COMERCIAL_II": D("8.73"), "INDUSTRIAL": D("17.46"), "PUBLICA": D("17.46")}
        t = {
            "RESIDENCIAL_SOCIAL": [(1, 10, "2.73", "2.18", "0.55"), (11, 15, "3.07", "2.46", "0.61"),
                                   (16, 20, "3.52", "2.82", "0.70")],
            "RESIDENCIAL_NORMAL": [(1, 10, "5.77", "4.61", "1.15"), (11, 15, "6.51", "5.21", "1.30"),
                                   (16, 20, "7.45", "5.96", "1.49"), (21, 25, "8.45", "6.76", "1.69"),
                                   (26, 30, "9.54", "7.63", "1.91"), (31, 40, "10.89", "8.71", "2.18"),
                                   (41, 50, "12.33", "9.86", "2.47"), (51, None, "14.06", "11.25", "2.81")],
            "COMERCIAL_I": [(1, 10, "12.33", "9.86", "2.47"), (11, None, "14.06", "11.25", "2.81")],
            "COMERCIAL_II": [(1, 10, "6.15", "4.92", "1.23")],
            "INDUSTRIAL": [(1, 10, "12.33", "9.86", "2.47"), (11, None, "14.06", "11.25", "2.81")],
            "PUBLICA": [(1, 10, "10.89", "8.71", "2.18"), (11, None, "12.33", "9.86", "2.47")],
        }
        faixas = {c: tuple(Faixa(a, b, D(w), D(x), D(y)) for a, b, w, x, y in v) for c, v in t.items()}
        return cls(vigencia=date(2026, 4, 1), basica=bas, faixas=faixas)

    # ------------------------------------------------------------------ cálculo
    def _custo_faixas(self, categoria: str, v_ini: Decimal, v_fim: Decimal, esgoto: bool) -> Decimal:
        total = Decimal(0)
        for fx in self.faixas[categoria]:
            teto = Decimal("Infinity") if fx.max_m3 is None else Decimal(fx.max_m3)
            q = min(v_fim, teto) - max(v_ini, Decimal(fx.min_m3 - 1))
            if q > 0:
                total += q * fx.preco_m3(esgoto)
        return total

    def fatura_mensal(self, categoria: str, volume_m3: float | Decimal, economias: int = 1,
                      esgoto: bool = True) -> Decimal:
        """Valor mensal da conta (R$, 2 casas) para o volume total da UC."""
        if categoria not in CATEGORIAS:
            raise ValueError(f"categoria inválida: {categoria}")
        n = max(int(economias), 1)
        v = max(Decimal(str(volume_m3)), Decimal(0)) / n

        if categoria == "COMERCIAL_II" and v > self.limite_comercial_ii_m3:
            return self.fatura_mensal("COMERCIAL_I", volume_m3, economias, esgoto)

        basica = self.basica[categoria]
        if categoria == "RESIDENCIAL_SOCIAL":
            teto_social = Decimal(max(f.max_m3 or 0 for f in self.faixas[categoria]))
            consumo = (self._custo_faixas(categoria, Decimal(0), min(v, teto_social), esgoto)
                       + self._custo_faixas(self.categoria_transbordo_social, teto_social,
                                            max(v, teto_social), esgoto))
        else:
            consumo = self._custo_faixas(categoria, Decimal(0), v, esgoto)
        return ((basica + consumo) * n).quantize(CENTAVO, rounding=ROUND_HALF_UP)

    def comparar(self, volume_m3: float, economias: int = 1, esgoto: bool = True) -> dict[str, Decimal]:
        return {c: self.fatura_mensal(c, volume_m3, economias, esgoto) for c in CATEGORIAS}
