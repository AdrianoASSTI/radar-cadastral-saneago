"""
Engenharia de atributos (feature engineering) — fonte ÚNICA para produção e experimentos.

O worker de IA (produção) e o benchmark (experimentos) chamam a MESMA função
`vetor_atributos`, o que elimina o risco de divergência treino/serviço
(training–serving skew). A entrada é o contrato "evidência":

    evidencia = {
      "cnpjs":   [{"porte": "MEI|ME|EPP|DEMAIS", "situacao": "ATIVA|...", "cnae": "5611201", "distancia_m": 8.2}],
      "alvaras": [{"vigente": true}],
      "zona_uso": "PREDOMINANTEMENTE_RESIDENCIAL|MISTO|COMERCIAL_SERVICOS|INDUSTRIAL|null",
      "imagem":  {"disponivel": true, "desatualizada": false},
    }
    serie_m3   = [v_1, …, v_T]          (mensal, do mais antigo ao mais recente)
    deteccoes  = [{"classe": "letreiro", "confianca": 0.91}, …]   (só classes comerciais)

Grupos de atributos (docs/02, seção Engenharia de Atributos):
  C — consumo: regime atual, mudança de regime, variabilidade, tendência
  B — bases públicas: CNPJ (por porte/situação), alvará, zoneamento
  V — visão computacional: confiança máxima por classe e contagem
"""

from __future__ import annotations

import math
from typing import Sequence

CLASSES_COMERCIAIS = ("placa_comercial", "letreiro", "vitrine", "banner",
                      "portao_industrial", "doca_carga", "estacionamento_clientes")
CLASSES_PRIVACIDADE = ("rosto", "placa_veiculo")
CLASSES_YOLO = CLASSES_COMERCIAIS + CLASSES_PRIVACIDADE   # ordem = índice da classe no YOLO

# Rótulos do classificador (categoria real agregada)
ROTULOS = ("RESIDENCIAL", "COMERCIAL_I", "COMERCIAL_II", "INDUSTRIAL")

DESCRICOES = {
    "c_volume_ref": "Consumo médio dos últimos 6 meses (m³)",
    "c_volume_inicial": "Consumo médio dos 6 primeiros meses da série (m³)",
    "c_razao_regime": "Razão consumo atual / consumo inicial",
    "c_salto_max": "Maior salto entre médias trimestrais consecutivas (m³)",
    "c_cv_12m": "Coeficiente de variação nos últimos 12 meses",
    "c_tendencia_12m": "Tendência linear nos últimos 12 meses (m³/mês)",
    "c_frac_estimadas": "Fração de leituras estimadas",
    "b_cnpj_ativo_nao_mei": "CNPJ ativo (ME/EPP/Demais) a até 30 m",
    "b_cnpj_ativo_mei": "MEI ativo a até 30 m",
    "b_cnpj_inativo": "CNPJ baixado/inapto a até 30 m",
    "b_cnae_alimentacao_veiculos": "CNAE de alto uso de água (alimentação, lavagem, estética, açougue)",
    "b_alvara_vigente": "Alvará de funcionamento vigente",
    "b_alvara_vencido": "Alvará de funcionamento vencido",
    "b_zona_misto": "Zona de uso misto",
    "b_zona_comercial": "Zona comercial/serviços",
    "b_zona_industrial": "Zona industrial",
    "v_imagem_disponivel": "Há imagem de fachada recente",
    "v_imagem_desatualizada": "Imagem ausente ou desatualizada (>18 meses)",
    "v_n_deteccoes": "Número de elementos comerciais detectados na fachada",
    **{f"v_{c}": f"Confiança máxima do detector para '{c.replace('_', ' ')}'" for c in CLASSES_COMERCIAIS},
}

NOMES = tuple(DESCRICOES)                     # ordem fixa do vetor
GRUPO = {n: n.split("_", 1)[0] for n in NOMES}  # c | b | v

# Divisões CNAE (2 dígitos) associadas a uso intenso de água
CNAE_ALTO_USO = ("56", "10", "11", "45", "96", "47")


def _media(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _tendencia(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = (n - 1) / 2, _media(xs)
    num = sum((i - mx) * (y - my) for i, y in enumerate(xs))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def atributos_consumo(serie: Sequence[float], estimadas: int = 0) -> dict:
    s = [float(v) for v in serie]
    ref, ini = _media(s[-6:]), _media(s[:6])
    saltos = [_media(s[t:t + 3]) - _media(s[t - 3:t]) for t in range(3, len(s) - 2)]
    ult = s[-12:]
    m = _media(ult)
    dp = math.sqrt(_media([(x - m) ** 2 for x in ult])) if ult else 0.0
    return {
        "c_volume_ref": ref,
        "c_volume_inicial": ini,
        "c_razao_regime": ref / max(ini, 1.0),
        "c_salto_max": max(saltos) if saltos else 0.0,
        "c_cv_12m": dp / m if m > 0 else 0.0,
        "c_tendencia_12m": _tendencia(ult),
        "c_frac_estimadas": estimadas / len(s) if s else 0.0,
    }


def atributos_bases(ev: dict) -> dict:
    cnpjs = ev.get("cnpjs") or []
    ativos = [c for c in cnpjs if c.get("situacao") == "ATIVA"]
    alv = ev.get("alvaras") or []
    zona = ev.get("zona_uso")
    return {
        "b_cnpj_ativo_nao_mei": float(any(c.get("porte") != "MEI" for c in ativos)),
        "b_cnpj_ativo_mei": float(any(c.get("porte") == "MEI" for c in ativos)),
        "b_cnpj_inativo": float(any(c.get("situacao") != "ATIVA" for c in cnpjs)),
        "b_cnae_alimentacao_veiculos": float(any(str(c.get("cnae", ""))[:2] in CNAE_ALTO_USO for c in ativos)),
        "b_alvara_vigente": float(any(a.get("vigente") for a in alv)),
        "b_alvara_vencido": float(any(not a.get("vigente") for a in alv)),
        "b_zona_misto": float(zona == "MISTO"),
        "b_zona_comercial": float(zona == "COMERCIAL_SERVICOS"),
        "b_zona_industrial": float(zona == "INDUSTRIAL"),
    }


def atributos_visuais(ev: dict, deteccoes: Sequence[dict]) -> dict:
    img = ev.get("imagem") or {}
    out = {
        "v_imagem_disponivel": float(bool(img.get("disponivel"))),
        "v_imagem_desatualizada": float(bool(img.get("desatualizada"))),
        "v_n_deteccoes": float(sum(1 for d in deteccoes if d["classe"] in CLASSES_COMERCIAIS)),
    }
    for c in CLASSES_COMERCIAIS:
        out[f"v_{c}"] = max((float(d["confianca"]) for d in deteccoes if d["classe"] == c), default=0.0)
    return out


def vetor_atributos(evidencia: dict, serie_m3: Sequence[float], deteccoes: Sequence[dict],
                    leituras_estimadas: int = 0) -> dict:
    """Dicionário {nome: valor} na ordem de NOMES."""
    f = {**atributos_consumo(serie_m3, leituras_estimadas), **atributos_bases(evidencia),
         **atributos_visuais(evidencia, deteccoes)}
    return {n: round(float(f[n]), 6) for n in NOMES}


def como_lista(f: dict, grupos: str = "cbv") -> list[float]:
    """Vetor numérico; `grupos` permite ablação (ex.: 'cb' = sem visão)."""
    return [f[n] if GRUPO[n] in grupos else 0.0 for n in NOMES]
