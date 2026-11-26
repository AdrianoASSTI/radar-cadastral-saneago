"""
Visão computacional: detecção (YOLOv11) e anonimização LGPD.

Pipeline por imagem (a imagem bruta só existe em RAM / tmpfs):
  1. YOLOv11n detecta 9 classes: 7 elementos comerciais/industriais + `rosto` + `placa_veiculo`.
  2. Anonimização: cada caixa de `rosto`/`placa_veiculo` (limiar BAIXO, 0,15, para
     priorizar o recall de privacidade) é ampliada em 15% e borrada (pixelização +
     desfoque gaussiano, irreversível). Um detector Haar de rostos frontais (OpenCV)
     roda como segunda camada, cobrindo fotos reais fora do domínio de treino.
  3. Só a imagem já borrada é gravada no storage; as detecções comerciais seguem
     para o modelo preditivo.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
import numpy as np
from radar_comum.features import CLASSES_COMERCIAIS, CLASSES_PRIVACIDADE, CLASSES_YOLO

log = logging.getLogger("radar.ia.visao")

CONF_COMERCIAL = float(os.getenv("YOLO_CONF_MIN", "0.35"))
CONF_PRIVACIDADE = float(os.getenv("YOLO_CONF_PRIVACIDADE", "0.15"))
IMGSZ = int(os.getenv("YOLO_IMGSZ", "416"))
MARGEM = 0.15


def localizar_modelo(nome: str) -> Path | None:
    """Procura primeiro no volume `modelos` (re-treinos) e depois nos pesos embutidos na imagem."""
    for pasta in (Path(os.getenv("MODELOS_DIR", "/models")), Path(__file__).resolve().parents[1] / "modelos"):
        p = pasta / nome
        if p.exists():
            return p
    return None


class Detector:
    def __init__(self, nome_pesos: str = "yolo11n-fachada.pt"):
        from ultralytics import YOLO
        import torch
        torch.set_num_threads(int(os.getenv("OMP_NUM_THREADS", "2")))
        self.caminho = localizar_modelo(nome_pesos)
        if self.caminho is None:
            raise FileNotFoundError(f"pesos {nome_pesos} não encontrados em /models nem na imagem")
        self.modelo = YOLO(str(self.caminho))
        nomes = [self.modelo.names[i] for i in sorted(self.modelo.names)]
        if tuple(nomes) != CLASSES_YOLO:
            raise ValueError(f"classes do modelo {nomes} ≠ esperado {CLASSES_YOLO}")
        self.versao = f"yolo11n-fachada@{self.caminho.stat().st_size}"
        self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if self.haar.empty():
            log.warning("detector Haar indisponível nesta versão do OpenCV; anonimização só pelo YOLO")
            self.haar = None
        log.info("detector carregado: %s", self.caminho)

    def detectar(self, img_bgr: np.ndarray) -> list[dict]:
        r = self.modelo.predict(img_bgr, imgsz=IMGSZ, conf=min(CONF_COMERCIAL, CONF_PRIVACIDADE),
                                device="cpu", verbose=False)[0]
        h, w = img_bgr.shape[:2]
        dets = []
        for (x1, y1, x2, y2), c, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
            classe = CLASSES_YOLO[int(k)]
            limiar = CONF_PRIVACIDADE if classe in CLASSES_PRIVACIDADE else CONF_COMERCIAL
            if c >= limiar:
                dets.append({"classe": classe, "confianca": round(float(c), 4),
                             "x1": x1 / w, "y1": y1 / h, "x2": x2 / w, "y2": y2 / h})
        return dets


def _borrar(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return
    hh, ww = roi.shape[:2]
    peq = cv2.resize(roi, (max(1, ww // 10), max(1, hh // 10)), interpolation=cv2.INTER_LINEAR)
    pix = cv2.resize(peq, (ww, hh), interpolation=cv2.INTER_NEAREST)
    img[y1:y2, x1:x2] = cv2.GaussianBlur(pix, (0, 0), sigmaX=max(3, ww / 8))


def anonimizar(img_bgr: np.ndarray, dets: list[dict], haar=None) -> tuple[np.ndarray, int, int]:
    """Borra rostos e placas. Retorna (imagem, n_rostos, n_placas)."""
    out = img_bgr.copy()
    h, w = out.shape[:2]
    n_rostos = n_placas = 0
    for d in dets:
        if d["classe"] not in CLASSES_PRIVACIDADE:
            continue
        mx, my = (d["x2"] - d["x1"]) * MARGEM, (d["y2"] - d["y1"]) * MARGEM
        _borrar(out, int(max(0, (d["x1"] - mx) * w)), int(max(0, (d["y1"] - my) * h)),
                int(min(w, (d["x2"] + mx) * w)), int(min(h, (d["y2"] + my) * h)))
        n_rostos += d["classe"] == "rosto"
        n_placas += d["classe"] == "placa_veiculo"
    if haar is not None:                                       # segunda camada (fotos reais)
        rostos_yolo = [d for d in dets if d["classe"] == "rosto"]
        cinza = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        for (x, y, ww, hh) in haar.detectMultiScale(cinza, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24)):
            _borrar(out, max(0, x - ww // 6), max(0, y - hh // 6), min(w, x + ww * 7 // 6), min(h, y + hh * 7 // 6))
            cx, cy = (x + ww / 2) / w, (y + hh / 2) / h        # não reconta rosto já tratado pelo YOLO
            if not any(d["x1"] <= cx <= d["x2"] and d["y1"] <= cy <= d["y2"] for d in rostos_yolo):
                n_rostos += 1
    return out, n_rostos, n_placas


def so_comerciais(dets: list[dict]) -> list[dict]:
    return [d for d in dets if d["classe"] in CLASSES_COMERCIAIS]
