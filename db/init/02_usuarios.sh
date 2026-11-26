#!/usr/bin/env bash
# =============================================================================
# Cria os usuários de LOGIN de cada microsserviço e os associa aos papéis de
# grupo definidos em 01_init.sql (privilégio mínimo por serviço).
# Executado pelo entrypoint do PostgreSQL logo após 01_init.sql.
# Senhas vêm do ambiente (docker-compose.yml / .env); nunca ficam no repositório.
# =============================================================================
set -euo pipefail

: "${DB_PASS_API:?defina DB_PASS_API}"
: "${DB_PASS_API_SOCIAL:?defina DB_PASS_API_SOCIAL}"
: "${DB_PASS_COLETOR:?defina DB_PASS_COLETOR}"
: "${DB_PASS_IA:?defina DB_PASS_IA}"
: "${DB_PASS_IA_SOCIAL:?defina DB_PASS_IA_SOCIAL}"
: "${DB_PASS_EXPERIMENTO:?defina DB_PASS_EXPERIMENTO}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v p_api="$DB_PASS_API" \
     -v p_api_social="$DB_PASS_API_SOCIAL" \
     -v p_coletor="$DB_PASS_COLETOR" \
     -v p_ia="$DB_PASS_IA" \
     -v p_ia_social="$DB_PASS_IA_SOCIAL" \
     -v p_exp="$DB_PASS_EXPERIMENTO" \
     -v db="$POSTGRES_DB" <<'EOSQL'
-- Um login por serviço e por finalidade. As conexões "_social" existem para que
-- o acesso ao CadÚnico fique isolado e rastreável (LGPD, finalidade única).
CREATE ROLE usr_api            LOGIN PASSWORD :'p_api'        IN ROLE radar_api;
CREATE ROLE usr_api_social     LOGIN PASSWORD :'p_api_social' IN ROLE radar_social;
CREATE ROLE usr_coletor        LOGIN PASSWORD :'p_coletor'    IN ROLE radar_coletor;
CREATE ROLE usr_ia             LOGIN PASSWORD :'p_ia'         IN ROLE radar_ia;
CREATE ROLE usr_ia_social      LOGIN PASSWORD :'p_ia_social'  IN ROLE radar_social;
CREATE ROLE usr_experimento    LOGIN PASSWORD :'p_exp'        IN ROLE radar_experimento;

GRANT CONNECT ON DATABASE :"db" TO usr_api, usr_api_social, usr_coletor, usr_ia, usr_ia_social, usr_experimento;

-- search_path padrão de cada login (evita qualificar tudo no código)
ALTER ROLE usr_api         SET search_path = cadastro, analise, fiscalizacao, regulatorio, publico, auditoria, public;
ALTER ROLE usr_coletor     SET search_path = cadastro, publico, analise, regulatorio, public;
ALTER ROLE usr_ia          SET search_path = cadastro, analise, publico, regulatorio, public;
ALTER ROLE usr_api_social  SET search_path = social, cadastro, regulatorio, auditoria, public;
ALTER ROLE usr_ia_social   SET search_path = social, cadastro, regulatorio, public;
ALTER ROLE usr_experimento SET search_path = experimento, cadastro, analise, fiscalizacao, regulatorio, publico, public;

-- Limite de conexões por serviço (protege o banco quando os workers escalam)
ALTER ROLE usr_ia      CONNECTION LIMIT 60;
ALTER ROLE usr_coletor CONNECTION LIMIT 40;
EOSQL

echo "[radar] usuários de serviço criados."
