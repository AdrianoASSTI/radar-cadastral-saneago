"""
Dados de referência do seed — Radar Cadastral SANEAGO.

TODOS os registros de UCs, pessoas, empresas e famílias são SINTÉTICOS.
- Bairros: nomes reais de Goiânia; centroides APROXIMADOS (erro esperado < ~1,5 km),
  a validar no portal Geo360 Goiânia ou na malha de setores censitários do IBGE.
- Faixa de renda dos bairros: estrato socioeconômico usado para auditar viés (I5).
  `renda_media_pc_ref` é um valor ILUSTRATIVO; substituir pela renda média domiciliar
  per capita dos setores censitários do Censo 2022 (IBGE) antes de publicar resultados.
- Logradouros seguem o padrão de nomenclatura de Goiânia; números/quadras são fictícios.
- CNPJs têm dígitos verificadores válidos, mas são gerados e marcados `sintetico=true`.
- CNAEs: subclasses da CNAE 2.3 (IBGE/CONCLA).
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Território
# -----------------------------------------------------------------------------
# (nome, região administrativa, faixa_renda, renda pc ilustrativa R$, lat, lon, uso da zona)
BAIRROS = [
    ("Setor Marista",          "Sul",       "ALTA",       6500.0, -16.7005, -49.2600, "MISTO"),
    ("Setor Bueno",            "Sul",       "ALTA",       5800.0, -16.7060, -49.2705, "MISTO"),
    ("Jardim Goiás",           "Sul",       "ALTA",       6200.0, -16.7085, -49.2370, "MISTO"),
    ("Setor Oeste",            "Central",   "MEDIA_ALTA", 4300.0, -16.6800, -49.2650, "MISTO"),
    ("Setor Sul",              "Central",   "MEDIA_ALTA", 3900.0, -16.6880, -49.2545, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Setor Campinas",         "Campinas",  "MEDIA",      2300.0, -16.6660, -49.2925, "COMERCIAL_SERVICOS"),
    ("Setor Pedro Ludovico",   "Sul",       "MEDIA",      2400.0, -16.7240, -49.2550, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Setor Leste Universitário", "Leste",  "MEDIA",      2100.0, -16.6805, -49.2420, "MISTO"),
    ("Jardim América",         "Sudoeste",  "MEDIA",      2500.0, -16.7135, -49.2850, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Setor Perimetral Norte", "Norte",     "MEDIA",      1900.0, -16.6260, -49.2800, "INDUSTRIAL"),
    ("Jardim Curitiba",        "Noroeste",  "BAIXA",       850.0, -16.6075, -49.3440, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Vila Finsocial",         "Noroeste",  "BAIXA",       900.0, -16.6235, -49.3330, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Vila Mutirão",           "Noroeste",  "BAIXA",       820.0, -16.6390, -49.3240, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Jardim Nova Esperança",  "Noroeste",  "BAIXA",       880.0, -16.6440, -49.3370, "PREDOMINANTEMENTE_RESIDENCIAL"),
    ("Jardim do Cerrado",      "Oeste",     "BAIXA",       950.0, -16.6860, -49.3800, "PREDOMINANTEMENTE_RESIDENCIAL"),
]

FONTE_RENDA = ("Valor ilustrativo do estrato socioeconômico (PI Radar Cadastral). "
               "Substituir por renda média per capita dos setores censitários — IBGE, Censo 2022.")

FONTE_ZONEAMENTO = ("Zoneamento SIMPLIFICADO e sintético para o MVP (buffer de 1 km do centroide). "
                    "Integrar com o Plano Diretor de Goiânia (LC nº 349/2022) via Geo360.")

# -----------------------------------------------------------------------------
# Cenários (o "mundo real" sintético). A IA NUNCA lê estes rótulos; eles vão
# para experimento.gabarito_sintetico e alimentam o gerador de fachadas e o benchmark.
# teto_m3: limite físico da série (Comercial II só existe até 10 m³).
# consumo: ("estavel", (min,max) média, dp) | ("degrau", (min,max) antes, (min,max) depois, (mes_min,mes_max))
# -----------------------------------------------------------------------------
CENARIOS = {
    "RES_OK": dict(
        descricao="Residência regular, cadastro correto.",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="RESIDENCIAL_NORMAL",
        consumo=("estavel", (9, 16), 1.2), visuais=[], armadilha=None),
    "CONSUMO_ALTO_RES": dict(
        descricao="Residência com consumo alto (piscina/família numerosa) sem atividade econômica.",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="RESIDENCIAL_NORMAL",
        consumo=("estavel", (22, 32), 2.5), visuais=[],
        armadilha="FALSO_POSITIVO_CONSUMO"),
    "RES_COM_I": dict(
        descricao="Uso comercial de médio porte não declarado (deveria ser Comercial I).",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="COMERCIAL_I",
        consumo=("degrau", (10, 14), (24, 45), (5, 16)),
        visuais=["letreiro", "placa_comercial"], armadilha=None),
    "RES_COM_II": dict(
        descricao="Pequeno comércio não declarado com consumo ≤ 10 m³ (Comercial II, ganho baixo).",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="COMERCIAL_II",
        consumo=("degrau", (6, 8), (8.5, 9.8), (6, 16)), teto_m3=10,
        visuais=["placa_comercial", "banner"], armadilha="GANHO_BAIXO"),
    "RES_IND": dict(
        descricao="Atividade industrial não declarada em imóvel residencial.",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="INDUSTRIAL",
        consumo=("degrau", (12, 16), (65, 95), (4, 12)),
        visuais=["portao_industrial", "doca_carga"], armadilha=None),
    "COM_INFORMAL": dict(
        descricao="Comércio informal sem CNPJ no endereço (cruzamento simples com CNPJ não detecta).",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="COMERCIAL_I",
        consumo=("degrau", (10, 13), (17, 24), (6, 16)),
        visuais=["placa_comercial"], armadilha="FALSO_NEGATIVO_CNPJ"),
    "HOME_SERVICE": dict(
        descricao="Serviço autônomo em casa (manicure/costura) que, pelas regras, permanece residencial.",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="RESIDENCIAL_NORMAL",
        consumo=("degrau", (10, 12), (12, 14), (6, 16)),
        visuais=["banner"], armadilha="FALSO_POSITIVO_VISUAL"),
    "MEI_SEM_ATIVIDADE": dict(
        descricao="MEI registrado no endereço residencial sem atendimento no local (home office).",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="RESIDENCIAL_NORMAL",
        consumo=("estavel", (9, 13), 1.0), visuais=[],
        armadilha="FALSO_POSITIVO_CNPJ"),
    "COM_OK": dict(
        descricao="Estabelecimento comercial corretamente cadastrado.",
        cat_atual="COMERCIAL_I", cat_real="COMERCIAL_I",
        consumo=("estavel", (28, 40), 3.0), visuais=["letreiro", "vitrine"], armadilha=None),
    "COM_II_OK": dict(
        descricao="Pequeno comércio corretamente cadastrado como Comercial II.",
        cat_atual="COMERCIAL_II", cat_real="COMERCIAL_II",
        consumo=("estavel", (7, 9.5), 0.6), teto_m3=10,
        visuais=["letreiro", "vitrine"], armadilha=None),
    "IND_OK": dict(
        descricao="Indústria corretamente cadastrada.",
        cat_atual="INDUSTRIAL", cat_real="INDUSTRIAL",
        consumo=("estavel", (110, 140), 8.0),
        visuais=["portao_industrial", "doca_carga", "estacionamento_clientes"], armadilha=None),
    "SOCIAL_ELEGIVEL": dict(
        descricao="Família elegível à Tarifa Social (CadÚnico ≤ 1/2 SM ou BPC) ainda na Residencial Normal.",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="RESIDENCIAL_SOCIAL",
        consumo=("estavel", (6, 10), 0.9), visuais=[], armadilha=None),
    "SOCIAL_OK": dict(
        descricao="Família já cadastrada na Residencial Social.",
        cat_atual="RESIDENCIAL_SOCIAL", cat_real="RESIDENCIAL_SOCIAL",
        consumo=("estavel", (6, 10), 0.9), visuais=[], armadilha=None),
    "IMAGEM_DESATUALIZADA": dict(
        descricao="Residência regular sem imagem recente em nenhuma fonte: sinalizar atualização em campo.",
        cat_atual="RESIDENCIAL_NORMAL", cat_real="RESIDENCIAL_NORMAL",
        consumo=("estavel", (9, 15), 1.2), visuais=[], armadilha="SEM_IMAGEM"),
}

# Para a fiscalização (subfaturamento), "irregular" = categoria real de maior tarifa
# que a atual. A elegibilidade social é rótulo separado (outra finalidade).
CATEGORIAS_SUBFATURAMENTO = {"COMERCIAL_I", "COMERCIAL_II", "INDUSTRIAL"}


def cnpj(cnpj_base: dict | None = None, **kw) -> dict:
    """Atalho para declarar um estabelecimento (o número é gerado no seed)."""
    d = dict(cnpj_base or {})
    d.update(kw)
    return d


# -----------------------------------------------------------------------------
# 30 UCs curadas. Distribuição por estrato: ALTA 7 | MEDIA_ALTA 5 | MEDIA 9 | BAIXA 9.
# Positivos de subfaturamento por estrato: 2 | 2 | 4 | 3 (prevalência ~33%, comparável).
# Armadilhas de falso positivo distribuídas em todos os estratos (permite medir I5).
# -----------------------------------------------------------------------------
UCS = [
    # ---------------------------------------------------------------- ALTA
    dict(n=1,  bairro="Setor Marista", logradouro="Rua 1137", numero="412", cenario="RES_OK"),
    dict(n=2,  bairro="Setor Marista", logradouro="Rua 1129", numero="88", cenario="RES_COM_I",
         atividade="Clínica de estética em casa",
         cnpj=cnpj(razao="Bella Pele Estética Ltda", fantasia="Bella Pele", cnae="9602502",
                   cnae_desc="Atividades de estética e outros serviços de cuidados com a beleza",
                   porte="ME", situacao="ATIVA", abertura="2025-03-10"),
         alvara=dict(atividade="Estética", emissao="2024-04-01", validade="2025-04-01")),  # alvará vencido
    dict(n=3,  bairro="Setor Bueno", logradouro="Rua T-37", numero="1520", cenario="CONSUMO_ALTO_RES",
         atividade="Residência com piscina"),
    dict(n=4,  bairro="Setor Bueno", logradouro="Avenida T-63", numero="2210", cenario="COM_OK",
         atividade="Restaurante",
         cnpj=cnpj(razao="Sabor do Cerrado Restaurante Ltda", fantasia="Sabor do Cerrado", cnae="5611201",
                   cnae_desc="Restaurantes e similares", porte="EPP", situacao="ATIVA", abertura="2018-08-20"),
         alvara=dict(atividade="Restaurante", emissao="2026-02-01", validade="2027-02-01")),
    dict(n=5,  bairro="Setor Bueno", logradouro="Rua T-48", numero="305", cenario="MEI_SEM_ATIVIDADE",
         atividade="Consultoria de TI (home office)",
         cnpj=cnpj(razao="R. A. Consultoria em TI", cnae="6204000",
                   cnae_desc="Consultoria em tecnologia da informação", porte="MEI",
                   situacao="ATIVA", abertura="2023-05-15")),
    dict(n=6,  bairro="Jardim Goiás", logradouro="Rua 56", numero="730", cenario="RES_OK"),
    dict(n=7,  bairro="Jardim Goiás", logradouro="Rua 52", numero="140", cenario="RES_COM_I",
         atividade="Pet shop com banho e tosa",
         cnpj=cnpj(razao="Patas Felizes Pet Shop Ltda", fantasia="Patas Felizes", cnae="9609208",
                   cnae_desc="Higiene e embelezamento de animais domésticos", porte="ME",
                   situacao="ATIVA", abertura="2025-06-02"),
         visuais=["letreiro", "placa_comercial", "estacionamento_clientes"]),

    # ---------------------------------------------------------- MEDIA_ALTA
    dict(n=8,  bairro="Setor Oeste", logradouro="Rua 9", numero="1044", cenario="RES_COM_II",
         atividade="Ateliê de costura sob medida com atendimento",
         cnpj=cnpj(razao="Ateliê Linha Fina", cnae="1412602",
                   cnae_desc="Confecção, sob medida, de peças do vestuário, exceto roupas íntimas",
                   porte="MEI", situacao="BAIXADA", abertura="2021-02-01")),
    dict(n=9,  bairro="Setor Oeste", logradouro="Rua 4", numero="611", cenario="RES_OK"),
    dict(n=10, bairro="Setor Sul", logradouro="Rua 90", numero="377", cenario="HOME_SERVICE",
         atividade="Manicure autônoma atendendo em casa",
         cnpj=cnpj(razao="M. S. Serviços de Manicure", cnae="9602501",
                   cnae_desc="Cabeleireiros, manicure e pedicure", porte="MEI",
                   situacao="ATIVA", abertura="2024-09-12")),
    dict(n=11, bairro="Setor Sul", logradouro="Rua 83", numero="215", cenario="RES_COM_I",
         atividade="Lanchonete",
         cnpj=cnpj(razao="Lanche do Sul Ltda", fantasia="Lanche do Sul", cnae="5611203",
                   cnae_desc="Lanchonetes, casas de chá, de sucos e similares", porte="ME",
                   situacao="ATIVA", abertura="2025-01-20"),
         visuais=["letreiro", "banner", "vitrine"]),
    dict(n=12, bairro="Setor Sul", logradouro="Rua 115", numero="58", cenario="IMAGEM_DESATUALIZADA"),

    # --------------------------------------------------------------- MEDIA
    dict(n=13, bairro="Setor Campinas", logradouro="Rua Rio Grande do Sul", numero="902", cenario="RES_COM_I",
         atividade="Lava-jato",
         cnpj=cnpj(razao="Brilho Total Lava Jato Ltda", fantasia="Brilho Total", cnae="4520005",
                   cnae_desc="Serviços de lavagem, lubrificação e polimento de veículos automotores",
                   porte="ME", situacao="ATIVA", abertura="2025-04-07"),
         visuais=["placa_comercial", "banner", "estacionamento_clientes"],
         consumo=("degrau", (11, 13), (38, 48), (6, 10))),
    dict(n=14, bairro="Setor Campinas", logradouro="Avenida 24 de Outubro", numero="1310", cenario="COM_II_OK",
         atividade="Papelaria",
         cnpj=cnpj(razao="Papelaria Campinense", cnae="4761003",
                   cnae_desc="Comércio varejista de artigos de papelaria", porte="ME",
                   situacao="ATIVA", abertura="2019-03-11"),
         alvara=dict(atividade="Papelaria", emissao="2026-01-15", validade="2027-01-15"),
         historico_controle="RECLASSIFICADA_2025"),   # foi encontrada pelo método atual em 2025
    dict(n=15, bairro="Setor Campinas", logradouro="Rua Pouso Alegre", numero="455", cenario="COM_INFORMAL",
         atividade="Salão de beleza informal",
         visuais=["placa_comercial", "banner"]),
    dict(n=16, bairro="Setor Pedro Ludovico", logradouro="Rua 1022", numero="96", cenario="RES_OK"),
    dict(n=17, bairro="Setor Pedro Ludovico", logradouro="Rua 1014", numero="233", cenario="SOCIAL_ELEGIVEL",
         cadunico=dict(renda_pc=1621.00, bpc=True, pessoas=1,
                       endereco="R 1014 233 Setor Pedro Ludovico")),   # BPC: elegível mesmo com renda = 1 SM
    dict(n=18, bairro="Setor Leste Universitário", logradouro="Avenida Universitária", numero="1780",
         cenario="RES_COM_I", atividade="Restaurante self-service",
         cnpj=cnpj(razao="Prato Cheio Refeições Ltda", fantasia="Prato Cheio", cnae="5611201",
                   cnae_desc="Restaurantes e similares", porte="ME", situacao="ATIVA", abertura="2024-11-04"),
         alvara=dict(atividade="Restaurante", emissao="2025-12-01", validade="2026-12-01"),
         visuais=["letreiro", "vitrine", "placa_comercial"]),
    dict(n=19, bairro="Setor Leste Universitário", logradouro="Rua 240", numero="512", cenario="MEI_SEM_ATIVIDADE",
         atividade="Designer gráfico (home office)",
         cnpj=cnpj(razao="J. P. Design", cnae="7410299",
                   cnae_desc="Atividades de design não especificadas anteriormente", porte="MEI",
                   situacao="ATIVA", abertura="2022-07-19")),
    dict(n=20, bairro="Setor Perimetral Norte", logradouro="Avenida Perimetral Norte", numero="4100",
         cenario="IND_OK", atividade="Fábrica de sorvetes",
         cnpj=cnpj(razao="Gelato Goiano Indústria de Alimentos Ltda", fantasia="Gelato Goiano", cnae="1053800",
                   cnae_desc="Fabricação de sorvetes e outros gelados comestíveis", porte="DEMAIS",
                   situacao="ATIVA", abertura="2012-05-30"),
         alvara=dict(atividade="Indústria de alimentos", emissao="2026-03-01", validade="2027-03-01")),
    dict(n=21, bairro="Setor Perimetral Norte", logradouro="Rua PN-12", numero="77", cenario="RES_IND",
         atividade="Fabricação de polpas de frutas em galpão nos fundos",
         cnpj=cnpj(razao="Polpas Cerrado Vivo Ltda", cnae="1033302",
                   cnae_desc="Fabricação de sucos de frutas, hortaliças e legumes, exceto concentrados",
                   porte="ME", situacao="ATIVA", abertura="2025-02-14")),

    # --------------------------------------------------------------- BAIXA
    dict(n=22, bairro="Jardim Curitiba", logradouro="Rua JC-15", numero="Qd. 30 Lt. 12", cenario="SOCIAL_ELEGIVEL",
         cadunico=dict(renda_pc=420.00, bpc=False, pessoas=4,
                       endereco="R JC 15 QD 30 LT 12 JD CURITIBA")),   # grafia diferente: testa vínculo por similaridade
    dict(n=23, bairro="Jardim Curitiba", logradouro="Rua JC-42", numero="Qd. 71 Lt. 3", cenario="RES_COM_II",
         atividade="Bar pequeno (boteco)", visuais=["placa_comercial", "banner"]),
    dict(n=24, bairro="Vila Finsocial", logradouro="Rua VF-31", numero="Qd. 12 Lt. 20", cenario="CONSUMO_ALTO_RES",
         atividade="Família numerosa (9 moradores)", economias=1),
    dict(n=25, bairro="Vila Finsocial", logradouro="Rua VF-58", numero="Qd. 40 Lt. 7", cenario="HOME_SERVICE",
         atividade="Costureira autônoma em casa"),
    dict(n=26, bairro="Vila Mutirão", logradouro="Rua M-9", numero="Qd. 15 Lt. 8", cenario="SOCIAL_OK",
         cadunico=dict(renda_pc=300.00, bpc=False, pessoas=5,
                       endereco="Rua M-9 Qd. 15 Lt. 8 Vila Mutirão")),
    dict(n=27, bairro="Vila Mutirão", logradouro="Rua M-21", numero="Qd. 33 Lt. 1", cenario="RES_COM_I",
         atividade="Açougue e mercearia",
         cnpj=cnpj(razao="Casa de Carnes Mutirão Ltda", cnae="4722901",
                   cnae_desc="Comércio varejista de carnes - açougues", porte="ME",
                   situacao="ATIVA", abertura="2025-05-26"),
         visuais=["letreiro", "placa_comercial", "vitrine"]),
    dict(n=28, bairro="Jardim Nova Esperança", logradouro="Rua NE-14", numero="Qd. 22 Lt. 5", cenario="SOCIAL_ELEGIVEL",
         cadunico=dict(renda_pc=610.00, bpc=False, pessoas=3,
                       endereco="Rua NE-14 Qd. 22 Lt. 5 Jardim Nova Esperança")),
    dict(n=29, bairro="Jardim Nova Esperança", logradouro="Rua NE-30", numero="Qd. 9 Lt. 16", cenario="RES_OK",
         cadunico=dict(renda_pc=1200.00, bpc=False, pessoas=2,       # no CadÚnico, mas acima de 1/2 SM: INELEGÍVEL
                       endereco="Rua NE-30 Qd. 9 Lt. 16 Jardim Nova Esperança")),
    dict(n=30, bairro="Jardim do Cerrado", logradouro="Rua JDC-7", numero="Qd. 4 Lt. 30", cenario="COM_INFORMAL",
         atividade="Borracharia com lavagem de veículos", visuais=["placa_comercial", "estacionamento_clientes"],
         consumo=("degrau", (10, 12), (20, 26), (6, 12))),
]

# -----------------------------------------------------------------------------
# Grupo controle histórico (método atual, 2025) — base do I1.
# 9 vistorias por sorteio de quadra, 1 acerto (UC 14, depois reclassificada).
# -----------------------------------------------------------------------------
VISTORIAS_METODO_ATUAL_2025 = [
    # (n da UC, data, resultado, categoria constatada)
    (1,  "2025-03-12", "CADASTRO_CORRETO",          "RESIDENCIAL_NORMAL"),
    (6,  "2025-03-12", "CADASTRO_CORRETO",          "RESIDENCIAL_NORMAL"),
    (9,  "2025-04-02", "CADASTRO_CORRETO",          "RESIDENCIAL_NORMAL"),
    (12, "2025-04-02", "IMOVEL_FECHADO",            None),
    (14, "2025-05-20", "IRREGULARIDADE_CONFIRMADA", "COMERCIAL_II"),
    (16, "2025-06-17", "CADASTRO_CORRETO",          "RESIDENCIAL_NORMAL"),
    (24, "2025-07-08", "CADASTRO_CORRETO",          "RESIDENCIAL_NORMAL"),
    (26, "2025-07-08", "CADASTRO_CORRETO",          "RESIDENCIAL_SOCIAL"),
    (29, "2025-08-26", "CADASTRO_CORRETO",          "RESIDENCIAL_NORMAL"),
]

# -----------------------------------------------------------------------------
# Geração procedural (SEED_EXTRA_UCS > 0): probabilidade de cada cenário por estrato.
# Prevalência de subfaturamento IGUAL entre estratos (~13%), mas a COMPOSIÇÃO muda:
# estratos baixos têm mais informalidade e mais serviço em casa (armadilha visual).
# Isso é proposital: cria o risco de viés territorial que o I5 deve detectar.
# -----------------------------------------------------------------------------
PROB_CENARIO_POR_ESTRATO = {
    "ALTA": {"RES_OK": .66, "CONSUMO_ALTO_RES": .10, "RES_COM_I": .07, "RES_COM_II": .03,
             "COM_INFORMAL": .01, "RES_IND": .02, "HOME_SERVICE": .02, "MEI_SEM_ATIVIDADE": .06,
             "COM_OK": .02, "COM_II_OK": .005, "IND_OK": .005, "SOCIAL_ELEGIVEL": 0.0, "SOCIAL_OK": 0.0,
             "IMAGEM_DESATUALIZADA": .01},
    "MEDIA_ALTA": {"RES_OK": .66, "CONSUMO_ALTO_RES": .06, "RES_COM_I": .06, "RES_COM_II": .04,
                   "COM_INFORMAL": .02, "RES_IND": .01, "HOME_SERVICE": .04, "MEI_SEM_ATIVIDADE": .05,
                   "COM_OK": .02, "COM_II_OK": .01, "IND_OK": .005, "SOCIAL_ELEGIVEL": .01, "SOCIAL_OK": .005,
                   "IMAGEM_DESATUALIZADA": .02},
    "MEDIA": {"RES_OK": .62, "CONSUMO_ALTO_RES": .04, "RES_COM_I": .05, "RES_COM_II": .04,
              "COM_INFORMAL": .03, "RES_IND": .01, "HOME_SERVICE": .06, "MEI_SEM_ATIVIDADE": .04,
              "COM_OK": .02, "COM_II_OK": .015, "IND_OK": .01, "SOCIAL_ELEGIVEL": .03, "SOCIAL_OK": .015,
              "IMAGEM_DESATUALIZADA": .02},
    "BAIXA": {"RES_OK": .50, "CONSUMO_ALTO_RES": .04, "RES_COM_I": .03, "RES_COM_II": .04,
              "COM_INFORMAL": .05, "RES_IND": .01, "HOME_SERVICE": .09, "MEI_SEM_ATIVIDADE": .02,
              "COM_OK": .01, "COM_II_OK": .015, "IND_OK": .005, "SOCIAL_ELEGIVEL": .11, "SOCIAL_OK": .05,
              "IMAGEM_DESATUALIZADA": .03},
}

# Atividades/CNAEs sorteáveis para UCs procedurais
ATIVIDADES_POR_CENARIO = {
    "RES_COM_I": [("Lanchonete", "5611203", "Lanchonetes, casas de chá, de sucos e similares"),
                  ("Lava-jato", "4520005", "Serviços de lavagem, lubrificação e polimento de veículos automotores"),
                  ("Restaurante", "5611201", "Restaurantes e similares"),
                  ("Açougue", "4722901", "Comércio varejista de carnes - açougues")],
    "RES_COM_II": [("Papelaria", "4761003", "Comércio varejista de artigos de papelaria"),
                   ("Ateliê", "1412602", "Confecção, sob medida, de peças do vestuário, exceto roupas íntimas")],
    "RES_IND": [("Fabricação de polpas", "1033302",
                 "Fabricação de sucos de frutas, hortaliças e legumes, exceto concentrados")],
    "MEI_SEM_ATIVIDADE": [("Consultoria de TI", "6204000", "Consultoria em tecnologia da informação"),
                          ("Design", "7410299", "Atividades de design não especificadas anteriormente")],
    "HOME_SERVICE": [("Manicure", "9602501", "Cabeleireiros, manicure e pedicure")],
    "COM_OK": [("Restaurante", "5611201", "Restaurantes e similares")],
    "COM_II_OK": [("Papelaria", "4761003", "Comércio varejista de artigos de papelaria")],
    "IND_OK": [("Fábrica de sorvetes", "1053800", "Fabricação de sorvetes e outros gelados comestíveis")],
}

# -----------------------------------------------------------------------------
# Ruído realista (SÓ nas UCs procedurais): sobreposição entre classes, para que
# nenhum grupo de atributos separe os cenários sozinho (docs/04, ameaças à validade).
# -----------------------------------------------------------------------------
# Variações de consumo: lista de (probabilidade, série alternativa)
VARIACOES_CONSUMO = {
    "RES_OK": [(0.18, ("degrau", (9, 14), (15, 24), (3, 20))),        # família cresceu / novos moradores
               (0.05, ("degrau", (14, 20), (8, 12), (3, 20)))],       # redução (moradores saíram)
    "CONSUMO_ALTO_RES": [(0.35, ("degrau", (12, 16), (22, 32), (3, 18)))],  # piscina construída
    "RES_COM_I": [(0.40, ("estavel", (20, 40), 3.0))],                 # negócio anterior à série histórica
    "COM_INFORMAL": [(0.45, ("estavel", (15, 24), 2.0))],
    "RES_COM_II": [(0.50, ("estavel", (7.5, 9.8), 0.7))],
    "RES_IND": [(0.30, ("estavel", (55, 95), 6.0))],
}
# Distratores visuais em imóveis SEM atividade (placa de imóvel à venda, faixa de festa/eleição)
DISTRATORES_VISUAIS = {
    "RES_OK": [(0.06, ["placa_comercial"]), (0.03, ["banner"])],
    "CONSUMO_ALTO_RES": [(0.06, ["placa_comercial"]), (0.03, ["banner"])],
    "MEI_SEM_ATIVIDADE": [(0.10, ["placa_comercial"])],
    "SOCIAL_ELEGIVEL": [(0.04, ["banner"])],
}
# Probabilidade de cada elemento comercial aparecer na foto (oclusão, ângulo, sinalização ausente)
PROB_ELEMENTO_VISIVEL = {"COM_INFORMAL": 0.6, "RES_COM_II": 0.7}
PROB_ELEMENTO_VISIVEL_PADRAO = 0.8
# Residências com CNPJ BAIXADO de negócio antigo no endereço
PROB_CNPJ_BAIXADO_RES = 0.04

# Probabilidade de o cenário ter CNPJ ativo no endereço (geração procedural)
PROB_CNPJ = {"RES_COM_I": .7, "RES_COM_II": .4, "RES_IND": .8, "MEI_SEM_ATIVIDADE": 1.0,
             "HOME_SERVICE": .5, "COM_OK": 1.0, "COM_II_OK": 1.0, "IND_OK": 1.0}

SIGLA_RUA = {"Setor Marista": "Rua 11", "Setor Bueno": "Rua T-", "Jardim Goiás": "Rua ",
             "Setor Oeste": "Rua ", "Setor Sul": "Rua ", "Setor Campinas": "Rua ",
             "Setor Pedro Ludovico": "Rua 10", "Setor Leste Universitário": "Rua ",
             "Jardim América": "Rua C-", "Setor Perimetral Norte": "Rua PN-",
             "Jardim Curitiba": "Rua JC-", "Vila Finsocial": "Rua VF-", "Vila Mutirão": "Rua M-",
             "Jardim Nova Esperança": "Rua NE-", "Jardim do Cerrado": "Rua JDC-"}
