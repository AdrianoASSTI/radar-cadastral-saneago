"""
Contratos das mensagens AMQP (versão 1). JSON UTF-8, `content_type=application/json`.

Fluxo:  API --(COLETAR_UC)--> radar.coleta[.seq] --> coletor
        coletor --(ANALISAR_UC)--> radar.analise[.seq] --> worker de IA
        worker de IA --(RESULTADO_UC)--> radar.resultados (telemetria/progresso)

Cada UC é uma mensagem independente (granularidade fina): é isso que torna o
problema embaraçosamente paralelo e permite escalar consumidores horizontalmente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

ModoExecucao = Literal["PARALELO", "SEQUENCIAL"]


def agora() -> datetime:
    return datetime.now(timezone.utc)


class _Base(BaseModel):
    versao: int = 1
    mensagem_id: UUID = Field(default_factory=uuid4)
    lote_id: UUID
    uc_id: int
    modo: ModoExecucao = "PARALELO"
    enviado_em: datetime = Field(default_factory=agora)
    tentativa: int = 0


class MensagemColeta(_Base):
    tipo: Literal["COLETAR_UC"] = "COLETAR_UC"
    matricula: str
    latitude: float
    longitude: float
    endereco: str


class MensagemAnalise(_Base):
    tipo: Literal["ANALISAR_UC"] = "ANALISAR_UC"
    evidencia_id: int
    imagem_quarentena: str | None = None     # caminho no tmpfs; None = sem imagem disponível
    imagem_fonte: str | None = None          # LEITURISTA | MAPILLARY | GEO360_GOIANIA | SINTETICA
    imagem_capturada_em: datetime | None = None
    imagem_referencia_origem: str | None = None


class MensagemResultado(_Base):
    tipo: Literal["RESULTADO_UC"] = "RESULTADO_UC"
    sucesso: bool
    resultado_analise_id: UUID | None = None
    tempo_ms: int | None = None
    worker_id: str | None = None
    erro: str | None = None
