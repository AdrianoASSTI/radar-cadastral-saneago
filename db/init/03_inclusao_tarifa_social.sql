-- =============================================================================
-- Migração 03 (Etapa 2) — Inclusão na Tarifa Social como segundo caminho
-- auditável de mudança de categoria.
--
-- A garantia G1 passa a ter DUAS portas, ambas decididas por um humano:
--   (a) fiscalizacao.aplicar_reclassificacao(laudo)      → laudo de vistoria aprovado
--   (b) social.aplicar_inclusao_tarifa_social(alerta)     → alerta INCLUIDA pela assistente social,
--                                                           com elegibilidade reconferida no ato
-- Qualquer outra tentativa de mudar a categoria continua bloqueada.
-- Também corrige aplicar_reclassificacao: recusa laudo já aplicado (idempotência).
--
-- Idempotente: roda sozinho em bancos novos (docker-entrypoint-initdb.d) e pode
-- ser aplicado manualmente em bancos já existentes:
--   docker compose exec -T db psql -U radar_owner -d radar -f /docker-entrypoint-initdb.d/03_inclusao_tarifa_social.sql
-- =============================================================================

\set ON_ERROR_STOP on

ALTER TABLE social.alerta_tarifa_social ADD COLUMN IF NOT EXISTS aplicado_em timestamptz;

CREATE OR REPLACE FUNCTION cadastro.fn_proteger_categoria() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_laudo_id  uuid := nullif(current_setting('radar.laudo_id', true), '')::uuid;
  v_alerta_id uuid := nullif(current_setting('radar.alerta_social_id', true), '')::uuid;
  v_ok        boolean;
  v_obs       text;
BEGIN
  IF NEW.categoria_atual IS NOT DISTINCT FROM OLD.categoria_atual THEN
    NEW.atualizado_em := now();
    RETURN NEW;
  END IF;

  IF v_alerta_id IS NOT NULL THEN
    -- Porta (b): inclusão na Tarifa Social decidida pela assistente social
    SELECT true INTO v_ok
    FROM social.alerta_tarifa_social a
    WHERE a.id = v_alerta_id AND a.uc_id = NEW.id AND a.status = 'INCLUIDA' AND a.aplicado_em IS NULL
      AND OLD.categoria_atual = 'RESIDENCIAL_NORMAL' AND NEW.categoria_atual = 'RESIDENCIAL_SOCIAL';
    v_obs := 'Inclusão na Tarifa Social — alerta ' || v_alerta_id;
  ELSE
    -- Porta (a): reclassificação por laudo de vistoria aprovado
    SELECT true INTO v_ok
    FROM fiscalizacao.laudo_vistoria l
    WHERE l.id = v_laudo_id AND l.uc_id = NEW.id AND l.decisao = 'RECLASSIFICAR'
      AND l.aprovado_por IS NOT NULL AND l.aplicado_em IS NULL
      AND l.categoria_constatada = NEW.categoria_atual;
  END IF;

  IF v_ok IS NULL THEN
    RAISE EXCEPTION
      'Mudança de categoria da UC % bloqueada: exige laudo humano aprovado (use fiscalizacao.aplicar_reclassificacao).',
      NEW.matricula USING ERRCODE = 'insufficient_privilege';
  END IF;

  INSERT INTO cadastro.historico_categoria (uc_id, categoria_anterior, categoria_nova, laudo_id, alterado_por, observacao)
  VALUES (NEW.id, OLD.categoria_atual, NEW.categoria_atual, v_laudo_id, auditoria.ator_atual(), v_obs);

  INSERT INTO auditoria.evento (ator, acao, entidade, entidade_id, detalhes)
  VALUES (auditoria.ator_atual(),
          CASE WHEN v_alerta_id IS NOT NULL THEN 'INCLUSAO_TARIFA_SOCIAL' ELSE 'RECLASSIFICACAO' END,
          'cadastro.unidade_consumidora', NEW.id::text,
          jsonb_build_object('de', OLD.categoria_atual, 'para', NEW.categoria_atual,
                             'laudo_id', v_laudo_id, 'alerta_social_id', v_alerta_id));

  NEW.atualizado_em := now();
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION social.aplicar_inclusao_tarifa_social(p_alerta_id uuid)
RETURNS cadastro.historico_categoria
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  v_alerta social.alerta_tarifa_social;
  v_hist   cadastro.historico_categoria;
BEGIN
  SELECT * INTO v_alerta FROM social.alerta_tarifa_social WHERE id = p_alerta_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Alerta % inexistente', p_alerta_id;
  END IF;
  IF v_alerta.status <> 'INCLUIDA' THEN
    RAISE EXCEPTION 'Alerta precisa estar INCLUIDA (família contatada e documentação conferida); status atual: %',
      v_alerta.status;
  END IF;
  IF v_alerta.aplicado_em IS NOT NULL THEN
    RAISE EXCEPTION 'Inclusão já aplicada em %', v_alerta.aplicado_em;
  END IF;
  -- Reconfere a elegibilidade no momento da aplicação (o CadÚnico pode ter mudado)
  PERFORM 1 FROM social.vw_elegibilidade e
   WHERE e.familia_id = v_alerta.familia_id AND e.uc_id = v_alerta.uc_id AND e.criterio IS NOT NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Família não é mais elegível pelos critérios da Lei 14.898/2024';
  END IF;

  PERFORM set_config('radar.alerta_social_id', p_alerta_id::text, true);
  UPDATE cadastro.unidade_consumidora SET categoria_atual = 'RESIDENCIAL_SOCIAL' WHERE id = v_alerta.uc_id;
  PERFORM set_config('radar.alerta_social_id', '', true);

  UPDATE social.alerta_tarifa_social SET aplicado_em = now(), atualizado_em = now() WHERE id = p_alerta_id;

  SELECT * INTO v_hist FROM cadastro.historico_categoria
   WHERE uc_id = v_alerta.uc_id ORDER BY id DESC LIMIT 1;
  RETURN v_hist;
END $$;

-- Correção (Etapa 2): recusar laudo já aplicado ou sem decisão aprovada.
-- Única porta de entrada para reclassificar. Executa com os privilégios do dono do schema.
CREATE OR REPLACE FUNCTION fiscalizacao.aplicar_reclassificacao(p_laudo_id uuid)
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

REVOKE EXECUTE ON FUNCTION social.aplicar_inclusao_tarifa_social(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION social.aplicar_inclusao_tarifa_social(uuid) TO radar_social;
