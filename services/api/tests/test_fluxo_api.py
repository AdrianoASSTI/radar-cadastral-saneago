"""
Teste de integração ponta a ponta da API (ALTERA O BANCO — use um banco descartável).

Pré-requisitos: banco com schema + seed + baseline_regras executado, RabbitMQ no ar e
as variáveis DATABASE_URL, DATABASE_URL_SOCIAL e RABBITMQ_URL apontando para eles.
Ative com RADAR_TEST_INTEGRACAO=1.

Roteiro (espelha o processo real e as garantias éticas):
  fila → ordens RADAR + amostra aleatória → laudos → decisão → aplicação (G1)
  tarifa social (perfil e conexão próprios, G2) → indicadores I1–I5
"""

import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RADAR_TEST_INTEGRACAO") != "1",
                                reason="defina RADAR_TEST_INTEGRACAO=1 (banco descartável)")


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        tok = {}
        for login in ("analista", "fiscal", "supervisor", "social", "gestor"):
            r = c.post("/auth/login", data={"username": login, "password": f"{login}123"})
            assert r.status_code == 200, r.text
            tok[login] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        c.tok = tok
        yield c


def test_saude_e_autenticacao(api):
    import time
    for _ in range(20):                       # broker conecta em segundo plano
        s = api.get("/saude").json()
        if s.get("rabbitmq") == "ok":
            break
        time.sleep(0.5)
    assert s["banco"] == "ok" and s["banco_social"] == "ok" and s["rabbitmq"] == "ok", s
    assert api.get("/ucs").status_code == 401
    assert api.post("/auth/login", data={"username": "fiscal", "password": "errada"}).status_code == 401


def test_ucs_e_detalhe(api):
    r = api.get("/ucs", headers=api.tok["analista"]).json()
    assert r["total"] >= 30
    d = api.get("/ucs/13", headers=api.tok["analista"]).json()
    assert len(d["consumo"]) == 24
    assert d["links"]["street_view"].startswith("https://www.google.com/maps/@?api=1&map_action=pano")
    assert d["bases_publicas"]["cnpjs_ate_30m"], "lava-jato tem CNPJ no endereço"
    assert d["ultima_analise"]["modelo_versao"]


def test_simulacao_tarifaria(api):
    r = api.get("/tarifas/simular?volume_m3=15", headers=api.tok["gestor"]).json()
    assert r["faturas_mensais"]["RESIDENCIAL_NORMAL"] == 197.86
    assert r["faturas_mensais"]["COMERCIAL_I"] == 404.66


def test_lote_publica_no_broker(api):
    r = api.post("/lotes", json={"limite": 5}, headers=api.tok["analista"])
    assert r.status_code == 202, r.text
    assert r.json()["mensagens_publicadas"] == 5
    assert api.post("/lotes", json={"limite": 1}, headers=api.tok["fiscal"]).status_code == 403
    r = api.post("/lotes", json={"limite": 2, "modo": "SEQUENCIAL"}, headers=api.tok["analista"])
    assert r.json()["fila"] == "radar.coleta.seq"


def test_segregacao_tarifa_social(api):
    for perfil in ("fiscal", "analista", "supervisor", "gestor"):
        assert api.get("/tarifa-social/alertas", headers=api.tok[perfil]).status_code == 403, perfil
    assert api.get("/tarifa-social/alertas", headers=api.tok["social"]).status_code == 200
    # gestor vê só o agregado do I3
    assert api.get("/indicadores/i3", headers=api.tok["gestor"]).status_code == 200


def test_tarifa_social_vinculo_alerta_e_inclusao(api):
    h = api.tok["social"]
    r = api.post("/tarifa-social/processar", headers=h).json()
    assert r["familias_vinculadas"] == 5 and r["alertas_gerados"] == 3, r
    alertas = api.get("/tarifa-social/alertas", headers=h).json()
    ucs = {a["uc_id"] for a in alertas}
    assert ucs == {17, 22, 28}, "elegíveis fora da Tarifa Social (BPC, renda baixa, endereço com grafia diferente)"
    a22 = next(a for a in alertas if a["uc_id"] == 22)
    assert a22["evidencia"]["vinculo_metodo"] in ("ENDERECO_SIMILAR", "PROXIMIDADE_GEO")

    # inclusão só depois de INCLUIDA
    assert api.post(f"/tarifa-social/alertas/{a22['id']}/aplicar-inclusao", headers=h).status_code == 409
    api.patch(f"/tarifa-social/alertas/{a22['id']}", json={"status": "INCLUIDA",
              "observacao": "Família contatada; documentação conferida"}, headers=h)
    r = api.post(f"/tarifa-social/alertas/{a22['id']}/aplicar-inclusao", headers=h)
    assert r.status_code == 200, r.text
    assert api.get("/ucs/22", headers=api.tok["analista"]).json()["categoria_atual"] == "RESIDENCIAL_SOCIAL"
    i3 = api.get("/indicadores/i3", headers=api.tok["gestor"]).json()
    assert i3["valor"] == 0.5        # (UC 26 + UC 22) / 4 famílias elegíveis


def test_fluxo_vistoria_completo(api):
    an, fi, su = api.tok["analista"], api.tok["fiscal"], api.tok["supervisor"]
    fila = api.get("/fila?limite=5", headers=an).json()
    assert fila["itens"][0]["ganho_esperado_anual"] >= fila["itens"][1]["ganho_esperado_anual"]

    r = api.post("/fila/ordens", json={"quantidade": 3}, headers=an).json()
    assert r["ordens_criadas"] == 3
    assert api.post("/ordens/controle", json={"origem": "AMOSTRA_ALEATORIA", "quantidade": 3},
                    headers=an).json()["ordens_criadas"] == 3

    ordens = {o["uc_id"]: o for o in api.get("/ordens?origem=RADAR&status=AGUARDANDO", headers=fi).json()}
    top = sorted(ordens.values(), key=lambda o: o["posicao_ranking"])
    o1, o2, o3 = top[0], top[1], top[2]

    # Fiscal registra laudos: 2 confirmações e 1 falso positivo
    l1 = api.post(f"/ordens/{o1['id']}/laudo", json={"resultado": "IRREGULARIDADE_CONFIRMADA",
                  "categoria_constatada": o1["categoria_sugerida"], "atividade_observada": "Atividade econômica no local"},
                  headers=fi).json()
    assert l1["decisao"] == "ENCAMINHAR_ANALISE"
    l2 = api.post(f"/ordens/{o2['id']}/laudo", json={"resultado": "IRREGULARIDADE_CONFIRMADA",
                  "categoria_constatada": "COMERCIAL_I"}, headers=fi).json()
    api.post(f"/ordens/{o3['id']}/laudo", json={"resultado": "CADASTRO_CORRETO"}, headers=fi)

    # Fiscal não decide reclassificação
    assert api.post(f"/laudos/{l1['laudo_id']}/decisao", json={"decisao": "RECLASSIFICAR"},
                    headers=fi).status_code == 403

    # Supervisor decide; com prazo aberto, a aplicação é recusada pelo banco
    api.post(f"/laudos/{l2['laudo_id']}/decisao", json={"decisao": "RECLASSIFICAR", "prazo_contestacao_dias": 30},
             headers=su)
    r = api.post(f"/laudos/{l2['laudo_id']}/aplicar", headers=su)
    assert r.status_code == 409 and "contestação" in r.json()["detail"]

    # Prazo zero (demonstração) → aplica e registra histórico
    api.post(f"/laudos/{l1['laudo_id']}/decisao", json={"decisao": "RECLASSIFICAR", "prazo_contestacao_dias": 0},
             headers=su)
    r = api.post(f"/laudos/{l1['laudo_id']}/aplicar", headers=su)
    assert r.status_code == 200, r.text
    assert r.json()["historico"]["categoria_nova"] == o1["categoria_sugerida"]
    assert api.post(f"/laudos/{l1['laudo_id']}/aplicar", headers=su).status_code in (403, 409)

    aud = api.get("/auditoria?entidade=cadastro.unidade_consumidora", headers=su).json()
    assert any(e["acao"] == "RECLASSIFICACAO" and e["ator"] == "supervisor" for e in aud)


def test_indicadores(api):
    r = api.get("/indicadores", headers=api.tok["gestor"]).json()
    i1 = r["I1"]["grupos"]["RADAR"]
    assert (i1["sucessos"], i1["n"]) == (2, 3) and i1["ic95"][0] < i1["valor"] < i1["ic95"][1]
    assert r["I2"]["receita_recuperada_anual"] > 0 and r["I2"]["custo"] > 0
    assert r["I3"]["valor"] == 0.5
    assert r["I4"]["k"] >= 1 and r["I4"]["precisao_at_k"]["n"] >= 1
    assert set(r["I5"]["paridade_de_selecao"]["por_faixa"]) == {"ALTA", "MEDIA_ALTA", "MEDIA", "BAIXA"}
    assert r["I5"]["situacao"] in ("amostra_insuficiente", "dentro_do_limite", "revisar_modelo")
