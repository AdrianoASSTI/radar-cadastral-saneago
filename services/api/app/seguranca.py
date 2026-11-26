"""
Autenticação (JWT) e autorização por perfil.

Perfis e o que cada um pode fazer (o banco reforça com papéis próprios):
  ANALISTA           UCs, ingestão, lotes de análise, fila, criação de ordens, indicadores
  FISCAL             ordens atribuídas e registro de laudo (não decide reclassificação)
  SUPERVISOR         tudo do analista + decisão/aplicação de reclassificação + auditoria
  GESTOR             leitura: indicadores, fila, auditoria
  ASSISTENTE_SOCIAL  APENAS o módulo Tarifa Social (único com acesso ao CadÚnico)
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from .config import settings

PERFIS = ("ANALISTA", "FISCAL", "SUPERVISOR", "GESTOR", "ASSISTENTE_SOCIAL")
esquema_oauth = OAuth2PasswordBearer(tokenUrl="/auth/login")


class Usuario(BaseModel):
    login: str
    nome: str
    perfil: str
    matricula: str


def autenticar(login: str, senha: str) -> Usuario | None:
    u = settings().usuarios.get(login)
    if not u or not hmac.compare_digest(u["senha"].encode(), senha.encode()):
        return None
    return Usuario(login=login, nome=u["nome"], perfil=u["perfil"], matricula=u["matricula"])


def emitir_token(u: Usuario) -> str:
    agora = datetime.now(timezone.utc)
    payload = {"sub": u.login, "nome": u.nome, "perfil": u.perfil, "matricula": u.matricula,
               "iat": agora, "exp": agora + timedelta(minutes=settings().jwt_expira_min)}
    return jwt.encode(payload, settings().jwt_secret, algorithm="HS256")


async def usuario_atual(token: str = Depends(esquema_oauth)) -> Usuario:
    try:
        p = jwt.decode(token, settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado",
                            headers={"WWW-Authenticate": "Bearer"})
    return Usuario(login=p["sub"], nome=p["nome"], perfil=p["perfil"], matricula=p["matricula"])


def exigir(*perfis: str):
    """Dependência: libera apenas os perfis informados."""
    async def _verificar(u: Usuario = Depends(usuario_atual)) -> Usuario:
        if u.perfil not in perfis:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Perfil {u.perfil} sem permissão (requer: {', '.join(perfis)})")
        return u
    return _verificar


# Atalhos usados nos routers
OPERACAO = ("ANALISTA", "SUPERVISOR")
LEITURA_GESTAO = ("ANALISTA", "SUPERVISOR", "GESTOR")
CAMPO = ("FISCAL", "SUPERVISOR")
SOCIAL = ("ASSISTENTE_SOCIAL",)
