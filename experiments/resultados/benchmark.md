# Resultados do benchmark — Radar Cadastral SANEAGO

Gerado em 2026-11-26T03:02:24+00:00 · semente 20261125 · W = 2000 UCs (CV 5 folds) ·
T = 1000 UCs (teste fora da amostra) · k = 10% das UCs residenciais · IC 95% por bootstrap (B = 1000).

## Tabela 1 — Validação cruzada em W (predições fora do fold)

| Modelo | P@10% | Recall@10% | Ganho capt.@10% | ROC-AUC | AUC-PR | F1 (0,5) | Brier |
|---|---|---|---|---|---|---|---|
| Baseline por regras | 0.648 | 0.473 | 0.731 | 0.823 | 0.683 | 0.500 | 0.073 |
| XGBoost — consumo | 0.694 | 0.508 | 0.770 | 0.950 | 0.792 | 0.684 | 0.065 |
| XGBoost — consumo + bases | 0.782 | 0.572 | 0.845 | 0.969 | 0.890 | 0.794 | 0.041 |
| XGBoost — só visão | 0.725 | 0.530 | 0.790 | 0.892 | 0.774 | 0.674 | 0.069 |
| XGBoost — completo (proposto) | 0.855 | 0.625 | 0.910 | 0.990 | 0.956 | 0.891 | 0.024 |

## Tabela 2 — Teste fora da amostra em T (treino em W)

| Modelo | P@10% | Recall@10% | Ganho capt.@10% | ROC-AUC | AUC-PR | F1 (0,5) | Brier |
|---|---|---|---|---|---|---|---|
| Baseline por regras | 0.557 [0.454; 0.639] | 0.454 | 0.754 [0.664; 0.821] | 0.802 [0.751; 0.853] | 0.643 [0.567; 0.717] | 0.509 | 0.068 |
| XGBoost — consumo | 0.639 [0.536; 0.711] | 0.521 | 0.828 [0.740; 0.886] | 0.960 [0.944; 0.972] | 0.808 [0.754; 0.860] | 0.703 | 0.056 |
| XGBoost — consumo + bases | 0.680 [0.588; 0.773] | 0.555 | 0.865 [0.801; 0.923] | 0.972 [0.958; 0.983] | 0.884 [0.842; 0.924] | 0.779 | 0.039 |
| XGBoost — só visão | 0.629 [0.526; 0.711] | 0.513 | 0.804 [0.717; 0.868] | 0.878 [0.837; 0.915] | 0.735 [0.667; 0.798] | 0.653 | 0.074 |
| XGBoost — completo (proposto) | 0.753 [0.639; 0.856] | 0.613 | 0.936 [0.886; 0.977] | 0.982 [0.968; 0.992] | 0.933 [0.902; 0.961] | 0.872 | 0.026 |

## Tabela 3 — Equidade por faixa de renda (I5), modelo proposto em T

| Faixa | UCs | Irregulares | FPR | TPR | FDR no top-10% | Taxa de indicação |
|---|---|---|---|---|---|---|
| ALTA | 187 | 20 | 0.000 | 0.950 | 0.167 | 0.096 |
| MEDIA_ALTA | 124 | 18 | 0.019 | 0.833 | 0.167 | 0.097 |
| MEDIA | 342 | 48 | 0.014 | 0.896 | 0.317 | 0.120 |
| BAIXA | 314 | 33 | 0.025 | 0.758 | 0.231 | 0.083 |

Razão max/min — FPR: **inf** · FDR@10%: **1.902** · TPR: 1.254
(limite de revisão do I5: 1.25). Baseline: razão FPR = inf, FDR@10% = 2.322.

## Tabela 4 — Taxa de indicação (p ≥ 0,5) por cenário em T

| Cenário | n | Baseline | Proposto |
|---|---|---|---|
| COM_INFORMAL | 30 | 0.000 | 0.667 |
| CONSUMO_ALTO_RES | 52 | 0.000 | 0.077 |
| HOME_SERVICE | 63 | 0.000 | 0.000 |
| IMAGEM_DESATUALIZADA | 16 | 0.000 | 0.000 |
| MEI_SEM_ATIVIDADE | 47 | 0.000 | 0.000 |
| RES_COM_I | 39 | 0.744 | 0.974 |
| RES_COM_II | 39 | 0.026 | 0.846 |
| RES_IND | 11 | 1.000 | 1.000 |
| RES_OK | 593 | 0.002 | 0.007 |
| SOCIAL_ELEGIVEL | 47 | 0.000 | 0.085 |
| SOCIAL_OK | 30 | 0.000 | 0.033 |

Cenários irregulares (RES_COM_I, RES_COM_II, RES_IND, COM_INFORMAL): quanto maior, melhor (recall).
Armadilhas (HOME_SERVICE, MEI_SEM_ATIVIDADE, CONSUMO_ALTO_RES, RES_OK): quanto menor, melhor.

## Detector (YOLOv11n, validação sintética)

Acurácia da categoria sugerida entre os irregulares (teste): 0.8487.
Prevalência de irregulares: W = 0.132 · T = 0.119.

mAP@0,5 = 0.9963 · mAP@0,5:0,95 = 0.94 ·
tempo médio de inferência = 32.2 ms/imagem (CPU, 1 processo).

## Importância dos atributos (ganho médio, modelo proposto)

| Atributo | Ganho |
|---|---|
| v_doca_carga | 43.173 |
| v_portao_industrial | 40.887 |
| b_cnpj_ativo_mei | 18.256 |
| v_n_deteccoes | 17.836 |
| b_cnpj_ativo_nao_mei | 9.863 |
| c_volume_ref | 8.916 |
| v_letreiro | 3.627 |
| c_volume_inicial | 3.618 |
| v_banner | 3.520 |
| b_cnae_alimentacao_veiculos | 2.189 |
| v_placa_comercial | 2.181 |
| v_imagem_disponivel | 1.882 |

