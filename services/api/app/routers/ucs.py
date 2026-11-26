"""Unidades Consumidoras: consulta, detalhe (com evidências e links) e ingestão em lote."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from radar_comum.ganho import volume_referencia

from ..config import settings
from ..db import conexao
from ..schemas import Categoria, FaixaRenda, ImportacaoIn
from ..seguranca import LEITURA_GESTAO, OPERACAO, Usuario, exigir
from ..servicos.tarifas import tabela_vigente

router = APIRouter(prefix="/ucs", tags=["unidades consumidoras"])


def links_externos(lat: float, lon: float) -> dict:
    """Links para CONSULTA VISUAL HUMANA. Street View nunca é usado na inferência automatizada."""
    return {
        "street_view": f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}",
        "google_maps": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
        "geo360_goiania": settings().geo360_base_url,
        "coordenadas": f"{lat:.6f}, {lon:.6f}",
        "aviso": "Street View: apenas visualização pelo analista (Termos do Google Maps Platform).",
    }


@router.get("", summary="Listar UCs com filtros")
async def listar(categoria: Categoria | None = None, bairro_id: int | None = None,
                 faixa_renda: FaixaRenda | None = None, busca: str | None = None,
                 limite: int = Query(50, le=500), offset: int = 0,
                 _: Usuario = Depends(exigir(*LEITURA_GESTAO)), conn=Depends(conexao)):
    params = {"cat": categoria, "b": bairro_id, "f": faixa_renda,
              "q": f"%{busca.lower()}%" if busca else None, "l": limite, "o": offset}
    cur = await conn.execute("""
        SELECT uc.id, uc.matricula, uc.logradouro, uc.numero, b.id AS bairro_id, b.nome AS bairro,
               b.faixa_renda::text, uc.categoria_atual::text, uc.economias, uc.ligacao_ativa,
               ST_Y(uc.geom) AS latitude, ST_X(uc.geom) AS longitude,
               count(*) OVER () AS total
        FROM cadastro.unidade_consumidora uc JOIN cadastro.bairro b ON b.id = uc.bairro_id
        WHERE (%(cat)s::text IS NULL OR uc.categoria_atual::text = %(cat)s)
          AND (%(b)s::int IS NULL OR b.id = %(b)s)
          AND (%(f)s::text IS NULL OR b.faixa_renda::text = %(f)s)
          AND (%(q)s::text IS NULL OR lower(uc.matricula || ' ' || uc.logradouro || ' ' || b.nome) LIKE %(q)s)
        ORDER BY uc.id LIMIT %(l)s OFFSET %(o)s""", params)
    linhas = await cur.fetchall()
    return {"total": linhas[0]["total"] if linhas else 0,
            "itens": [{k: v for k, v in r.items() if k != "total"} for r in linhas]}


@router.get("/bairros", summary="Bairros e faixas de renda")
async def bairros(_: Usuario = Depends(exigir(*LEITURA_GESTAO)), conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT b.id, b.nome, b.regiao, b.faixa_renda::text, b.renda_media_pc_ref,
               ST_Y(b.centroide) AS latitude, ST_X(b.centroide) AS longitude,
               (SELECT count(*) FROM cadastro.unidade_consumidora u WHERE u.bairro_id = b.id) AS ucs
        FROM cadastro.bairro b ORDER BY b.id""")
    return await cur.fetchall()


@router.get("/imagens/{imagem_id}", summary="Imagem de fachada JÁ ANONIMIZADA (rostos e placas borrados)",
            response_class=FileResponse)
async def imagem(imagem_id: UUID, _: Usuario = Depends(exigir(*LEITURA_GESTAO, "FISCAL")), conn=Depends(conexao)):
    cur = await conn.execute("""SELECT uri_objeto, anonimizada, expurgada_em FROM analise.imagem_fachada
                                WHERE id = %s""", (imagem_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, "Imagem não encontrada")
    if r["expurgada_em"]:
        raise HTTPException(410, "Imagem expurgada (prazo de retenção LGPD vencido)")
    raiz = Path(os.getenv("STORAGE_LOCAL_PATH", "/data/imagens")).resolve()
    arq = (raiz / r["uri_objeto"]).resolve()
    if raiz not in arq.parents or not arq.exists():
        raise HTTPException(404, "Arquivo indisponível")
    return FileResponse(arq, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/{uc_id}", summary="Detalhe da UC: consumo, evidências, última análise, links, simulação")
async def detalhe(uc_id: int, _: Usuario = Depends(exigir(*LEITURA_GESTAO, "FISCAL")), conn=Depends(conexao)):
    cur = await conn.execute("""
        SELECT uc.id, uc.matricula, uc.logradouro, uc.numero, uc.complemento, uc.cep,
               uc.categoria_atual::text, uc.economias, uc.possui_esgoto, uc.ligacao_ativa, uc.data_ligacao,
               b.nome AS bairro, b.regiao, b.faixa_renda::text,
               ST_Y(uc.geom) AS latitude, ST_X(uc.geom) AS longitude,
               (SELECT z.descricao || ' (' || z.uso || ')' FROM publico.zona_urbana z
                 WHERE ST_Contains(z.geom, uc.geom) LIMIT 1) AS zona
        FROM cadastro.unidade_consumidora uc JOIN cadastro.bairro b ON b.id = uc.bairro_id
        WHERE uc.id = %s""", (uc_id,))
    uc = await cur.fetchone()
    if not uc:
        raise HTTPException(404, "UC não encontrada")

    cur = await conn.execute("""SELECT competencia, volume_m3, tipo_leitura::text FROM cadastro.consumo_mensal
                                WHERE uc_id = %s ORDER BY competencia""", (uc_id,))
    consumo = await cur.fetchall()

    cur = await conn.execute("""
        SELECT cnpj, razao_social, nome_fantasia, cnae_principal, cnae_descricao, porte::text, situacao::text,
               data_abertura, round(ST_Distance(geom::geography, (SELECT geom FROM cadastro.unidade_consumidora
                                                                  WHERE id = %(id)s)::geography)::numeric, 1) AS distancia_m
        FROM publico.estabelecimento_cnpj
        WHERE ST_DWithin(geom::geography, (SELECT geom FROM cadastro.unidade_consumidora WHERE id = %(id)s)::geography, 30)
        ORDER BY distancia_m""", {"id": uc_id})
    cnpjs = await cur.fetchall()
    cur = await conn.execute("""
        SELECT numero, cnpj, atividade, data_emissao, data_validade, data_validade >= current_date AS vigente
        FROM publico.alvara_funcionamento
        WHERE ST_DWithin(geom::geography, (SELECT geom FROM cadastro.unidade_consumidora WHERE id = %(id)s)::geography, 30)
        """, {"id": uc_id})
    alvaras = await cur.fetchall()

    cur = await conn.execute("""SELECT * FROM analise.vw_ultima_analise WHERE uc_id = %s""", (uc_id,))
    analise = await cur.fetchone()
    deteccoes, imagem = [], None
    if analise and analise.get("imagem_id"):
        cur = await conn.execute("""SELECT id, fonte::text, uri_objeto, capturada_em, largura_px, altura_px,
                                           rostos_borrados, placas_borradas, expira_em
                                    FROM analise.imagem_fachada WHERE id = %s""", (analise["imagem_id"],))
        imagem = await cur.fetchone()
        cur = await conn.execute("""SELECT d.classe, c.descricao, d.confianca, d.bbox_x1, d.bbox_y1, d.bbox_x2, d.bbox_y2
                                    FROM analise.deteccao_visual d JOIN analise.classe_visual c ON c.codigo = d.classe
                                    WHERE d.imagem_id = %s ORDER BY d.confianca DESC""", (analise["imagem_id"],))
        deteccoes = await cur.fetchall()

    cur = await conn.execute("""SELECT categoria_anterior::text, categoria_nova::text, alterado_em, alterado_por, laudo_id
                                FROM cadastro.historico_categoria WHERE uc_id = %s ORDER BY alterado_em""", (uc_id,))
    historico = await cur.fetchall()
    cur = await conn.execute("""
        SELECT o.id AS ordem_id, o.origem::text, o.status::text, o.criada_em, l.id AS laudo_id,
               l.resultado::text, l.decisao::text, l.categoria_constatada::text, l.realizada_em, l.aplicado_em
        FROM fiscalizacao.ordem_vistoria o LEFT JOIN fiscalizacao.laudo_vistoria l ON l.ordem_id = o.id
        WHERE o.uc_id = %s ORDER BY o.criada_em DESC""", (uc_id,))
    vistorias = await cur.fetchall()

    tab = await tabela_vigente(conn)
    v_ref = volume_referencia([float(c["volume_m3"]) for c in consumo])
    return {
        **uc, "consumo": consumo, "volume_referencia_m3": round(v_ref, 2),
        "simulacao_tarifaria_mensal": tab.comparar(v_ref, uc["economias"], uc["possui_esgoto"]),
        "bases_publicas": {"cnpjs_ate_30m": cnpjs, "alvaras_ate_30m": alvaras, "zona": uc["zona"]},
        "ultima_analise": analise, "imagem": imagem, "deteccoes": deteccoes,
        "historico_categoria": historico, "vistorias": vistorias,
        "links": links_externos(uc["latitude"], uc["longitude"]),
    }


@router.post("/importacao", summary="Ingestão em lote de UCs e consumo (idempotente por matrícula)")
async def importar(dados: ImportacaoIn, _: Usuario = Depends(exigir(*OPERACAO)), conn=Depends(conexao)):
    salt = settings().pseudonimizacao_salt
    rel = {"inseridas": 0, "ja_existentes": 0, "leituras_gravadas": 0, "erros": []}
    for u in dados.ucs:
        cur = await conn.execute("""
            SELECT id FROM cadastro.bairro
            WHERE (%(nome)s::text IS NOT NULL AND lower(nome) = lower(%(nome)s))
               OR (%(nome)s::text IS NULL AND ST_Contains(area, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)))
            LIMIT 1""", {"nome": u.bairro, "lat": u.latitude, "lon": u.longitude})
        b = await cur.fetchone()
        if not b:
            rel["erros"].append({"matricula": u.matricula, "erro": "bairro não encontrado"})
            continue
        cur = await conn.execute("""
            INSERT INTO cadastro.unidade_consumidora
              (matricula, logradouro, numero, complemento, bairro_id, cep, geom, categoria_atual,
               economias, possui_esgoto, titular_hash)
            VALUES (%s,%s,%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), %s, %s, %s, %s)
            ON CONFLICT (matricula) DO NOTHING RETURNING id""",
            (u.matricula, u.logradouro, u.numero, u.complemento, b["id"], u.cep, u.longitude, u.latitude,
             u.categoria_atual, u.economias, u.possui_esgoto,
             hashlib.sha256(f"{salt}|titular|{u.titular_id}".encode()).hexdigest()))
        novo = await cur.fetchone()
        if novo:
            uc_id = novo["id"]
            rel["inseridas"] += 1
        else:
            rel["ja_existentes"] += 1
            cur = await conn.execute("SELECT id FROM cadastro.unidade_consumidora WHERE matricula = %s", (u.matricula,))
            uc_id = (await cur.fetchone())["id"]
        for c in u.consumo:
            await conn.execute("""
                INSERT INTO cadastro.consumo_mensal (uc_id, competencia, volume_m3, tipo_leitura)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (uc_id, competencia) DO UPDATE
                  SET volume_m3 = EXCLUDED.volume_m3, tipo_leitura = EXCLUDED.tipo_leitura""",
                (uc_id, c.competencia, c.volume_m3, c.tipo_leitura))
            rel["leituras_gravadas"] += 1
    return rel
