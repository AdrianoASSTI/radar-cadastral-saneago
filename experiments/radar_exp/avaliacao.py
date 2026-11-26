"""
Métricas do protocolo experimental (docs/04).

População avaliada: UCs atualmente RESIDENCIAIS (as que entram na fila de vistoria).
Rótulo binário y = 1 se a categoria real é Comercial I/II ou Industrial.

  Precisão@k  = (1/k) Σ_{i ∈ top-k} y_i                 (k = ⌈0,10·N⌉; ranking pelo score)
  Recall@k    = Σ_{i ∈ top-k} y_i / Σ_i y_i
  GanhoCapt@k = Σ_{i ∈ top-k} G_i / Σ_i G_i              (G_i = ganho real anual se irregular)
  ROC-AUC, AUC-PR (precisão média), F1 no limiar 0,5, Brier
  IC 95% por bootstrap percentil (B reamostragens estratificadas)

Equidade por faixa de renda g (I5): FPR_g, FDR_g@k (falsos positivos entre os indicados),
TPR_g e taxa de indicação; razões max/min.
"""

from __future__ import annotations

import math
import random

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, roc_auc_score


def k_de(n: int, fracao: float) -> int:
    return max(1, math.ceil(fracao * n))


def metricas(y, p, score, ganho_real, fracao_k: float = 0.10, limiar: float = 0.5) -> dict:
    y, p, score, g = map(np.asarray, (y, p, score, ganho_real))
    n = len(y)
    k = k_de(n, fracao_k)
    ordem = np.argsort(-score, kind="stable")
    topo = ordem[:k]
    pred = p >= limiar
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    return {
        "n": int(n), "positivos": int(y.sum()), "prevalencia": round(float(y.mean()), 4), "k": k,
        "precisao_at_k": round(float(y[topo].mean()), 4),
        "recall_at_k": round(float(y[topo].sum() / max(y.sum(), 1)), 4),
        "ganho_capturado_at_k": round(float(g[topo].sum() / g.sum()), 4) if g.sum() > 0 else None,
        "roc_auc": round(float(roc_auc_score(y, p)), 4) if 0 < y.sum() < n else None,
        "auc_pr": round(float(average_precision_score(y, p)), 4) if y.sum() else None,
        "f1_limiar": round(float(f1_score(y, pred, zero_division=0)), 4),
        "precisao_limiar": round(tp / max(tp + fp, 1), 4), "recall_limiar": round(tp / max(tp + fn, 1), 4),
        "brier": round(float(brier_score_loss(y, np.clip(p, 0, 1))), 4),
        "matriz_confusao": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}, "limiar": limiar, "fracao_k": fracao_k,
    }


def bootstrap(y, p, score, ganho, b: int = 1000, semente: int = 0, fracao_k: float = 0.10) -> dict:
    """IC 95% (percentil) por bootstrap estratificado de P@k, AUC-PR e ROC-AUC."""
    y, p, score, ganho = map(np.asarray, (y, p, score, ganho))
    rng = np.random.default_rng(semente)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    acc = {"precisao_at_k": [], "auc_pr": [], "roc_auc": [], "ganho_capturado_at_k": []}
    for _ in range(b):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        m = metricas(y[idx], p[idx], score[idx], ganho[idx], fracao_k)
        for c in acc:
            if m[c] is not None:
                acc[c].append(m[c])
    return {c: [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]
            for c, v in acc.items() if v}


def equidade(y, p, score, faixas, fracao_k: float = 0.10, limiar: float = 0.5) -> dict:
    y, p, score, faixas = np.asarray(y), np.asarray(p), np.asarray(score), np.asarray(faixas)
    k = k_de(len(y), fracao_k)
    no_topo = np.zeros(len(y), bool)
    no_topo[np.argsort(-score, kind="stable")[:k]] = True
    pred = p >= limiar
    out = {}
    for f in ("ALTA", "MEDIA_ALTA", "MEDIA", "BAIXA"):
        s = faixas == f
        if not s.any():
            continue
        neg, pos = s & (y == 0), s & (y == 1)
        ind = s & no_topo
        out[f] = {
            "ucs": int(s.sum()), "irregulares": int(pos.sum()),
            "fpr": round(float((pred & neg).sum() / max(neg.sum(), 1)), 4),
            "tpr": round(float((pred & pos).sum() / max(pos.sum(), 1)), 4),
            "fdr_top_k": round(float((ind & (y == 0)).sum() / ind.sum()), 4) if ind.sum() else None,
            "indicadas_top_k": int(ind.sum()),
            "taxa_indicacao": round(float(ind.sum() / s.sum()), 4),
        }

    def razao(campo):
        v = [d[campo] for d in out.values() if d[campo] is not None]
        if len(v) < 2:
            return None
        if min(v) == 0:
            return None if max(v) == 0 else "inf"      # uma faixa sem erros e outra com erros
        return round(max(v) / min(v), 3)

    return {"por_faixa": out, "razao_fpr": razao("fpr"), "razao_fdr_top_k": razao("fdr_top_k"),
            "razao_tpr": razao("tpr"), "limite_I5": 1.25, "k": k}


def amostra_estratificada(idx_por_rotulo: dict, frac: float, semente: int) -> list:
    rng = random.Random(semente)
    return [i for v in idx_por_rotulo.values() for i in rng.sample(v, max(1, int(len(v) * frac)))]
