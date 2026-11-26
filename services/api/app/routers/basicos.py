"""Autenticação, saúde, tarifas e auditoria."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from radar_comum.ganho import ganho_esperado

from ..db import conexao
from ..schemas import CustoIn, GanhoIn
from ..seguranca import Usuario, autenticar, emitir_token, exigir, usuario_atual
from ..servicos.tarifas import tabela_vigente

router = APIRouter()


# ------------------------------------------------------------------- auth
@router.post("/auth/login", tags=["autenticação"], summary="Obter token (usuário/senha)")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    u = autenticar(form.username, form.password)
    if not u:
        raise HTTPException(401, "Usuário ou senha inválidos")
    return {"access_token": emitir_token(u), "token_type": "bearer", "usuario": u}


@router.get("/auth/eu", tags=["autenticação"])
async def eu(u: Usuario = Depends(usuario_atual)):
    return u


# ------------------------------------------------------------------- saúde
@router.get("/saude", tags=["sistema"], summary="Estado do banco e do broker")
async def saude(request: Request):
    estado = {"api": "ok"}
    for nome, pool in (("banco", request.app.state.pool), ("banco_social", request.app.state.pool_social)):
        try:
            async with pool.connection(timeout=3) as c:
                await c.execute("SELECT 1")
            estado[nome] = "ok"
        except Exception as e:  # noqa: BLE001
            estado[nome] = f"erro: {e.__class__.__name__}"
    m = request.app.state.mensageria
    estado["rabbitmq"] = "ok" if m.conectado else "desconectado"
    if m.conectado:
        estado["filas"] = await m.contagem_filas()
    return estado


# ------------------------------------------------------------------- tarifas
@router.get("/tarifas/tabela", tags=["tarifas"], summary="Estrutura tarifária vigente")
async def tabela(conn=Depends(conexao)):
    t = await tabela_vigente(conn)
    return {"vigencia": t.vigencia, "fonte": t.fonte, "basica": t.basica,
            "faixas": {c: [f.__dict__ for f in fx] for c, fx in t.faixas.items()},
            "premissas": {"comercial_ii_limite_m3": t.limite_comercial_ii_m3,
                          "residencial_social_transbordo": t.categoria_transbordo_social}}


@router.get("/tarifas/simular", tags=["tarifas"], summary="Fatura mensal em todas as categorias")
async def simular(volume_m3: float = Query(ge=0), economias: int = Query(1, ge=1),
                  possui_esgoto: bool = True, conn=Depends(conexao)):
    t = await tabela_vigente(conn)
    faturas = t.comparar(volume_m3, economias, possui_esgoto)
    base = faturas["RESIDENCIAL_NORMAL"]
    return {"volume_m3": volume_m3, "economias": economias, "possui_esgoto": possui_esgoto,
            "faturas_mensais": faturas,
            "diferenca_anual_vs_residencial_normal": {c: (v - base) * 12 for c, v in faturas.items()}}


@router.post("/tarifas/ganho-esperado", tags=["tarifas"], summary="E[G] e score para probabilidades dadas")
async def ganho(dados: GanhoIn, conn=Depends(conexao)):
    t = await tabela_vigente(conn)
    return ganho_esperado(t, dados.categoria_atual, dados.probabilidades, dados.volume_m3,
                          dados.economias, dados.possui_esgoto).como_dict()


@router.post("/custos", tags=["indicadores"], summary="Registrar custo real da solução (usado no I2)",
             dependencies=[Depends(exigir("SUPERVISOR", "GESTOR"))])
async def registrar_custo(c: CustoIn, conn=Depends(conexao)):
    await conn.execute("""INSERT INTO fiscalizacao.custo_solucao (competencia, item, valor)
                          VALUES (date_trunc('month', %s::date), %s, %s)
                          ON CONFLICT (competencia, item) DO UPDATE SET valor = EXCLUDED.valor""",
                       (c.competencia, c.item, c.valor))
    return {"ok": True}


# ------------------------------------------------------------------- auditoria
@router.get("/auditoria", tags=["auditoria"], dependencies=[Depends(exigir("SUPERVISOR", "GESTOR"))])
async def auditoria(entidade: str | None = None, entidade_id: str | None = None,
                    limite: int = Query(100, le=1000), conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT id, ocorrido_em, ator, papel_db, acao, entidade, entidade_id, detalhes
        FROM auditoria.evento
        WHERE (%(e)s::text IS NULL OR entidade = %(e)s) AND (%(i)s::text IS NULL OR entidade_id = %(i)s)
        ORDER BY id DESC LIMIT %(l)s""", {"e": entidade, "i": entidade_id, "l": limite})
    return await cur.fetchall()


