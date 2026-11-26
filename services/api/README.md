# API — Radar Cadastral SANEAGO (Etapa 2)

FastAPI + PostgreSQL/PostGIS + RabbitMQ. Documentação interativa em **http://localhost:8000/docs**.

## Perfis de demonstração (senha = login + `123`)

| Login | Perfil | Pode |
|---|---|---|
| `analista` | ANALISTA | UCs, ingestão, lotes, fila, gerar ordens, indicadores |
| `fiscal` | FISCAL | ver ordens e registrar laudo (não decide reclassificação) |
| `supervisor` | SUPERVISOR | tudo do analista + decidir/aplicar reclassificação + auditoria |
| `gestor` | GESTOR | leitura: indicadores, fila, auditoria |
| `social` | ASSISTENTE_SOCIAL | **somente** o módulo Tarifa Social (único com acesso ao CadÚnico) |

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/login` | token JWT (form `username`/`password`) |
| GET | `/saude` | banco, banco social, RabbitMQ e mensagens por fila |
| GET | `/ucs`, `/ucs/bairros`, `/ucs/{id}` | consulta; detalhe com consumo, CNPJ/alvará a 30 m, zona, última análise, detecções, links Street View/Geo360, simulação tarifária |
| GET | `/ucs/imagens/{imagem_id}` | imagem de fachada JÁ anonimizada (com token; 410 se expurgada) |
| POST | `/ucs/importacao` | ingestão em lote (idempotente por matrícula; titular pseudonimizado) |
| GET | `/tarifas/tabela`, `/tarifas/simular` | estrutura SANEAGO 2026 e fatura em todas as categorias |
| POST | `/tarifas/ganho-esperado` | E[G] e score para probabilidades informadas |
| POST/GET | `/lotes`, `/lotes/{id}` | cria lote e publica 1 mensagem por UC (`PARALELO` ou `SEQUENCIAL`, `etiqueta` opcional); progresso e vazão |
| GET | `/fila` | fila priorizada por Ganho Esperado (filtros de probabilidade, faixa de renda, bairro) |
| POST | `/fila/ordens` | ordens RADAR a partir do topo da fila |
| POST | `/ordens/controle` | grupo controle (`METODO_ATUAL`) ou `AMOSTRA_ALEATORIA` (recall), sorteio reprodutível |
| GET/PATCH | `/ordens`, `/ordens/{id}` | listar, atribuir fiscal, mudar status |
| POST | `/ordens/{id}/laudo` | laudo do fiscal |
| POST | `/laudos/{id}/decisao` | supervisor: `RECLASSIFICAR` (abre prazo de contestação) ou `MANTER` |
| POST | `/laudos/{id}/aplicar` | aplica após o prazo (função do banco; idempotência garantida) |
| GET | `/indicadores`, `/indicadores/i1` … `/i5` | indicadores dinâmicos com IC 95% de Wilson |
| POST | `/custos` | custo real da solução (substitui a premissa no I2) |
| POST | `/tarifa-social/processar` | vincula CadÚnico → UC e gera alertas |
| GET/PATCH | `/tarifa-social/alertas[/{id}]` | acompanhamento (contatada, incluída, recusada…) |
| POST | `/tarifa-social/alertas/{id}/aplicar-inclusao` | muda a UC para Residencial Social (alerta INCLUIDA; elegibilidade reconferida) |
| GET | `/auditoria` | trilha imutável de eventos |

## Fluxo de demonstração (em /docs)

1. `supervisor` → `GET /fila` (depois de rodar o baseline).
2. `analista` → `POST /fila/ordens {"quantidade": 3}` e `POST /ordens/controle {"origem": "AMOSTRA_ALEATORIA", "quantidade": 3}`.
3. `fiscal` → `GET /ordens` e `POST /ordens/{id}/laudo`.
4. `supervisor` → `POST /laudos/{id}/decisao {"decisao": "RECLASSIFICAR", "prazo_contestacao_dias": 0}` → `POST /laudos/{id}/aplicar`.
5. `social` → `POST /tarifa-social/processar` → `GET /tarifa-social/alertas`.
6. `gestor` → `GET /indicadores`.

## Testes

```bash
# unitários (sem banco)
docker compose exec api python -m pytest -q tests/test_tarifas.py
```
O teste de integração (`tests/test_fluxo_api.py`) **altera o banco**; rode-o só em banco descartável
com `RADAR_TEST_INTEGRACAO=1`.
