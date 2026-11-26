"""
Modelo preditivo (XGBoost multiclasse) + explicabilidade (TreeSHAP).

Saída: P(categoria real | atributos) para RESIDENCIAL, COMERCIAL_I, COMERCIAL_II, INDUSTRIAL.
A massa de RESIDENCIAL é atribuída à categoria residencial atual da UC antes do
cálculo do Ganho Esperado (radar_comum.ganho).

Explicabilidade: valores SHAP exatos para árvores (TreeSHAP, Lundberg et al., 2020),
obtidos com `pred_contribs=True` do próprio XGBoost — sem dependência extra. Para a
classe explicada c, logit_c(x) = φ₀ + Σ_j φ_j(x); cada φ_j é a contribuição do
atributo j, em log-odds, para a previsão daquela UC.
"""

from __future__ import annotations

import json
import os

import numpy as np
import xgboost as xgb
from radar_comum.features import DESCRICOES, NOMES, ROTULOS, como_lista

from .visao import localizar_modelo


class Preditor:
    def __init__(self, nome: str = os.getenv("CLASSIFICADOR", "classificador-v1")):
        caminho = localizar_modelo(f"{nome}.json")
        meta = localizar_modelo(f"{nome}.meta.json")
        if caminho is None or meta is None:
            raise FileNotFoundError(f"modelo {nome} não encontrado")
        self.meta = json.loads(meta.read_text())
        if tuple(self.meta["atributos"]) != NOMES or tuple(self.meta["rotulos"]) != ROTULOS:
            raise ValueError("modelo incompatível com radar_comum.features (atributos/rótulos)")
        self.booster = xgb.Booster()
        self.booster.load_model(str(caminho))
        self.booster.set_param({"nthread": int(os.getenv("OMP_NUM_THREADS", "2"))})
        self.grupos = self.meta.get("grupos", "cbv")
        self.versao = self.meta["versao"]

    def prever(self, atributos: dict) -> tuple[dict[str, float], dict]:
        x = np.asarray([como_lista(atributos, self.grupos)], dtype=np.float32)
        dm = xgb.DMatrix(x, feature_names=list(NOMES))
        p = self.booster.predict(dm)[0]
        probs = {r: float(v) for r, v in zip(ROTULOS, p)}
        contrib = self.booster.predict(dm, pred_contribs=True)[0]        # (classes, atributos + viés)
        return probs, self._explicar(probs, contrib, atributos)

    def _explicar(self, probs: dict, contrib: np.ndarray, atributos: dict, top: int = 8) -> dict:
        nao_res = {k: v for k, v in probs.items() if k != "RESIDENCIAL"}
        alvo = max(nao_res, key=nao_res.get)
        k = ROTULOS.index(alvo)
        phi = contrib[k]
        fatores = sorted(
            ({"fator": n, "descricao": DESCRICOES[n], "valor": round(float(atributos[n]), 3),
              "contribuicao": round(float(phi[j]), 4)} for j, n in enumerate(NOMES) if abs(phi[j]) > 1e-4),
            key=lambda f: -abs(f["contribuicao"]))[:top]
        a_favor = [f for f in fatores if f["contribuicao"] > 0]
        contra = [f for f in fatores if f["contribuicao"] < 0]
        return {
            "metodo": "TreeSHAP (XGBoost pred_contribs) — contribuições em log-odds",
            "classe_explicada": alvo,
            "valor_base": round(float(phi[-1]), 4),
            "fatores": fatores,
            "resumo_a_favor": [f["descricao"] for f in a_favor[:3]],
            "resumo_contra": [f["descricao"] for f in contra[:2]],
            "aviso": "Recomendação para vistoria. A decisão sobre a categoria é sempre humana.",
        }
