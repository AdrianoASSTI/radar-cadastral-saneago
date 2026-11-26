"""Modelos de entrada (validação) da API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Categoria = Literal["RESIDENCIAL_SOCIAL", "RESIDENCIAL_NORMAL", "COMERCIAL_I", "COMERCIAL_II", "INDUSTRIAL", "PUBLICA"]
FaixaRenda = Literal["ALTA", "MEDIA_ALTA", "MEDIA", "BAIXA"]


# ------------------------------------------------------------------ ingestão
class ConsumoIn(BaseModel):
    competencia: date
    volume_m3: float = Field(ge=0)
    tipo_leitura: Literal["REAL", "ESTIMADA"] = "REAL"

    @field_validator("competencia")
    @classmethod
    def primeiro_dia(cls, v: date) -> date:
        return v.replace(day=1)


class UCIn(BaseModel):
    matricula: str = Field(min_length=3, max_length=40)
    logradouro: str
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = Field(None, description="Nome do bairro; se ausente, é inferido pela geometria")
    cep: str | None = Field(None, pattern=r"^\d{8}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    categoria_atual: Categoria
    economias: int = Field(1, ge=1)
    possui_esgoto: bool = True
    titular_id: str = Field(description="Código interno do titular; armazenado só como hash (pseudonimização)")
    consumo: list[ConsumoIn] = []


class ImportacaoIn(BaseModel):
    ucs: list[UCIn] = Field(min_length=1, max_length=5000)


# ------------------------------------------------------------------ lotes
class LoteIn(BaseModel):
    uc_ids: list[int] | None = Field(None, description="UCs específicas; se vazio, usa os filtros")
    bairro_ids: list[int] | None = None
    categorias: list[Categoria] = ["RESIDENCIAL_NORMAL", "RESIDENCIAL_SOCIAL"]
    limite: int | None = Field(None, ge=1, le=200_000)
    modo: Literal["PARALELO", "SEQUENCIAL"] = "PARALELO"
    etiqueta: str | None = Field(None, max_length=80,
                                 description="Rótulo livre (ex.: 'speedup:n=4:rep=1') para agrupar lotes de experimento")


# ------------------------------------------------------------------ fila / ordens
class OrdensRadarIn(BaseModel):
    quantidade: int | None = Field(None, ge=1, le=5000, description="Topo da fila priorizada")
    resultado_analise_ids: list[UUID] | None = None
    probabilidade_minima: float = Field(0.0, ge=0, le=1)
    fiscal_matricula: str | None = None


class OrdensControleIn(BaseModel):
    origem: Literal["METODO_ATUAL", "AMOSTRA_ALEATORIA"]
    quantidade: int = Field(ge=1, le=5000)
    semente: int = Field(20261125, description="Sorteio reprodutível (md5(id||semente))")
    fiscal_matricula: str | None = None


class OrdemPatch(BaseModel):
    fiscal_matricula: str | None = None
    status: Literal["AGUARDANDO", "EM_CAMPO", "CANCELADA"] | None = None


# ------------------------------------------------------------------ laudos
class LaudoIn(BaseModel):
    resultado: Literal["IRREGULARIDADE_CONFIRMADA", "CADASTRO_CORRETO", "INCONCLUSIVO", "IMOVEL_FECHADO"]
    categoria_constatada: Categoria | None = None
    atividade_observada: str | None = None
    observacoes: str | None = None
    evidencias: dict = {}
    realizada_em: datetime | None = None


class DecisaoIn(BaseModel):
    decisao: Literal["RECLASSIFICAR", "MANTER"]
    prazo_contestacao_dias: int = Field(30, ge=0, le=180,
                                        description="Prazo entre a notificação ao usuário e a aplicação")
    observacoes: str | None = None


# ------------------------------------------------------------------ tarifas
class GanhoIn(BaseModel):
    categoria_atual: Categoria
    probabilidades: dict[Categoria, float]
    volume_m3: float = Field(ge=0)
    economias: int = Field(1, ge=1)
    possui_esgoto: bool = True


# ------------------------------------------------------------------ social
class AlertaPatch(BaseModel):
    status: Literal["IDENTIFICADO", "FAMILIA_CONTATADA", "INCLUIDA", "RECUSADA", "INELEGIVEL_APOS_ANALISE"]
    observacao: str | None = None


class CustoIn(BaseModel):
    competencia: date
    item: str
    valor: float = Field(ge=0)
