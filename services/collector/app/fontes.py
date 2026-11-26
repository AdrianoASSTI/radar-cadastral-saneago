"""
Adaptadores de fontes de imagem de fachada (para INFERÊNCIA automatizada).

Fontes permitidas (Termos de Uso e LGPD):
  * LEITURISTA      fotos tiradas pelos leituristas da própria concessionária
  * MAPILLARY       imagens de nível de rua abertas (CC BY-SA 4.0; exige atribuição)
  * GEO360_GOIANIA  portal geoespacial da Prefeitura de Goiânia (acordo de cooperação)

O Google Street View NÃO é uma fonte aqui: seus termos proíbem uso em inferência
automatizada. Ele aparece apenas como link para consulta humana no frontend.

Modos:
  simulado  lê o "acervo" local gerado por experiments/gerar_acervo.py, no mesmo
            layout que o app dos leituristas usaria: <acervo>/<fonte>/<matricula>.jpg + .json
  producao  usa as APIs reais (Mapillary Graph API v4; Geo360 por URL configurável).

Toda imagem é copiada para a QUARENTENA (tmpfs, só RAM) — nunca para disco — até
o worker de IA aplicar a anonimização.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("radar.coletor.fontes")

ACERVO = Path(os.getenv("ACERVO_PATH", "/data/acervo"))
QUARENTENA = Path(os.getenv("QUARENTENA_PATH", "/data/quarentena"))
MAPILLARY_TOKEN = os.getenv("MAPILLARY_TOKEN", "")
GEO360_URL_TEMPLATE = os.getenv("GEO360_URL_TEMPLATE", "")   # ex.: https://.../foto?lat={lat}&lon={lon}
RAIO_BUSCA_M = float(os.getenv("RAIO_BUSCA_IMAGEM_M", "25"))


@dataclass
class ImagemEncontrada:
    fonte: str                 # LEITURISTA | MAPILLARY | GEO360_GOIANIA | SINTETICA
    caminho_quarentena: Path
    capturada_em: datetime
    referencia_origem: str


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class FonteAcervoLocal:
    """Acervo em pastas (leituristas em produção; acervo sintético no modo simulado)."""

    def __init__(self, fonte: str, pasta: str):
        self.fonte, self.pasta = fonte, ACERVO / pasta

    async def buscar(self, matricula: str, lat: float, lon: float, destino_id: str) -> ImagemEncontrada | None:
        jpg, meta = self.pasta / f"{matricula}.jpg", self.pasta / f"{matricula}.json"
        if not jpg.exists():
            return None
        info = json.loads(meta.read_text()) if meta.exists() else {}
        cap = datetime.fromisoformat(info["capturada_em"]) if "capturada_em" in info else \
            datetime.fromtimestamp(jpg.stat().st_mtime, tz=timezone.utc)
        alvo = QUARENTENA / f"{destino_id}.jpg"
        shutil.copyfile(jpg, alvo)
        return ImagemEncontrada(info.get("fonte", self.fonte), alvo, cap, info.get("referencia", f"{self.fonte}:{matricula}"))


class FonteMapillary:
    """Mapillary Graph API v4: imagem mais próxima do ponto dentro de RAIO_BUSCA_M."""

    URL = "https://graph.mapillary.com/images"

    async def buscar(self, matricula: str, lat: float, lon: float, destino_id: str) -> ImagemEncontrada | None:
        if not MAPILLARY_TOKEN:
            return None
        import httpx
        d = RAIO_BUSCA_M / 111_320
        params = {"access_token": MAPILLARY_TOKEN, "fields": "id,captured_at,thumb_1024_url,computed_geometry",
                  "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}", "limit": 20}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(self.URL, params=params)
            r.raise_for_status()
            imgs = r.json().get("data", [])
            if not imgs:
                return None
            def dist(i):
                x, y = i["computed_geometry"]["coordinates"]
                return _haversine_m(lat, lon, y, x)
            melhor = min(imgs, key=dist)
            foto = await c.get(melhor["thumb_1024_url"])
            foto.raise_for_status()
        alvo = QUARENTENA / f"{destino_id}.jpg"
        alvo.write_bytes(foto.content)
        cap = datetime.fromtimestamp(melhor["captured_at"] / 1000, tz=timezone.utc)
        return ImagemEncontrada("MAPILLARY", alvo, cap, f"mapillary:{melhor['id']}")


class FonteGeo360:
    """
    Portal Geo360 Goiânia. Não há API pública documentada para fotos de fachada;
    o adaptador baixa de uma URL configurada no acordo com a Prefeitura
    (GEO360_URL_TEMPLATE com {lat} e {lon}). Sem configuração, retorna None.
    """

    async def buscar(self, matricula: str, lat: float, lon: float, destino_id: str) -> ImagemEncontrada | None:
        if not GEO360_URL_TEMPLATE:
            return None
        import httpx
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(GEO360_URL_TEMPLATE.format(lat=lat, lon=lon))
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
                return None
        alvo = QUARENTENA / f"{destino_id}.jpg"
        alvo.write_bytes(r.content)
        return ImagemEncontrada("GEO360_GOIANIA", alvo, datetime.now(timezone.utc), f"geo360:{lat:.6f},{lon:.6f}")


def montar_fontes(nomes: list[str], modo: str) -> list:
    fontes = []
    for n in nomes:
        n = n.strip().lower()
        if n == "leiturista":
            fontes.append(FonteAcervoLocal("LEITURISTA", "leiturista"))
        elif n == "mapillary":
            fontes.append(FonteAcervoLocal("MAPILLARY", "mapillary") if modo == "simulado" else FonteMapillary())
        elif n == "geo360":
            fontes.append(FonteAcervoLocal("GEO360_GOIANIA", "geo360") if modo == "simulado" else FonteGeo360())
        elif n in ("streetview", "street_view", "google"):
            raise ValueError("Street View não pode ser fonte de inferência automatizada (Termos do Google Maps Platform)")
    return fontes


async def melhor_imagem(fontes: list, matricula: str, lat: float, lon: float, destino_id: str) -> ImagemEncontrada | None:
    """Consulta todas as fontes e fica com a imagem MAIS RECENTE; descarta as demais."""
    achadas = []
    for i, f in enumerate(fontes):
        try:
            img = await f.buscar(matricula, lat, lon, f"{destino_id}-{i}")
        except Exception as e:  # noqa: BLE001 — fonte externa indisponível não derruba a coleta
            log.warning("fonte %s falhou para %s: %s", f.__class__.__name__, matricula, e)
            img = None
        if img:
            achadas.append(img)
    if not achadas:
        return None
    melhor = max(achadas, key=lambda x: x.capturada_em)
    for a in achadas:
        if a is not melhor:
            a.caminho_quarentena.unlink(missing_ok=True)
    final = QUARENTENA / f"{destino_id}.jpg"
    melhor.caminho_quarentena.rename(final)
    melhor.caminho_quarentena = final
    return melhor
