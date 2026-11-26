#!/usr/bin/env python3
"""
Seed do Radar Cadastral SANEAGO.

Popula o banco com:
  * 15 bairros de Goiânia em 4 estratos de renda (base do indicador de equidade I5);
  * zoneamento simplificado (um polígono por bairro);
  * 30 UCs curadas com cenários mistos + histórico de 24 meses de consumo;
  * bases públicas sintéticas (CNPJ, alvarás) e famílias do CadÚnico (schema restrito);
  * grupo controle histórico (vistorias do "método atual" em 2025) para o I1;
  * gabarito sintético (rótulos reais) em schema isolado, lido só pelo benchmark.

Opcionalmente gera N UCs procedurais (SEED_EXTRA_UCS / --extra) para testes de
escala e para o protocolo experimental (docs/04).

Reprodutibilidade: toda aleatoriedade vem de um único `random.Random(SEED_RANDOM_STATE)`.
Idempotência: se já houver UCs no banco, o seed não faz nada.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import psycopg

import dados_referencia as ref

FUSO = timezone(timedelta(hours=-3))
N_MESES = 24
ULTIMA_COMPETENCIA = date(2026, 10, 1)          # último mês faturado no momento do seed
METADE_SM = 1621.00 * 0.5                       # Lei 14.898/2024 (conferido também no banco)


# =============================================================================
# Utilidades
# =============================================================================

def competencias(n: int = N_MESES, fim: date = ULTIMA_COMPETENCIA) -> list[date]:
    """Lista de 1º dias de mês, do mais antigo ao mais recente."""
    out, ano, mes = [], fim.year, fim.month
    for _ in range(n):
        out.append(date(ano, mes, 1))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return out[::-1]


def fator_sazonal(mes: int, amplitude: float = 0.08) -> float:
    """Goiânia: estiagem de maio a setembro eleva o consumo; pico em setembro."""
    return 1.0 + amplitude * math.cos(2 * math.pi * (mes - 9) / 12)


def gerar_serie_consumo(spec: tuple, meses: list[date], rng: random.Random,
                        teto: float | None = None) -> list[tuple[date, float, str]]:
    """
    Gera a série mensal (m³) de uma UC.
      ("estavel", (a,b), dp)                 média ~ U(a,b), ruído N(0, dp)
      ("degrau", (a,b), (c,d), (m0,m1))      mudança de regime no mês t0 ~ U{m0..m1},
                                             com rampa de 2 meses (abertura do negócio)
    5% das leituras são ESTIMADAS (média das 3 anteriores), como ocorre com hidrômetro inacessível.
    `teto` limita a série (ex.: Comercial II só existe até 10 m³).
    """
    tipo = spec[0]
    valores: list[float] = []
    if tipo == "estavel":
        media = rng.uniform(*spec[1])
        dp = spec[2]
        for m in meses:
            valores.append(media * fator_sazonal(m.month) + rng.gauss(0, dp))
    elif tipo == "degrau":
        antes, depois = rng.uniform(*spec[1]), rng.uniform(*spec[2])
        t0 = rng.randint(*spec[3])
        dp_a, dp_d = max(0.8, antes * 0.08), max(1.0, depois * 0.08)
        for i, m in enumerate(meses):
            if i < t0:
                base, dp = antes, dp_a
            elif i < t0 + 2:                                   # rampa
                frac = (i - t0 + 1) / 3
                base, dp = antes + frac * (depois - antes), dp_d
            else:
                base, dp = depois, dp_d
            valores.append(base * fator_sazonal(m.month) + rng.gauss(0, dp))
    else:
        raise ValueError(f"tipo de série desconhecido: {tipo}")

    serie = []
    for i, (m, v) in enumerate(zip(meses, valores)):
        v = max(1.0, v)
        if teto is not None:
            v = min(v, teto)
        tipo_leitura = "REAL"
        if i >= 3 and rng.random() < 0.05:
            v = sum(x for _, x, _ in serie[-3:]) / 3
            tipo_leitura = "ESTIMADA"
        serie.append((m, float(round(v)), tipo_leitura))     # hidrômetro registra m³ inteiros
    return serie


def dv_cnpj(base12: str) -> str:
    """Dígitos verificadores do CNPJ (módulo 11)."""
    def dv(nums: str, pesos: list[int]) -> str:
        r = sum(int(n) * p for n, p in zip(nums, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    d1 = dv(base12, p1)
    return d1 + dv(base12 + d1, p2)


def novo_cnpj(rng: random.Random, usados: set[str]) -> str:
    while True:
        base = f"{rng.randint(10_000_000, 99_999_999)}0001"
        c = base + dv_cnpj(base)
        if c not in usados:
            usados.add(c)
            return c


def pseudonimo(salt: str, *partes: str) -> str:
    return hashlib.sha256((salt + "|" + "|".join(partes)).encode()).hexdigest()


def deslocar(lat: float, lon: float, metros: float, rng: random.Random) -> tuple[float, float]:
    """Desloca um ponto em direção aleatória por até `metros` (aproximação local)."""
    ang = rng.uniform(0, 2 * math.pi)
    d = rng.uniform(0, metros)
    dlat = (d * math.cos(ang)) / 111_320
    dlon = (d * math.sin(ang)) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def conectar(url: str, tentativas: int = 30) -> psycopg.Connection:
    for i in range(tentativas):
        try:
            return psycopg.connect(url, autocommit=False)
        except psycopg.OperationalError as e:
            print(f"[seed] aguardando banco ({i + 1}/{tentativas}): {e.__class__.__name__}")
            time.sleep(2)
    sys.exit("[seed] banco indisponível")


# =============================================================================
# Especificações de UC (curadas + procedurais)
# =============================================================================

def especificar_ucs(rng: random.Random, n_extra: int) -> list[dict]:
    """Retorna as UCs curadas (ref.UCS) e, se pedido, UCs procedurais."""
    specs = [dict(u, origem="curada") for u in ref.UCS]
    if n_extra <= 0:
        return specs

    bairros_por_estrato: dict[str, list[str]] = {}
    for nome, _, estrato, *_ in ref.BAIRROS:
        bairros_por_estrato.setdefault(estrato, []).append(nome)
    estrato_de = {b[0]: b[2] for b in ref.BAIRROS}
    todos_bairros = [b[0] for b in ref.BAIRROS]

    for k in range(n_extra):
        n = len(ref.UCS) + k + 1
        bairro = rng.choice(todos_bairros)
        probs = ref.PROB_CENARIO_POR_ESTRATO[estrato_de[bairro]]
        cenario = rng.choices(list(probs), weights=list(probs.values()))[0]
        spec = dict(n=n, bairro=bairro, cenario=cenario, origem="procedural",
                    logradouro=f"{ref.SIGLA_RUA[bairro]}{rng.randint(1, 99)}",
                    numero=(f"Qd. {rng.randint(1, 90)} Lt. {rng.randint(1, 30)}"
                            if estrato_de[bairro] == "BAIXA" else str(rng.randint(10, 2500))))
        atividades = ref.ATIVIDADES_POR_CENARIO.get(cenario)
        if atividades:
            nome_ativ, cnae, desc = rng.choice(atividades)
            spec["atividade"] = nome_ativ
            if rng.random() < ref.PROB_CNPJ.get(cenario, 0):
                porte = "MEI" if cenario in ("MEI_SEM_ATIVIDADE", "HOME_SERVICE") else rng.choice(["ME", "EPP"])
                if cenario == "IND_OK":
                    porte = "DEMAIS"
                spec["cnpj"] = dict(razao=f"{nome_ativ} {n:05d}", cnae=cnae, cnae_desc=desc, porte=porte,
                                    situacao="ATIVA",
                                    abertura=(date(2015, 1, 1) + timedelta(days=rng.randint(0, 4000))).isoformat())
        # Alvará de funcionamento: frequente nos estabelecimentos regulares, raro nos não declarados
        p_alv = {"COM_OK": .85, "COM_II_OK": .7, "IND_OK": .9, "RES_COM_I": .2, "RES_IND": .3}.get(cenario, 0)
        if rng.random() < p_alv:
            emissao = date(2024, 1, 1) + timedelta(days=rng.randint(0, 900))
            spec["alvara"] = dict(atividade=spec.get("atividade", "Comércio"), emissao=emissao.isoformat(),
                                  validade=(emissao + timedelta(days=365)).isoformat())
        # Elementos visuais: cada elemento do cenário aparece com prob. ~0,8
        # (oclusão, ângulo, placa removida) — gera falsos negativos realistas.
        base_vis = ref.CENARIOS[cenario]["visuais"]
        p_vis = ref.PROB_ELEMENTO_VISIVEL.get(cenario, ref.PROB_ELEMENTO_VISIVEL_PADRAO)
        spec["visuais"] = [v for v in base_vis if rng.random() < p_vis]
        # Ruído realista: séries alternativas, distratores visuais e CNPJ baixado em residências
        for prob, alt in ref.VARIACOES_CONSUMO.get(cenario, []):
            if rng.random() < prob:
                spec["consumo"] = alt
                break
        for prob, elems in ref.DISTRATORES_VISUAIS.get(cenario, []):
            if rng.random() < prob:
                spec["visuais"] = sorted(set(spec["visuais"]) | set(elems))
        if cenario in ("RES_OK", "CONSUMO_ALTO_RES") and rng.random() < ref.PROB_CNPJ_BAIXADO_RES:
            nome_ativ, cnae, desc = rng.choice(ref.ATIVIDADES_POR_CENARIO["RES_COM_I"])
            spec["cnpj"] = dict(razao=f"{nome_ativ} {n:05d} (encerrada)", cnae=cnae, cnae_desc=desc, porte="ME",
                                situacao="BAIXADA",
                                abertura=(date(2012, 1, 1) + timedelta(days=rng.randint(0, 2500))).isoformat())
        # CadÚnico: famílias elegíveis nos cenários sociais; algumas inelegíveis em RES_OK
        if cenario in ("SOCIAL_ELEGIVEL", "SOCIAL_OK"):
            bpc = rng.random() < 0.25
            spec["cadunico"] = dict(renda_pc=1621.00 if bpc else round(rng.uniform(120, METADE_SM), 2),
                                    bpc=bpc, pessoas=1 if bpc else rng.randint(2, 6))
        elif cenario == "RES_OK" and estrato_de[bairro] in ("BAIXA", "MEDIA") and rng.random() < 0.08:
            spec["cadunico"] = dict(renda_pc=round(rng.uniform(METADE_SM + 10, 1700), 2),
                                    bpc=False, pessoas=rng.randint(1, 4))
        specs.append(spec)
    return specs


# =============================================================================
# Carga
# =============================================================================

def carregar(conn: psycopg.Connection, specs: list[dict], rng: random.Random, salt: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT set_config('radar.usuario', 'seed', false)")
    meses = competencias()
    cnpjs_usados: set[str] = set()
    stats: Counter = Counter()

    # ---------------------------------------------------------------- bairros
    bairro_info: dict[str, dict] = {}
    for nome, regiao, estrato, renda, lat, lon, uso in ref.BAIRROS:
        cur.execute(
            """
            INSERT INTO cadastro.bairro (nome, regiao, faixa_renda, renda_media_pc_ref, fonte_renda, centroide, area)
            VALUES (%s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    ST_Multi(ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 900)::geometry))
            RETURNING id
            """,
            (nome, regiao, estrato, renda, ref.FONTE_RENDA, lon, lat, lon, lat))
        bid = cur.fetchone()[0]
        bairro_info[nome] = dict(id=bid, lat=lat, lon=lon, estrato=estrato)

        cur.execute(
            """
            INSERT INTO publico.zona_urbana (codigo, descricao, uso, geom, fonte, sintetico)
            VALUES (%s, %s, %s,
                    ST_Multi(ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 1000)::geometry),
                    %s, true)
            """,
            (f"Z-{bid:02d}", f"Zona simplificada — {nome}", uso, lon, lat, ref.FONTE_ZONEAMENTO))

    # ---------------------------------------------------------------- UCs
    uc_ids: dict[int, int] = {}
    for spec in specs:
        cen = ref.CENARIOS[spec["cenario"]]
        b = bairro_info[spec["bairro"]]
        lat, lon = deslocar(b["lat"], b["lon"], 450, rng)
        spec["_lat"], spec["_lon"] = lat, lon
        matricula = f"GYN{spec['n']:08d}"
        data_ligacao = date(2004, 1, 1) + timedelta(days=rng.randint(0, 6200))

        cur.execute(
            """
            INSERT INTO cadastro.unidade_consumidora
              (matricula, logradouro, numero, bairro_id, geom, categoria_atual, economias,
               possui_esgoto, ligacao_ativa, data_ligacao, titular_hash)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, true, true, %s, %s)
            RETURNING id
            """,
            (matricula, spec["logradouro"], spec["numero"], b["id"], lon, lat,
             cen["cat_atual"], spec.get("economias", 1), data_ligacao,
             pseudonimo(salt, "titular", matricula)))
        uc_id = cur.fetchone()[0]
        uc_ids[spec["n"]] = uc_id
        stats[f"estrato:{b['estrato']}"] += 1

        # Consumo (COPY = carga rápida também no modo procedural)
        serie = gerar_serie_consumo(spec.get("consumo", cen["consumo"]), meses, rng, cen.get("teto_m3"))
        with cur.copy("COPY cadastro.consumo_mensal (uc_id, competencia, volume_m3, tipo_leitura) FROM STDIN") as cp:
            for m, v, t in serie:
                cp.write_row((uc_id, m, v, t))

        endereco = f"{spec['logradouro']}, {spec['numero']}, {spec['bairro']}, Goiânia - GO"

        # CNPJ (geocodificação com ruído de ~15 m, como em bases reais)
        cnpj_num = None
        if spec.get("cnpj"):
            c = spec["cnpj"]
            cnpj_num = novo_cnpj(rng, cnpjs_usados)
            clat, clon = deslocar(lat, lon, 15, rng)
            abertura = date.fromisoformat(c["abertura"])
            cur.execute(
                """
                INSERT INTO publico.estabelecimento_cnpj
                  (cnpj, razao_social, nome_fantasia, cnae_principal, cnae_descricao, porte, situacao,
                   data_abertura, data_situacao, endereco_texto, geom, sintetico)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), true)
                """,
                (cnpj_num, c["razao"], c.get("fantasia"), c["cnae"], c["cnae_desc"], c["porte"], c["situacao"],
                 abertura, abertura if c["situacao"] == "ATIVA" else date(2024, 6, 30),
                 endereco, clon, clat))
            stats["cnpj"] += 1

        # Alvará
        if spec.get("alvara"):
            a = spec["alvara"]
            emissao = date.fromisoformat(a["emissao"])
            cur.execute(
                """
                INSERT INTO publico.alvara_funcionamento
                  (numero, cnpj, atividade, endereco_texto, geom, data_emissao, data_validade, sintetico)
                VALUES (%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), %s, %s, true)
                """,
                (f"ALV-{emissao.year}-{spec['n']:06d}", cnpj_num, a["atividade"], endereco, lon, lat,
                 emissao, date.fromisoformat(a["validade"])))
            stats["alvara"] += 1

        # CadÚnico (schema social). O VÍNCULO família→UC não é criado aqui:
        # é tarefa do módulo Tarifa Social (Etapa 3), avaliada contra o gabarito.
        elegivel = False
        if spec.get("cadunico"):
            f = spec["cadunico"]
            flat, flon = deslocar(lat, lon, 40, rng)
            end_cad = f.get("endereco") or endereco
            cur.execute(
                """
                INSERT INTO social.familia_cadunico
                  (codigo_familiar_hash, renda_per_capita, recebe_bpc, qtd_pessoas, endereco_texto, geom,
                   data_atualizacao_cadunico, sintetico)
                VALUES (%s,%s,%s,%s,%s, ST_SetSRID(ST_MakePoint(%s,%s),4326), %s, true)
                """,
                (pseudonimo(salt, "familia", str(spec["n"])), f["renda_pc"], f["bpc"], f["pessoas"],
                 end_cad, flon, flat, date(2025, 6, 1) + timedelta(days=rng.randint(0, 480))))
            elegivel = bool(f["bpc"] or f["renda_pc"] <= METADE_SM)
            stats["cadunico"] += 1
            stats["cadunico_elegivel"] += int(elegivel)

        # Gabarito (rótulo real) — schema `experimento`
        irregular = cen["cat_real"] in ref.CATEGORIAS_SUBFATURAMENTO and cen["cat_real"] != cen["cat_atual"]
        visuais = spec.get("visuais", cen["visuais"])
        cur.execute(
            """
            INSERT INTO experimento.gabarito_sintetico
              (uc_id, cenario, categoria_real, irregular, atividade_real, elementos_visuais,
               imagem_disponivel, elegivel_tarifa_social, armadilha, notas)
            VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
            """,
            (uc_id, spec["cenario"], cen["cat_real"], irregular, spec.get("atividade"),
             json.dumps(visuais), spec["cenario"] != "IMAGEM_DESATUALIZADA", elegivel,
             cen["armadilha"], f"{spec['origem']}: {cen['descricao']}"))
        stats["irregular"] += int(irregular)
        stats[f"irregular:{b['estrato']}"] += int(irregular)

    # ------------------------------------------------- grupo controle 2025 (I1)
    for n, dia, resultado, cat_const in ref.VISTORIAS_METODO_ATUAL_2025:
        if n not in uc_ids:
            continue
        quando = datetime.fromisoformat(dia).replace(hour=10, tzinfo=FUSO)
        cur.execute(
            """
            INSERT INTO fiscalizacao.ordem_vistoria (uc_id, origem, status, fiscal_matricula, criada_em, criada_por)
            VALUES (%s, 'METODO_ATUAL', 'CONCLUIDA', 'FIS-0107', %s, 'seed-historico') RETURNING id
            """, (uc_ids[n], quando - timedelta(days=7)))
        ordem_id = cur.fetchone()[0]
        reclass = resultado == "IRREGULARIDADE_CONFIRMADA"
        decisao = "RECLASSIFICAR" if reclass else ("ENCAMINHAR_ANALISE" if resultado == "IMOVEL_FECHADO" else "MANTER")
        cur.execute(
            """
            INSERT INTO fiscalizacao.laudo_vistoria
              (ordem_id, uc_id, fiscal_matricula, realizada_em, resultado, categoria_constatada,
               atividade_observada, decisao, aprovado_por, aprovado_em, notificacao_previa_em,
               prazo_contestacao_ate, aplicado_em, observacoes)
            VALUES (%s,%s,'FIS-0107',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (ordem_id, uc_ids[n], quando, resultado, cat_const,
             "Papelaria em funcionamento" if reclass else None, decisao,
             "SUP-0042" if reclass else None, quando + timedelta(days=2) if reclass else None,
             quando + timedelta(days=3) if reclass else None,
             (quando + timedelta(days=33)).date() if reclass else None,
             quando + timedelta(days=40) if reclass else None,
             "Histórico sintético do método atual (sorteio por quadra)."))
        laudo_id = cur.fetchone()[0]
        if reclass:
            # A UC já foi inserida na categoria atual (pós-reclassificação); registra-se o histórico.
            cur.execute(
                """
                INSERT INTO cadastro.historico_categoria
                  (uc_id, categoria_anterior, categoria_nova, laudo_id, alterado_em, alterado_por, observacao)
                VALUES (%s, 'RESIDENCIAL_NORMAL', %s, %s, %s, 'SUP-0042', 'Carga histórica (seed)')
                """, (uc_ids[n], cat_const, laudo_id, quando + timedelta(days=40)))
        stats["vistorias_controle"] += 1
        stats["acertos_controle"] += int(reclass)

    conn.commit()
    return stats


def resumo(conn: psycopg.Connection, stats: Counter) -> None:
    cur = conn.cursor()
    print("\n[seed] ================= RESUMO =================")
    for k in sorted(stats):
        print(f"  {k:<28} {stats[k]}")
    cur.execute("""
        SELECT b.faixa_renda, count(*) AS ucs,
               sum(g.irregular::int) AS irregulares,
               round(avg(c.volume_m3), 1) AS consumo_medio
        FROM cadastro.unidade_consumidora uc
        JOIN cadastro.bairro b ON b.id = uc.bairro_id
        JOIN experimento.gabarito_sintetico g ON g.uc_id = uc.id
        JOIN cadastro.consumo_mensal c ON c.uc_id = uc.id
        GROUP BY b.faixa_renda ORDER BY b.faixa_renda
    """)
    print("\n  estrato       UCs  irregulares  consumo médio (m³)")
    for row in cur.fetchall():
        print(f"  {row[0]:<12} {row[1] // N_MESES:>4}  {row[2] // N_MESES:>11}  {row[3]:>10}")
    cur.execute("""
        SELECT regulatorio.fatura_mensal('RESIDENCIAL_NORMAL', 15),
               regulatorio.fatura_mensal('COMERCIAL_I', 15)
    """)
    rn, c1 = cur.fetchone()
    print(f"\n  Conferência tarifária (15 m³): Residencial Normal R$ {rn} | Comercial I R$ {c1} "
          f"| Δ anual R$ {(c1 - rn) * 12}")
    print("[seed] concluído.\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed do Radar Cadastral SANEAGO")
    ap.add_argument("--extra", type=int, default=int(os.getenv("SEED_EXTRA_UCS", "0")),
                    help="número de UCs procedurais adicionais")
    ap.add_argument("--random-state", type=int, default=int(os.getenv("SEED_RANDOM_STATE", "20261125")))
    args = ap.parse_args()

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("[seed] defina DATABASE_URL")
    salt = os.getenv("PSEUDONIMIZACAO_SALT", "troque-este-salt")
    rng = random.Random(args.random_state)

    with conectar(url) as conn:
        n = conn.execute("SELECT count(*) FROM cadastro.unidade_consumidora").fetchone()[0]
        if n > 0:
            print(f"[seed] banco já populado ({n} UCs). Nada a fazer.")
            return
        print(f"[seed] random_state={args.random_state} | UCs curadas={len(ref.UCS)} | extras={args.extra}")
        specs = especificar_ucs(rng, args.extra)
        stats = carregar(conn, specs, rng, salt)
        resumo(conn, stats)


if __name__ == "__main__":
    main()
