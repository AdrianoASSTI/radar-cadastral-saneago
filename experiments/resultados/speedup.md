# Speedup — processamento distribuído do lote

| Modo | p | T (s) | S(p) | E(p) | Vazão (UC/s) | Karp–Flatt | Latência med. (ms) | Desequilíbrio |
|---|---|---|---|---|---|---|---|---|
| SEQUENCIAL | 1 | 26.4 ± 1.19 | 1.0 | 1.0 | 11.365 | — | 82.0 | 1.0 |
| PARALELO | 1 | 26.25 ± 0.29 | 1.006 | 1.006 | 11.43 | — | 81.0 | 1.0 |
| PARALELO | 2 | 17.04 ± 3.01 | 1.549 | 0.775 | 17.61 | 0.2908 | 75.0 | 1.258 |
| PARALELO | 3 | 21.99 ± 16.32 | 1.201 | 0.4 | 13.645 | 0.7494 | 116.0 | 1.23 |

Fração serial estimada (Amdahl): **0.5841** → speedup máximo teórico **1.71×**.
