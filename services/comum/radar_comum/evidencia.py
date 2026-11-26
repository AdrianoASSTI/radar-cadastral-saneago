"""
Cruzamento da UC com as bases públicas (CNPJ, alvarás, zoneamento) via PostGIS.

Regra de pareamento endereço × estabelecimento (evita atribuir o CNPJ do vizinho):
  candidato a até 50 m  E  (endereço normalizado da UC contido no do estabelecimento
                            OU  word_similarity ≥ 0,8 e distância ≤ 15 m).
Zona: a zona que contém o ponto com centroide mais próximo.

O resultado segue o contrato "evidência" de radar_comum.features.
CadÚnico NÃO é consultado aqui (finalidade exclusiva da Tarifa Social).
"""

from __future__ import annotations

SQL_EVIDENCIA = """
WITH u AS (
  SELECT id, geom, endereco_normalizado || ' ' AS ender FROM cadastro.unidade_consumidora WHERE id = %(uc)s
)
SELECT
  (SELECT coalesce(jsonb_agg(jsonb_build_object(
            'cnpj', e.cnpj, 'porte', e.porte, 'situacao', e.situacao, 'cnae', e.cnae_principal,
            'cnae_descricao', e.cnae_descricao, 'razao_social', e.razao_social,
            'distancia_m', round(ST_Distance(e.geom::geography, u.geom::geography)::numeric, 1))), '[]'::jsonb)
     FROM publico.estabelecimento_cnpj e
    WHERE ST_DWithin(e.geom::geography, u.geom::geography, 50)
      AND (e.endereco_normalizado || ' ' LIKE '%%' || u.ender || '%%'
           OR (word_similarity(u.ender, e.endereco_normalizado) >= 0.8
               AND ST_DWithin(e.geom::geography, u.geom::geography, 15)))) AS cnpjs,
  (SELECT coalesce(jsonb_agg(jsonb_build_object(
            'numero', a.numero, 'atividade', a.atividade, 'validade', a.data_validade,
            'vigente', a.data_validade >= current_date)), '[]'::jsonb)
     FROM publico.alvara_funcionamento a
    WHERE ST_DWithin(a.geom::geography, u.geom::geography, 50)
      AND (cadastro.normalizar_endereco(a.endereco_texto) || ' ' LIKE '%%' || u.ender || '%%'
           OR ST_DWithin(a.geom::geography, u.geom::geography, 10))) AS alvaras,
  (SELECT z.uso::text FROM publico.zona_urbana z
    WHERE ST_Contains(z.geom, u.geom)
    ORDER BY ST_Distance(ST_Centroid(z.geom), u.geom) LIMIT 1) AS zona_uso
FROM u
"""


async def evidencia_bases(conn, uc_id: int) -> dict:
    cur = await conn.execute(SQL_EVIDENCIA, {"uc": uc_id})
    r = await cur.fetchone()
    return {"cnpjs": r["cnpjs"], "alvaras": r["alvaras"], "zona_uso": r["zona_uso"]}
