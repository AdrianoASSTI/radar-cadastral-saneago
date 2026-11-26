"""
Módulo Tarifa Social (Lei 14.898/2024) — vínculo CadÚnico → UC e geração de alertas.

Executado SOMENTE com uma conexão do papel `radar_social` (finalidade única, LGPD).
O resultado nunca alimenta o modelo de fiscalização.

Vínculo família → UC (problema de record linkage):
  candidatos = UCs ativas a até R metros do ponto geocodificado da família;
  sim  = similaridade de trigramas (pg_trgm) entre o endereço normalizado da
         família e "logradouro número bairro" normalizado da UC;
  prox = 1 − d/R;
  confiança = 0,6·sim + 0,4·prox; escolhe-se o candidato de maior confiança.
  Método: ENDERECO_EXATO (sim = 1), ENDERECO_SIMILAR (sim ≥ 0,45) ou PROXIMIDADE_GEO.

Elegibilidade: renda per capita ≤ ½ salário mínimo OU BPC (social.vw_elegibilidade).
Alerta: família elegível, vínculo com confiança ≥ limiar, UC ativa e ainda fora da
Residencial Social, sem alerta aberto. Cada alerta guarda a evidência da regra.
"""

from __future__ import annotations

RAIO_VINCULO_M = 150
CONFIANCA_MINIMA = 0.5

SQL_VINCULAR = """
WITH candidatos AS (
  SELECT f.id AS familia_id, uc.id AS uc_id,
         similarity(f.endereco_normalizado,
                    uc.endereco_normalizado || ' ' || cadastro.normalizar_endereco(b.nome)) AS sim,
         ST_Distance(f.geom::geography, uc.geom::geography) AS dist
  FROM social.familia_cadunico f
  JOIN cadastro.unidade_consumidora uc
    ON uc.ligacao_ativa AND ST_DWithin(f.geom::geography, uc.geom::geography, %(raio)s)
  JOIN cadastro.bairro b ON b.id = uc.bairro_id
  WHERE NOT EXISTS (SELECT 1 FROM social.vinculo_familia_uc v WHERE v.familia_id = f.id)
),
melhor AS (
  SELECT DISTINCT ON (familia_id) familia_id, uc_id, sim, dist,
         0.6 * sim + 0.4 * (1 - dist / %(raio)s) AS confianca
  FROM candidatos
  ORDER BY familia_id, 0.6 * sim + 0.4 * (1 - dist / %(raio)s) DESC
)
INSERT INTO social.vinculo_familia_uc (familia_id, uc_id, metodo, confianca)
SELECT familia_id, uc_id,
       CASE WHEN sim >= 0.999 THEN 'ENDERECO_EXATO'
            WHEN sim >= 0.45  THEN 'ENDERECO_SIMILAR'
            ELSE 'PROXIMIDADE_GEO' END::social.metodo_vinculo,
       round(LEAST(GREATEST(confianca, 0), 1)::numeric, 3)
FROM melhor
RETURNING familia_id
"""

SQL_GERAR_ALERTAS = """
INSERT INTO social.alerta_tarifa_social (uc_id, familia_id, criterio, evidencia)
SELECT e.uc_id, e.familia_id, e.criterio,
       jsonb_build_object(
         'regra', 'Lei 14.898/2024: renda per capita <= 1/2 salário mínimo OU BPC',
         'criterio', e.criterio,
         'renda_per_capita', e.renda_per_capita,
         'limite_renda_per_capita', e.limite_renda_pc,
         'recebe_bpc', e.recebe_bpc,
         'vinculo_metodo', e.metodo,
         'vinculo_confianca', e.confianca,
         'categoria_atual', e.categoria_atual,
         'gerado_por', 'radar_comum.tarifa_social')
FROM social.vw_elegibilidade e
WHERE e.criterio IS NOT NULL
  AND e.ligacao_ativa
  AND e.categoria_atual = 'RESIDENCIAL_NORMAL'
  AND e.confianca >= %(conf)s
  AND NOT EXISTS (SELECT 1 FROM social.alerta_tarifa_social a
                  WHERE a.uc_id = e.uc_id AND a.status IN ('IDENTIFICADO', 'FAMILIA_CONTATADA'))
ON CONFLICT DO NOTHING
RETURNING id
"""

# I3 — cobertura da Tarifa Social (ICTS, AIR nº 17/2026 — AGR).
SQL_COBERTURA = """
WITH social AS (
  SELECT COALESCE(sum(uc.economias), 0) AS economias_social
  FROM cadastro.unidade_consumidora uc
  WHERE uc.ligacao_ativa AND uc.categoria_atual = 'RESIDENCIAL_SOCIAL'
),
elegiveis AS (
  SELECT count(*) AS familias_elegiveis
  FROM social.familia_cadunico f
  WHERE f.recebe_bpc OR f.renda_per_capita <=
        (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'salario_minimo')
      * (SELECT valor_num FROM regulatorio.parametro WHERE chave = 'tarifa_social_renda_pc_max_fracao_sm')
),
alertas AS (
  SELECT count(*) FILTER (WHERE status IN ('IDENTIFICADO','FAMILIA_CONTATADA')) AS alertas_abertos,
         count(*) FILTER (WHERE status = 'INCLUIDA') AS familias_incluidas_pelo_sistema
  FROM social.alerta_tarifa_social
),
vinc AS (SELECT count(*) AS familias_vinculadas FROM social.vinculo_familia_uc)
SELECT * FROM social, elegiveis, alertas, vinc
"""


async def processar(conn, raio_m: int = RAIO_VINCULO_M, confianca_minima: float = CONFIANCA_MINIMA) -> dict:
    """Vincula famílias ainda sem UC e gera alertas. `conn` deve ser do papel radar_social."""
    cur = await conn.execute(SQL_VINCULAR, {"raio": raio_m})
    vinculadas = len(await cur.fetchall())
    cur = await conn.execute(SQL_GERAR_ALERTAS, {"conf": confianca_minima})
    alertas = len(await cur.fetchall())
    return {"familias_vinculadas": vinculadas, "alertas_gerados": alertas,
            "raio_m": raio_m, "confianca_minima": confianca_minima}
