"""Configuração da API (variáveis de ambiente; ver .env.example)."""

from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Usuários de demonstração (MVP). Em produção: integrar ao provedor de identidade
# da concessionária (OIDC/LDAP). Formato: login -> {senha, nome, perfil, matricula}.
USUARIOS_DEMO_PADRAO = {
    "analista":   {"senha": "analista123",   "nome": "Ana Analista",      "perfil": "ANALISTA",          "matricula": "AN-0010"},
    "fiscal":     {"senha": "fiscal123",     "nome": "Fábio Fiscal",      "perfil": "FISCAL",            "matricula": "FIS-0200"},
    "supervisor": {"senha": "supervisor123", "nome": "Sílvia Supervisora", "perfil": "SUPERVISOR",       "matricula": "SUP-0042"},
    "social":     {"senha": "social123",     "nome": "Sofia Assistente",  "perfil": "ASSISTENTE_SOCIAL", "matricula": "AS-0007"},
    "gestor":     {"senha": "gestor123",     "nome": "Gustavo Gestor",    "perfil": "GESTOR",            "matricula": "GE-0001"},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql://usr_api:api_dev@localhost:5432/radar"
    database_url_social: str = "postgresql://usr_api_social:api_social_dev@localhost:5432/radar"
    rabbitmq_url: str = "amqp://radar:radar_dev@localhost:5672/radar"

    jwt_secret: str = "troque-este-segredo"
    jwt_expira_min: int = 480
    cors_origins: str = "http://localhost:5173"
    usuarios_demo: str = Field(default_factory=lambda: json.dumps(USUARIOS_DEMO_PADRAO))
    pseudonimizacao_salt: str = "troque-este-salt"

    geo360_base_url: str = "https://portal-goiania.geo360.com.br/"
    pool_min: int = 1
    pool_max: int = 10

    @property
    def usuarios(self) -> dict:
        return json.loads(self.usuarios_demo)

    @property
    def origens_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def settings() -> Settings:
    return Settings()
