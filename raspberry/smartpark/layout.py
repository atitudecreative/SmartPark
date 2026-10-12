"""
Aqui eu modelo o estacionamento como um grafo.

- Nós: a guarita (cancela), os cruzamentos e as pontas de cada corredor.
- Arestas: os trechos de via (mão dupla, uma faixa em cada sentido).
- Vagas: ficam ao longo das arestas do tipo "corredor". Cada vaga é identificada pela
  distância (offset) até o nó de origem do corredor.

Trabalho tudo em metros. As mesmas coordenadas servem para calcular a caminhada até a
porta da igreja e para desenhar o mapa no painel, no tablet e no simulador web.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class No:
    id: str
    x: float
    y: float
    nome: str = ""           # nome usado nas instruções da guarita ("esquina da livraria")


@dataclass
class Aresta:
    a: str
    b: str
    comprimento: float
    tipo: str  # "via" ou "corredor"
    zona: str | None = None  # zona atendida (apenas corredores)


@dataclass
class Vaga:
    id: str
    zona: str
    aresta: tuple[str, str]  # (a, b) do corredor
    offset: float            # distância a partir do nó "a"
    lado: int                # -1 esquerda, +1 direita (apenas desenho)
    tipo: str = "comum"      # "comum", "idoso", "pcd"
    x: float = 0.0
    y: float = 0.0
    largura: float = 2.5     # largura da vaga ao longo da via (PcD: 3,5 m)


@dataclass
class Layout:
    nome: str
    nos: dict[str, No]
    arestas: list[Aresta]
    vagas: list[Vaga]
    entrada: str                 # nó da guarita
    porta: tuple[float, float]   # porta da igreja (destino da caminhada)
    decoracao: list = field(default_factory=list)        # prédios, canteiros, setas... (só desenho)
    roteiro_busca: list = field(default_factory=list)    # caminho de quem procura vaga sem o sistema
    penalidade_equipe: dict = field(default_factory=lambda: {"A": 300.0, "B": 120.0})  # s, por setor
    limites: tuple = (-10.0, -10.0, 110.0, 50.0)         # x0, y0, x1, y1 do desenho
    tempo_cancela: float = 6.0                           # s por carro (leitura da placa + abertura)
    # Prioridade de proximidade que a igreja pediu: PcD, idosos e visitantes ficam mais perto do templo,
    # depois membros, e por último equipe e voluntários. Membros "pagam" esta penalidade nos setores
    # da frente; visitantes não pagam nada. É uma preferência suave: se só sobrar vaga na frente, o membro
    # recebe a vaga da frente, e nenhuma vaga fica parada esperando visitante.
    penalidade_membro: dict = field(default_factory=lambda: {"A": 45.0})  # s, por setor
    _adj: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._adj = {n: [] for n in self.nos}
        for e in self.arestas:
            self._adj[e.a].append((e.b, e))
            self._adj[e.b].append((e.a, e))

    # ------------------------------------------------------------------ util
    def vizinhos(self, no: str):
        return self._adj[no]

    def aresta(self, a: str, b: str) -> Aresta:
        for viz, e in self._adj[a]:
            if viz == b:
                return e
        raise KeyError(f"Não existe aresta {a}-{b}")

    def vaga(self, vid: str) -> Vaga:
        for v in self.vagas:
            if v.id == vid:
                return v
        raise KeyError(vid)

    def zonas(self) -> list[str]:
        return sorted({v.zona for v in self.vagas})

    def distancia_caminhada(self, v: Vaga) -> float:
        return math.dist((v.x, v.y), self.porta)

    def para_dict(self) -> dict:
        return {
            "nome": self.nome,
            "entrada": self.entrada,
            "porta": list(self.porta),
            "nos": [asdict(n) for n in self.nos.values()],
            "arestas": [asdict(e) for e in self.arestas],
            "vagas": [{**asdict(v), "aresta": list(v.aresta)} for v in self.vagas],
            "decoracao": self.decoracao,
            "roteiro_busca": [list(e) for e in self.roteiro_busca],
            "limites": list(self.limites),
            "tempo_cancela": self.tempo_cancela,
            "penalidade_equipe": self.penalidade_equipe,
            "penalidade_membro": self.penalidade_membro,
        }

    def salvar_json(self, caminho: str | Path):
        Path(caminho).write_text(json.dumps(self.para_dict(), indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------
def _posicionar_vagas(nos, a, b, zona, prefixo, offsets, tipos):
    """Crio as vagas dos dois lados de um corredor a-b."""
    na, nb = nos[a], nos[b]
    comp = math.dist((na.x, na.y), (nb.x, nb.y))
    ux, uy = (nb.x - na.x) / comp, (nb.y - na.y) / comp
    px, py = -uy, ux  # perpendicular
    vagas, n = [], 1
    for off in offsets:
        for lado in (-1, 1):
            tipo = tipos.get(n, "comum")
            cx = na.x + ux * off + px * lado * 4.0
            cy = na.y + uy * off + py * lado * 4.0
            vagas.append(Vaga(f"{prefixo}{n:02d}", zona, (a, b), off, lado, tipo, round(cx, 2), round(cy, 2)))
            n += 1
    return vagas


def _arestas(nos, pares):
    out = []
    for a, b, tipo, zona in pares:
        comp = math.dist((nos[a].x, nos[a].y), (nos[b].x, nos[b].y))
        out.append(Aresta(a, b, round(comp, 2), tipo, zona))
    return out


def layout_igreja() -> Layout:
    """
    Estacionamento de referência que usei nos experimentos (escala real, 48 vagas em 3 zonas).

        TA ──────── TB ──────── TC      (via de fundo)
        │A          │B          │C      (corredores com vagas)
    G ──J1 ──────── J2 ──────── J3      (via principal)
    🚧
        ⛪ porta da igreja
    """
    nos = {n.id: n for n in [
        No("G", 0, 30), No("J1", 25, 30), No("J2", 60, 30), No("J3", 95, 30),
        No("TA", 25, 4), No("TB", 60, 4), No("TC", 95, 4),
    ]}
    arestas = _arestas(nos, [
        ("G", "J1", "via", None), ("J1", "J2", "via", None), ("J2", "J3", "via", None),
        ("TA", "TB", "via", None), ("TB", "TC", "via", None),
        ("J1", "TA", "corredor", "A"), ("J2", "TB", "corredor", "B"), ("J3", "TC", "corredor", "C"),
    ])
    offsets = [4 + 2.6 * i for i in range(8)]
    # Vagas preferenciais para 48 vagas: 5% para idosos -> 3 (Lei 10.741/2003, art. 41)
    #                                   2% para PcD    -> 1 (Lei 13.146/2015, art. 47)
    vagas = (
        _posicionar_vagas(nos, "J1", "TA", "A", "A", offsets, {1: "idoso", 2: "idoso", 3: "idoso", 4: "pcd"})
        + _posicionar_vagas(nos, "J2", "TB", "B", "B", offsets, {})
        + _posicionar_vagas(nos, "J3", "TC", "C", "C", offsets, {})
    )
    return Layout("Igreja Batista Atitude (referência)", nos, arestas, vagas, "G", (22.0, 44.0))


def layout_maquete() -> Layout:
    """Maquete física que vou levar na defesa: 6 vagas (3 por corredor), uma para cada sensor do ESP32."""
    nos = {n.id: n for n in [
        No("G", 0, 30), No("J1", 25, 30), No("J2", 60, 30), No("TA", 25, 12), No("TB", 60, 12),
    ]}
    arestas = _arestas(nos, [
        ("G", "J1", "via", None), ("J1", "J2", "via", None), ("TA", "TB", "via", None),
        ("J1", "TA", "corredor", "A"), ("J2", "TB", "corredor", "B"),
    ])
    vA = _posicionar_vagas(nos, "J1", "TA", "A", "A", [5, 10], {1: "pcd"})[:3]
    vB = _posicionar_vagas(nos, "J2", "TB", "B", "B", [5, 10], {})[:3]
    return Layout("Maquete (6 vagas)", nos, arestas, vA + vB, "G", (22.0, 44.0))


# ==========================================================================
# PLANTA COMPLETA (250 vagas) — desenhei a partir da planta baixa do estacionamento da igreja
# ==========================================================================
VIA, CORREDOR = 7.0, 6.0          # larguras (m), como na planta
PROF = 5.0                         # profundidade da vaga (m)


def _fila(nos, a, b, zona, lado, inicio, larguras, tipos, numero):
    """Monto uma fileira de vagas de um lado da aresta a→b, começando a 'inicio' metros de 'a'.
    lado: +1 / -1 em relação à perpendicular (-uy, ux). Como o eixo y cresce para baixo, +1 fica à direita de quem vai de a para b."""
    na, nb = nos[a], nos[b]
    comp = math.dist((na.x, na.y), (nb.x, nb.y))
    ux, uy = (nb.x - na.x) / comp, (nb.y - na.y) / comp
    px, py = -uy, ux
    lateral = (VIA if zona in ("A", "B") else CORREDOR) / 2 + PROF / 2
    vagas, pos = [], inicio
    for i, larg in enumerate(larguras):
        off = pos + larg / 2
        cx, cy = na.x + ux * off + px * lado * lateral, na.y + uy * off + py * lado * lateral
        vagas.append(Vaga(f"{numero + i:02d}", zona, (a, b), round(off, 2), lado, tipos.get(i, "comum"),
                          round(cx, 2), round(cy, 2), larg))
        pos += larg
    return vagas


def layout_planta() -> Layout:
    """
    Planta do estacionamento da igreja, que ampliei para 250 vagas.

    Setores e numeração:
        A  01–11   frente da igreja (01 PcD, 02–11 idosos)            ┐ setores EXCLUSIVOS de idosos e PcD,
        B  12–16   restaurante e livraria (12–13 e 16 idosos, 14–15 PcD) ┘ a pedido da igreja
        C  17–33   corredor C  ┐ vagas da planta original
        D  34–50   corredor D  ┘
        E–I 51–250 ampliação: 5 corredores de 40 vagas
    Preferenciais (Lei 10.741/2003 art. 41: 5% para idosos; Lei 13.146/2015 art. 47: 2% para PcD):
        250 vagas -> no mínimo 13 de idosos e 5 de PcD. Como a igreja pediu os setores A e B só para
        idosos e PcD, ficaram 21 de idosos e 5 de PcD: as 16 de A e B mais as da ampliação, no fim de cada
        corredor, do lado da via sul, que é o caminho de volta para a igreja (menos caminhada).
    Circulação: o carro entra pela guarita (sudoeste), segue pela via oeste e pela via norte da igreja;
    os corredores C–I ficam entre a via de cima (y=5) e a via sul (y=66), e a saída é a sudeste.
    """
    xs = {"C": 72, "D": 90, "E": 108, "F": 126, "G": 144, "H": 162, "I": 180}
    nos = {n.id: n for n in [
        No("E0", 20, 102, "guarita"),
        No("N1", 20, 66, "esquina da entrada"),
        No("N0", 20, 27, "esquina do restaurante"),
        No("T0", 56, 27, "esquina da livraria"),
        No("K0", 56, 5, "via norte"),
        No("B0", 56, 66, "via sul"),
        No("BZ", 192, 66, "via de saída"),
        No("S0", 192, 102, "saída"),
    ] + [No(f"K{z}", x, 5, f"topo do corredor {z}") for z, x in xs.items()]
      + [No(f"B{z}", x, 66, f"corredor {z}") for z, x in xs.items()]}

    z = list(xs)
    pares = [
        ("E0", "N1", "via", None), ("N1", "B0", "corredor", "B"), ("N0", "N1", "corredor", "B"),
        ("N0", "T0", "corredor", "A"), ("T0", "K0", "via", None), ("T0", "B0", "via", None),
        ("K0", f"K{z[0]}", "via", None), ("B0", f"B{z[0]}", "via", None),
        (f"B{z[-1]}", "BZ", "via", None), ("BZ", "S0", "via", None),
    ]
    for i in range(len(z) - 1):
        pares += [(f"K{z[i]}", f"K{z[i + 1]}", "via", None), (f"B{z[i]}", f"B{z[i + 1]}", "via", None)]
    for k in z:
        pares.append((f"K{k}", f"B{k}", "corredor", k))
    arestas = _arestas(nos, pares)

    vagas = []
    # A: frente da igreja, lado norte da via (N0→T0)
    vagas += _fila(nos, "N0", "T0", "A", -1, 3.0, [3.5] + [2.5] * 10, {0: "pcd", **{i: "idoso" for i in range(1, 11)}}, 1)
    # B: ao lado do restaurante (via oeste, lado oeste) e em frente à livraria (via sul, lado norte)
    vagas += _fila(nos, "N0", "N1", "B", +1, 11.0, [2.5, 2.5], {0: "idoso", 1: "idoso"}, 12)
    vagas += _fila(nos, "N1", "B0", "B", -1, 12.0, [3.5, 3.5, 2.5], {0: "pcd", 1: "pcd", 2: "idoso"}, 14)
    # C e D: vagas da planta original (17 cada), encostadas na via sul
    num = 17
    for k in ("C", "D"):
        vagas += _fila(nos, f"K{k}", f"B{k}", k, +1, 5 + 2.5 * 11, [2.5] * 9, {}, num); num += 9
        vagas += _fila(nos, f"K{k}", f"B{k}", k, -1, 5 + 2.5 * 12, [2.5] * 8, {}, num); num += 8
    # E–I: ampliação, 20 vagas de cada lado; deixei as preferenciais no fim do corredor (perto da via sul)
    pref = {"E": {18: "idoso", 19: "pcd"}, "F": {18: "idoso", 19: "idoso"}, "G": {18: "idoso", 19: "pcd"},
            "H": {18: "idoso", 19: "idoso"}, "I": {18: "idoso", 19: "idoso"}}
    for k in ("E", "F", "G", "H", "I"):
        vagas += _fila(nos, f"K{k}", f"B{k}", k, +1, 5.0, [2.5] * 20, pref[k], num); num += 20
        vagas += _fila(nos, f"K{k}", f"B{k}", k, -1, 5.0, [2.5] * 20, {}, num); num += 20

    # Quem chega sem orientação entra pela via norte e vai percorrendo os corredores em zigue-zague
    rot = [("E0", "N1"), ("N1", "N0"), ("N0", "T0"), ("T0", "K0"), ("K0", "KC"), ("KC", "BC"), ("BC", "BD"), ("BD", "KD"),
           ("KD", "KE"), ("KE", "BE"), ("BE", "BF"), ("BF", "KF"), ("KF", "KG"), ("KG", "BG"), ("BG", "BH"), ("BH", "KH"),
           ("KH", "KI"), ("KI", "BI")]

    deco = _decoracao_planta(xs)
    penal = {"A": 400.0, "B": 400.0, "C": 300.0, "D": 240.0, "E": 180.0, "F": 120.0, "G": 60.0}
    # Com 250 carros chegando em ~20 min, 6 s por carro na cancela viraria gargalo (10 carros/min).
    # Por isso considero que a câmera lê a placa enquanto o carro se aproxima: 3,5 s por carro (~17/min).
    return Layout("Igreja Batista Atitude — planta (250 vagas)", nos, arestas, vagas, "E0", (30.0, 16.5),
                  deco, rot, penal, (0.0, 0.0, 200.0, 112.0), 3.5, penalidade_membro={"C": 45.0})   # A e B são só de idosos/PcD; C fica de preferência para visitantes


def _decoracao_planta(xs):
    """Elementos que servem só para o desenho, em metros (y para baixo)."""
    d = []
    R = lambda tipo, x, y, w, h, **kw: d.append({"tipo": tipo, "x": x, "y": y, "w": w, "h": h, **kw})
    # canteiros (grama com árvores)
    R("canteiro", 0, 0, 200, 112)                                  # terreno
    R("calcada", 0, 106, 200, 6)                                   # calçada da rua
    R("calcada", 2, 16, 52, 2.4)                                   # calçada na frente da igreja
    R("calcada", 2, 55, 9.2, 4)                                    # calçada do restaurante
    for k, x in xs.items():
        if k in ("C", "D"):
            R("canteiro", x - 8, 9.5, 5, 26, arvores=3)                # parte de cima, sem vagas,
            R("canteiro", x + 3, 9.5, 5, 28.5, arvores=3)              # dos dois lados do corredor
    for x in list(xs.values())[:-1]:
        R("canteiro", x + 8, 9, 2, 53.5, arvores=4)                # ilha entre corredores
    R("canteiro", 60, 70, 128, 30, arvores=9)                      # jardim sul entre entrada e saída
    R("canteiro", 25, 70, 31, 30, arvores=4)
    # prédios
    R("predio", 3, 2, 50, 14, rotulo="IGREJA", porta=[30, 16])
    R("predio", 2, 32, 9.2, 23, rotulo="RESTAURANTE")
    R("predio", 29, 33, 19, 21, rotulo="LIVRARIA")
    # guarita, cancelas e faixas
    R("guarita", 25.5, 92, 3, 4)
    R("guarita", 196.2, 92, 3, 4)
    d.append({"tipo": "cancela", "x1": 16.5, "y1": 91, "x2": 25.5, "y2": 91})
    d.append({"tipo": "cancela", "x1": 196.2, "y1": 91, "x2": 188.5, "y2": 91})
    R("faixa", 16.5, 100.5, 7, 3)
    R("faixa", 188.5, 100.5, 7, 3)
    d.append({"tipo": "rotulo", "x": 20, "y": 110, "texto": "ENTRADA"})
    d.append({"tipo": "rotulo", "x": 192, "y": 110, "texto": "SAÍDA"})
    d.append({"tipo": "rotulo", "x": 38, "y": 30.2, "texto": "CIRCULAÇÃO", "pequeno": True})
    d.append({"tipo": "rotulo", "x": 124, "y": 69.2, "texto": "CIRCULAÇÃO", "pequeno": True})
    # setas de circulação (ângulo em graus: 0 = para a direita, 90 = para baixo)
    for x, y, a in [(20, 84, -90), (20, 45, -90), (30, 28, 0), (46, 28, 0), (56, 16, -90), (90, 66, 0), (150, 66, 0),
                    (192, 80, 90), (130, 5, 0)]:
        d.append({"tipo": "seta", "x": x, "y": y, "ang": a})
    return d


LAYOUTS = {"igreja": layout_igreja, "maquete": layout_maquete, "planta": layout_planta}
