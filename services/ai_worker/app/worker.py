"""
Worker de IA — Radar Cadastral SANEAGO.

Para cada mensagem ANALISAR_UC:
  1. lê a imagem da quarentena (RAM), detecta elementos (YOLOv11n) e ANONIMIZA
     rostos/placas; grava somente a imagem borrada, com data de expurgo (LGPD);
  2. monta o vetor de atributos (consumo + bases públicas + visão) — mesma função
     usada no treino (radar_comum.features);
  3. XGBoost → P(categoria); TreeSHAP → explicação; Ganho Esperado → score;
  4. grava `analise.resultado_analise` e atualiza o progresso do lote (atômico);
  5. o worker que fecha o lote dispara o módulo Tarifa Social (conexão própria);
  6. publica RESULTADO_UC (telemetria de vazão/latência para o benchmark).

A IA NUNCA altera a categoria da UC (o papel do banco nem tem essa permissão).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from radar_comum import tarifa_social, topologia
from radar_comum.features import vetor_atributos
from radar_comum.ganho import ganho_esperado, volume_referencia
from radar_comum.mensagens import MensagemAnalise, MensagemResultado
from radar_comum.tarifas import TabelaTarifaria
from radar_comum.worker_base import WorkerBase

from .modelo import Preditor
from .visao import Detector, anonimizar, so_comerciais

log = logging.getLogger("radar.ia")
STORAGE = Path(os.getenv("STORAGE_LOCAL_PATH", "/data/imagens"))
RETENCAO_DIAS = int(os.getenv("RETENCAO_IMAGENS_DIAS", "45"))
INTERVALO_EXPURGO_S = int(os.getenv("INTERVALO_EXPURGO_S", "3600"))


class WorkerIA(WorkerBase):
    nome = "ia"
    filas = (topologia.FILA_ANALISE, f"{topologia.FILA_ANALISE}.seq")

    async def preparar(self) -> None:
        STORAGE.mkdir(parents=True, exist_ok=True)
        self.detector = await asyncio.to_thread(Detector)
        self.preditor = Preditor()
        self.versao = f"{self.preditor.versao}+{self.detector.versao}"
        self.pool = AsyncConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=3,
                                        kwargs={"row_factory": dict_row}, open=False)
        await self.pool.open(wait=True, timeout=60)
        url_social = os.getenv("DATABASE_URL_SOCIAL")
        self.pool_social = AsyncConnectionPool(url_social, min_size=0, max_size=1, kwargs={"row_factory": dict_row},
                                               open=False) if url_social else None
        if self.pool_social:
            await self.pool_social.open(wait=False)
        async with self.pool.connection() as c:
            bas = await (await c.execute("SELECT categoria::text, valor_mensal FROM regulatorio.tarifa_basica")).fetchall()
            fx = await (await c.execute("SELECT vigencia_inicio, categoria::text, faixa_min_m3, faixa_max_m3, agua_m3, "
                                        "esgoto_coleta_m3, esgoto_tratam_m3 FROM regulatorio.tarifa_faixa")).fetchall()
            par = {r["chave"]: r["v"] for r in await (await c.execute(
                "SELECT chave, coalesce(valor_num::text, valor_texto) AS v FROM regulatorio.parametro")).fetchall()}
        self.tabela = TabelaTarifaria.de_linhas(bas, fx, par)
        self._expurgo = asyncio.create_task(self._laco_expurgo())
        log.info("worker de IA pronto: %s", self.versao)

    # ------------------------------------------------------------------ visão
    def _pipeline_visao(self, caminho: str):
        img = cv2.imread(caminho)
        if img is None:
            raise ValueError(f"imagem ilegível: {caminho}")
        dets = self.detector.detectar(img)
        anon, n_rostos, n_placas = anonimizar(img, dets, self.detector.haar)
        ok, buf = cv2.imencode(".jpg", anon, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return dets, buf.tobytes(), img.shape[1], img.shape[0], n_rostos, n_placas

    async def processar(self, dados: dict) -> None:
        m = MensagemAnalise.model_validate(dados)
        t0 = time.perf_counter()
        async with self.pool.connection() as conn:
            uc = await (await conn.execute("""
                SELECT id, categoria_atual::text AS categoria_atual, economias, possui_esgoto
                FROM cadastro.unidade_consumidora WHERE id = %s""", (m.uc_id,))).fetchone()
            leit = await (await conn.execute("""
                SELECT volume_m3::float AS v, tipo_leitura::text AS t FROM cadastro.consumo_mensal
                WHERE uc_id = %s ORDER BY competencia""", (m.uc_id,))).fetchall()
            sinais = (await (await conn.execute("SELECT sinais FROM analise.evidencia_coleta WHERE id = %s",
                                                (m.evidencia_id,))).fetchone())["sinais"]

            dets, imagem_id = [], None
            if m.imagem_quarentena and Path(m.imagem_quarentena).exists():
                try:
                    dets, jpg, w, h, nr, npl = await asyncio.to_thread(self._pipeline_visao, m.imagem_quarentena)
                finally:
                    Path(m.imagem_quarentena).unlink(missing_ok=True)     # bruta sai da RAM imediatamente
                agora = datetime.now(timezone.utc)
                imagem_id = uuid.uuid4()
                rel = Path(f"{agora:%Y/%m}/{imagem_id}.jpg")
                (STORAGE / rel).parent.mkdir(parents=True, exist_ok=True)
                (STORAGE / rel).write_bytes(jpg)
                capt = m.imagem_capturada_em or agora
                await conn.execute("""
                    INSERT INTO analise.imagem_fachada
                      (id, uc_id, fonte, uri_objeto, referencia_origem, capturada_em, largura_px, altura_px,
                       sha256, anonimizada, rostos_borrados, placas_borradas, expira_em)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s)""",
                    (imagem_id, m.uc_id, m.imagem_fonte or "SINTETICA", str(rel), m.imagem_referencia_origem, capt,
                     w, h, hashlib.sha256(jpg).hexdigest(), nr, npl,
                     max(agora, capt) + timedelta(days=RETENCAO_DIAS)))
                for d in so_comerciais(dets):
                    await conn.execute("""
                        INSERT INTO analise.deteccao_visual
                          (imagem_id, classe, confianca, bbox_x1, bbox_y1, bbox_x2, bbox_y2, modelo_versao)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (imagem_id, d["classe"], d["confianca"], max(0, d["x1"]), max(0, d["y1"]),
                         min(1, d["x2"]), min(1, d["y2"]), self.detector.versao))

            serie = [r["v"] for r in leit]
            comerciais = so_comerciais(dets)
            atrib = vetor_atributos(sinais, serie, comerciais, sum(r["t"] == "ESTIMADA" for r in leit))
            probs, explic = await asyncio.to_thread(self.preditor.prever, atrib)

            cat = uc["categoria_atual"]
            residencial = cat if cat.startswith("RESIDENCIAL") else "RESIDENCIAL_NORMAL"
            p_cat = {residencial: probs["RESIDENCIAL"], "COMERCIAL_I": probs["COMERCIAL_I"],
                     "COMERCIAL_II": probs["COMERCIAL_II"], "INDUSTRIAL": probs["INDUSTRIAL"]}
            g = ganho_esperado(self.tabela, cat, p_cat, volume_referencia(serie), uc["economias"], uc["possui_esgoto"])
            explic.update({
                "probabilidades": {k: round(v, 4) for k, v in probs.items()},
                "deteccoes": [{"classe": d["classe"], "confianca": d["confianca"]} for d in comerciais],
                "evidencias": {
                    "cnpjs": [{k: c.get(k) for k in ("razao_social", "cnae_descricao", "porte", "situacao", "distancia_m")}
                              for c in sinais.get("cnpjs", [])],
                    "alvaras": sinais.get("alvaras", []), "zona_uso": sinais.get("zona_uso"),
                    "imagem": sinais.get("imagem")},
                "ganho": {"volume_referencia_m3": g.volume_referencia_m3,
                          "ganho_se_confirmado_anual": float(g.ganho_se_confirmado_anual)},
            })
            ms = int((time.perf_counter() - t0) * 1000)
            cur = await conn.execute("""
                INSERT INTO analise.resultado_analise
                  (uc_id, lote_id, imagem_id, modelo_versao, categoria_atual, probabilidade_irregularidade,
                   categoria_sugerida, probabilidades_categoria, fatura_atual_mensal, fatura_sugerida_mensal,
                   ganho_esperado_anual, score_prioridade, explicabilidade, features, imagem_desatualizada,
                   tempo_inferencia_ms, worker_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (m.uc_id, m.lote_id, imagem_id, self.versao, cat, g.probabilidade_irregularidade,
                 g.categoria_sugerida, Jsonb({k: round(v, 4) for k, v in p_cat.items()}),
                 g.fatura_atual_mensal, g.fatura_sugerida_mensal, g.ganho_esperado_anual, g.score_prioridade,
                 Jsonb(explic), Jsonb(atrib), bool(sinais.get("imagem", {}).get("desatualizada")), ms, self.worker_id))
            resultado_id = (await cur.fetchone())["id"]
            prog = await (await conn.execute("SELECT * FROM analise.registrar_progresso(%s, true, %s)",
                                             (m.lote_id, self.worker_id))).fetchone()

        if prog["concluiu"]:
            log.info("lote %s concluído (%s/%s, falhas=%s)", m.lote_id, prog["processadas"], prog["total"], prog["falhas"])
            await self._tarifa_social()
        r = MensagemResultado(lote_id=m.lote_id, uc_id=m.uc_id, modo=m.modo, sucesso=True,
                              resultado_analise_id=resultado_id, tempo_ms=ms, worker_id=self.worker_id)
        await self.publicar(topologia.RK_RESULTADO, r.model_dump_json().encode(), r.tipo)

    async def _tarifa_social(self) -> None:
        """Ao fechar um lote: vínculo CadÚnico → UC e alertas (conexão usr_ia_social)."""
        if not self.pool_social:
            return
        try:
            async with self.pool_social.connection() as c:
                await c.execute("SELECT set_config('radar.usuario', %s, true)", (self.worker_id,))
                r = await tarifa_social.processar(c)
            log.info("tarifa social: %s", r)
        except Exception:  # noqa: BLE001 — não pode derrubar a fiscalização
            log.exception("falha no módulo tarifa social")

    async def ao_falhar(self, dados: dict, erro: str) -> None:
        q = dados.get("imagem_quarentena")
        if q:
            Path(q).unlink(missing_ok=True)
        async with self.pool.connection() as conn:
            prog = await (await conn.execute("SELECT * FROM analise.registrar_progresso(%s, false, %s)",
                                              (dados["lote_id"], self.worker_id))).fetchone()
        if prog["concluiu"]:
            await self._tarifa_social()
        r = MensagemResultado(lote_id=dados["lote_id"], uc_id=dados["uc_id"], modo=dados.get("modo", "PARALELO"),
                              sucesso=False, erro=erro, worker_id=self.worker_id)
        await self.publicar(topologia.RK_RESULTADO, r.model_dump_json().encode(), r.tipo)

    async def _laco_expurgo(self) -> None:
        """LGPD (minimização): apaga imagens vencidas do storage e marca no banco."""
        while True:
            try:
                async with self.pool.connection() as conn:
                    for r in await (await conn.execute("SELECT * FROM analise.imagens_a_expurgar()")).fetchall():
                        (STORAGE / r["uri_objeto"]).unlink(missing_ok=True)
                        await conn.execute("UPDATE analise.imagem_fachada SET expurgada_em = now() "
                                           "WHERE id = %s AND expurgada_em IS NULL", (r["imagem_id"],))
            except Exception:  # noqa: BLE001
                log.exception("expurgo falhou")
            await asyncio.sleep(INTERVALO_EXPURGO_S)

    async def encerrar(self) -> None:
        self._expurgo.cancel()
        await self.pool.close()
        if self.pool_social:
            await self.pool_social.close()


if __name__ == "__main__":
    asyncio.run(WorkerIA().executar())
