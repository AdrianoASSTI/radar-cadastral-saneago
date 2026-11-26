"""
Gerador procedural de fachadas sintéticas com anotação automática (bounding boxes).

Por que sintético: não há base pública rotulada de fachadas de Goiânia, e o Street
View não pode ser usado para treino (Termos do Google Maps Platform). O gerador:
  * produz o "acervo de fotos dos leituristas" simulado para o MVP rodar ponta a ponta;
  * produz o conjunto de treino/validação do YOLOv11 (rótulos no formato YOLO);
  * inclui DISTRATORES (portão residencial gradeado, aviso "cuidado com o cão",
    janelas grandes) para que o detector não aprenda atalhos triviais;
  * inclui rostos e placas de veículos para treinar/avaliar a anonimização (LGPD).

Limitação (declarada no artigo, docs/03): o domínio sintético difere de fotos reais;
o pipeline está pronto para re-treino com fotos rotuladas dos leituristas.
"""

from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from radar_comum.features import CLASSES_YOLO

L, A = 640, 480                       # largura × altura
CHAO = 400                            # linha da calçada

NOMES_NEGOCIO = ["LANCHES", "PET SHOP", "ESTÉTICA", "LAVA JATO", "AÇOUGUE", "MERCEARIA", "SALÃO",
                 "RESTAURANTE", "BORRACHARIA", "PAPELARIA", "AÇAÍ", "BAR DO ZÉ", "ATELIÊ", "FARMÁCIA"]
FRASES_CARTAZ = ["VENDE-SE", "PROMOÇÃO", "ABERTO", "DELIVERY", "AÇAÍ 10,00", "MARMITEX", "LAVAGEM 30,00",
                 "FAZEMOS UNHAS", "CONSERTOS", "AQUI TEM"]
CORES_PAREDE = [(236, 226, 200), (210, 225, 236), (240, 210, 190), (220, 220, 220), (250, 240, 215),
                (200, 220, 190), (230, 200, 210), (245, 245, 240)]
PELE = [(241, 194, 167), (198, 134, 100), (141, 85, 54), (224, 172, 105), (255, 219, 172)]


def _sem_acento(t: str) -> str:
    """A fonte embutida do Pillow não tem glifos acentuados."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def _fonte(tam: int):
    try:
        return ImageFont.load_default(size=tam)
    except TypeError:                 # Pillow antigo
        return ImageFont.load_default()


def _rnd_cor(rng, base=None, var=40):
    if base:
        return tuple(max(0, min(255, c + rng.randint(-var, var))) for c in base)
    return tuple(rng.randint(30, 230) for _ in range(3))


class Cena:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.img = Image.new("RGB", (L, A))
        self.d = ImageDraw.Draw(self.img)
        self.caixas: list[tuple[str, int, int, int, int]] = []
        self.ocupado: list[tuple[int, int, int, int]] = []

    def caixa(self, classe, x1, y1, x2, y2):
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(L - 1, x2), min(A - 1, y2)
        if x2 - x1 > 6 and y2 - y1 > 6:
            self.caixas.append((classe, x1, y1, x2, y2))

    def livre(self, x1, y1, x2, y2) -> bool:
        return all(x2 < a or x1 > c or y2 < b or y1 > d for a, b, c, d in self.ocupado)

    def reservar(self, *r):
        self.ocupado.append(r)

    # ------------------------------------------------------------ fundo
    def fundo(self):
        r, d = self.rng, self.d
        ceu = (r.randint(120, 190), r.randint(170, 215), r.randint(215, 250))
        for y in range(0, 140):
            k = y / 140
            d.line([(0, y), (L, y)], fill=tuple(int(c * (1 - 0.25 * k)) for c in ceu))
        self.parede = _rnd_cor(r, r.choice(CORES_PAREDE), 15)
        self.topo = r.randint(70, 130)
        d.rectangle([0, self.topo, L, CHAO], fill=self.parede)
        d.polygon([(0, self.topo), (L, self.topo), (L - 20, self.topo - 18), (20, self.topo - 18)],
                  fill=_rnd_cor(r, (150, 80, 60), 30))
        d.rectangle([0, CHAO, L, A], fill=_rnd_cor(r, (175, 175, 170), 15))      # calçada
        d.rectangle([0, A - 25, L, A], fill=(70, 70, 75))                          # rua
        for x in range(0, L, 40):                                                  # textura
            d.line([(x, CHAO), (x + 8, A - 25)], fill=_rnd_cor(r, (160, 160, 155), 8))

    # ------------------------------------------------------- elementos neutros
    def janela(self, x, y, w, h):
        self.d.rectangle([x, y, x + w, y + h], fill=(90, 110, 130), outline=(240, 240, 240), width=4)
        self.d.line([(x + w // 2, y), (x + w // 2, y + h)], fill=(240, 240, 240), width=3)

    def porta(self, x):
        self.d.rectangle([x, CHAO - 130, x + 60, CHAO], fill=_rnd_cor(self.rng, (120, 80, 50), 30))
        self.d.ellipse([x + 48, CHAO - 70, x + 54, CHAO - 64], fill=(220, 200, 80))

    def portao_residencial(self, x, w):              # distrator: grades verticais
        self.d.rectangle([x, CHAO - 150, x + w, CHAO], outline=(40, 40, 40), width=3)
        for xi in range(x, x + w, 12):
            self.d.line([(xi, CHAO - 150), (xi, CHAO)], fill=(40, 40, 40), width=3)

    def aviso_cao(self, x, y):                       # distrator: placa pequena não comercial
        self.d.rectangle([x, y, x + 60, y + 25], fill=(250, 250, 250), outline=(200, 0, 0), width=2)
        self.d.text((x + 4, y + 6), "CAO BRAVO", fill=(200, 0, 0), font=_fonte(10))

    def arvore(self, x):
        self.d.rectangle([x + 18, CHAO - 90, x + 28, CHAO + 10], fill=(100, 70, 40))
        self.d.ellipse([x - 25, CHAO - 190, x + 70, CHAO - 70], fill=_rnd_cor(self.rng, (60, 130, 60), 25))

    def pessoa(self, x):
        r, d = self.rng, self.d
        pele = r.choice(PELE)
        cab = r.randint(20, 32)
        y0 = CHAO - r.randint(150, 175)
        d.rectangle([x - 18, y0 + cab, x + 18 + cab // 2, CHAO + 30], fill=_rnd_cor(r))
        d.ellipse([x, y0, x + cab, y0 + cab], fill=pele)
        d.ellipse([x + cab * .25, y0 + cab * .35, x + cab * .38, y0 + cab * .48], fill=(30, 30, 30))
        d.ellipse([x + cab * .62, y0 + cab * .35, x + cab * .75, y0 + cab * .48], fill=(30, 30, 30))
        d.line([(x + cab * .35, y0 + cab * .72), (x + cab * .65, y0 + cab * .72)], fill=(120, 40, 40), width=2)
        self.caixa("rosto", x - 2, y0 - 2, x + cab + 2, y0 + cab + 2)

    def carro(self, x):
        r, d = self.rng, self.d
        y = A - 95
        d.rounded_rectangle([x, y, x + 190, y + 60], 12, fill=_rnd_cor(r))
        d.rectangle([x + 35, y - 30, x + 150, y + 5], fill=(60, 70, 80))
        for cx in (x + 35, x + 150):
            d.ellipse([cx - 18, y + 45, cx + 18, y + 81], fill=(20, 20, 20))
        px, py = x + 70, y + 35
        d.rectangle([px, py, px + 52, py + 17], fill=(245, 245, 245), outline=(30, 30, 30))
        d.rectangle([px, py, px + 52, py + 4], fill=(20, 60, 160))
        txt = "".join(r.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(3)) + str(r.randint(0, 9)) + \
              r.choice("ABCDEFGHJ") + f"{r.randint(0, 99):02d}"
        d.text((px + 3, py + 5), txt, fill=(10, 10, 10), font=_fonte(10))
        self.caixa("placa_veiculo", px - 1, py - 1, px + 53, py + 18)

    # ----------------------------------------------------- elementos comerciais
    def letreiro(self):
        r, d = self.rng, self.d
        w, h = r.randint(260, 520), r.randint(45, 75)
        x, y = r.randint(10, L - w - 10), self.topo + r.randint(5, 25)
        cor = _rnd_cor(r)
        d.rectangle([x, y, x + w, y + h], fill=cor, outline=_rnd_cor(r), width=4)
        d.text((x + 15, y + h // 4), _sem_acento(r.choice(NOMES_NEGOCIO)), fill=tuple(255 - c for c in cor), font=_fonte(int(h * .55)))
        self.caixa("letreiro", x, y, x + w, y + h)
        self.reservar(x, y, x + w, y + h)

    def placa_comercial(self):
        r, d = self.rng, self.d
        for _ in range(20):
            w, h = r.randint(70, 140), r.randint(55, 110)
            x, y = r.randint(10, L - w - 10), r.randint(self.topo + 90, CHAO - h)
            if self.livre(x, y, x + w, y + h):
                break
        cor = r.choice([(250, 220, 40), (230, 40, 40), (250, 250, 250), (30, 120, 220)])
        d.rectangle([x, y, x + w, y + h], fill=cor, outline=(30, 30, 30), width=3)
        if r.random() < .5:                             # cavalete na calçada
            d.line([(x + 10, y + h), (x, CHAO + 30)], fill=(60, 60, 60), width=4)
            d.line([(x + w - 10, y + h), (x + w, CHAO + 30)], fill=(60, 60, 60), width=4)
        d.multiline_text((x + 6, y + 8), _sem_acento(r.choice(FRASES_CARTAZ)).replace(" ", "\n"),
                         fill=(20, 20, 20) if sum(cor) > 400 else (250, 250, 250), font=_fonte(16))
        self.caixa("placa_comercial", x, y, x + w, y + h)
        self.reservar(x, y, x + w, y + h)

    def vitrine(self):
        r, d = self.rng, self.d
        w, h = r.randint(180, 300), r.randint(140, 200)
        x = r.randint(10, L - w - 10)
        y = CHAO - h
        d.rectangle([x, y, x + w, CHAO], fill=(170, 200, 215), outline=(80, 80, 80), width=6)
        for yy in range(y + 40, CHAO - 10, 45):                       # prateleiras com produtos
            d.line([(x + 10, yy), (x + w - 10, yy)], fill=(120, 100, 80), width=3)
            for xx in range(x + 15, x + w - 25, 22):
                d.rectangle([xx, yy - r.randint(12, 30), xx + 14, yy], fill=_rnd_cor(r))
        d.line([(x + 20, y + 15), (x + 80, y + h - 20)], fill=(235, 245, 250), width=3)  # reflexo
        self.caixa("vitrine", x, y, x + w, CHAO)
        self.reservar(x, y, x + w, CHAO)

    def banner(self, pequeno=False):
        r, d = self.rng, self.d
        w = r.randint(90, 150) if pequeno else r.randint(180, 320)
        h = r.randint(35, 55) if pequeno else r.randint(55, 90)
        for _ in range(20):
            x, y = r.randint(10, L - w - 10), r.randint(self.topo + 80, CHAO - h - 60)
            if self.livre(x, y, x + w, y + h):
                break
        cor = _rnd_cor(r)
        d.rectangle([x, y, x + w, y + h], fill=cor)
        for i in range(0, w, 30):
            d.line([(x + i, y), (x + i + 10, y + h)], fill=_rnd_cor(r, cor, 30), width=2)
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(50, 50, 50))
        d.ellipse([x + w - 3, y - 3, x + w + 3, y + 3], fill=(50, 50, 50))
        d.text((x + 8, y + h // 3), _sem_acento(r.choice(FRASES_CARTAZ)), fill=tuple(255 - c for c in cor), font=_fonte(int(h * .4)))
        self.caixa("banner", x, y, x + w, y + h)
        self.reservar(x, y, x + w, y + h)

    def portao_industrial(self):
        r, d = self.rng, self.d
        w, h = r.randint(200, 320), r.randint(170, 240)
        x, y = r.randint(10, L - w - 10), CHAO - h
        d.rectangle([x, y, x + w, CHAO], fill=_rnd_cor(r, (160, 165, 170), 20), outline=(70, 70, 70), width=5)
        for yy in range(y + 6, CHAO, 9):                               # lâminas horizontais
            d.line([(x + 4, yy), (x + w - 4, yy)], fill=(110, 115, 120), width=2)
        self.caixa("portao_industrial", x, y, x + w, CHAO)
        self.reservar(x, y, x + w, CHAO)

    def doca_carga(self):
        r, d = self.rng, self.d
        w = r.randint(170, 260)
        x = r.randint(10, L - w - 10)
        y = CHAO - r.randint(150, 200)
        d.rectangle([x, y, x + w, CHAO - 40], fill=(35, 35, 40))                       # abertura
        d.rectangle([x - 10, CHAO - 40, x + w + 10, CHAO + 15], fill=(140, 140, 135))  # plataforma
        for i in range(x - 10, x + w + 10, 24):                                        # faixa zebrada
            d.polygon([(i, CHAO - 40), (i + 12, CHAO - 40), (i + 24, CHAO - 28), (i + 12, CHAO - 28)], fill=(240, 200, 20))
        self.caixa("doca_carga", x - 10, y, x + w + 10, CHAO + 15)
        self.reservar(x - 10, y, x + w + 10, CHAO + 15)

    def estacionamento(self):
        r, d = self.rng, self.d
        x1, x2 = r.randint(0, 200), r.randint(420, L)
        d.rectangle([x1, CHAO, x2, A - 25], fill=(95, 95, 100))
        for xx in range(x1 + 10, x2, 70):
            d.line([(xx, CHAO + 5), (xx - 15, A - 28)], fill=(250, 250, 250), width=4)
        sx = r.randint(x1 + 10, max(x1 + 11, x2 - 50))
        d.rectangle([sx, CHAO - 70, sx + 40, CHAO - 30], fill=(20, 80, 200))
        d.text((sx + 12, CHAO - 66), "E", fill=(255, 255, 255), font=_fonte(28))
        d.line([(sx + 20, CHAO - 30), (sx + 20, CHAO + 10)], fill=(80, 80, 80), width=4)
        self.caixa("estacionamento_clientes", x1, CHAO - 70, x2, A - 25)

    # ------------------------------------------------------------ pós-processo
    def efeitos_de_foto(self):
        r = self.rng
        img = self.img
        if r.random() < .6:
            img = img.filter(ImageFilter.GaussianBlur(r.uniform(0.3, 1.2)))
        fator = r.uniform(0.6, 1.25)
        img = img.point(lambda p: max(0, min(255, int(p * fator))))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=r.randint(55, 90))
        self.img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


DESENHO = {"letreiro": Cena.letreiro, "placa_comercial": Cena.placa_comercial, "vitrine": Cena.vitrine,
           "banner": Cena.banner, "portao_industrial": Cena.portao_industrial, "doca_carga": Cena.doca_carga,
           "estacionamento_clientes": Cena.estacionamento}
ORDEM = ["estacionamento_clientes", "portao_industrial", "doca_carga", "vitrine", "letreiro", "banner", "placa_comercial"]


def renderizar(elementos: list[str], rng: random.Random, banner_pequeno: bool = False,
               p_pessoa: float = .35, p_carro: float = .4) -> tuple[Image.Image, list[tuple]]:
    """Desenha uma fachada com os `elementos` comerciais e devolve (imagem, caixas)."""
    c = Cena(rng)
    c.fundo()
    # base residencial: janelas, porta, distratores
    for _ in range(rng.randint(1, 3)):
        x = rng.randint(20, L - 140)
        if c.livre(x, c.topo + 40, x + 110, c.topo + 130):
            c.janela(x, c.topo + 40 + rng.randint(0, 30), rng.randint(70, 110), rng.randint(55, 90))
    if "portao_industrial" not in elementos and "doca_carga" not in elementos:
        c.porta(rng.randint(30, L - 100))
        if rng.random() < .45:
            c.portao_residencial(rng.randint(0, L - 220), rng.randint(120, 220))
    if rng.random() < .25:
        c.aviso_cao(rng.randint(20, L - 80), CHAO - rng.randint(120, 160))
    if rng.random() < .3:
        c.arvore(rng.choice([rng.randint(-20, 60), rng.randint(L - 90, L)]))

    for e in sorted(set(elementos), key=ORDEM.index):
        if e == "banner":
            c.banner(pequeno=banner_pequeno)
        else:
            DESENHO[e](c)

    if rng.random() < p_carro:
        c.carro(rng.randint(0, L - 200))
    if rng.random() < p_pessoa:
        for _ in range(rng.randint(1, 2)):
            c.pessoa(rng.randint(20, L - 60))
    c.efeitos_de_foto()
    return c.img, c.caixas


def rotulos_yolo(caixas: list[tuple]) -> str:
    """Linhas `classe cx cy w h` normalizadas (formato Ultralytics)."""
    linhas = []
    for classe, x1, y1, x2, y2 in caixas:
        k = CLASSES_YOLO.index(classe)
        linhas.append(f"{k} {(x1 + x2) / 2 / L:.6f} {(y1 + y2) / 2 / A:.6f} {(x2 - x1) / L:.6f} {(y2 - y1) / A:.6f}")
    return "\n".join(linhas)
