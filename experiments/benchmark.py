#!/usr/bin/env python3
"""
Benchmark e experimentação — Radar Cadastral SANEAGO (docs/04).

Desenho:
  * Mundo de desenvolvimento W (n UCs, semente s)  → validação cruzada estratificada (k folds)
  * Mundo de teste T (n_teste UCs, semente s+1)     → teste fora da amostra ("retroativo"):
    o modelo é treinado em W e avaliado uma única vez em T.
  * Ablação: baseline por regras × XGBoost com grupos de atributos
      C (consumo) · CB (consumo + bases) · V (só visão) · CBV (completo)
  * Equidade (I5) por faixa de renda; análise de erros por tipo de armadilha.
  * Tempo de inferência por imagem (sequencial, 1 processo) — insumo do speedup.

Saídas em experiments/resultados/:
  benchmark.json · benchmark.md · benchmark_tabelas.tex · figuras/*.png
  e, com --salvar-modelo, o classificador final (CBV treinado em W) em <dir>.

Uso: python benchmark.py --n 2000 --n-teste 1000 --folds 5 --salvar-modelo /models
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "services" / "ai_worker"))   # execução fora do contêiner

from radar_comum import baseline                                   # noqa: E402
from radar_comum.features import NOMES, ROTULOS, como_lista, vetor_atributos  # noqa: E402
from radar_comum.ganho import ganho_esperado, volume_referencia    # noqa: E402
from radar_comum.tarifas import TabelaTarifaria                    # noqa: E402
from radar_exp import avaliacao as av                              # noqa: E402
from radar_exp import mundo                                        # noqa: E402
from radar_exp.fachadas import renderizar                          # noqa: E402

RESULTADOS = AQUI / "resultados"
TAB = TabelaTarifaria.padrao_2026()

PARAMS_XGB = {"objective": "multi:softprob", "num_class": len(ROTULOS), "max_depth": 4, "eta": 0.08,
              "subsample": 0.9, "colsample_bytree": 0.9, "min_child_weight": 2, "lambda": 1.0,
              "eval_metric": "mlogloss", "tree_method": "hist", "nthread": 2}
N_ARVORES = 300
CONFIGS = {"XGB-C": "c", "XGB-CB": "cb", "XGB-V": "v", "XGB-CBV": "cbv"}
NOME_MODELO = {"BASELINE": "Baseline por regras", "XGB-C": "XGBoost — consumo",
               "XGB-CB": "XGBoost — consumo + bases", "XGB-V": "XGBoost — só visão",
               "XGB-CBV": "XGBoost — completo (proposto)"}


# --------------------------------------------------------------------- dados
def detectar_mundo(m: list[dict], detector, rotulo: str) -> float:
    """Renderiza as fachadas disponíveis e roda o detector. Retorna segundos/imagem."""
    import cv2
    from app.visao import so_comerciais
    tempos = []
    for i, u in enumerate(m):
        if not u["imagem"]["disponivel"]:
            u["deteccoes"] = []
            continue
        img, _ = renderizar(u["elementos"], random.Random(u["semente_imagem"]), banner_pequeno=u["banner_pequeno"])
        bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
        t0 = time.perf_counter()
        u["deteccoes"] = so_comerciais(detector.detectar(bgr))
        tempos.append(time.perf_counter() - t0)
        if i % 250 == 0:
            print(f"  [{rotulo}] {i}/{len(m)} imagens", flush=True)
    return float(np.mean(tempos)) if tempos else 0.0


def preparar(m: list[dict]) -> None:
    for u in m:
        u["atributos"] = vetor_atributos(u["evidencia"], u["serie"], u["deteccoes"], u["estimadas"])
        v = volume_referencia(u["serie"])
        u["v_ref"] = v
        # ganho real só conta receita (Comercial II pode custar menos que Residencial com ≤ 10 m³)
        u["ganho_real"] = max(0.0, float((TAB.fatura_mensal(u["categoria_real"], v, u["economias"])
                                          - TAB.fatura_mensal(u["categoria_atual"], v, u["economias"])) * 12)) \
            if u["irregular"] else 0.0


def matriz(m, grupos):
    return np.asarray([como_lista(u["atributos"], grupos) for u in m], dtype=np.float32)


def pesos_classe(y):
    c = Counter(y)
    return np.asarray([(len(y) / (len(c) * c[v])) ** 0.5 for v in y], dtype=np.float32)


def treinar(m, grupos, semente):
    y = np.asarray([u["rotulo_idx"] for u in m])
    dm = xgb.DMatrix(matriz(m, grupos), label=y, weight=pesos_classe(y), feature_names=list(NOMES))
    return xgb.train({**PARAMS_XGB, "seed": semente}, dm, N_ARVORES)


def prever_xgb(booster, m, grupos):
    return booster.predict(xgb.DMatrix(matriz(m, grupos), feature_names=list(NOMES)))


def pontuar(m, probs_mat):
    """probs (n × 4) → p_irregular e score (E[G]) por UC, como o worker de IA."""
    p_irr, score, sug = [], [], []
    for u, pr in zip(m, probs_mat):
        cat = u["categoria_atual"]
        res = cat if cat.startswith("RESIDENCIAL") else "RESIDENCIAL_NORMAL"
        g = ganho_esperado(TAB, cat, {res: pr[0], "COMERCIAL_I": pr[1], "COMERCIAL_II": pr[2], "INDUSTRIAL": pr[3]},
                           u["v_ref"], u["economias"])
        p_irr.append(g.probabilidade_irregularidade)
        score.append(g.score_prioridade)
        sug.append(g.categoria_sugerida)
    return np.asarray(p_irr), np.asarray(score), sug


def pontuar_baseline(m):
    p_irr, score, sug = [], [], []
    for u in m:
        p, cat, x, _ = baseline.prever(u["serie"], u["evidencia"])
        g = ganho_esperado(TAB, u["categoria_atual"], {cat: p, u["categoria_atual"]: 1 - p}, x["_volume_ref"],
                           u["economias"])
        p_irr.append(g.probabilidade_irregularidade)
        score.append(g.score_prioridade)
        sug.append(cat)
    return np.asarray(p_irr), np.asarray(score), sug


def residenciais(m):
    return [i for i, u in enumerate(m) if u["categoria_atual"].startswith("RESIDENCIAL")]


def avaliar(m, p, score, fracao_k, b, semente):
    idx = residenciais(m)
    y = np.asarray([int(m[i]["irregular"]) for i in idx])
    pp, ss = p[idx], score[idx]
    g = np.asarray([m[i]["ganho_real"] for i in idx])
    met = av.metricas(y, pp, ss, g, fracao_k)
    if b:
        met["ic95"] = av.bootstrap(y, pp, ss, g, b, semente, fracao_k)
    met["equidade"] = av.equidade(y, pp, ss, [m[i]["faixa_renda"] for i in idx], fracao_k)
    return met


def armadilhas(m, p, limiar=0.5):
    """Taxa de indicação (p ≥ limiar) por cenário — FP em armadilhas, recall nos irregulares."""
    por = defaultdict(list)
    for u, pi in zip(m, p):
        if u["categoria_atual"].startswith("RESIDENCIAL"):
            por[u["cenario"]].append(pi >= limiar)
    return {c: {"n": len(v), "taxa_indicada": round(float(np.mean(v)), 4)} for c, v in sorted(por.items())}


# --------------------------------------------------------------------- relatórios
def tabela_md(linhas, cab):
    s = "| " + " | ".join(cab) + " |\n|" + "---|" * len(cab) + "\n"
    return s + "".join("| " + " | ".join(str(x) for x in l) + " |\n" for l in linhas)


def fmt(v, ic=None):
    if v is None:
        return "—"
    return f"{v:.3f}" + (f" [{ic[0]:.3f}; {ic[1]:.3f}]" if ic else "")


def escrever_relatorios(r: dict) -> None:
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    (RESULTADOS / "benchmark.json").write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str))

    cab = ["Modelo", "P@10%", "Recall@10%", "Ganho capt.@10%", "ROC-AUC", "AUC-PR", "F1 (0,5)", "Brier"]
    def linhas(bloco):
        out = []
        for k, met in r[bloco].items():
            ic = met.get("ic95", {})
            out.append([NOME_MODELO[k], fmt(met["precisao_at_k"], ic.get("precisao_at_k")), fmt(met["recall_at_k"]),
                        fmt(met["ganho_capturado_at_k"], ic.get("ganho_capturado_at_k")),
                        fmt(met["roc_auc"], ic.get("roc_auc")), fmt(met["auc_pr"], ic.get("auc_pr")),
                        fmt(met["f1_limiar"]), fmt(met["brier"])])
        return out

    eq = r["teste"]["XGB-CBV"]["equidade"]
    eqb = r["teste"]["BASELINE"]["equidade"]
    lin_eq = [[f, d["ucs"], d["irregulares"], fmt(d["fpr"]), fmt(d["tpr"]), fmt(d["fdr_top_k"]), fmt(d["taxa_indicacao"])]
              for f, d in eq["por_faixa"].items()]
    lin_arm = [[c, d["n"], fmt(r["armadilhas"]["BASELINE"][c]["taxa_indicada"]), fmt(d["taxa_indicada"])]
               for c, d in r["armadilhas"]["XGB-CBV"].items()]
    yolo = r.get("yolo") or {}
    md = f"""# Resultados do benchmark — Radar Cadastral SANEAGO

Gerado em {r['gerado_em']} · semente {r['config']['semente']} · W = {r['config']['n']} UCs (CV {r['config']['folds']} folds) ·
T = {r['config']['n_teste']} UCs (teste fora da amostra) · k = 10% das UCs residenciais · IC 95% por bootstrap (B = {r['config']['bootstrap']}).

## Tabela 1 — Validação cruzada em W (predições fora do fold)

{tabela_md(linhas('cv'), cab)}
## Tabela 2 — Teste fora da amostra em T (treino em W)

{tabela_md(linhas('teste'), cab)}
## Tabela 3 — Equidade por faixa de renda (I5), modelo proposto em T

{tabela_md(lin_eq, ['Faixa', 'UCs', 'Irregulares', 'FPR', 'TPR', 'FDR no top-10%', 'Taxa de indicação'])}
Razão max/min — FPR: **{eq['razao_fpr']}** · FDR@10%: **{eq['razao_fdr_top_k']}** · TPR: {eq['razao_tpr']}
(limite de revisão do I5: {eq['limite_I5']}). Baseline: razão FPR = {eqb['razao_fpr']}, FDR@10% = {eqb['razao_fdr_top_k']}.

## Tabela 4 — Taxa de indicação (p ≥ 0,5) por cenário em T

{tabela_md(lin_arm, ['Cenário', 'n', 'Baseline', 'Proposto'])}
Cenários irregulares (RES_COM_I, RES_COM_II, RES_IND, COM_INFORMAL): quanto maior, melhor (recall).
Armadilhas (HOME_SERVICE, MEI_SEM_ATIVIDADE, CONSUMO_ALTO_RES, RES_OK): quanto menor, melhor.

## Detector (YOLOv11n, validação sintética)

Acurácia da categoria sugerida entre os irregulares (teste): {r['teste']['XGB-CBV'].get('acuracia_categoria_nos_irregulares')}.
Prevalência de irregulares: W = {r['prevalencia']['W']} · T = {r['prevalencia']['T']}.

mAP@0,5 = {yolo.get('mAP50', '—')} · mAP@0,5:0,95 = {yolo.get('mAP50_95', '—')} ·
tempo médio de inferência = {r['tempo_inferencia_s_por_imagem'] * 1000:.1f} ms/imagem (CPU, 1 processo).

## Importância dos atributos (ganho médio, modelo proposto)

{tabela_md([[n, f"{v:.3f}"] for n, v in r['importancia_atributos'][:12]], ['Atributo', 'Ganho'])}
"""
    (RESULTADOS / "benchmark.md").write_text(md)

    def tex(linhas_, cab_, legenda, rotulo):
        cols = "l" + "c" * (len(cab_) - 1)
        corpo = " \\\\\n".join(" & ".join(str(x).replace("%", "\\%").replace("_", "\\_") for x in l) for l in linhas_)
        cab_t = " & ".join(c.replace("%", "\\%").replace("_", "\\_") for c in cab_)
        return (f"\\begin{{table}}[ht]\n\\centering\n\\caption{{{legenda}}}\n\\label{{{rotulo}}}\n"
                f"\\resizebox{{\\linewidth}}{{!}}{{\\begin{{tabular}}{{{cols}}}\n\\hline\n{cab_t} \\\\\n\\hline\n"
                f"{corpo} \\\\\n\\hline\n\\end{{tabular}}}}\n\\end{{table}}\n")
    (RESULTADOS / "benchmark_tabelas.tex").write_text(
        tex(linhas("cv"), cab, "Validação cruzada estratificada (predições fora do fold).", "tab:cv")
        + "\n" + tex(linhas("teste"), cab, "Teste fora da amostra (IC 95\\% por bootstrap).", "tab:teste")
        + "\n" + tex(lin_eq, ["Faixa", "UCs", "Irreg.", "FPR", "TPR", "FDR@10%", "Indicação"],
                     "Auditoria de equidade territorial (I5) do modelo proposto.", "tab:i5"))


def figuras(r: dict, curvas: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve, roc_curve
    d = RESULTADOS / "figuras"
    d.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
    for nome, (y, p) in curvas.items():
        fpr, tpr, _ = roc_curve(y, p)
        pr, rc, _ = precision_recall_curve(y, p)
        ax[0].plot(fpr, tpr, label=NOME_MODELO[nome])
        ax[1].plot(rc, pr, label=NOME_MODELO[nome])
    ax[0].plot([0, 1], [0, 1], "k:", lw=.8)
    ax[0].set(xlabel="Taxa de falsos positivos", ylabel="Taxa de verdadeiros positivos", title="Curva ROC (teste)")
    ax[1].set(xlabel="Recall", ylabel="Precisão", title="Curva Precisão–Recall (teste)")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(d / "roc_pr_teste.png", dpi=160)
    plt.close(fig)

    eq = r["teste"]["XGB-CBV"]["equidade"]["por_faixa"]
    eqb = r["teste"]["BASELINE"]["equidade"]["por_faixa"]
    fx = list(eq)
    x = np.arange(len(fx))
    val = lambda d, f, c: np.nan if d[f][c] is None else d[f][c]   # noqa: E731
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    for a_, campo, titulo in ((ax[0], "fdr_top_k", "Falsos positivos entre os indicados (FDR@10%)"),
                              (ax[1], "tpr", "Sensibilidade (TPR, p ≥ 0,5)")):
        a_.bar(x - .2, [val(eqb, f, campo) for f in fx], .4, label="Baseline")
        a_.bar(x + .2, [val(eq, f, campo) for f in fx], .4, label="Proposto (XGB-CBV)")
        a_.set_xticks(x, fx)
        a_.set(title=titulo, ylim=(0, 1.05 if campo == "tpr" else None))
    ax[0].legend()
    fig.suptitle("Equidade territorial por faixa de renda (I5) — teste")
    fig.tight_layout()
    fig.savefig(d / "i5_equidade_por_faixa.png", dpi=160)
    plt.close(fig)


# --------------------------------------------------------------------- principal
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--n-teste", type=int, default=1000)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--semente", type=int, default=20261125)
    ap.add_argument("--fracao-k", type=float, default=0.10)
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--salvar-modelo", default=None, help="pasta para salvar o classificador final")
    a = ap.parse_args()
    t_ini = time.time()

    from app.visao import Detector
    detector = Detector()

    print("[1/5] gerando mundos sintéticos e detectando fachadas…", flush=True)
    W, T = mundo.gerar(a.n, a.semente), mundo.gerar(a.n_teste, a.semente + 1)
    t_img = detectar_mundo(W, detector, "W")
    detectar_mundo(T, detector, "T")
    preparar(W)
    preparar(T)

    print("[2/5] validação cruzada…", flush=True)
    y_w = np.asarray([u["rotulo_idx"] for u in W])
    skf = StratifiedKFold(a.folds, shuffle=True, random_state=a.semente)
    oof = {k: np.zeros((len(W), len(ROTULOS))) for k in CONFIGS}
    for tr, te in skf.split(np.zeros(len(W)), y_w):
        for k, gr in CONFIGS.items():
            b = treinar([W[i] for i in tr], gr, a.semente)
            oof[k][te] = prever_xgb(b, [W[i] for i in te], gr)
    cv = {"BASELINE": avaliar(W, *pontuar_baseline(W)[:2], a.fracao_k, 0, a.semente)}
    for k in CONFIGS:
        cv[k] = avaliar(W, *pontuar(W, oof[k])[:2], a.fracao_k, 0, a.semente)

    print("[3/5] teste fora da amostra…", flush=True)
    finais, teste, arm, curvas = {}, {}, {}, {}
    idx_t = residenciais(T)
    y_t = np.asarray([int(T[i]["irregular"]) for i in idx_t])
    pb, sb, _ = pontuar_baseline(T)
    teste["BASELINE"] = avaliar(T, pb, sb, a.fracao_k, a.bootstrap, a.semente)
    arm["BASELINE"] = armadilhas(T, pb)
    curvas["BASELINE"] = (y_t, pb[idx_t])
    for k, gr in CONFIGS.items():
        finais[k] = treinar(W, gr, a.semente)
        p, s, sug = pontuar(T, prever_xgb(finais[k], T, gr))
        teste[k] = avaliar(T, p, s, a.fracao_k, a.bootstrap, a.semente)
        arm[k] = armadilhas(T, p)
        curvas[k] = (y_t, p[idx_t])
        if k == "XGB-CBV":
            irr = [i for i in idx_t if T[i]["irregular"]]
            teste[k]["acuracia_categoria_nos_irregulares"] = round(
                float(np.mean([sug[i] == T[i]["categoria_real"] for i in irr])), 4)

    imp = finais["XGB-CBV"].get_score(importance_type="gain")
    importancia = sorted(((n, float(imp.get(n, 0.0))) for n in NOMES), key=lambda t: -t[1])

    print("[4/5] casos curados…", flush=True)
    C = mundo.gerar(0, a.semente, incluir_curadas=True)
    detectar_mundo(C, detector, "curadas")
    preparar(C)
    pc, sc, sugc = pontuar(C, prever_xgb(finais["XGB-CBV"], C, "cbv"))
    ordem = {i: r + 1 for r, i in enumerate(sorted(residenciais(C), key=lambda i: -sc[i]))}
    curadas = [{"uc": C[i]["n"], "cenario": C[i]["cenario"], "faixa": C[i]["faixa_renda"],
                "irregular": C[i]["irregular"], "p": round(float(pc[i]), 3), "sugerida": sugc[i],
                "posicao": ordem.get(i)} for i in range(len(C))]

    yolo_m = None
    for pasta in (Path(a.salvar_modelo) if a.salvar_modelo else None, RESULTADOS, Path("/models")):
        if pasta and (pasta / "yolo11n-fachada.metricas.json").exists():
            yolo_m = json.loads((pasta / "yolo11n-fachada.metricas.json").read_text())
            break

    r = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"n": a.n, "n_teste": a.n_teste, "folds": a.folds, "semente": a.semente, "fracao_k": a.fracao_k,
                   "bootstrap": a.bootstrap, "xgboost": {**PARAMS_XGB, "n_arvores": N_ARVORES},
                   "data_referencia": str(mundo.DATA_REFERENCIA)},
        "ambiente": {"python": platform.python_version(), "plataforma": platform.platform(),
                     "xgboost": xgb.__version__, "numpy": np.__version__, "processador": platform.processor()},
        "prevalencia": {"W": round(float(np.mean([u["irregular"] for u in W])), 4),
                        "T": round(float(np.mean([u["irregular"] for u in T])), 4)},
        "cv": cv, "teste": teste, "armadilhas": arm, "importancia_atributos": importancia,
        "casos_curados": curadas, "yolo": yolo_m,
        "tempo_inferencia_s_por_imagem": round(t_img, 4),
        "tempo_total_s": None,
    }

    print("[5/5] relatórios…", flush=True)
    if a.salvar_modelo:
        destino = Path(a.salvar_modelo)
        destino.mkdir(parents=True, exist_ok=True)
        finais["XGB-CBV"].save_model(str(destino / "classificador-v1.json"))
        (destino / "classificador-v1.meta.json").write_text(json.dumps({
            "versao": "xgb-cbv-v1", "atributos": list(NOMES), "rotulos": list(ROTULOS), "grupos": "cbv",
            "treinado_em": r["gerado_em"], "n_treino": a.n, "semente": a.semente,
            "parametros": r["config"]["xgboost"], "metricas_teste": {k: teste["XGB-CBV"][k] for k in
                                                                     ("precisao_at_k", "roc_auc", "auc_pr")},
        }, indent=2, ensure_ascii=False))
    r["tempo_total_s"] = round(time.time() - t_ini, 1)
    escrever_relatorios(r)
    figuras(r, curvas)
    print((RESULTADOS / "benchmark.md").read_text())


if __name__ == "__main__":
    main()
