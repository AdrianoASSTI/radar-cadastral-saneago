#!/usr/bin/env python3
"""
Treino (fine-tuning) do YOLOv11n para fachadas — Radar Cadastral SANEAGO.

1. Gera um conjunto sintético anotado (fachadas com 0–3 elementos comerciais,
   distratores, rostos e placas de veículos) no formato Ultralytics.
2. Faz fine-tuning do yolo11n.pt (pré-treinado no COCO) em CPU.
3. Avalia no conjunto de validação (mAP@0,5 e mAP@0,5:0,95 por classe) e salva
   pesos + métricas em --saida (volume `modelos`) e em experiments/resultados.

Uso (no contêiner de experimentos):
  python treinar_yolo.py --n-treino 600 --n-val 150 --epocas 12 --imgsz 416

Hiperparâmetros documentados em docs/02 (Tabela de treino do detector).
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from pathlib import Path

from radar_comum.features import CLASSES_COMERCIAIS, CLASSES_YOLO
from radar_exp.fachadas import renderizar, rotulos_yolo

RESULTADOS = Path(__file__).resolve().parent / "resultados"


def gerar_dataset(raiz: Path, n_treino: int, n_val: int, semente: int) -> Path:
    rng = random.Random(semente)
    for parte, n in (("train", n_treino), ("val", n_val)):
        (raiz / "images" / parte).mkdir(parents=True, exist_ok=True)
        (raiz / "labels" / parte).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            if rng.random() < 0.25:
                elementos = []                                   # fachada puramente residencial
            else:
                elementos = [c for c in CLASSES_COMERCIAIS if rng.random() < 0.28] or [rng.choice(CLASSES_COMERCIAIS)]
            img, caixas = renderizar(elementos, random.Random(rng.randint(0, 2**31)),
                                     banner_pequeno=rng.random() < .4, p_pessoa=.5, p_carro=.5)
            img.save(raiz / "images" / parte / f"{i:05d}.jpg", quality=92)
            (raiz / "labels" / parte / f"{i:05d}.txt").write_text(rotulos_yolo(caixas))
    yaml = raiz / "data.yaml"
    yaml.write_text(f"path: {raiz}\ntrain: images/train\nval: images/val\n"
                    f"names:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES_YOLO)))
    return yaml


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-treino", type=int, default=600)
    ap.add_argument("--n-val", type=int, default=150)
    ap.add_argument("--epocas", type=int, default=12)
    ap.add_argument("--imgsz", type=int, default=416)
    ap.add_argument("--lote", type=int, default=8, help="8 cabe em 4 GB de RAM; 16 usa ~3 GB")
    ap.add_argument("--semente", type=int, default=20261125)
    ap.add_argument("--base", default="yolo11n.pt", help="pesos pré-treinados (COCO)")
    ap.add_argument("--trabalho", default="/tmp/radar_yolo")
    ap.add_argument("--saida", default="/models")
    a = ap.parse_args()

    from ultralytics import YOLO

    trab = Path(a.trabalho)
    shutil.rmtree(trab, ignore_errors=True)
    t0 = time.time()
    yaml = gerar_dataset(trab / "dataset", a.n_treino, a.n_val, a.semente)
    t_dados = time.time() - t0

    modelo = YOLO(a.base)
    t0 = time.time()
    modelo.train(data=str(yaml), epochs=a.epocas, imgsz=a.imgsz, batch=a.lote, device="cpu", workers=1,
                  seed=a.semente, deterministic=True, project=str(trab), name="treino", exist_ok=True,
                  patience=50, plots=False, verbose=False, mosaic=0.5, fliplr=0.5, hsv_v=0.3)
    t_treino = time.time() - t0

    melhor = trab / "treino" / "weights" / "best.pt"
    val = YOLO(str(melhor)).val(data=str(yaml), imgsz=a.imgsz, device="cpu", plots=False, verbose=False)
    por_classe = {CLASSES_YOLO[int(c)]: {"mAP50": round(float(val.box.ap50[i]), 4),
                                         "mAP50_95": round(float(val.box.ap[i]), 4)}
                  for i, c in enumerate(val.box.ap_class_index)}
    metricas = {
        "modelo": "YOLOv11n (fine-tuning a partir de COCO)", "classes": list(CLASSES_YOLO),
        "n_treino": a.n_treino, "n_val": a.n_val, "epocas": a.epocas, "imgsz": a.imgsz, "lote": a.lote,
        "semente": a.semente, "dispositivo": "cpu",
        "mAP50": round(float(val.box.map50), 4), "mAP50_95": round(float(val.box.map), 4),
        "precisao_media": round(float(val.box.mp), 4), "recall_medio": round(float(val.box.mr), 4),
        "por_classe": por_classe,
        "tempo_geracao_dados_s": round(t_dados, 1), "tempo_treino_s": round(t_treino, 1),
    }
    for destino in (Path(a.saida), RESULTADOS):
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "yolo11n-fachada.metricas.json").write_text(json.dumps(metricas, indent=2, ensure_ascii=False))
    shutil.copy(melhor, Path(a.saida) / "yolo11n-fachada.pt")
    print(json.dumps(metricas, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
