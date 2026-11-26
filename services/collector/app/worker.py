"""
Worker de Coleta e Cruzamento — Radar Cadastral SANEAGO.

Para cada mensagem COLETAR_UC:
  1. cruza a UC com CNPJ, alvarás e zoneamento (PostGIS);
  2. busca a imagem de fachada mais recente nas fontes permitidas e a coloca na
     QUARENTENA (tmpfs) — a imagem bruta nunca é gravada em disco;
  3. grava `analise.evidencia_coleta`;
  4. publica ANALISAR_UC para o worker de IA (fila paralela ou sequencial, conforme o lote).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from radar_comum import topologia
from radar_comum.mensagens import MensagemAnalise, MensagemColeta, MensagemResultado
from radar_comum.worker_base import WorkerBase

from radar_comum.evidencia import evidencia_bases
from .fontes import QUARENTENA, melhor_imagem, montar_fontes

DIAS_DESATUALIZADA = int(os.getenv("DIAS_IMAGEM_DESATUALIZADA", "540"))


class Coletor(WorkerBase):
    nome = "coletor"
    filas = (topologia.FILA_COLETA, f"{topologia.FILA_COLETA}.seq")

    async def preparar(self) -> None:
        QUARENTENA.mkdir(parents=True, exist_ok=True)
        self.fontes = montar_fontes(os.getenv("FONTES_IMAGEM", "leiturista,mapillary,geo360").split(","),
                                    os.getenv("MODO_FONTES", "simulado"))
        self.pool = AsyncConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=4,
                                        kwargs={"row_factory": dict_row}, open=False)
        await self.pool.open(wait=True, timeout=60)

    async def processar(self, dados: dict) -> None:
        m = MensagemColeta.model_validate(dados)
        async with self.pool.connection() as conn:
            ev = await evidencia_bases(conn, m.uc_id)
            img = await melhor_imagem(self.fontes, m.matricula, m.latitude, m.longitude, str(m.mensagem_id))
            idade = (datetime.now(timezone.utc) - img.capturada_em).days if img else None
            ev["imagem"] = {
                "disponivel": img is not None,
                "desatualizada": img is None or idade > DIAS_DESATUALIZADA,
                "fonte": img.fonte if img else None,
                "capturada_em": img.capturada_em.isoformat() if img else None,
                "idade_dias": idade,
            }
            cur = await conn.execute("""
                INSERT INTO analise.evidencia_coleta (uc_id, lote_id, sinais, imagem_disponivel, imagem_desatualizada)
                VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (m.uc_id, m.lote_id, Jsonb(ev), ev["imagem"]["disponivel"], ev["imagem"]["desatualizada"]))
            evid_id = (await cur.fetchone())["id"]
        saida = MensagemAnalise(lote_id=m.lote_id, uc_id=m.uc_id, modo=m.modo, evidencia_id=evid_id,
                                imagem_quarentena=str(img.caminho_quarentena) if img else None,
                                imagem_fonte=img.fonte if img else None,
                                imagem_capturada_em=img.capturada_em if img else None,
                                imagem_referencia_origem=img.referencia_origem if img else None)
        await self.publicar(topologia.rk_analise(m.modo), saida.model_dump_json().encode(), saida.tipo,
                            str(saida.mensagem_id), str(m.lote_id))

    async def ao_falhar(self, dados: dict, erro: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("SELECT * FROM analise.registrar_progresso(%s, false, %s)",
                               (dados["lote_id"], self.worker_id))
        r = MensagemResultado(lote_id=dados["lote_id"], uc_id=dados["uc_id"], modo=dados.get("modo", "PARALELO"),
                              sucesso=False, erro=f"coleta: {erro}", worker_id=self.worker_id)
        await self.publicar(topologia.RK_RESULTADO, r.model_dump_json().encode(), r.tipo)

    async def encerrar(self) -> None:
        await self.pool.close()


if __name__ == "__main__":
    asyncio.run(Coletor().executar())
