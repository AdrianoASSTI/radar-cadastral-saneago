"""
Testes do cálculo tarifário e do Ganho Esperado.

* Valores de referência da Entrega 04 (Res. Conjunta AGR/ARM 1/2026).
* Paridade Python × SQL (`regulatorio.fatura_mensal`) para todas as categorias e
  volumes de 0 a 150 m³ — executado se RADAR_TEST_OWNER_URL estiver definido.
"""

import os
from decimal import Decimal

import pytest
from radar_comum.ganho import ganho_esperado, volume_referencia
from radar_comum.tarifas import CATEGORIAS, TabelaTarifaria

T = TabelaTarifaria.padrao_2026()


@pytest.mark.parametrize("cat,vol,esperado", [
    ("RESIDENCIAL_NORMAL", 15, "197.86"),
    ("COMERCIAL_I", 15, "404.66"),
    ("RESIDENCIAL_NORMAL", 10, "132.76"),
    ("COMERCIAL_II", 10, "131.73"),
])
def test_valores_entrega_04(cat, vol, esperado):
    assert T.fatura_mensal(cat, vol) == Decimal(esperado)


def test_diferenca_anual_entrega_04():
    d = (T.fatura_mensal("COMERCIAL_I", 15) - T.fatura_mensal("RESIDENCIAL_NORMAL", 15)) * 12
    assert d == Decimal("2481.60")


def test_comercial_ii_acima_do_limite_vira_comercial_i():
    assert T.fatura_mensal("COMERCIAL_II", 12) == T.fatura_mensal("COMERCIAL_I", 12)


def test_economias_dividem_o_volume():
    assert T.fatura_mensal("RESIDENCIAL_NORMAL", 30, economias=2) == 2 * T.fatura_mensal("RESIDENCIAL_NORMAL", 15)


def test_sem_esgoto_cobra_so_agua():
    assert T.fatura_mensal("RESIDENCIAL_NORMAL", 10, esgoto=False) == Decimal("17.46") + 10 * Decimal("5.77")


def test_monotonia_no_volume():
    for c in CATEGORIAS:
        vals = [T.fatura_mensal(c, v) for v in range(0, 120)]
        assert all(b >= a for a, b in zip(vals, vals[1:])), c


def test_ganho_esperado_formula():
    g = ganho_esperado(T, "RESIDENCIAL_NORMAL", {"COMERCIAL_I": 0.7, "RESIDENCIAL_NORMAL": 0.3}, 15)
    assert g.ganho_se_confirmado_anual == Decimal("2481.60")
    assert g.ganho_esperado_anual == Decimal("1737.12")          # 0,7 × 2481,60
    assert g.categoria_sugerida == "COMERCIAL_I"
    assert g.probabilidade_irregularidade == pytest.approx(0.7)


def test_ganho_nulo_quando_comercial_ii_e_mais_barato():
    g = ganho_esperado(T, "RESIDENCIAL_NORMAL", {"COMERCIAL_II": 0.9, "RESIDENCIAL_NORMAL": 0.1}, 9)
    assert g.ganho_esperado_anual == 0
    assert g.score_prioridade == pytest.approx(0.9)               # só o desempate α·p


def test_volume_referencia_usa_regime_recente():
    assert volume_referencia([10] * 18 + [40] * 6) == 40


@pytest.mark.skipif(not os.getenv("RADAR_TEST_OWNER_URL"), reason="defina RADAR_TEST_OWNER_URL")
def test_paridade_python_sql():
    import psycopg
    with psycopg.connect(os.environ["RADAR_TEST_OWNER_URL"]) as conn:
        for c in CATEGORIAS:
            for v in range(0, 151):
                (sql,) = conn.execute("SELECT regulatorio.fatura_mensal(%s, %s)", (c, v)).fetchone()
                assert T.fatura_mensal(c, v) == sql, (c, v)
