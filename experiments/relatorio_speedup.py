#!/usr/bin/env python3
"""
Relatório do experimento de speedup (lê os lotes etiquetados 'speedup:*' no banco).

Métricas (docs/01, seção Computação Paralela):
  T_p      makespan do lote com p consumidores (criado_em → concluido_em), média de R repetições
  S(p)     = T_seq / T_p           (T_seq: modo SEQUENCIAL na mesma infraestrutura)
  E(p)     = S(p) / p              eficiência
  X(p)     = N / T_p               vazão (UCs/s)
  e(p)     = (1/S − 1/p) / (1 − 1/p)   métrica de Karp–Flatt (fração serial experimental)
  Amdahl   S(p) = 1 / (f + (1 − f)/p), f estimado por mínimos quadrados
Também: latência por UC (tempo_inferencia_ms) e balanceamento entre workers.
"""

from __future__ import annotations

import json
import os
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg
from psycopg.rows import dict_row

RES = Path(__file__).resolve().parent / "resultados"


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        lotes = c.execute("""
            SELECT id, parametros->>'etiqueta' AS etiqueta, total_ucs, falhas, n_workers,
                   extract(epoch FROM (concluido_em - criado_em))::float AS t
            FROM analise.lote_processamento
            WHERE parametros->>'etiqueta' LIKE 'speedup:%%' AND concluido_em IS NOT NULL
            ORDER BY criado_em""").fetchall()
        lat = c.execute("""
            SELECT l.parametros->>'etiqueta' AS etiqueta, r.worker_id, r.tempo_inferencia_ms
            FROM analise.resultado_analise r JOIN analise.lote_processamento l ON l.id = r.lote_id
            WHERE l.parametros->>'etiqueta' LIKE 'speedup:%%'""").fetchall()
    if not lotes:
        raise SystemExit("Nenhum lote 'speedup:*' concluído. Rode antes: bash experiments/speedup.sh")

    grupos = defaultdict(list)
    for l in lotes:
        partes = dict(p.split("=") for p in l["etiqueta"].split(":")[1:] if "=" in p)
        grupos[(partes["modo"], int(partes["n"]))].append(l)
    lat_por = defaultdict(list)
    carga = defaultdict(lambda: defaultdict(int))
    for r in lat:
        partes = dict(p.split("=") for p in r["etiqueta"].split(":")[1:] if "=" in p)
        chave = (partes["modo"], int(partes["n"]))
        lat_por[chave].append(r["tempo_inferencia_ms"])
        carga[chave][r["worker_id"]] += 1

    seq = grupos.get(("SEQUENCIAL", 1))
    t_seq = st.mean(l["t"] for l in seq) if seq else None
    linhas = []
    for (modo, n), ls in sorted(grupos.items(), key=lambda kv: (kv[0][0] != "SEQUENCIAL", kv[0][1])):
        ts = [l["t"] for l in ls]
        t = st.mean(ts)
        N = ls[0]["total_ucs"]
        s = t_seq / t if t_seq else None
        kf = ((1 / s - 1 / n) / (1 - 1 / n)) if (s and n > 1) else None
        ws = carga[(modo, n)]
        linhas.append({
            "modo": modo, "p": n, "repeticoes": len(ts), "ucs": N, "T_medio_s": round(t, 2),
            "T_dp_s": round(st.stdev(ts), 2) if len(ts) > 1 else 0.0,
            "speedup": round(s, 3) if s else None, "eficiencia": round(s / n, 3) if s else None,
            "vazao_ucs_s": round(N / t, 3), "karp_flatt": round(kf, 4) if kf is not None else None,
            "latencia_ms_mediana": round(st.median(lat_por[(modo, n)]), 1) if lat_por[(modo, n)] else None,
            "workers_ativos": len(ws),
            "desequilibrio_carga": round(max(ws.values()) / (sum(ws.values()) / len(ws)), 3) if ws else None,
            "falhas": sum(l["falhas"] for l in ls),
        })

    par = [r for r in linhas if r["modo"] == "PARALELO" and r["speedup"]]
    f = None
    if len(par) >= 1:
        p = np.array([r["p"] for r in par], float)
        S = np.array([r["speedup"] for r in par], float)
        # 1/S = f + (1−f)/p = 1/p + f(1 − 1/p)  →  regressão sem intercepto de (1/S − 1/p) em (1 − 1/p)
        x, y = 1 - 1 / p, 1 / S - 1 / p
        f = float(max(0.0, min(1.0, (x @ y) / (x @ x)))) if (x @ x) > 0 else None
    out = {"linhas": linhas, "T_sequencial_s": round(t_seq, 2) if t_seq else None,
           "amdahl_fracao_serial": round(f, 4) if f is not None else None,
           "amdahl_speedup_maximo": round(1 / f, 2) if f else None}
    RES.mkdir(parents=True, exist_ok=True)
    (RES / "speedup.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))

    cab = ["Modo", "p", "T (s)", "S(p)", "E(p)", "Vazão (UC/s)", "Karp–Flatt", "Latência med. (ms)", "Desequilíbrio"]
    tab = "| " + " | ".join(cab) + " |\n|" + "---|" * len(cab) + "\n" + "".join(
        f"| {r['modo']} | {r['p']} | {r['T_medio_s']} ± {r['T_dp_s']} | {r['speedup']} | {r['eficiencia']} | "
        f"{r['vazao_ucs_s']} | {r['karp_flatt'] if r['karp_flatt'] is not None else '—'} | "
        f"{r['latencia_ms_mediana']} | {r['desequilibrio_carga']} |\n" for r in linhas)
    md = (f"# Speedup — processamento distribuído do lote\n\n{tab}\n"
          f"Fração serial estimada (Amdahl): **{out['amdahl_fracao_serial']}** → speedup máximo teórico "
          f"**{out['amdahl_speedup_maximo']}×**.\n")
    (RES / "speedup.md").write_text(md)
    corpo = " \\\\\n".join(f"{r['modo']} & {r['p']} & {r['T_medio_s']} $\\pm$ {r['T_dp_s']} & {r['speedup']} & "
                           f"{r['eficiencia']} & {r['vazao_ucs_s']} & {r['karp_flatt'] if r['karp_flatt'] is not None else '--'}"
                           for r in linhas)
    (RES / "speedup.tex").write_text(
        "\\begin{table}[ht]\n\\centering\n\\caption{Speedup do processamento distribuído (coleta + IA).}\n"
        "\\label{tab:speedup}\n\\begin{tabular}{lcccccc}\n\\hline\nModo & $p$ & $T_p$ (s) & $S(p)$ & $E(p)$ & "
        f"Vazão (UC/s) & $e_{{KF}}$ \\\\\n\\hline\n{corpo} \\\\\n\\hline\n\\end{{tabular}}\n\\end{{table}}\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if par:
        p = [1] + [r["p"] for r in par]
        S = [1] + [r["speedup"] for r in par]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(p, p, "k:", label="Ideal (linear)")
        ax.plot(p, S, "o-", label="Medido")
        if f is not None:
            pp = np.linspace(1, max(p), 50)
            ax.plot(pp, 1 / (f + (1 - f) / pp), "--", label=f"Amdahl (f = {f:.3f})")
        ax.set(xlabel="Réplicas de workers (p)", ylabel="Speedup S(p)", title="Speedup do lote de análise")
        ax.legend()
        fig.tight_layout()
        (RES / "figuras").mkdir(exist_ok=True)
        fig.savefig(RES / "figuras" / "speedup.png", dpi=160)
    print(md)


if __name__ == "__main__":
    main()
