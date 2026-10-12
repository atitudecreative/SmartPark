"""
Gero placas de TESTE no padrão visual Mercosul para eu imprimir e fotografar com o celular
no modo "carro de teste" (/carro). Não são placas de verdade: cada uma leva a faixa
"AMOSTRA PARA TESTE · SMART PARK" fora da placa e serve só para testar a leitura (OCR).

    python scripts/gerar_placas_teste.py                 # placas do cadastro de demonstração + visitante
    python scripts/gerar_placas_teste.py ABC1D23 XYZ9A88 # placas que eu escolher

Saída em ../docs/placas_teste/: um PNG por placa e um PDF A4 pronto para imprimir.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "docs" / "placas_teste"
FONTES = Path("/usr/share/fonts/truetype/dejavu")

# As placas do cadastro de demonstração (scripts/cadastrar.py demo usa semente fixa, então são sempre estas)
PADRAO = [
    ("UDA4H28", "Dona Maria · cadastrada como IDOSA"),
    ("SIZ0Y20", "Lúcia · cadastrada como PcD"),
    ("QTA8G91", "Ana · cadastrada como MEMBRO"),
    ("NBA1G29", "Pr. Carlos · cadastrado como EQUIPE"),
    ("TCC2A26", "Placa fora do cadastro · entra como VISITANTE"),
]


def _fonte(nomes, tamanho):
    for n in nomes:
        for pasta in (FONTES, Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts")):
            if (pasta / n).exists():
                return ImageFont.truetype(str(pasta / n), tamanho)
    return ImageFont.load_default()


def desenhar_placa(texto: str, largura=1200) -> Image.Image:
    """Placa 40 × 13 cm (proporção real), faixa azul com BRASIL e os 7 caracteres em preto."""
    alt = round(largura * 13 / 40)
    img = Image.new("RGB", (largura, alt), "white")
    d = ImageDraw.Draw(img)
    borda = max(6, largura // 120)
    d.rounded_rectangle([0, 0, largura - 1, alt - 1], radius=largura // 40, outline="black", width=borda)
    faixa = round(alt * 0.22)
    d.rounded_rectangle([borda, borda, largura - borda, faixa], radius=largura // 60, fill="#1f4fa8")
    f_brasil = _fonte(["DejaVuSans-Bold.ttf", "Arial Bold.ttf"], round(faixa * 0.55))
    d.text((largura / 2, borda + (faixa - borda) / 2), "BRASIL", fill="white", font=f_brasil, anchor="mm")
    tam = round(alt * 0.56)
    while True:   # os 7 caracteres ocupam no máximo 84% da largura, como numa placa real
        f_placa = _fonte(["DejaVuSansCondensed-Bold.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"], tam)
        if d.textlength(texto, font=f_placa) <= largura * 0.84 or tam < 20:
            break
        tam -= 4
    d.text((largura / 2, faixa + (alt - faixa) / 2 + alt * 0.02), texto, fill="black", font=f_placa, anchor="mm")
    return img


def com_legenda(placa: Image.Image, legenda: str) -> Image.Image:
    w, h = placa.size
    margem = 40
    tela = Image.new("RGB", (w + 2 * margem, h + 2 * margem + 110), "white")
    tela.paste(placa, (margem, margem))
    d = ImageDraw.Draw(tela)
    d.text((tela.width / 2, h + margem + 38), "AMOSTRA PARA TESTE · SMART PARK (TCC)", fill="#b00020",
           font=_fonte(["DejaVuSans-Bold.ttf"], 30), anchor="mm")
    d.text((tela.width / 2, h + margem + 82), legenda, fill="#333333", font=_fonte(["DejaVuSans.ttf"], 28), anchor="mm")
    return tela


def main():
    itens = [(p.upper(), "Placa escolhida para teste") for p in sys.argv[1:]] or PADRAO
    SAIDA.mkdir(parents=True, exist_ok=True)
    imagens = []
    for placa, legenda in itens:
        img = com_legenda(desenhar_placa(placa), legenda)
        img.save(SAIDA / f"placa_{placa}.png")
        imagens.append(img)
        print(f"placa_{placa}.png  ({legenda})")
    # PDF A4 (150 dpi): 3 placas por folha, cada uma com ~18 cm de largura impressa
    a4 = (1240, 1754)
    paginas = []
    for i in range(0, len(imagens), 3):
        pg = Image.new("RGB", a4, "white")
        y = 90
        for img in imagens[i:i + 3]:
            esc = 1063 / img.width          # 18 cm a 150 dpi
            peq = img.resize((round(img.width * esc), round(img.height * esc)))
            pg.paste(peq, ((a4[0] - peq.width) // 2, y))
            y += peq.height + 90
        paginas.append(pg)
    paginas[0].save(SAIDA / "placas_teste.pdf", save_all=True, append_images=paginas[1:], resolution=150)
    print(f"placas_teste.pdf  ({len(paginas)} folha(s) A4) em {SAIDA}")


if __name__ == "__main__":
    main()
