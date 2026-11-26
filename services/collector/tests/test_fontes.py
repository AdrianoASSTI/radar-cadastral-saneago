"""Testes do coletor: fontes permitidas e escolha da imagem mais recente."""

import asyncio
import json
from datetime import datetime, timezone

import pytest


def test_recusa_street_view():
    from app.fontes import montar_fontes
    with pytest.raises(ValueError, match="Street View"):
        montar_fontes(["leiturista", "streetview"], "producao")


def test_escolhe_a_imagem_mais_recente(tmp_path, monkeypatch):
    import app.fontes as f
    monkeypatch.setattr(f, "ACERVO", tmp_path / "acervo")
    monkeypatch.setattr(f, "QUARENTENA", tmp_path / "q")
    (tmp_path / "q").mkdir()
    for pasta, data in (("leiturista", "2024-01-10"), ("mapillary", "2026-09-01")):
        d = tmp_path / "acervo" / pasta
        d.mkdir(parents=True)
        (d / "GYN1.jpg").write_bytes(b"\xff\xd8" + pasta.encode())
        (d / "GYN1.json").write_text(json.dumps({"fonte": pasta.upper(), "capturada_em": f"{data}T00:00:00+00:00"}))
    fontes = f.montar_fontes(["leiturista", "mapillary"], "simulado")
    img = asyncio.run(f.melhor_imagem(fontes, "GYN1", -16.7, -49.2, "msg1"))
    assert img.fonte == "MAPILLARY" and img.capturada_em == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert sorted(p.name for p in (tmp_path / "q").iterdir()) == ["msg1.jpg"]   # descartadas apagadas
    assert img.caminho_quarentena.read_bytes().endswith(b"mapillary")
