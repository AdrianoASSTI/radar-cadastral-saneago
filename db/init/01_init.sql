-- =============================================================================
-- Radar Cadastral SANEAGO — Schema PostgreSQL 16 + PostGIS 3.4
-- -----------------------------------------------------------------------------
-- Executado automaticamente pelo entrypoint do contêiner `db` na primeira
-- inicialização do volume (docker-entrypoint-initdb.d).
--
-- Organização em schemas por FINALIDADE (princípio da finalidade, LGPD art. 6º, I):
--
--   regulatorio   tabela tarifária SANEAGO 2026 e parâmetros normativos
--   cadastro      UCs, consumo, território (bairros/setores)
--   publico       bases públicas: CNPJ, alvarás, zoneamento
--   social        CadÚnico/BPC — ACESSO RESTRITO, só para Tarifa Social
--   analise       lotes, imagens anonimizadas, detecções, scores e XAI
--   fiscalizacao  ordens de vistoria, laudos humanos, custos (I1, I2)
--   auditoria     trilha de eventos imutável (append-only)
--   experimento   gabarito sintético e execuções de benchmark (fora da produção)
--
-- Garantias implementadas no próprio banco (não dependem do código da API):
--   G1. A categoria tarifária de uma UC só muda via laudo humano aprovado
--       (trigger + função SECURITY DEFINER). Nenhum papel de IA tem UPDATE.
--   G2. Dados do CadÚnico ficam em schema que os papéis de fiscalização e de
--       modelo preditivo não conseguem ler.
--   G3. Só imagens anonimizadas são registradas (CHECK) e toda imagem tem
--       data de expurgo (retenção mínima).
--   G4. Fonte "Street View" não existe no domínio de fontes de inferência.
--   G5. Auditoria é append-only (UPDATE/DELETE bloqueados).
-- =============================================================================

\set ON_ERROR_STOP on

SET client_encoding = 'UTF8';
SET timezone = 'America/Sao_Paulo';

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- similaridade de endereços (vínculo CadÚnico x UC)
CREATE EXTENSION IF NOT EXISTS unaccent;   -- normalização de logradouros

CREATE SCHEMA regulatorio;
CREATE SCHEMA cadastro;
CREATE SCHEMA publico;
CREATE SCHEMA social;
CREATE SCHEMA analise;
CREATE SCHEMA fiscalizacao;
CREATE SCHEMA auditoria;
CREATE SCHEMA experimento;

COMMENT ON SCHEMA social IS
  'Dados do CadÚnico/BPC. Uso EXCLUSIVO para concessão de Tarifa Social (Lei 14.898/2024). '
  'Proibido para fiscalização ou cobrança. Acesso apenas pelo papel radar_social.';

-- =============================================================================
-- 1. TIPOS DE DOMÍNIO
-- =============================================================================

CREATE TYPE regulatorio.categoria_tarifaria AS ENUM (
  'RESIDENCIAL_SOCIAL',
  'RESIDENCIAL_NORMAL',
  'COMERCIAL_I',        -- médio e grande porte
  'COMERCIAL_II',       -- pequeno porte
  'INDUSTRIAL',
  'PUBLICA'
);

CREATE TYPE cadastro.faixa_renda AS ENUM ('ALTA', 'MEDIA_ALTA', 'MEDIA', 'BAIXA');
CREATE TYPE cadastro.tipo_leitura AS ENUM ('REAL', 'ESTIMADA');

-- G4: Street View NÃO é fonte válida para inferência (Termos do Google Maps Platform).
CREATE TYPE analise.fonte_imagem AS ENUM ('LEITURISTA', 'MAPILLARY', 'GEO360_GOIANIA', 'SINTETICA');
CREATE TYPE analise.status_lote AS ENUM ('PENDENTE', 'EM_PROCESSAMENTO', 'CONCLUIDO', 'CONCLUIDO_COM_FALHAS', 'FALHOU');
CREATE TYPE analise.modo_execucao AS ENUM ('PARALELO', 'SEQUENCIAL');

CREATE TYPE publico.situacao_cnpj AS ENUM ('ATIVA', 'SUSPENSA', 'INAPTA', 'BAIXADA', 'NULA');
CREATE TYPE publico.porte_empresa AS ENUM ('MEI', 'ME', 'EPP', 'DEMAIS');
CREATE TYPE publico.uso_zona AS ENUM ('PREDOMINANTEMENTE_RESIDENCIAL', 'MISTO', 'COMERCIAL_SERVICOS', 'INDUSTRIAL');

CREATE TYPE fiscalizacao.origem_ordem AS ENUM (
  'RADAR',              -- indicada pelo ranking do sistema (grupo tratamento)
  'METODO_ATUAL',       -- rotina atual da concessionária (grupo controle, I1)
  'AMOSTRA_ALEATORIA'   -- sorteio para estimar recall (I4)
);
CREATE TYPE fiscalizacao.status_ordem AS ENUM ('AGUARDANDO', 'EM_CAMPO', 'CONCLUIDA', 'CANCELADA');
CREATE TYPE fiscalizacao.resultado_vistoria AS ENUM (
  'IRREGULARIDADE_CONFIRMADA', 'CADASTRO_CORRETO', 'INCONCLUSIVO', 'IMOVEL_FECHADO'
);
CREATE TYPE fiscalizacao.decisao_laudo AS ENUM ('MANTER', 'RECLASSIFICAR', 'ENCAMINHAR_ANALISE');

CREATE TYPE social.criterio_elegibilidade AS ENUM ('RENDA_ATE_MEIO_SM', 'BPC');
CREATE TYPE social.status_alerta AS ENUM ('IDENTIFICADO', 'FAMILIA_CONTATADA', 'INCLUIDA', 'RECUSADA', 'INELEGIVEL_APOS_ANALISE');
CREATE TYPE social.metodo_vinculo AS ENUM ('ENDERECO_EXATO', 'ENDERECO_SIMILAR', 'PROXIMIDADE_GEO', 'MANUAL');

-- =============================================================================
-- 2. REGULATÓRIO — Estrutura tarifária SANEAGO 2026
-- Fonte: Resolução Conjunta AGR/ARM nº 1/2026, Anexo Único (vigência 01/04/2026).
-- Tarifas progressivas por faixa (R$/m³): água + esgoto (coleta/afastamento + tratamento).
-- =============================================================================

CREATE TABLE regulatorio.tarifa_basica (
  vigencia_inicio  date NOT NULL,
  categoria        regulatorio.categoria_tarifaria NOT NULL,
  valor_mensal     numeric(10,2) NOT NULL CHECK (valor_mensal >= 0),  -- custo mínimo fixo por economia
  fonte            text NOT NULL,
  PRIMARY KEY (vigencia_inicio, categoria)
);

CREATE TABLE regulatorio.tarifa_faixa (
  id                 integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vigencia_inicio    date NOT NULL,
  categoria          regulatorio.categoria_tarifaria NOT NULL,
  faixa_min_m3       integer NOT NULL CHECK (faixa_min_m3 >= 1),
  faixa_max_m3       integer CHECK (faixa_max_m3 IS NULL OR faixa_max_m3 >= faixa_min_m3),  -- NULL = sem teto
  agua_m3            numeric(8,2) NOT NULL,
  esgoto_coleta_m3   numeric(8,2) NOT NULL,
  esgoto_tratam_m3   numeric(8,2) NOT NULL,
  fonte              text NOT NULL,
  UNIQUE (vigencia_inicio, categoria, faixa_min_m3)
);

CREATE TABLE regulatorio.parametro (
  chave        text PRIMARY KEY,
  valor_num    numeric,
  valor_texto  text,
  descricao    text NOT NULL,
  fonte        text NOT NULL,
  premissa     boolean NOT NULL DEFAULT false   -- true = hipótese do grupo, a validar com a concessionária
);

-- Tarifas básicas (R$/mês por economia)
INSERT INTO regulatorio.tarifa_basica VALUES
  ('2026-04-01','RESIDENCIAL_SOCIAL', 8.73, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',17.46, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','COMERCIAL_I',       17.46, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','COMERCIAL_II',       8.73, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','INDUSTRIAL',        17.46, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','PUBLICA',           17.46, 'Res. Conjunta AGR/ARM 1/2026');

-- Faixas de consumo (R$/m³)
INSERT INTO regulatorio.tarifa_faixa
  (vigencia_inicio, categoria, faixa_min_m3, faixa_max_m3, agua_m3, esgoto_coleta_m3, esgoto_tratam_m3, fonte)
VALUES
  ('2026-04-01','RESIDENCIAL_SOCIAL', 1, 10,  2.73,  2.18, 0.55, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_SOCIAL',11, 15,  3.07,  2.46, 0.61, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_SOCIAL',16, 20,  3.52,  2.82, 0.70, 'Res. Conjunta AGR/ARM 1/2026'),

  ('2026-04-01','RESIDENCIAL_NORMAL', 1, 10,  5.77,  4.61, 1.15, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',11, 15,  6.51,  5.21, 1.30, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',16, 20,  7.45,  5.96, 1.49, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',21, 25,  8.45,  6.76, 1.69, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',26, 30,  9.54,  7.63, 1.91, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',31, 40, 10.89,  8.71, 2.18, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',41, 50, 12.33,  9.86, 2.47, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','RESIDENCIAL_NORMAL',51, NULL,14.06, 11.25, 2.81, 'Res. Conjunta AGR/ARM 1/2026'),

  ('2026-04-01','COMERCIAL_I',        1, 10, 12.33,  9.86, 2.47, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','COMERCIAL_I',       11, NULL,14.06, 11.25, 2.81, 'Res. Conjunta AGR/ARM 1/2026'),

  ('2026-04-01','COMERCIAL_II',       1, 10,  6.15,  4.92, 1.23, 'Res. Conjunta AGR/ARM 1/2026'),

  ('2026-04-01','INDUSTRIAL',         1, 10, 12.33,  9.86, 2.47, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','INDUSTRIAL',        11, NULL,14.06, 11.25, 2.81, 'Res. Conjunta AGR/ARM 1/2026'),

  ('2026-04-01','PUBLICA',            1, 10, 10.89,  8.71, 2.18, 'Res. Conjunta AGR/ARM 1/2026'),
  ('2026-04-01','PUBLICA',           11, NULL,12.33,  9.86, 2.47, 'Res. Conjunta AGR/ARM 1/2026');

INSERT INTO regulatorio.parametro (chave, valor_num, valor_texto, descricao, fonte, premissa) VALUES
  ('salario_minimo', 1621.00, NULL,
   'Salário mínimo nacional vigente em 2026 (R$).', 'Decreto nº 12.797/2025', false),
  ('tarifa_social_renda_pc_max_fracao_sm', 0.5, NULL,
   'Renda familiar per capita máxima, em fração do salário mínimo, para elegibilidade à Tarifa Social.',
   'Lei nº 14.898/2024', false),
  ('tarifa_social_limite_desconto_m3', 15, NULL,
   'Volume mensal (m³) até o qual o desconto da Tarifa Social se aplica.', 'Lei nº 14.898/2024', false),
  ('residencial_social_transbordo', NULL, 'RESIDENCIAL_NORMAL',
   'Acima da última faixa da Residencial Social (20 m³), o excedente é faturado pelas faixas da Residencial Normal.',
   'Premissa do grupo — confirmar no Regulamento de Serviços da SANEAGO', true),
  ('comercial_ii_limite_m3', 10, NULL,
   'Comercial II (pequeno porte) só possui faixa até 10 m³; acima disso a UC é enquadrada como Comercial I.',
   'Premissa do grupo a partir do Anexo Único — confirmar no Regulamento da SANEAGO', true),
  ('custo_solucao_por_imovel_mes', 0.15, NULL,
   'Custo da solução por imóvel analisado por mês (R$), usado no I2.', 'Entrega 04 — hipótese do grupo', true),
  ('custo_implantacao', 40000.00, NULL,
   'Custo de implantação (R$), usado no I2 do primeiro ano.', 'Entrega 04 — hipótese do grupo', true),
  ('i5_limite_razao_fpr', 1.25, NULL,
   'Razão máxima entre a maior e a menor taxa de falsos positivos por faixa de renda antes de disparar revisão do modelo.',
   'Entrega 04 — indicador I5', false),
  ('i1_meta_razao_controle', 3.0, NULL,
   'Meta do piloto: taxa de acerto do Radar ao menos N vezes a do método atual.', 'Entrega 04 — indicador I1', false),
  ('meses_ganho_esperado', 12, NULL,
   'Horizonte (meses) para anualizar o ganho esperado da reclassificação.', 'Entrega 04', false),
  ('retencao_imagens_dias', 45, NULL,
   'Dias até o expurgo obrigatório de imagens de fachada após a captura (LGPD, minimização).',
   'Premissa do grupo (ciclo mensal de leitura + margem)', true);

-- -----------------------------------------------------------------------------
-- Função de referência para cálculo da fatura mensal (água + esgoto).
-- A API (Etapa 2) implementa a mesma regra em Python e usa esta função como
-- oráculo em testes. Verificação com os números da Entrega 04:
--   fatura('RESIDENCIAL_NORMAL', 15) = 197,86 ; fatura('COMERCIAL_I', 15) = 404,66
--   fatura('RESIDENCIAL_NORMAL', 10) = 132,76 ; fatura('COMERCIAL_II', 10) = 131,73
-- -----------------------------------------------------------------------------

-- Custo das faixas de `cat` para o volume no intervalo (v_ini, v_fim] em m³.
CREATE FUNCTION regulatorio._custo_faixas(
  p_cat regulatorio.categoria_tarifaria, p_v_ini numeric, p_v_fim numeric,
  p_esgoto boolean, p_vigencia date
) RETURNS numeric LANGUAGE sql STABLE AS $$
  SELECT COALESCE(SUM(
           GREATEST(0, LEAST(p_v_fim, COALESCE(f.faixa_max_m3::numeric, 'Infinity'))
                     - GREATEST(p_v_ini, f.faixa_min_m3 - 1))
           * (f.agua_m3 + CASE WHEN p_esgoto THEN f.esgoto_coleta_m3 + f.esgoto_tratam_m3 ELSE 0 END)
         ), 0)
  FROM regulatorio.tarifa_faixa f
  WHERE f.categoria = p_cat
    AND f.vigencia_inicio = (SELECT max(vigencia_inicio) FROM regulatorio.tarifa_faixa
                              WHERE vigencia_inicio <= p_vigencia AND categoria = p_cat)
$$;

CREATE FUNCTION regulatorio.fatura_mensal(
  p_categoria  regulatorio.categoria_tarifaria,
  p_volume_m3  numeric,
  p_economias  integer DEFAULT 1,
  p_esgoto     boolean DEFAULT true,
  p_vigencia   date    DEFAULT current_date
) RETURNS numeric LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_vol_eco   numeric := GREATEST(p_volume_m3, 0) / GREATEST(p_economias, 1);  -- volume por economia
  v_basica    numeric;
  v_consumo   numeric;
  v_lim_com2  numeric := (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'comercial_ii_limite_m3');
BEGIN
  -- Comercial II acima do limite → enquadra como Comercial I (premissa parametrizada)
  IF p_categoria = 'COMERCIAL_II' AND v_vol_eco > v_lim_com2 THEN
    RETURN regulatorio.fatura_mensal('COMERCIAL_I', p_volume_m3, p_economias, p_esgoto, p_vigencia);
  END IF;

  SELECT valor_mensal INTO v_basica FROM regulatorio.tarifa_basica
   WHERE categoria = p_categoria AND vigencia_inicio <= p_vigencia
   ORDER BY vigencia_inicio DESC LIMIT 1;
  IF v_basica IS NULL THEN
    RAISE EXCEPTION 'Sem tarifa vigente para % em %', p_categoria, p_vigencia;
  END IF;

  IF p_categoria = 'RESIDENCIAL_SOCIAL' THEN
    v_consumo := regulatorio._custo_faixas('RESIDENCIAL_SOCIAL', 0, LEAST(v_vol_eco, 20), p_esgoto, p_vigencia)
               + regulatorio._custo_faixas('RESIDENCIAL_NORMAL', 20, GREATEST(v_vol_eco, 20), p_esgoto, p_vigencia);
  ELSE
    v_consumo := regulatorio._custo_faixas(p_categoria, 0, v_vol_eco, p_esgoto, p_vigencia);
  END IF;

  RETURN round((v_basica + v_consumo) * GREATEST(p_economias, 1), 2);
END $$;

COMMENT ON FUNCTION regulatorio.fatura_mensal IS
  'Fatura mensal (R$) de água+esgoto pela estrutura SANEAGO vigente. Faixas progressivas por economia.';

-- =============================================================================
-- 3. CADASTRO — Território, UCs e consumo
-- =============================================================================

CREATE TABLE cadastro.bairro (
  id                     integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nome                   text NOT NULL UNIQUE,
  regiao                 text NOT NULL,                       -- região administrativa de Goiânia
  faixa_renda            cadastro.faixa_renda NOT NULL,       -- estrato usado no I5
  renda_media_pc_ref     numeric(10,2),                       -- R$; ver `fonte_renda`
  fonte_renda            text NOT NULL,
  centroide              geometry(Point, 4326) NOT NULL,
  area                   geometry(MultiPolygon, 4326)
);
CREATE INDEX bairro_area_gix ON cadastro.bairro USING gist (area);


-- Normalização de endereço (minúsculas, sem acento, sem pontuação, espaços únicos).
-- unaccent() não é IMMUTABLE; este wrapper fixa o dicionário e pode ser usado em colunas geradas/índices.
CREATE FUNCTION cadastro.normalizar_endereco(p text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
  SELECT btrim(regexp_replace(
           lower(public.unaccent('public.unaccent'::regdictionary, p)),
           '[^a-z0-9]+', ' ', 'g'))
$$;

CREATE TABLE cadastro.unidade_consumidora (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  matricula            text NOT NULL UNIQUE,
  logradouro           text NOT NULL,
  numero               text,
  complemento          text,
  bairro_id            integer NOT NULL REFERENCES cadastro.bairro(id),
  cep                  char(8),
  municipio            text NOT NULL DEFAULT 'Goiânia',
  uf                   char(2) NOT NULL DEFAULT 'GO',
  geom                 geometry(Point, 4326) NOT NULL,
  categoria_atual      regulatorio.categoria_tarifaria NOT NULL,
  economias            integer NOT NULL DEFAULT 1 CHECK (economias >= 1),
  possui_esgoto        boolean NOT NULL DEFAULT true,
  ligacao_ativa        boolean NOT NULL DEFAULT true,
  data_ligacao         date,
  titular_hash         text NOT NULL,   -- SHA-256(salt || id do titular); o nome nunca é armazenado
  endereco_normalizado text GENERATED ALWAYS AS (
                         cadastro.normalizar_endereco(logradouro || ' ' || coalesce(numero, ''))) STORED,
  criado_em            timestamptz NOT NULL DEFAULT now(),
  atualizado_em        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX uc_geom_gix      ON cadastro.unidade_consumidora USING gist (geom);
CREATE INDEX uc_bairro_ix     ON cadastro.unidade_consumidora (bairro_id);
CREATE INDEX uc_categoria_ix  ON cadastro.unidade_consumidora (categoria_atual);
CREATE INDEX uc_end_trgm_ix   ON cadastro.unidade_consumidora USING gin (endereco_normalizado gin_trgm_ops);

COMMENT ON COLUMN cadastro.unidade_consumidora.categoria_atual IS
  'Somente alterável por fiscalizacao.aplicar_reclassificacao(laudo) — garantia G1.';

CREATE TABLE cadastro.consumo_mensal (
  uc_id         bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id) ON DELETE CASCADE,
  competencia   date   NOT NULL CHECK (extract(day FROM competencia) = 1),  -- 1º dia do mês
  volume_m3     numeric(10,2) NOT NULL CHECK (volume_m3 >= 0),
  tipo_leitura  cadastro.tipo_leitura NOT NULL DEFAULT 'REAL',
  PRIMARY KEY (uc_id, competencia)
);
CREATE INDEX consumo_competencia_ix ON cadastro.consumo_mensal (competencia);

-- Histórico de mudanças de categoria (preenchido pelo trigger da garantia G1)
CREATE TABLE cadastro.historico_categoria (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uc_id               bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  categoria_anterior  regulatorio.categoria_tarifaria NOT NULL,
  categoria_nova      regulatorio.categoria_tarifaria NOT NULL,
  laudo_id            uuid,            -- FK adicionada após criar fiscalizacao.laudo_vistoria
  alterado_em         timestamptz NOT NULL DEFAULT now(),
  alterado_por        text NOT NULL,
  observacao          text
);

-- =============================================================================
-- 4. PÚBLICO — Bases públicas cruzadas pelo coletor
-- =============================================================================

CREATE TABLE publico.estabelecimento_cnpj (
  cnpj               char(14) PRIMARY KEY CHECK (cnpj ~ '^[0-9]{14}$'),
  razao_social       text NOT NULL,
  nome_fantasia      text,
  cnae_principal     char(7) NOT NULL,          -- ex.: 5611201
  cnae_descricao     text NOT NULL,
  porte              publico.porte_empresa NOT NULL,
  situacao           publico.situacao_cnpj NOT NULL,
  data_abertura      date,
  data_situacao      date,
  endereco_texto     text NOT NULL,
  endereco_normalizado text GENERATED ALWAYS AS (cadastro.normalizar_endereco(endereco_texto)) STORED,
  geom               geometry(Point, 4326),
  fonte              text NOT NULL DEFAULT 'Receita Federal — Dados Abertos CNPJ',
  sintetico          boolean NOT NULL DEFAULT false
);
CREATE INDEX cnpj_geom_gix ON publico.estabelecimento_cnpj USING gist (geom);
CREATE INDEX cnpj_end_trgm ON publico.estabelecimento_cnpj USING gin (endereco_normalizado gin_trgm_ops);

CREATE TABLE publico.alvara_funcionamento (
  numero             text PRIMARY KEY,
  cnpj               char(14) REFERENCES publico.estabelecimento_cnpj(cnpj),
  atividade          text NOT NULL,
  endereco_texto     text NOT NULL,
  geom               geometry(Point, 4326),
  data_emissao       date NOT NULL,
  data_validade      date NOT NULL,
  fonte              text NOT NULL DEFAULT 'Prefeitura de Goiânia',
  sintetico          boolean NOT NULL DEFAULT false
);
CREATE INDEX alvara_geom_gix ON publico.alvara_funcionamento USING gist (geom);

CREATE TABLE publico.zona_urbana (
  id                 integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  codigo             text NOT NULL,
  descricao          text NOT NULL,
  uso                publico.uso_zona NOT NULL,
  geom               geometry(MultiPolygon, 4326) NOT NULL,
  fonte              text NOT NULL,
  sintetico          boolean NOT NULL DEFAULT false
);
CREATE INDEX zona_geom_gix ON publico.zona_urbana USING gist (geom);

-- =============================================================================
-- 5. SOCIAL — CadÚnico/BPC (garantia G2: acesso só por radar_social)
-- =============================================================================

CREATE TABLE social.familia_cadunico (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  codigo_familiar_hash     text NOT NULL UNIQUE,       -- pseudonimizado
  renda_per_capita         numeric(10,2) NOT NULL CHECK (renda_per_capita >= 0),
  recebe_bpc               boolean NOT NULL DEFAULT false,
  qtd_pessoas              integer NOT NULL CHECK (qtd_pessoas >= 1),
  endereco_texto           text NOT NULL,
  endereco_normalizado     text GENERATED ALWAYS AS (cadastro.normalizar_endereco(endereco_texto)) STORED,
  geom                     geometry(Point, 4326),
  data_atualizacao_cadunico date NOT NULL,
  fonte                    text NOT NULL DEFAULT 'CadÚnico (MDS) — via acordo de cooperação',
  sintetico                boolean NOT NULL DEFAULT false
);
CREATE INDEX familia_end_trgm ON social.familia_cadunico USING gin (endereco_normalizado gin_trgm_ops);
CREATE INDEX familia_geom_gix ON social.familia_cadunico USING gist (geom);

CREATE TABLE social.vinculo_familia_uc (
  familia_id   uuid   NOT NULL REFERENCES social.familia_cadunico(id) ON DELETE CASCADE,
  uc_id        bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  metodo       social.metodo_vinculo NOT NULL,
  confianca    numeric(4,3) NOT NULL CHECK (confianca BETWEEN 0 AND 1),
  criado_em    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (familia_id, uc_id)
);

CREATE TABLE social.alerta_tarifa_social (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uc_id          bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  familia_id     uuid   NOT NULL REFERENCES social.familia_cadunico(id),
  criterio       social.criterio_elegibilidade NOT NULL,
  status         social.status_alerta NOT NULL DEFAULT 'IDENTIFICADO',
  evidencia      jsonb NOT NULL,     -- regra aplicada, renda_pc, limite, vínculo e confiança (auditável)
  criado_em      timestamptz NOT NULL DEFAULT now(),
  atualizado_em  timestamptz NOT NULL DEFAULT now(),
  responsavel    text,
  observacao     text
);
-- No máximo um alerta "aberto" por UC
CREATE UNIQUE INDEX alerta_aberto_uq ON social.alerta_tarifa_social (uc_id)
  WHERE status IN ('IDENTIFICADO', 'FAMILIA_CONTATADA');

-- Elegibilidade (Lei 14.898/2024): renda per capita <= 1/2 SM OU BPC.
CREATE VIEW social.vw_elegibilidade AS
SELECT f.id AS familia_id, v.uc_id, v.metodo, v.confianca,
       f.renda_per_capita, f.recebe_bpc,
       (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'salario_minimo')
     * (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'tarifa_social_renda_pc_max_fracao_sm')
         AS limite_renda_pc,
       CASE WHEN f.recebe_bpc THEN 'BPC'::social.criterio_elegibilidade
            WHEN f.renda_per_capita <= (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'salario_minimo')
                                     * (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'tarifa_social_renda_pc_max_fracao_sm')
            THEN 'RENDA_ATE_MEIO_SM'::social.criterio_elegibilidade
       END AS criterio,
       uc.categoria_atual,
       uc.ligacao_ativa
FROM social.familia_cadunico f
JOIN social.vinculo_familia_uc v ON v.familia_id = f.id
JOIN cadastro.unidade_consumidora uc ON uc.id = v.uc_id;

-- =============================================================================
-- 6. ANÁLISE — Lotes, imagens, detecções, evidências e scores
-- =============================================================================

CREATE TABLE analise.lote_processamento (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  criado_em       timestamptz NOT NULL DEFAULT now(),
  iniciado_em     timestamptz,
  concluido_em    timestamptz,
  status          analise.status_lote NOT NULL DEFAULT 'PENDENTE',
  modo            analise.modo_execucao NOT NULL DEFAULT 'PARALELO',
  n_workers       integer,
  total_ucs       integer NOT NULL CHECK (total_ucs >= 0),
  processadas     integer NOT NULL DEFAULT 0,
  falhas          integer NOT NULL DEFAULT 0,
  parametros      jsonb NOT NULL DEFAULT '{}'::jsonb,
  solicitado_por  text NOT NULL,
  CHECK (processadas + falhas <= total_ucs)
);

-- Catálogo das classes-alvo do detector (YOLOv11)
CREATE TABLE analise.classe_visual (
  codigo        text PRIMARY KEY,
  descricao     text NOT NULL,
  indica        regulatorio.categoria_tarifaria NOT NULL,   -- categoria que o elemento sugere
  peso_prior    numeric(4,3) NOT NULL CHECK (peso_prior BETWEEN 0 AND 1)  -- prior para o modelo/XAI
);
INSERT INTO analise.classe_visual VALUES
  ('placa_comercial',         'Placa/cartaz de anúncio de produto ou serviço',          'COMERCIAL_I', 0.70),
  ('letreiro',                'Letreiro/fachada com nome de estabelecimento',            'COMERCIAL_I', 0.80),
  ('vitrine',                 'Vitrine ou porta de vidro de loja com exposição',         'COMERCIAL_I', 0.75),
  ('banner',                  'Banner/faixa promocional temporária',                     'COMERCIAL_II',0.45),
  ('portao_industrial',       'Portão de enrolar/galpão de grande porte',                'INDUSTRIAL',  0.65),
  ('doca_carga',              'Doca ou área de carga e descarga',                        'INDUSTRIAL',  0.80),
  ('estacionamento_clientes', 'Estacionamento demarcado para clientes / fluxo de veículos','COMERCIAL_I', 0.50);

-- G3: só imagens anonimizadas entram aqui; toda imagem tem data de expurgo.
CREATE TABLE analise.imagem_fachada (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uc_id               bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  fonte               analise.fonte_imagem NOT NULL,
  uri_objeto          text NOT NULL,          -- chave no storage (imagem já borrada)
  referencia_origem   text,                   -- id/URL na fonte (Mapillary image_id, Geo360, OS do leiturista)
  capturada_em        timestamptz NOT NULL,
  recebida_em         timestamptz NOT NULL DEFAULT now(),
  largura_px          integer CHECK (largura_px > 0),
  altura_px           integer CHECK (altura_px > 0),
  sha256              char(64) NOT NULL,
  anonimizada         boolean NOT NULL,
  rostos_borrados     integer NOT NULL DEFAULT 0,
  placas_borradas     integer NOT NULL DEFAULT 0,
  expira_em           timestamptz NOT NULL,
  expurgada_em        timestamptz,
  CONSTRAINT imagem_deve_estar_anonimizada CHECK (anonimizada),
  CONSTRAINT expiracao_apos_captura CHECK (expira_em > capturada_em)
);
CREATE INDEX imagem_uc_ix ON analise.imagem_fachada (uc_id, capturada_em DESC);
CREATE INDEX imagem_expira_ix ON analise.imagem_fachada (expira_em) WHERE expurgada_em IS NULL;

CREATE TABLE analise.deteccao_visual (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  imagem_id      uuid NOT NULL REFERENCES analise.imagem_fachada(id) ON DELETE CASCADE,
  classe         text NOT NULL REFERENCES analise.classe_visual(codigo),
  confianca      numeric(5,4) NOT NULL CHECK (confianca BETWEEN 0 AND 1),
  -- caixa delimitadora normalizada [0,1] (x1,y1 canto sup. esquerdo; x2,y2 canto inf. direito)
  bbox_x1        real NOT NULL CHECK (bbox_x1 BETWEEN 0 AND 1),
  bbox_y1        real NOT NULL CHECK (bbox_y1 BETWEEN 0 AND 1),
  bbox_x2        real NOT NULL CHECK (bbox_x2 BETWEEN 0 AND 1),
  bbox_y2        real NOT NULL CHECK (bbox_y2 BETWEEN 0 AND 1),
  modelo_versao  text NOT NULL,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  CHECK (bbox_x2 > bbox_x1 AND bbox_y2 > bbox_y1)
);
CREATE INDEX deteccao_imagem_ix ON analise.deteccao_visual (imagem_id);

-- Saída do worker de coleta: cruzamento com bases públicas (sem CadÚnico)
CREATE TABLE analise.evidencia_coleta (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  uc_id          bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  lote_id        uuid REFERENCES analise.lote_processamento(id),
  coletado_em    timestamptz NOT NULL DEFAULT now(),
  sinais         jsonb NOT NULL,   -- {cnpjs:[...], alvaras:[...], zona:{...}, imagem:{fonte,...}}
  imagem_disponivel boolean NOT NULL,
  imagem_desatualizada boolean NOT NULL DEFAULT false   -- sinaliza atualização em campo
);
CREATE INDEX evidencia_uc_ix ON analise.evidencia_coleta (uc_id, coletado_em DESC);

CREATE TABLE analise.resultado_analise (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uc_id                       bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  lote_id                     uuid REFERENCES analise.lote_processamento(id),
  imagem_id                   uuid REFERENCES analise.imagem_fachada(id) ON DELETE SET NULL,
  modelo_versao               text NOT NULL,
  categoria_atual             regulatorio.categoria_tarifaria NOT NULL,   -- snapshot no momento da análise
  probabilidade_irregularidade numeric(5,4) NOT NULL CHECK (probabilidade_irregularidade BETWEEN 0 AND 1),
  categoria_sugerida          regulatorio.categoria_tarifaria NOT NULL,
  probabilidades_categoria    jsonb NOT NULL,      -- {"RESIDENCIAL_NORMAL":0.2,"COMERCIAL_I":0.7,...}
  fatura_atual_mensal         numeric(12,2) NOT NULL,
  fatura_sugerida_mensal      numeric(12,2) NOT NULL,
  ganho_esperado_anual        numeric(12,2) NOT NULL,  -- E[G] = p * Δfatura * 12 (docs/02)
  score_prioridade            numeric(14,4) NOT NULL,
  explicabilidade             jsonb NOT NULL,      -- fatores e contribuições (SHAP/regras)
  features                    jsonb NOT NULL,      -- vetor de atributos usado (reprodutibilidade)
  imagem_desatualizada        boolean NOT NULL DEFAULT false,
  tempo_inferencia_ms         integer,
  worker_id                   text,
  criado_em                   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX resultado_uc_ix    ON analise.resultado_analise (uc_id, criado_em DESC);
CREATE INDEX resultado_score_ix ON analise.resultado_analise (score_prioridade DESC);
CREATE INDEX resultado_lote_ix  ON analise.resultado_analise (lote_id);

CREATE VIEW analise.vw_ultima_analise AS
SELECT DISTINCT ON (uc_id) *
FROM analise.resultado_analise
ORDER BY uc_id, criado_em DESC;

-- Imagens vencidas a expurgar (o worker apaga o objeto e marca expurgada_em)
CREATE FUNCTION analise.imagens_a_expurgar(p_agora timestamptz DEFAULT now())
RETURNS TABLE (imagem_id uuid, uri_objeto text) LANGUAGE sql STABLE AS $$
  SELECT id, uri_objeto FROM analise.imagem_fachada
  WHERE expurgada_em IS NULL AND expira_em <= p_agora
$$;

-- =============================================================================
-- 7. FISCALIZAÇÃO — Fila, laudos humanos e custos
-- =============================================================================

CREATE TABLE fiscalizacao.ordem_vistoria (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  uc_id              bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  resultado_analise_id uuid REFERENCES analise.resultado_analise(id),  -- NULL nos grupos controle/aleatório
  origem             fiscalizacao.origem_ordem NOT NULL,
  posicao_ranking    integer,
  status             fiscalizacao.status_ordem NOT NULL DEFAULT 'AGUARDANDO',
  fiscal_matricula   text,
  criada_em          timestamptz NOT NULL DEFAULT now(),
  criada_por         text NOT NULL,
  CONSTRAINT ordem_radar_exige_analise CHECK (origem <> 'RADAR' OR resultado_analise_id IS NOT NULL)
);
CREATE UNIQUE INDEX ordem_aberta_uq ON fiscalizacao.ordem_vistoria (uc_id)
  WHERE status IN ('AGUARDANDO', 'EM_CAMPO');

CREATE TABLE fiscalizacao.laudo_vistoria (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ordem_id               uuid NOT NULL UNIQUE REFERENCES fiscalizacao.ordem_vistoria(id),
  uc_id                  bigint NOT NULL REFERENCES cadastro.unidade_consumidora(id),
  fiscal_matricula       text NOT NULL,
  realizada_em           timestamptz NOT NULL,
  resultado              fiscalizacao.resultado_vistoria NOT NULL,
  categoria_constatada   regulatorio.categoria_tarifaria,
  atividade_observada    text,
  evidencias             jsonb NOT NULL DEFAULT '{}'::jsonb,   -- fotos do fiscal, checklist
  observacoes            text,
  decisao                fiscalizacao.decisao_laudo NOT NULL,
  aprovado_por           text,             -- servidor responsável (≠ fiscal), exigido para RECLASSIFICAR
  aprovado_em            timestamptz,
  notificacao_previa_em  timestamptz,      -- comunicação ao usuário antes da mudança
  prazo_contestacao_ate  date,
  aplicado_em            timestamptz,      -- quando a reclassificação foi efetivada
  criado_em              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT irregularidade_exige_categoria
    CHECK (resultado <> 'IRREGULARIDADE_CONFIRMADA' OR categoria_constatada IS NOT NULL),
  CONSTRAINT reclassificar_exige_aprovacao_independente CHECK (decisao <> 'RECLASSIFICAR' OR (
           resultado = 'IRREGULARIDADE_CONFIRMADA'
       AND categoria_constatada IS NOT NULL
       AND aprovado_por IS NOT NULL AND aprovado_em IS NOT NULL
       AND aprovado_por <> fiscal_matricula)),   -- segregação de funções (quatro olhos)
  CONSTRAINT aplicacao_so_para_reclassificacao CHECK (aplicado_em IS NULL OR decisao = 'RECLASSIFICAR')
);
CREATE INDEX laudo_uc_ix ON fiscalizacao.laudo_vistoria (uc_id);

ALTER TABLE cadastro.historico_categoria
  ADD CONSTRAINT historico_laudo_fk FOREIGN KEY (laudo_id) REFERENCES fiscalizacao.laudo_vistoria(id);

-- Custos reais da operação (I2). Se vazio, a API usa os parâmetros de premissa.
CREATE TABLE fiscalizacao.custo_solucao (
  competencia   date NOT NULL CHECK (extract(day FROM competencia) = 1),
  item          text NOT NULL,
  valor         numeric(12,2) NOT NULL CHECK (valor >= 0),
  PRIMARY KEY (competencia, item)
);

-- Fila priorizada: última análise de UCs residenciais, sem ordem aberta, ordenada pelo score.
CREATE VIEW fiscalizacao.vw_fila_priorizada AS
SELECT
  row_number() OVER (ORDER BY ua.score_prioridade DESC, ua.ganho_esperado_anual DESC) AS posicao,
  ua.id AS resultado_analise_id,
  uc.id AS uc_id, uc.matricula,
  uc.logradouro, uc.numero, b.nome AS bairro, b.regiao, b.faixa_renda,
  ST_Y(uc.geom) AS latitude, ST_X(uc.geom) AS longitude,
  uc.categoria_atual, ua.categoria_sugerida,
  ua.probabilidade_irregularidade, ua.ganho_esperado_anual, ua.score_prioridade,
  ua.explicabilidade, ua.imagem_id, ua.imagem_desatualizada, ua.modelo_versao, ua.criado_em AS analisado_em
FROM analise.vw_ultima_analise ua
JOIN cadastro.unidade_consumidora uc ON uc.id = ua.uc_id
JOIN cadastro.bairro b ON b.id = uc.bairro_id
WHERE uc.categoria_atual IN ('RESIDENCIAL_NORMAL', 'RESIDENCIAL_SOCIAL')
  AND uc.ligacao_ativa
  AND NOT EXISTS (SELECT 1 FROM fiscalizacao.ordem_vistoria o
                  WHERE o.uc_id = uc.id AND o.status IN ('AGUARDANDO', 'EM_CAMPO'));

-- =============================================================================
-- 8. AUDITORIA — trilha imutável (G5)
-- =============================================================================

CREATE TABLE auditoria.evento (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ocorrido_em   timestamptz NOT NULL DEFAULT clock_timestamp(),
  ator          text NOT NULL,      -- usuário da aplicação (radar.usuario) ou papel do banco
  papel_db      text NOT NULL DEFAULT current_user,
  acao          text NOT NULL,
  entidade      text NOT NULL,
  entidade_id   text,
  detalhes      jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX evento_entidade_ix ON auditoria.evento (entidade, entidade_id);

CREATE FUNCTION auditoria.fn_imutavel() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'auditoria.evento é append-only (operação % bloqueada)', TG_OP;
END $$;

CREATE TRIGGER evento_imutavel
  BEFORE UPDATE OR DELETE OR TRUNCATE ON auditoria.evento
  FOR EACH STATEMENT EXECUTE FUNCTION auditoria.fn_imutavel();

-- Ator da aplicação: a API executa `SET LOCAL radar.usuario = '<login>'` em cada transação.
CREATE FUNCTION auditoria.ator_atual() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT coalesce(nullif(current_setting('radar.usuario', true), ''), session_user::text)
$$;

CREATE FUNCTION auditoria.fn_registrar() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  v_id text;
BEGIN
  v_id := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD)->>'id' ELSE to_jsonb(NEW)->>'id' END;
  INSERT INTO auditoria.evento (ator, papel_db, acao, entidade, entidade_id, detalhes)
  VALUES (auditoria.ator_atual(), current_user, TG_OP, TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, v_id,
          jsonb_build_object(
            'antes',  CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
            'depois', CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END));
  RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER audit_ordem   AFTER INSERT OR UPDATE OR DELETE ON fiscalizacao.ordem_vistoria
  FOR EACH ROW EXECUTE FUNCTION auditoria.fn_registrar();
CREATE TRIGGER audit_laudo   AFTER INSERT OR UPDATE OR DELETE ON fiscalizacao.laudo_vistoria
  FOR EACH ROW EXECUTE FUNCTION auditoria.fn_registrar();
CREATE TRIGGER audit_alerta  AFTER INSERT OR UPDATE OR DELETE ON social.alerta_tarifa_social
  FOR EACH ROW EXECUTE FUNCTION auditoria.fn_registrar();
CREATE TRIGGER audit_lote    AFTER INSERT ON analise.lote_processamento
  FOR EACH ROW EXECUTE FUNCTION auditoria.fn_registrar();

-- =============================================================================
-- 9. GARANTIA G1 — categoria só muda por laudo humano aprovado
-- =============================================================================

CREATE FUNCTION cadastro.fn_proteger_categoria() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_laudo_id uuid := nullif(current_setting('radar.laudo_id', true), '')::uuid;
  v_ok       boolean;
BEGIN
  IF NEW.categoria_atual IS NOT DISTINCT FROM OLD.categoria_atual THEN
    NEW.atualizado_em := now();
    RETURN NEW;
  END IF;

  SELECT true INTO v_ok
  FROM fiscalizacao.laudo_vistoria l
  WHERE l.id = v_laudo_id
    AND l.uc_id = NEW.id
    AND l.decisao = 'RECLASSIFICAR'
    AND l.aprovado_por IS NOT NULL
    AND l.aplicado_em IS NULL
    AND l.categoria_constatada = NEW.categoria_atual;

  IF v_ok IS NULL THEN
    RAISE EXCEPTION
      'Mudança de categoria da UC % bloqueada: exige laudo humano aprovado (use fiscalizacao.aplicar_reclassificacao).',
      NEW.matricula USING ERRCODE = 'insufficient_privilege';
  END IF;

  INSERT INTO cadastro.historico_categoria (uc_id, categoria_anterior, categoria_nova, laudo_id, alterado_por)
  VALUES (NEW.id, OLD.categoria_atual, NEW.categoria_atual, v_laudo_id, auditoria.ator_atual());

  INSERT INTO auditoria.evento (ator, acao, entidade, entidade_id, detalhes)
  VALUES (auditoria.ator_atual(), 'RECLASSIFICACAO', 'cadastro.unidade_consumidora', NEW.id::text,
          jsonb_build_object('de', OLD.categoria_atual, 'para', NEW.categoria_atual, 'laudo_id', v_laudo_id));

  NEW.atualizado_em := now();
  RETURN NEW;
END $$;

CREATE TRIGGER uc_proteger_categoria
  BEFORE UPDATE ON cadastro.unidade_consumidora
  FOR EACH ROW EXECUTE FUNCTION cadastro.fn_proteger_categoria();

-- Única porta de entrada para reclassificar. Executa com os privilégios do dono do schema.
CREATE FUNCTION fiscalizacao.aplicar_reclassificacao(p_laudo_id uuid)
RETURNS cadastro.historico_categoria
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  v_laudo fiscalizacao.laudo_vistoria;
  v_hist  cadastro.historico_categoria;
BEGIN
  SELECT * INTO v_laudo FROM fiscalizacao.laudo_vistoria WHERE id = p_laudo_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Laudo % inexistente', p_laudo_id;
  END IF;
  IF v_laudo.aplicado_em IS NOT NULL THEN
    RAISE EXCEPTION 'Reclassificação já aplicada em %', v_laudo.aplicado_em;
  END IF;
  IF v_laudo.decisao <> 'RECLASSIFICAR' OR v_laudo.aprovado_por IS NULL THEN
    RAISE EXCEPTION 'Laudo sem decisão RECLASSIFICAR aprovada por supervisor';
  END IF;
  IF v_laudo.prazo_contestacao_ate IS NOT NULL AND v_laudo.prazo_contestacao_ate > current_date THEN
    RAISE EXCEPTION 'Prazo de contestação aberto até %', v_laudo.prazo_contestacao_ate;
  END IF;

  PERFORM set_config('radar.laudo_id', p_laudo_id::text, true);   -- vale só nesta transação
  UPDATE cadastro.unidade_consumidora
     SET categoria_atual = v_laudo.categoria_constatada
   WHERE id = v_laudo.uc_id;
  PERFORM set_config('radar.laudo_id', '', true);

  UPDATE fiscalizacao.laudo_vistoria SET aplicado_em = now() WHERE id = p_laudo_id;

  SELECT * INTO v_hist FROM cadastro.historico_categoria
   WHERE laudo_id = p_laudo_id ORDER BY id DESC LIMIT 1;
  RETURN v_hist;
END $$;

-- =============================================================================
-- 10. EXPERIMENTO — gabarito sintético (nunca lido pelos papéis de produção)
-- =============================================================================

CREATE TABLE experimento.gabarito_sintetico (
  uc_id                     bigint PRIMARY KEY REFERENCES cadastro.unidade_consumidora(id) ON DELETE CASCADE,
  cenario                   text NOT NULL,
  categoria_real            regulatorio.categoria_tarifaria NOT NULL,
  irregular                 boolean NOT NULL,          -- categoria_real ≠ categoria_atual (rótulo y)
  atividade_real            text,
  elementos_visuais         jsonb NOT NULL DEFAULT '[]'::jsonb,  -- usados pelo gerador de fachadas sintéticas
  imagem_disponivel         boolean NOT NULL DEFAULT true,
  elegivel_tarifa_social    boolean NOT NULL DEFAULT false,
  armadilha                 text,                      -- tipo de caso difícil (falso positivo/negativo esperado)
  notas                     text
);

CREATE TABLE experimento.execucao_benchmark (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  iniciado_em    timestamptz NOT NULL DEFAULT now(),
  concluido_em   timestamptz,
  git_commit     text,
  random_state   integer NOT NULL,
  configuracao   jsonb NOT NULL,
  metricas       jsonb,
  ambiente       jsonb               -- CPU, GPU, versões de bibliotecas
);

-- =============================================================================
-- 11. PAPÉIS E PRIVILÉGIOS (grupos NOLOGIN; logins criados em 02_usuarios.sh)
-- =============================================================================

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO PUBLIC;   -- funções do PostGIS/unaccent

CREATE ROLE radar_base         NOLOGIN;
CREATE ROLE radar_api          NOLOGIN IN ROLE radar_base;
CREATE ROLE radar_coletor      NOLOGIN IN ROLE radar_base;
CREATE ROLE radar_ia           NOLOGIN IN ROLE radar_base;
CREATE ROLE radar_social       NOLOGIN;            -- NÃO herda radar_base: só o necessário
CREATE ROLE radar_experimento  NOLOGIN IN ROLE radar_base;

-- Base: leitura de cadastro, bases públicas e regulatório
GRANT USAGE ON SCHEMA regulatorio, cadastro, publico, analise, fiscalizacao TO radar_base;
GRANT SELECT ON ALL TABLES IN SCHEMA regulatorio, cadastro, publico TO radar_base;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA regulatorio TO radar_base;
GRANT EXECUTE ON FUNCTION cadastro.normalizar_endereco(text) TO radar_base, radar_social;
GRANT USAGE ON SCHEMA auditoria TO radar_base, radar_social;
GRANT EXECUTE ON FUNCTION auditoria.ator_atual() TO radar_base, radar_social;

-- API (fiscalização, gestão de UCs, laudos, indicadores I1, I2, I4, I5)
GRANT SELECT ON ALL TABLES IN SCHEMA analise, fiscalizacao TO radar_api;
GRANT INSERT ON cadastro.unidade_consumidora, cadastro.consumo_mensal TO radar_api;
GRANT UPDATE (logradouro, numero, complemento, cep, geom, economias, possui_esgoto, ligacao_ativa)
  ON cadastro.unidade_consumidora TO radar_api;       -- sem categoria_atual (G1)
GRANT UPDATE (volume_m3, tipo_leitura) ON cadastro.consumo_mensal TO radar_api;
GRANT INSERT, UPDATE ON analise.lote_processamento TO radar_api;
GRANT INSERT, UPDATE ON fiscalizacao.ordem_vistoria, fiscalizacao.laudo_vistoria TO radar_api;
GRANT INSERT, UPDATE ON fiscalizacao.custo_solucao TO radar_api;
GRANT EXECUTE ON FUNCTION fiscalizacao.aplicar_reclassificacao(uuid) TO radar_api;
GRANT SELECT, INSERT ON auditoria.evento TO radar_api;
REVOKE EXECUTE ON FUNCTION fiscalizacao.aplicar_reclassificacao(uuid) FROM PUBLIC;

-- Coletor: grava evidências do cruzamento (sem CadÚnico, sem imagens persistidas)
GRANT SELECT ON analise.lote_processamento TO radar_coletor;
GRANT INSERT ON analise.evidencia_coleta TO radar_coletor;
GRANT SELECT ON analise.evidencia_coleta TO radar_coletor;

-- IA: persiste imagem anonimizada, detecções e resultados; nunca altera categoria
GRANT SELECT ON ALL TABLES IN SCHEMA analise TO radar_ia;
GRANT INSERT ON analise.imagem_fachada, analise.deteccao_visual, analise.resultado_analise TO radar_ia;
GRANT UPDATE (expurgada_em) ON analise.imagem_fachada TO radar_ia;
GRANT UPDATE (status, iniciado_em, concluido_em, processadas, falhas, n_workers)
  ON analise.lote_processamento TO radar_ia;
GRANT SELECT ON fiscalizacao.laudo_vistoria TO radar_ia;   -- rótulos para retreino
GRANT EXECUTE ON FUNCTION analise.imagens_a_expurgar(timestamptz) TO radar_ia;

-- Social: módulo Tarifa Social (único papel com acesso ao CadÚnico)
GRANT USAGE ON SCHEMA social, cadastro, regulatorio TO radar_social;
GRANT SELECT ON ALL TABLES IN SCHEMA social TO radar_social;
GRANT INSERT, UPDATE ON social.familia_cadunico, social.vinculo_familia_uc, social.alerta_tarifa_social TO radar_social;
GRANT SELECT ON cadastro.unidade_consumidora, cadastro.bairro, cadastro.consumo_mensal TO radar_social;
GRANT SELECT ON regulatorio.parametro, regulatorio.tarifa_basica, regulatorio.tarifa_faixa TO radar_social;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA regulatorio TO radar_social;
GRANT SELECT, INSERT ON auditoria.evento TO radar_social;

-- Experimentos: lê tudo exceto o schema social; acesso exclusivo ao gabarito
GRANT SELECT ON ALL TABLES IN SCHEMA analise, fiscalizacao TO radar_experimento;
GRANT USAGE ON SCHEMA experimento TO radar_experimento;
GRANT SELECT ON ALL TABLES IN SCHEMA experimento TO radar_experimento;
GRANT INSERT, UPDATE ON experimento.execucao_benchmark TO radar_experimento;

-- Sequências das colunas IDENTITY
GRANT USAGE ON ALL SEQUENCES IN SCHEMA cadastro, analise, fiscalizacao, auditoria
  TO radar_api, radar_coletor, radar_ia, radar_social, radar_experimento;

-- Garantia G2 explícita: ninguém além de radar_social (e do dono) acessa `social`
REVOKE ALL ON SCHEMA social FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA social FROM radar_base, radar_api, radar_coletor, radar_ia, radar_experimento;
REVOKE ALL ON SCHEMA experimento FROM PUBLIC;
