# Experimentos — Radar Cadastral SANEAGO (Etapa 3)

Scripts que geram os números da seção **Resultados e Discussão** do artigo. Todos rodam no
contêiner `experiments`, que usa a mesma imagem do worker de IA (mesmas bibliotecas e pesos).

| Script | O que faz | Saída |
|---|---|---|
| `gerar_acervo.py` | Gera o acervo simulado de fotos de fachada das UCs do banco (fonte do coletor no modo `simulado`) | volume `acervo_fontes` |
| `benchmark.py` | Mundo sintético W (validação cruzada) + T (teste fora da amostra); ablação baseline × XGBoost (C, CB, V, CBV); IC 95% por bootstrap; auditoria de equidade (I5); análise por armadilha; casos curados | `resultados/benchmark.{json,md}`, `benchmark_tabelas.tex`, `figuras/` |
| `treinar_yolo.py` | Gera o conjunto anotado e faz fine-tuning do YOLOv11n em CPU | `/models/yolo11n-fachada.pt` + métricas |
| `speedup.sh` | (no terminal do host) mede o lote com 1, 2, 4 réplicas e o baseline sequencial | lotes etiquetados no banco |
| `relatorio_speedup.py` | Speedup, eficiência, vazão, Karp–Flatt e ajuste de Amdahl | `resultados/speedup.{json,md,tex}`, `figuras/speedup.png` |

## Reprodutibilidade

* Toda aleatoriedade é controlada por `--semente` (padrão 20261125) e pelo `SEED_RANDOM_STATE` do seed.
* Os pesos distribuídos em `services/ai_worker/modelos/` foram gerados com:
  `treinar_yolo.py --n-treino 600 --n-val 150 --epocas 12 --imgsz 416 --lote 16` e
  `benchmark.py --n 2000 --n-teste 1000 --folds 5 --salvar-modelo ...`.
* `benchmark.json` registra parâmetros, versões das bibliotecas, CPU e a data de referência.
* Re-treinos gravam no volume `modelos`, que tem prioridade sobre os pesos embutidos na imagem.

## Comandos

```bash
# benchmark completo (≈ 10–20 min em CPU)
docker compose --profile experimentos run --rm experiments

# rápido, para conferir que tudo roda
docker compose --profile experimentos run --rm experiments python benchmark.py --n 400 --n-teste 200 --folds 3 --bootstrap 100

# re-treinar o detector (≈ 40–60 min em CPU) e o classificador
docker compose --profile experimentos run --rm experiments python treinar_yolo.py
docker compose --profile experimentos run --rm experiments python benchmark.py --salvar-modelo /models
docker compose restart ai_worker

# speedup (no Git Bash, com API e workers no ar e o banco com UCs extras)
bash experiments/speedup.sh 300 "1 2 4" 3
docker compose --profile experimentos run --rm experiments python relatorio_speedup.py
```

## Limitações (declarar no artigo)

* Dados **sintéticos**: as fachadas e os cenários são gerados; as métricas medem a capacidade do
  pipeline de recuperar o sinal que foi plantado, não o desempenho em campo. A validação real é o
  piloto com grupo controle (I1) e amostra aleatória (I4), já suportado pela API.
* O detector foi treinado em domínio sintético; com fotos reais dos leituristas é preciso
  rotular uma amostra e re-treinar (o pipeline está pronto para isso).
