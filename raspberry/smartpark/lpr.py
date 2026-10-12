"""
Reconhecimento de placas (LPR — License Plate Recognition).

Fiz duas implementações com a mesma interface `ler(imagem) -> LeituraPlaca`:

1. LPRCamera  : pipeline real para o Raspberry Pi (OpenCV + OCR).
                Acho a placa por contornos retangulares, recorto, binarizo
                e passo o OCR (EasyOCR se estiver instalado; senão, Tesseract).
2. LPRSimulado: a que uso nos experimentos e no simulador. Reproduz taxas de erro
                configuráveis (placa ilegível, troca de caractere), para eu medir
                o impacto das falhas de leitura no sistema.

Nas duas, a saída passa por `normalizar_placa`, que corrige confusões comuns
do OCR usando a posição de cada caractere no padrão Mercosul (LLLNLNN) e no antigo
(LLLNNNN).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

PADRAO_MERCOSUL = re.compile(r"^[A-Z]{3}[0-9][A-Z][0-9]{2}$")
PADRAO_ANTIGO = re.compile(r"^[A-Z]{3}[0-9]{4}$")

# confusões típicas de OCR
PARA_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A", "7": "T"}
PARA_NUMERO = {v: k for k, v in PARA_LETRA.items()} | {"Q": "0", "D": "0", "U": "0"}


@dataclass
class LeituraPlaca:
    placa: str | None     # None = ilegível
    confianca: float      # 0..1
    bruto: str = ""       # texto antes da normalização


def normalizar_placa(texto: str) -> str | None:
    """Limpo o texto do OCR e tento encaixar num padrão de placa válido."""
    t = re.sub(r"[^A-Z0-9]", "", texto.upper())
    if len(t) != 7:
        return None
    # posições 0-2 sempre letras; 3, 5, 6 sempre números; 4 letra (Mercosul) ou número (antigo)
    c = list(t)
    for i in (0, 1, 2):
        c[i] = PARA_LETRA.get(c[i], c[i])
    for i in (3, 5, 6):
        c[i] = PARA_NUMERO.get(c[i], c[i])
    cand = "".join(c)
    if PADRAO_MERCOSUL.match(cand) or PADRAO_ANTIGO.match(cand):
        return cand
    return None


def placa_aleatoria(rng: random.Random) -> str:
    L = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(rng.choice(L) for _ in range(3)) + str(rng.randint(0, 9)) + rng.choice(L) + f"{rng.randint(0, 99):02d}"


class LPRSimulado:
    def __init__(self, taxa_ilegivel=0.04, taxa_troca=0.03, seed=None):
        self.taxa_ilegivel = taxa_ilegivel
        self.taxa_troca = taxa_troca
        self.rng = random.Random(seed)

    def ler(self, placa_real: str) -> LeituraPlaca:
        r = self.rng.random()
        if r < self.taxa_ilegivel:
            return LeituraPlaca(None, 0.2, "")
        texto = placa_real
        if r < self.taxa_ilegivel + self.taxa_troca:
            # erro de OCR: troca um caractere por um visualmente parecido
            i = self.rng.randrange(7)
            ch = texto[i]
            troca = PARA_NUMERO.get(ch) or PARA_LETRA.get(ch) or ch
            texto = texto[:i] + troca + texto[i + 1:]
        return LeituraPlaca(normalizar_placa(texto), 0.9, texto)


class LeitorImagem:
    """Leio a placa numa FOTO (arquivo ou bytes), sem câmera ligada ao computador.

    É o que o modo "carro de teste" usa: o celular tira a foto da placa e manda para o servidor.
    Precisa de opencv-python(-headless) e de pytesseract (com o programa tesseract instalado).

    Procuro quadriláteros com proporção de placa (~3:1), endireito cada um (correção de perspectiva,
    porque a foto quase nunca sai de frente), corto a faixa azul "BRASIL" e passo o OCR. Se nenhum
    recorte virar placa válida, leio a imagem inteira, aceitando só uma "palavra" de 7 caracteres.
    Em cada recorte testo a imagem binarizada pelo método de Otsu e a versão com contraste adaptativo.
    """

    LARGURA_TRABALHO = 1000   # px: reduzo fotos grandes do celular para o OCR ficar rápido

    def __init__(self):
        import cv2
        import numpy as np
        import pytesseract
        self.cv2, self.np, self.tess = cv2, np, pytesseract
        self.tess.get_tesseract_version()     # falha cedo, com mensagem clara, se o tesseract não estiver instalado

    def _ocr(self, img, psm):
        cfg = f"--psm {psm} -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return self.tess.image_to_string(img, config=cfg)

    @staticmethod
    def _procurar(texto: str, estrito: bool = False) -> str | None:
        """Procuro uma placa no texto do OCR. No modo estrito (imagem inteira) só aceito uma "palavra"
        de 7 caracteres: juntar o texto todo e varrer achava placas falsas em legendas e adesivos."""
        linhas = [re.sub(r"[^A-Z0-9 ]", "", l.upper()) for l in texto.splitlines()]
        candidatos = []
        for l in linhas:
            candidatos += l.split()
            if not estrito:
                candidatos.append(l.replace(" ", ""))   # "ABC 1D23": OCR às vezes separa os blocos
        for c in candidatos:
            p = normalizar_placa(c)
            if p:
                return p
            if not estrito and len(c) == 8:
                # um caractere a mais (borda lida como "I", ou um "Z" fantasma entre letras): tiro cada
                # posição e fico com a placa que exigiu menos correções de OCR
                opcoes = []
                for i in range(8):
                    q = c[:i] + c[i + 1:]
                    r = normalizar_placa(q)
                    if r:
                        opcoes.append((sum(a != b for a, b in zip(q, r)), i not in (0, 7), r))   # empate: tiro a borda
                if opcoes:
                    return min(opcoes)[2]
        return None

    @staticmethod
    def _ordenar_cantos(pts):
        import numpy as np
        pts = pts.reshape(4, 2).astype("float32")
        s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
        return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype="float32")

    def _regioes(self, cinza):
        """Recortes candidatos, já endireitados (correção de perspectiva) e sem a faixa "BRASIL"."""
        cv2, np = self.cv2, self.np
        h_img, w_img = cinza.shape
        area_img = h_img * w_img
        out = []
        suave = cv2.bilateralFilter(cinza, 9, 40, 40)
        for bordas in (cv2.Canny(suave, 30, 200), cv2.dilate(cv2.Canny(suave, 50, 150), None)):
            contornos, _ = cv2.findContours(bordas, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for c in sorted(contornos, key=cv2.contourArea, reverse=True)[:25]:
                if cv2.contourArea(c) < area_img * 0.01:
                    break
                (cx, cy), (rw, rh), _ = cv2.minAreaRect(c)
                lado_maior, lado_menor = max(rw, rh), max(1.0, min(rw, rh))
                if not 2.0 < lado_maior / lado_menor < 5.0:
                    continue
                aprox = cv2.approxPolyDP(c, 0.03 * cv2.arcLength(c, True), True)
                cantos = aprox if len(aprox) == 4 else cv2.boxPoints(cv2.minAreaRect(c))
                W, H = 800, 260
                M = cv2.getPerspectiveTransform(self._ordenar_cantos(np.array(cantos)),
                                                np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
                reta = cv2.warpPerspective(cinza, M, (W, H))
                out.append(reta[int(H * 0.24):int(H * 0.95), int(W * 0.03):int(W * 0.97)])
                if len(out) >= 4:
                    return out + [cinza]
        return out + [cinza]

    def ler_frame(self, frame) -> LeituraPlaca:
        cv2 = self.cv2
        if frame is None:
            return LeituraPlaca(None, 0.0, "imagem inválida")
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = frame.shape
        if w > self.LARGURA_TRABALHO:
            frame = cv2.resize(frame, (self.LARGURA_TRABALHO, round(h * self.LARGURA_TRABALHO / w)), interpolation=cv2.INTER_AREA)
        brutos = []
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        regioes = self._regioes(frame)
        for n, reg in enumerate(regioes):
            inteira = n == len(regioes) - 1
            if reg.size == 0:
                continue
            if reg.shape[1] < 600:
                f = 600 / reg.shape[1]
                reg = cv2.resize(reg, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
            variantes = [cv2.threshold(reg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
                         cv2.threshold(clahe.apply(reg), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
            for img in variantes:
                for psm in ((11, 6) if inteira else (7, 8)):
                    bruto = self._ocr(img, psm).strip()
                    brutos.append(bruto)
                    placa = self._procurar(bruto, estrito=inteira)
                    if placa:
                        return LeituraPlaca(placa, 0.6 if inteira else 0.9, bruto)
        return LeituraPlaca(None, 0.0, " | ".join(b for b in brutos if b)[:200])

    def ler_bytes(self, dados: bytes) -> LeituraPlaca:
        arr = self.np.frombuffer(dados, dtype=self.np.uint8)
        return self.ler_frame(self.cv2.imdecode(arr, self.cv2.IMREAD_COLOR))

    def ler_arquivo(self, caminho) -> LeituraPlaca:
        return self.ler_bytes(open(caminho, "rb").read())


class LPRCamera:
    """Câmera fixa na cancela (USB no Raspberry Pi, ou câmera IP/celular pelo endereço do vídeo).
    Quando o HC-SR04 detecta o carro, capturo um quadro e uso o mesmo leitor das fotos (LeitorImagem)."""

    def __init__(self, indice_camera=0):
        import cv2  # importo só aqui: o simulador não precisa de câmera
        self.cv2 = cv2
        self.cam = cv2.VideoCapture(indice_camera)   # 0 = câmera USB; ou "http://IP:porta/video" de uma câmera IP
        self.leitor = LeitorImagem()

    def capturar(self):
        for _ in range(3):        # descarto quadros velhos do buffer: quero a imagem do carro que acabou de parar
            self.cam.grab()
        ok, frame = self.cam.read()
        if not ok:
            raise RuntimeError("Falha ao capturar imagem da câmera")
        return frame

    def ler(self, frame=None) -> LeituraPlaca:
        return self.leitor.ler_frame(frame if frame is not None else self.capturar())
