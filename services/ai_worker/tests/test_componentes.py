"""Testes unitários do worker de IA e do contrato de atributos (sem banco, sem broker)."""

import numpy as np
import pytest
from radar_comum import baseline
from radar_comum.features import CLASSES_YOLO, GRUPO, NOMES, como_lista, vetor_atributos

EV_COMERCIAL = {"cnpjs": [{"porte": "ME", "situacao": "ATIVA", "cnae": "5611201", "distancia_m": 4}],
                "alvaras": [{"vigente": True}], "zona_uso": "MISTO",
                "imagem": {"disponivel": True, "desatualizada": False}}
EV_VAZIA = {"cnpjs": [], "alvaras": [], "zona_uso": "PREDOMINANTEMENTE_RESIDENCIAL",
            "imagem": {"disponivel": False, "desatualizada": True}}
SERIE_DEGRAU = [12.0] * 12 + [35.0] * 12


def test_contrato_de_atributos_ordem_fixa():
    f = vetor_atributos(EV_COMERCIAL, SERIE_DEGRAU, [{"classe": "letreiro", "confianca": 0.9}])
    assert tuple(f) == NOMES
    assert f["b_cnpj_ativo_nao_mei"] == 1 and f["b_alvara_vigente"] == 1 and f["b_cnae_alimentacao_veiculos"] == 1
    assert f["c_volume_ref"] == 35 and f["c_razao_regime"] == pytest.approx(35 / 12, rel=1e-4)
    assert f["v_letreiro"] == 0.9 and f["v_n_deteccoes"] == 1


def test_classes_de_privacidade_nao_viram_atributo():
    f = vetor_atributos(EV_COMERCIAL, SERIE_DEGRAU, [{"classe": "rosto", "confianca": 0.99}])
    assert f["v_n_deteccoes"] == 0
    assert not any("rosto" in n or "placa_veiculo" in n for n in NOMES)


def test_ablacao_zera_grupos():
    f = vetor_atributos(EV_COMERCIAL, SERIE_DEGRAU, [{"classe": "vitrine", "confianca": 0.8}])
    v = como_lista(f, "cb")
    assert all(x == 0 for x, n in zip(v, NOMES) if GRUPO[n] == "v")


def test_baseline_ordena_casos_obvios():
    p_com, *_ = baseline.prever(SERIE_DEGRAU, EV_COMERCIAL)
    p_res, *_ = baseline.prever([12.0] * 24, EV_VAZIA)
    assert p_com > 0.9 > 0.1 > p_res


def test_anonimizacao_borra_somente_a_regiao():
    pytest.importorskip("cv2")
    from app.visao import anonimizar
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)      # textura de alta frequência
    det = [{"classe": "rosto", "confianca": 0.9, "x1": 0.25, "y1": 0.25, "x2": 0.35, "y2": 0.40},
           {"classe": "letreiro", "confianca": 0.9, "x1": 0.6, "y1": 0.1, "x2": 0.9, "y2": 0.2}]
    out, n_rostos, n_placas = anonimizar(img, det, haar=None)
    assert (n_rostos, n_placas) == (1, 0)
    reg = (slice(130, 182), slice(170, 214))                         # interior da caixa do rosto
    assert out[reg].std() < 0.25 * img[reg].std()                    # detalhe destruído
    assert np.array_equal(out[400:, :100], img[400:, :100])          # fora das caixas: intacto
    assert np.array_equal(out[48:96, 384:576], img[48:96, 384:576])  # letreiro NÃO é borrado


def test_classes_yolo():
    assert CLASSES_YOLO[-2:] == ("rosto", "placa_veiculo") and len(CLASSES_YOLO) == 9
