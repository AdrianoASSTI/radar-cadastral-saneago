-- =============================================================================
-- Migração 04 (Etapa 3) — Suporte aos workers de coleta e de IA.
--
-- * analise.registrar_progresso(lote, sucesso, worker): incremento ATÔMICO do
--   progresso do lote e fechamento (CONCLUIDO / CONCLUIDO_COM_FALHAS) por quem
--   processar a última UC. Evita condição de corrida entre N workers.
-- * Papel do coletor pode registrar falhas (UC sem coleta possível).
-- * Índice para a telemetria do benchmark de speedup.
--
-- Idempotente. Em banco existente:
--   docker compose exec -T db psql -U radar_owner -d radar -f /docker-entrypoint-initdb.d/04_workers.sql
-- =============================================================================

\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION analise.registrar_progresso(
  p_lote_id uuid, p_sucesso boolean, p_worker text DEFAULT NULL
) RETURNS TABLE (status analise.status_lote, processadas integer, falhas integer, total integer, concluiu boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  v analise.lote_processamento;
BEGIN
  UPDATE analise.lote_processamento l
     SET processadas = l.processadas + CASE WHEN p_sucesso THEN 1 ELSE 0 END,
         falhas      = l.falhas      + CASE WHEN p_sucesso THEN 0 ELSE 1 END,
         iniciado_em = coalesce(l.iniciado_em, now()),
         parametros  = CASE WHEN p_worker IS NULL THEN l.parametros
                            ELSE jsonb_set(l.parametros, '{workers}',
                                   (SELECT to_jsonb(array_agg(DISTINCT w)) FROM (
                                      SELECT jsonb_array_elements_text(coalesce(l.parametros->'workers', '[]')) AS w
                                      UNION SELECT p_worker) s))
                       END
   WHERE l.id = p_lote_id
  RETURNING * INTO v;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Lote % inexistente', p_lote_id;
  END IF;

  IF v.processadas + v.falhas >= v.total_ucs AND v.concluido_em IS NULL THEN
    UPDATE analise.lote_processamento
       SET status = CASE WHEN v.falhas = 0 THEN 'CONCLUIDO' ELSE 'CONCLUIDO_COM_FALHAS' END::analise.status_lote,
           concluido_em = clock_timestamp(),
           n_workers = jsonb_array_length(coalesce(parametros->'workers', '[]'))
     WHERE id = p_lote_id
    RETURNING * INTO v;
    RETURN QUERY SELECT v.status, v.processadas, v.falhas, v.total_ucs, true;
  ELSE
    RETURN QUERY SELECT v.status, v.processadas, v.falhas, v.total_ucs, false;
  END IF;
END $$;

REVOKE EXECUTE ON FUNCTION analise.registrar_progresso(uuid, boolean, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analise.registrar_progresso(uuid, boolean, text) TO radar_ia, radar_coletor;

CREATE INDEX IF NOT EXISTS resultado_worker_ix ON analise.resultado_analise (lote_id, worker_id);

-- O worker de IA lê a evidência coletada (já tinha SELECT em analise.*); o coletor
-- precisa ler UCs e consumo (radar_base) e gravar evidências (concedido em 01).
