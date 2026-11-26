# Speedup — processamento distribuído do lote

| Modo | p | T (s) | S(p) | E(p) | Vazão (UC/s) | Karp–Flatt | Latência med. (ms) | Desequilíbrio |
|---|---|---|---|---|---|---|---|---|
| SEQUENCIAL | 1 | 22.65 ± 1.41 | 1.0 | 1.0 | 8.83 | — | 106.0 | 1.0 |
| PARALELO | 1 | 21.39 ± 0.47 | 1.059 | 1.059 | 9.35 | — | 101.5 | 1.0 |
| PARALELO | 2 | 17.14 ± 3.19 | 1.321 | 0.661 | 11.668 | 0.5135 | 121.0 | 1.22 |

Fração serial estimada (Amdahl): **0.514** → speedup máximo teórico **1.95×**.
