#!/usr/bin/env bash
# =============================================================================
# Experimento de speedup (computação paralela) — Radar Cadastral SANEAGO
#
# Mede o tempo para processar um lote de N UCs (coleta + IA) variando o número
# de réplicas dos workers, na MESMA infraestrutura:
#   * baseline sequencial: modo SEQUENCIAL (fila com x-single-active-consumer
#     → um único consumidor ativo, mesmo com vários workers no ar);
#   * paralelo: modo PARALELO com n = 1, 2, 4… réplicas de coletor e de IA.
# Cada configuração é repetida R vezes após um lote de aquecimento de
# 10 UCs por réplica (cada worker recebe ao menos uma mensagem e carrega
# os modelos antes da medição). O relatório usa a MEDIANA das repetições.
#
# Uso (Git Bash, na raiz do projeto, com a API no ar):
#   bash experiments/speedup.sh            # N=300, workers "1 2 4", 3 repetições
#   bash experiments/speedup.sh 200 "1 2" 3
# Depois: docker compose --profile experimentos run --rm experiments python relatorio_speedup.py
# =============================================================================
set -euo pipefail

N=${1:-300}
WORKERS=${2:-"1 2 4"}
REP=${3:-3}
API=${API:-http://localhost:8000}
ESPERA_WORKERS=${ESPERA_WORKERS:-45}     # segundos para os workers carregarem YOLO + XGBoost

token() {
  curl -s -X POST "$API/auth/login" -d "username=analista&password=analista123" \
    | sed -E 's/.*"access_token":"([^"]+)".*/\1/'
}
TOKEN=$(token)
AUTH=(-H "Authorization: Bearer $TOKEN")

filas_pendentes() {
  curl -s "$API/saude" | grep -o '"radar\.[a-z.]*": *[0-9]*' | grep -v resultados \
    | awk -F: '{s += $2} END {print s + 0}'
}

esperar_filas_vazias() {
  local n
  while n=$(filas_pendentes); [ "$n" -gt 0 ]; do
    echo "   aguardando $n mensagem(ns) pendente(s) nas filas…"; sleep 5
  done
}

criar_lote() {   # $1 = modo, $2 = etiqueta, $3 = limite
  curl -s -X POST "$API/lotes" "${AUTH[@]}" -H 'Content-Type: application/json' \
    -d "{\"limite\": $3, \"modo\": \"$1\", \"etiqueta\": \"$2\"}" \
    | sed -E 's/.*"lote_id":"([^"]+)".*/\1/'
}

esperar_lote() {
  local s
  while :; do
    s=$(curl -s "$API/lotes/$1" "${AUTH[@]}" | sed -E 's/.*"status":"([A-Z_]+)".*/\1/')
    case "$s" in CONCLUIDO*|FALHOU) echo "$s"; return ;; esac
    sleep 2
  done
}

medir() {   # $1 = modo, $2 = etiqueta-base, $3 = réplicas no ar
  local id
  id=$(criar_lote "$1" "aquecimento" $((10 * ${3:-1}))); esperar_lote "$id" > /dev/null
  for r in $(seq 1 "$REP"); do
    esperar_filas_vazias
    local t0=$SECONDS
    id=$(criar_lote "$1" "$2:rep=$r" "$N")
    local st; st=$(esperar_lote "$id")
    echo "   $2 rep=$r → $st em $((SECONDS - t0)) s (lote $id)"
  done
}

echo "== Speedup: N=$N UCs · workers: $WORKERS · repetições: $REP =="
esperar_filas_vazias

MAX=$(echo "$WORKERS" | tr ' ' '\n' | sort -n | tail -1)
echo "-- baseline SEQUENCIAL ($MAX réplicas no ar, 1 consumidor ativo)"
docker compose up -d --scale ai_worker="$MAX" --scale collector="$MAX" ai_worker collector > /dev/null
sleep "$ESPERA_WORKERS"
medir SEQUENCIAL "speedup:modo=SEQUENCIAL:n=1" "$MAX"

for n in $WORKERS; do
  echo "-- PARALELO com n=$n réplica(s)"
  docker compose up -d --scale ai_worker="$n" --scale collector="$n" ai_worker collector > /dev/null
  sleep "$ESPERA_WORKERS"
  medir PARALELO "speedup:modo=PARALELO:n=$n" "$n"
done

docker compose up -d --scale ai_worker=1 --scale collector=1 ai_worker collector > /dev/null
echo "== Concluído. Gere o relatório com:"
echo "   docker compose --profile experimentos run --rm experiments python relatorio_speedup.py"
