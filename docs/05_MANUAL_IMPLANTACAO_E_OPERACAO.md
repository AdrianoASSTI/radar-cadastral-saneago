# 05 — Manual de Implantação e Operação

**Radar Cadastral SANEAGO** · SENAI FATESG · Inteligência Artificial · 3º período · 2/2026

> **Escopo.** Instalação via Docker, configuração de variáveis de ambiente, referência da API
> REST, manual do usuário por perfil (analista, fiscal, supervisor, assistente social e gestor),
> operação do dia a dia, solução de problemas e guia de reprodutibilidade científica.

---

## Sumário

1. [Requisitos](#1-requisitos)
2. [Instalação passo a passo](#2-instalação-passo-a-passo)
3. [Variáveis de ambiente](#3-variáveis-de-ambiente)
4. [Endereços e acessos](#4-endereços-e-acessos)
5. [Referência da API REST](#5-referência-da-api-rest)
6. [Manual do usuário](#6-manual-do-usuário)
7. [Operação](#7-operação)
8. [Solução de problemas](#8-solução-de-problemas)
9. [Guia de reprodutibilidade científica](#9-guia-de-reprodutibilidade-científica)
10. [Implantação em produção](#10-implantação-em-produção)

---

## 1. Requisitos

| Item | Mínimo | Recomendado |
|---|---|---|
| Sistema | Windows 10/11 com WSL2, Linux ou macOS | — |
| Docker | Docker Desktop 4.x (Compose v2) | — |
| Memória para o Docker | 6 GB | **8 GB ou mais** (cada réplica de IA carrega PyTorch e o YOLO) |
| CPU | 4 núcleos | 8 ou mais (para o experimento de *speedup*) |
| Disco | 15 GB livres | 25 GB |
| Ferramentas | Git; Git Bash no Windows (para `speedup.sh`) | VS Code |

No Windows, ajuste a memória do Docker em *Settings → Resources* (ou no `.wslconfig`) e
mantenha o Docker Desktop **aberto** enquanto usa o sistema.

## 2. Instalação passo a passo

Todos os comandos abaixo são executados **na pasta raiz do projeto** (a que contém o
`docker-compose.yml`), no terminal do VS Code com Git Bash.

### 2.1 Obter o código e configurar o ambiente

```bash
git clone <url-do-repositorio> radar-cadastral-saneago
cd radar-cadastral-saneago
cp .env.example .env
```

O `.gitattributes` força finais de linha LF nos *scripts* (`.sh`, `.sql`, `.py`,
`Dockerfile`). Se o repositório foi copiado de outra forma, confirme que
`db/init/02_usuarios.sh` está em LF (no VS Code, canto inferior direito).

Edite o `.env` se precisar. Para a demonstração, os valores padrão funcionam. Para ter mais UCs
na fila, use `SEED_EXTRA_UCS=300`.

### 2.2 Subir os serviços

```bash
docker compose up -d --build
```

Na primeira vez, o Docker baixa as imagens e instala as dependências (PyTorch CPU, Ultralytics,
Node). Pode levar de 10 a 20 minutos. Acompanhe com:

```bash
docker compose ps
docker compose logs -f seed      # termina com a contagem de UCs criadas
```

O serviço `seed` roda uma vez e sai com código 0; os demais ficam `Up` (`db` e `rabbitmq`
como `healthy`).

### 2.3 Verificar as garantias do banco

```bash
bash db/tests/verificar_garantias.sh
```

Executa 19 verificações (G1 a G5) e deve terminar sem falhas.

### 2.4 Gerar o acervo de fotos de fachada (modo simulado)

```bash
docker compose --profile experimentos run --rm experiments python gerar_acervo.py
```

Gera as "fotos dos leituristas" simuladas para as UCs do banco, no volume `acervo_fontes`, de
onde o coletor as lê.

### 2.5 Processar o primeiro lote

Abra **http://localhost:5173**, entre como `analista` / `analista123`, vá em
**Processamento** e crie um lote (por exemplo, 50 UCs, modo paralelo). Quando o lote
terminar, a **Fila de vistoria** mostra as UCs ranqueadas.

Pela linha de comando, o equivalente é:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -d "username=analista&password=analista123" | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
curl -s -X POST http://localhost:8000/lotes -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"limite": 50, "modo": "PARALELO"}'
```

### 2.6 (Opcional) Linha de base por regras

```bash
docker compose --profile ferramentas run --rm baseline
```

Grava análises da linha de base, úteis para comparação e para gerar ordens sem o worker de IA.

## 3. Variáveis de ambiente

Arquivo `.env` (modelo em `.env.example`). Nunca versione o `.env` com senhas reais.

| Grupo | Variável | Padrão | Descrição |
|---|---|---|---|
| Banco | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `radar`, `radar_owner`, `radar_owner_dev` | Dono do banco (usado só pelo *seed* e por administração) |
| | `DB_PORT` | 5432 | Porta exposta no host (desenvolvimento) |
| | `DB_PASS_API`, `DB_PASS_API_SOCIAL`, `DB_PASS_COLETOR`, `DB_PASS_IA`, `DB_PASS_IA_SOCIAL`, `DB_PASS_EXPERIMENTO` | `*_dev` | Senhas dos *logins* de cada serviço (mínimo privilégio) |
| Broker | `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_VHOST` | `radar`, `radar_dev`, `radar` | Credenciais do RabbitMQ |
| | `RABBITMQ_MGMT_PORT` | 15672 | Painel de gestão |
| | `FILA_COLETA`, `FILA_ANALISE`, `FILA_RESULTADOS` | `radar.*` | Nomes das filas |
| | `PREFETCH_COUNT` | 4 (coletor); 1 (IA, fixo no compose) | Mensagens não confirmadas por consumidor |
| *Seed* | `SEED_RANDOM_STATE` | 20261125 | Semente da geração (reprodutibilidade) |
| | `SEED_EXTRA_UCS` | 0 | UCs procedurais além das 30 curadas |
| | `PSEUDONIMIZACAO_SALT` | `troque-este-salt` | Sal do *hash* do titular (**trocar em produção**) |
| Imagens | `STORAGE_BACKEND` | `local` | `local` ou `s3` |
| | `RETENCAO_IMAGENS_DIAS` | 45 | Prazo até o expurgo (LGPD) |
| | `FONTES_IMAGEM` | `leiturista,mapillary,geo360` | Ordem de preferência das fontes (Street View é recusado) |
| | `MODO_FONTES` | `simulado` | `simulado` (acervo local) ou `producao` (APIs reais) |
| | `MAPILLARY_TOKEN` | vazio | Token da Graph API v4 (modo produção) |
| | `GEO360_URL_TEMPLATE` | vazio | URL com `{lat}` e `{lon}` acordada com a Prefeitura |
| Workers | `COLLECTOR_REPLICAS`, `AI_WORKER_REPLICAS` | 1, 1 | Réplicas iniciais |
| | `PREFETCH_COLETOR` | 4 | *Prefetch* do coletor |
| | `YOLO_CONF_MIN` | 0,35 | Limiar das classes comerciais |
| | `YOLO_CONF_PRIVACIDADE` | 0,15 | Limiar de rosto e placa (baixo para priorizar o recall da anonimização) |
| | `OMP_NUM_THREADS` | **1** | *Threads* por réplica de IA (1 escala melhor entre réplicas) |
| API / Frontend | `API_PORT`, `FRONTEND_PORT` | 8000, 5173 | Portas no host |
| | `VITE_API_URL` | `/api` | Endereço da API visto pelo navegador (o Nginx repassa `/api`) |
| | `VITE_DADOS_DEMONSTRACAO` | (ligado) | `0` desliga o aviso de localização aproximada nos links de mapa |
| | `CORS_ORIGINS` | `http://localhost:5173` | Só necessário se o frontend chamar a API em outra origem |
| | `JWT_SECRET` | `troque-este-segredo` | Assinatura dos *tokens* (**trocar em produção**) |
| Experimentos | `EXPERIMENTO_N_UCS`, `EXPERIMENTO_N_TESTE`, `EXPERIMENTO_FOLDS` | 2000, 1000, 5 | Tamanho de $W$, de $T$ e número de *folds* |

Parâmetros **normativos** (tarifas, salário mínimo, limites do I1 e do I5, custos do I2) não
ficam no `.env`: estão em `regulatorio.parametro` e `regulatorio.tarifa_*`, com a fonte de cada
valor e a flag `premissa` para hipóteses do grupo.

## 4. Endereços e acessos

| O quê | Endereço | Acesso |
|---|---|---|
| Aplicação web | http://localhost:5173 | contas de demonstração abaixo |
| API — documentação interativa (Swagger) | http://localhost:8000/docs | botão *Authorize* com usuário e senha |
| API — saúde | http://localhost:8000/saude | público |
| RabbitMQ — painel | http://localhost:15672 | `radar` / `radar_dev` |
| PostgreSQL | `localhost:5432`, banco `radar` | `radar_owner` / `radar_owner_dev` |

**Contas de demonstração** (senha = login + `123`):

| Login | Perfil | Telas |
|---|---|---|
| `analista` | Analista | Fila, Vistorias (leitura), Indicadores, Processamento |
| `fiscal` | Fiscal de campo | Vistorias (minhas ordens) |
| `supervisor` | Supervisor | Fila, Vistorias (decisão e aplicação), Indicadores, Processamento, Auditoria |
| `social` | Assistente social | Tarifa Social |
| `gestor` | Gestor | Fila, Indicadores, Processamento, Auditoria |

## 5. Referência da API REST

Base: `http://localhost:8000` (ou `/api` pelo frontend). Autenticação: `POST /auth/login`
(formulário `username`, `password`) devolve `access_token`; envie
`Authorization: Bearer <token>`. A documentação completa, com esquemas e exemplos, é gerada
em `/docs` (OpenAPI).

Perfis abreviados: **A** analista, **F** fiscal, **S** supervisor, **G** gestor,
**AS** assistente social.

### 5.1 Sistema, autenticação e tarifas

| Método | Rota | Perfis | Descrição |
|---|---|---|---|
| POST | `/auth/login` | público | Obter *token* |
| GET | `/auth/eu` | todos | Usuário atual |
| GET | `/saude` | público | Estado do banco e do *broker* (com tamanho das filas) |
| GET | `/tarifas/tabela` | todos (autenticado) | Estrutura tarifária vigente |
| GET | `/tarifas/simular?volume_m3=15` | todos (autenticado) | Fatura em todas as categorias e diferença anual |
| POST | `/tarifas/ganho-esperado` | todos (autenticado) | $\mathbb{E}[G]$ e *score* para probabilidades informadas |
| POST | `/custos` | S, G | Registrar custo real (I2) |
| GET | `/auditoria` | S, G | Trilha de auditoria (filtro por entidade) |

### 5.2 UCs e lotes

| Método | Rota | Perfis | Descrição |
|---|---|---|---|
| GET | `/ucs` | A, S, G | Listar UCs com filtros |
| GET | `/ucs/bairros` | A, S, G | Bairros e faixas de renda |
| GET | `/ucs/{uc_id}` | A, S, G, F | Detalhe: consumo, evidências, última análise, links, simulação tarifária |
| GET | `/ucs/imagens/{imagem_id}` | A, S, G, F | Imagem **anonimizada** (410 após o expurgo) |
| POST | `/ucs/importacao` | A, S | Ingestão em lote de UCs e consumo (idempotente por matrícula; até 5.000 por chamada) |
| POST | `/lotes` | A, S | Criar lote de análise (202, assíncrono) |
| GET | `/lotes` | A, S, G | Listar lotes |
| GET | `/lotes/{lote_id}` | A, S, G | Situação do lote |

Corpo de `POST /lotes`:

```json
{ "limite": 50, "modo": "PARALELO", "etiqueta": "teste",
  "uc_ids": null, "bairro_ids": null, "categorias": ["RESIDENCIAL_NORMAL", "RESIDENCIAL_SOCIAL"] }
```

### 5.3 Fila, ordens e laudos

| Método | Rota | Perfis | Descrição |
|---|---|---|---|
| GET | `/fila` | A, S, G | Fila priorizada; filtros `probabilidade_minima`, `faixa_renda`, `bairro`, `categoria_sugerida`, `limite`, `offset` |
| POST | `/fila/ordens` | A, S | Gerar ordens (origem RADAR) para o topo da fila: `{"quantidade": 10, "probabilidade_minima": 0.5}` |
| POST | `/ordens/controle` | A, S | Ordens do grupo controle ou da amostra aleatória: `{"origem": "AMOSTRA_ALEATORIA", "quantidade": 10, "semente": 20261125}` |
| GET | `/ordens` | A, S, G, F | Listar ordens (o fiscal vê as suas e as não atribuídas, sem origem nem probabilidade) |
| PATCH | `/ordens/{ordem_id}` | A, S, F | Atribuir fiscal ou mudar status |
| POST | `/ordens/{ordem_id}/laudo` | F, S | Registrar laudo |
| GET | `/laudos` | A, S, G | Listar laudos |
| POST | `/laudos/{laudo_id}/decisao` | S | `{"decisao": "RECLASSIFICAR", "prazo_contestacao_dias": 30}` (supervisor diferente do fiscal) |
| POST | `/laudos/{laudo_id}/aplicar` | S | Aplicar a reclassificação após o prazo (chama `fiscalizacao.aplicar_reclassificacao`) |

Corpo de `POST /ordens/{id}/laudo`:

```json
{ "resultado": "IRREGULARIDADE_CONFIRMADA", "categoria_constatada": "COMERCIAL_I",
  "atividade_observada": "Lanchonete aberta ao público", "observacoes": "", "evidencias": {} }
```

### 5.4 Indicadores e Tarifa Social

| Método | Rota | Perfis | Descrição |
|---|---|---|---|
| GET | `/indicadores` | A, S, G | Painel I1–I5 |
| GET | `/indicadores/i1` … `/i5` | A, S, G (I3 também AS) | Cada indicador, com parâmetros de período |
| POST | `/tarifa-social/processar` | AS | Vincular famílias do CadÚnico às UCs e gerar alertas |
| GET | `/tarifa-social/alertas` | AS | Alertas (filtro por status) |
| PATCH | `/tarifa-social/alertas/{id}` | AS | `{"status": "FAMILIA_CONTATADA"}` (também `INCLUIDA`, `RECUSADA`, `INELEGIVEL_APOS_ANALISE`) |
| POST | `/tarifa-social/alertas/{id}/aplicar-inclusao` | AS | Aplicar o desconto (alerta `INCLUIDA`; chama `social.aplicar_inclusao_tarifa_social`) |
| GET | `/tarifa-social/cobertura` | AS | I3 detalhado |

### 5.5 Códigos de resposta usuais

| Código | Significado |
|---|---|
| 401 | *Token* ausente ou expirado (faça login de novo) |
| 403 | Perfil sem permissão (ex.: analista tentando registrar laudo) |
| 404 | Recurso inexistente (ex.: id de imagem usado em `/ucs/{uc_id}`) |
| 409 | Conflito de regra (ex.: ordem já aberta para a UC, laudo já aplicado) |
| 410 | Imagem já expurgada |
| 422 | Corpo inválido (o Swagger mostra o campo com erro) |

## 6. Manual do usuário

### 6.1 Analista: fila de vistoria

1. Em **Processamento**, crie um lote. A tabela atualiza sozinha enquanto há lote ativo.
2. Em **Fila de vistoria**, a lista vem ordenada pelo **ganho anual esperado**. Filtre por
   probabilidade mínima, faixa de renda do bairro ou categoria sugerida.
3. Clique em uma UC para ver:
   * a **fachada anonimizada**, com as caixas dos elementos detectados (passe o mouse para ver a
     confiança) e a legenda com fonte, data e quantidade de rostos e placas borrados;
   * a **explicação**: fatores que aumentam (laranja) e diminuem (azul) a chance de uso
     comercial;
   * as **bases públicas** encontradas (CNPJ, alvará, zona);
   * a **comparação tarifária** e a **série de consumo** (pontos vazados são leituras estimadas);
   * links para **Street View, Google Maps e Geo360**, só para conferência visual. Nos dados de
     demonstração, as coordenadas são aproximadas e o mapa abre perto do bairro, não no imóvel.
4. Gere ordens: **Gerar ordem de vistoria** (uma UC) ou **Gerar ordens para os N primeiros**.
5. Para o grupo de comparação, use **Sortear amostra aleatória** (estima o recall, I4).

A recomendação **não altera nada**. A categoria só muda depois do laudo e da decisão do
supervisor.

### 6.2 Fiscal de campo: laudo

1. Entre como `fiscal`. A tela **Vistorias** lista as ordens abertas, sem probabilidade e sem a
   origem (laudo cego).
2. Abra a ordem, vá ao endereço (**Abrir no mapa**) e registre o que encontrou:
   * **Uso diferente do cadastro**: informe a categoria que corresponde ao uso e a atividade
     observada;
   * **Cadastro correto**, **Inconclusivo** ou **Imóvel fechado**.
3. **Registrar laudo**. Você não decide a categoria: laudos com uso diferente seguem para o
   supervisor.

### 6.3 Supervisor: decisão e aplicação

1. **Decisões pendentes:** para cada laudo, escolha **Reclassificar e notificar** (defina o
   prazo de contestação, padrão 30 dias) ou **Manter cadastro**. O sistema recusa a decisão se
   o supervisor for o mesmo servidor que fez a vistoria.
2. **Aguardando aplicação:** quando o prazo vence, **Aplicar reclassificação**. A mudança fica
   registrada no histórico da UC e na auditoria.
3. **Histórico de laudos:** consulta de todos os laudos.

### 6.4 Assistente social: Tarifa Social

1. **Cruzar CadÚnico com o cadastro**: vincula famílias às UCs e gera alertas para quem é
   elegível (renda per capita até ½ salário mínimo ou BPC) e ainda paga a tarifa normal.
2. Para cada alerta: **Registrar contato**, **Confirmar inclusão**, **Família recusou** ou
   **Inelegível**.
3. Com a inclusão confirmada, **Aplicar desconto na conta** muda a UC para Residencial Social.
4. O resumo no topo mostra a cobertura (I3). Os dados do CadÚnico ficam só neste módulo.

### 6.5 Gestor: indicadores e auditoria

* **Indicadores:** I1 (acerto por origem, com intervalo de confiança), I2 (receita por real
  investido), I3 (cobertura da Tarifa Social), I4 (precisão e recall) e I5 (equidade entre
  faixas de renda, com a paridade de seleção). Os intervalos aparecem como traço sobre as
  barras; com poucas vistorias, o painel avisa que a amostra é insuficiente.
* **Auditoria:** quem criou ou alterou ordens, laudos, alertas, lotes e categorias, e quando.
  O registro não pode ser editado nem apagado.

## 7. Operação

### 7.1 Comandos do dia a dia

```bash
docker compose ps                          # estado dos serviços
docker compose logs -f ai_worker           # acompanhar a IA
docker compose restart ai_worker           # recarregar modelos re-treinados
docker compose up -d --scale ai_worker=2 --scale collector=2   # escalar
docker compose stop                        # parar mantendo os dados
docker compose down                        # remover contêineres (volumes ficam)
docker compose down -v                     # APAGA os volumes (banco, imagens, modelos)
```

Depois de mudar `SEED_EXTRA_UCS`, é preciso recriar o banco (`down -v` e `up -d --build`),
porque o *seed* só roda na primeira inicialização do volume.

### 7.2 Monitoramento

* `GET /saude` mostra o banco, o *broker* e o tamanho de cada fila.
* No painel do RabbitMQ, filas `*.dlq` com mensagens indicam UCs que falharam três vezes;
  inspecione o conteúdo e o log do worker.
* A tela **Processamento** mostra processadas, falhas e status de cada lote.

### 7.3 Ciclo mensal sugerido

1. Importar UCs e consumo do mês (`POST /ucs/importacao`).
2. Criar um lote com todas as residenciais.
3. Conferir a paridade de seleção (I5) **antes** de emitir ordens.
4. Emitir ordens do Radar, do grupo controle e da amostra aleatória.
5. Após as vistorias, revisar I1, I4 e I5; se o I5 passar de 1,25, revisar o modelo.

### 7.4 Backup

```bash
docker compose exec -T db pg_dump -U radar_owner -d radar -Fc > backup_radar.dump
```

As imagens não precisam de *backup* (são temporárias por desenho, LGPD).

## 8. Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `failed to connect to the docker API` / `dockerDesktopLinuxEngine` | Docker Desktop fechado | Abra o Docker Desktop e espere "Engine running" |
| `seed` falha com `\r` ou `bad interpreter` | *Script* em CRLF | Converta `db/init/02_usuarios.sh` para LF e recrie o volume (`down -v`) |
| `role ... already exists` no início | Volume antigo com *init* parcial | `docker compose down -v` e suba de novo |
| No Git Bash aparece `[200~` ao colar | *Bracketed paste* | Cole com o botão direito, ou rode `bind 'set enable-bracketed-paste off'` |
| Fila vazia | Nenhum lote processado | Crie um lote em **Processamento** (ou rode a linha de base) |
| Fila sem fachada | Acervo não gerado | Rode `gerar_acervo.py` (seção 2.4) e processe outro lote |
| `403` ao registrar laudo | Perfil errado | Entre como `fiscal` (ou `supervisor`) |
| Decisão recusada | Supervisor igual ao fiscal | Outro servidor deve decidir (segregação de funções) |
| Imagem com `410` | Imagem já expurgada (45 dias) | Processar novo lote para nova captura |
| Rota nova não aparece no `/docs` | Navegador com cache ou API antiga | `Ctrl+F5`; se persistir, `docker compose up -d --build api` |
| Computador lento, memória acima de 85% | Réplicas de IA demais para a RAM | Volte a 1 réplica; feche programas; aumente a memória do Docker |
| Tela branca no frontend | Build antigo ou `VITE_API_URL` errado | Confira `VITE_API_URL=/api` no `.env` e `docker compose up -d --build frontend` |
| Link do mapa abre outro endereço | Coordenadas sintéticas (centroide do bairro + deslocamento) | Esperado nos dados de demonstração |
| `psql` mostra acentos quebrados | Codificação do terminal | `chcp 65001` no Windows ou `PGCLIENTENCODING=UTF8` |

## 9. Guia de reprodutibilidade científica

### 9.1 O que garante a reprodução

| Elemento | Como é controlado |
|---|---|
| Versões | Imagens Docker com versões fixas (`postgis/postgis:16-3.4`, `rabbitmq:3.13`, `torch 2.15.0` CPU, `ultralytics 8.4.219`, `xgboost 3.4.1`, `opencv 4.10.0.84`); `package-lock.json` no frontend |
| Dados | Gerados por semente (`SEED_RANDOM_STATE`, `--semente`), sem dependência de dados externos |
| Código de atributos | Um único módulo (`radar_comum.features`) em produção e nos experimentos |
| Modelos | Pesos versionados em `services/ai_worker/modelos/`, com metadados (atributos, rótulos, hiperparâmetros, semente, data, métricas) |
| Ambiente registrado | `benchmark.json` grava Python, plataforma, versões e CPU |
| Resultados | JSON, Markdown e LaTeX gerados por *script*, sem edição manual |

### 9.2 Roteiro completo

```bash
# 1. Ambiente
cp .env.example .env                       # SEED_EXTRA_UCS=300 para o speedup
docker compose up -d --build
bash db/tests/verificar_garantias.sh

# 2. Detector e classificador (opcional: os pesos já vêm no repositório)
docker compose --profile experimentos run --rm experiments python treinar_yolo.py
docker compose --profile experimentos run --rm experiments python benchmark.py --salvar-modelo /models
docker compose restart ai_worker

# 3. Benchmark (tabelas 1–3 do artigo)
docker compose --profile experimentos run --rm experiments

# 4. Speedup (Git Bash; ajuste a lista de réplicas à memória disponível)
docker compose --profile experimentos run --rm experiments python gerar_acervo.py
bash experiments/speedup.sh 300 "1 2 3" 3
docker compose --profile experimentos run --rm experiments python relatorio_speedup.py
```

### 9.3 Variação esperada

* **Benchmark:** determinístico para a mesma semente, versão das bibliotecas e CPU. Diferenças
  de ponto flutuante entre arquiteturas podem alterar a terceira casa decimal.
* **Detector:** o treino em CPU tem pequenas variações entre máquinas (ordem de operações);
  o mAP deve ficar dentro de ±0,01.
* ***Speedup*:** depende da máquina e da carga do sistema. Reporte sempre a máquina, a memória
  do Docker, `OMP_NUM_THREADS`, a mediana e o IQR, e liste todas as repetições.

## 10. Implantação em produção

Itens obrigatórios antes de usar dados reais:

1. Trocar **todas** as senhas, o `JWT_SECRET` e o `PSEUDONIMIZACAO_SALT`; usar um cofre de
   segredos.
2. Substituir os usuários de demonstração pelo provedor de identidade da concessionária
   (OIDC/LDAP).
3. Não expor as portas do banco e do RabbitMQ; servir o frontend com HTTPS.
4. `MODO_FONTES=producao`, com `MAPILLARY_TOKEN` e o acordo do Geo360 (`GEO360_URL_TEMPLATE`).
5. Rotular uma amostra de fotos reais e refazer o *fine-tuning* do detector; retreinar o
   classificador com laudos reais.
6. Validar as premissas tarifárias (`regulatorio.parametro` com `premissa = true`) com a
   concessionária.
7. Registrar o tratamento de dados (RIPD/DPIA), as bases legais e o acordo de uso do CadÚnico.
8. Resolver a licença do Ultralytics (AGPL-3.0) para uso comercial.
9. Em Kubernetes: um *Deployment* por serviço, *Horizontal Pod Autoscaler* (ou KEDA) pelo
   tamanho da fila `radar.analise`, PostgreSQL gerenciado e RabbitMQ com filas *quorum*.
