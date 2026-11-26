#!/usr/bin/env bash
# =============================================================================
# Verifica as garantias G1–G5 do schema e a tabela tarifária.
# Uso (com o compose no ar):   bash db/tests/verificar_garantias.sh
# Fora do Docker:              PSQL="psql -h localhost -p 5432" DB=radar bash db/tests/verificar_garantias.sh
# Saída: uma linha OK/FALHOU por verificação; código de saída != 0 se algo falhar.
# =============================================================================
set -uo pipefail

DB="${DB:-radar}"
OWNER="${POSTGRES_USER:-radar_owner}"
PSQL="${PSQL:-docker compose exec -T db psql}"
falhas=0

q() {  # q <usuario> <sql>  -> stdout+stderr da consulta
  $PSQL -U "$1" -d "$DB" -X -q -t -A -v ON_ERROR_STOP=1 -c "$2" 2>&1
}

espera_erro() {  # espera_erro <descricao> <usuario> <sql> <trecho esperado na mensagem>
  local out; out="$(q "$2" "$3")"
  if grep -qi -- "$4" <<<"$out"; then echo "OK      $1"; else echo "FALHOU  $1 -> $out"; falhas=$((falhas+1)); fi
}

espera_valor() {  # espera_valor <descricao> <usuario> <sql> <valor esperado>
  local out; out="$(q "$2" "$3" | tr -d '[:space:]')"
  if [[ "$out" == "$4" ]]; then echo "OK      $1"; else echo "FALHOU  $1 -> obtido '$out', esperado '$4'"; falhas=$((falhas+1)); fi
}

echo "== Tarifas SANEAGO 2026 (Res. Conjunta AGR/ARM 1/2026) =="
espera_valor "Residencial Normal 15 m³ = 197,86" "$OWNER" "SELECT regulatorio.fatura_mensal('RESIDENCIAL_NORMAL',15)" "197.86"
espera_valor "Comercial I 15 m³ = 404,66"        "$OWNER" "SELECT regulatorio.fatura_mensal('COMERCIAL_I',15)"        "404.66"
espera_valor "Residencial Normal 10 m³ = 132,76" "$OWNER" "SELECT regulatorio.fatura_mensal('RESIDENCIAL_NORMAL',10)" "132.76"
espera_valor "Comercial II 10 m³ = 131,73"       "$OWNER" "SELECT regulatorio.fatura_mensal('COMERCIAL_II',10)"       "131.73"

echo "== G1: categoria só muda por laudo humano aprovado =="
espera_erro "UPDATE direto (dono) bloqueado" "$OWNER" \
  "UPDATE cadastro.unidade_consumidora SET categoria_atual='COMERCIAL_I' WHERE matricula='GYN00000002'" "laudo humano aprovado"
espera_erro "Papel de IA sem UPDATE na UC" usr_ia \
  "UPDATE cadastro.unidade_consumidora SET categoria_atual='COMERCIAL_I' WHERE matricula='GYN00000002'" "permission denied"
espera_erro "Aprovador não pode ser o próprio fiscal" usr_api \
  "INSERT INTO fiscalizacao.laudo_vistoria (ordem_id, uc_id, fiscal_matricula, realizada_em, resultado, categoria_constatada, decisao, aprovado_por, aprovado_em)
   SELECT id, uc_id, 'FIS-1', now(), 'IRREGULARIDADE_CONFIRMADA','COMERCIAL_I','RECLASSIFICAR','FIS-1', now()
   FROM fiscalizacao.ordem_vistoria LIMIT 1" "reclassificar_exige_aprovacao_independente"
espera_valor "Fluxo completo via aplicar_reclassificacao (em transação revertida)" usr_api \
  "BEGIN;
   WITH o AS (INSERT INTO fiscalizacao.ordem_vistoria (uc_id, origem, status, fiscal_matricula, criada_por)
              SELECT id,'AMOSTRA_ALEATORIA','CONCLUIDA','FIS-9','teste' FROM cadastro.unidade_consumidora
              WHERE matricula='GYN00000002' RETURNING id, uc_id)
   INSERT INTO fiscalizacao.laudo_vistoria (ordem_id, uc_id, fiscal_matricula, realizada_em, resultado,
               categoria_constatada, decisao, aprovado_por, aprovado_em)
   SELECT id, uc_id, 'FIS-9', now(), 'IRREGULARIDADE_CONFIRMADA','COMERCIAL_I','RECLASSIFICAR','SUP-1', now() FROM o;
   SELECT categoria_nova FROM fiscalizacao.aplicar_reclassificacao(
          (SELECT id FROM fiscalizacao.laudo_vistoria WHERE fiscal_matricula='FIS-9'));
   ROLLBACK;" "COMERCIAL_I"

espera_erro "Mesma reclassificação não pode ser aplicada duas vezes" usr_api \
  "BEGIN;
   WITH o AS (INSERT INTO fiscalizacao.ordem_vistoria (uc_id, origem, status, fiscal_matricula, criada_por)
              SELECT id,'AMOSTRA_ALEATORIA','CONCLUIDA','FIS-8','teste' FROM cadastro.unidade_consumidora
              WHERE matricula='GYN00000007' RETURNING id, uc_id)
   INSERT INTO fiscalizacao.laudo_vistoria (ordem_id, uc_id, fiscal_matricula, realizada_em, resultado,
               categoria_constatada, decisao, aprovado_por, aprovado_em)
   SELECT id, uc_id, 'FIS-8', now(), 'IRREGULARIDADE_CONFIRMADA','COMERCIAL_I','RECLASSIFICAR','SUP-1', now() FROM o;
   SELECT 1 FROM fiscalizacao.aplicar_reclassificacao((SELECT id FROM fiscalizacao.laudo_vistoria WHERE fiscal_matricula='FIS-8'));
   SELECT 1 FROM fiscalizacao.aplicar_reclassificacao((SELECT id FROM fiscalizacao.laudo_vistoria WHERE fiscal_matricula='FIS-8'));
   ROLLBACK;" "já aplicada"
espera_erro "Inclusão na Tarifa Social exige alerta INCLUIDA (decisão humana)" usr_api_social \
  "SELECT social.aplicar_inclusao_tarifa_social(gen_random_uuid())" "inexistente"

echo "== G2: segregação do CadÚnico e do gabarito =="
espera_erro "API de fiscalização não lê CadÚnico" usr_api "SELECT count(*) FROM social.familia_cadunico" "permission denied"
espera_erro "Worker de IA não lê CadÚnico"        usr_ia  "SELECT count(*) FROM social.familia_cadunico" "permission denied"
espera_erro "Worker de IA não lê o gabarito"      usr_ia  "SELECT count(*) FROM experimento.gabarito_sintetico" "permission denied"
espera_valor "Módulo social lê CadÚnico (5 famílias)" usr_api_social "SELECT count(*) FROM social.familia_cadunico" "5"

echo "== G3/G4: imagens =="
espera_erro "Imagem não anonimizada rejeitada" usr_ia \
  "INSERT INTO analise.imagem_fachada (uc_id,fonte,uri_objeto,capturada_em,sha256,anonimizada,expira_em)
   VALUES (1,'LEITURISTA','x',now(),repeat('a',64),false,now()+interval '1 day')" "imagem_deve_estar_anonimizada"
espera_erro "Street View não é fonte de inferência" usr_ia \
  "INSERT INTO analise.imagem_fachada (uc_id,fonte,uri_objeto,capturada_em,sha256,anonimizada,expira_em)
   VALUES (1,'STREET_VIEW','x',now(),repeat('a',64),true,now()+interval '1 day')" "invalid input value"

echo "== G5: auditoria append-only =="
espera_erro "DELETE na auditoria bloqueado" "$OWNER" "DELETE FROM auditoria.evento" "append-only"

echo
if (( falhas > 0 )); then echo "$falhas verificação(ões) falharam."; exit 1; fi
echo "Todas as verificações passaram."
