# Speedup — processamento distribuído do lote

| Modo | p | T (s) | S(p) | E(p) | Vazão (UC/s) | Karp–Flatt | Latência med. (ms) | Desequilíbrio |
|---|---|---|---|---|---|---|---|---|
| SEQUENCIAL | 1 | 26.2 ± 1.21 | 1.0 | 1.0 | 11.45 | — | 82.5 | 1.0 |
| PARALELO | 1 | 26.25 ± 0.29 | 0.998 | 0.998 | 11.43 | — | 81.0 | 1.0 |
| PARALELO | 2 | 17.04 ± 3.01 | 1.538 | 0.769 | 17.61 | 0.3004 | 75.0 | 1.258 |

Fração serial estimada (Amdahl): **0.3004** → speedup máximo teórico **3.33×**.
