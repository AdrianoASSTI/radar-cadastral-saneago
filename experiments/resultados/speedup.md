# Speedup — processamento distribuído do lote

S(p) calculado pela mediana dos tempos.

| Modo | p | T mediana (s) [IQR] | S(p) | E(p) | Vazão (UC/s) | Karp–Flatt | Latência med. (ms) | Desequilíbrio |
|---|---|---|---|---|---|---|---|---|
| SEQUENCIAL | 1 | 26.72 [1.43] | 1.0 | 1.0 | 11.226 | — | 82.0 | 1.0 |
| PARALELO | 1 | 26.32 [0.29] | 1.015 | 1.015 | 11.399 | — | 81.0 | 1.0 |
| PARALELO | 2 | 15.64 [2.76] | 1.709 | 0.854 | 19.183 | 0.1704 | 75.0 | 1.258 |
| PARALELO | 3 | 13.53 [14.58] | 1.975 | 0.658 | 22.171 | 0.2595 | 116.0 | 1.23 |

## Todas as repetições

- SEQUENCIAL p=1: 27.04 s, 24.82 s, 26.75 s, 27.94 s, 26.7 s, 25.15 s
- PARALELO p=1: 26.32 s, 26.5 s, 25.92 s
- PARALELO p=2: 20.5 s, 14.97 s, 15.64 s
- PARALELO p=3: 40.8 s, 13.53 s, 11.63 s

Fração serial estimada (Amdahl): **0.2274** → speedup máximo teórico **4.4×**.
