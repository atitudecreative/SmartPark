"""
Alocador de vagas: é aqui que eu decido QUAL vaga entregar para cada carro na guarita.

Um cuidado que tomei: o alocador só usa informação que o sistema real tem de verdade —
o estado dos sensores das vagas, as reservas que ele mesmo fez (carros "em trânsito"
indo para uma vaga) e a previsão de demanda. Ele NÃO enxerga onde os carros estão.
Assim, o que funciona no simulador funciona igual no Raspberry Pi.
funciona igual no Raspberry Pi.

Estratégias que comparo no TCC:
    mais_proxima : menor distância da guarita até uma vaga livre (Dijkstra/A* estático)
    reativa      : menor tempo estimado, considerando o congestionamento ATUAL
                   (modelo de Greenshields) e manobras à frente no corredor
    preditiva    : igual à reativa, mas o peso do congestionamento é ajustado
                   pela demanda PREVISTA para os próximos minutos (IA)

Função objetivo que eu minimizo (em segundos):
    custo = T_livre + w * (T_congestionamento + T_bloqueio) + α * T_caminhada + P_categoria
    (α = 0,3 em geral; para idoso e PcD α = 1,0 e a caminhada é calculada a 0,8 m/s)
    P_categoria monta a ordem de proximidade do templo: PcD, idosos e visitantes (sem penalidade),
    membros (penalidade pequena nos setores da frente) e equipe/voluntários (penalidade maior).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .layout import Layout, Vaga
from .roteamento import rota_ate_vaga, descrever_rota, pontos_rota

V_VIA = 4.0          # m/s (~14 km/h)
V_CORREDOR = 2.5     # m/s (~9 km/h)
DENS_CONGEST = 1 / 7.0  # veículos por metro com fila parada (1 carro a cada 7 m)
MANOBRA_MEDIA_S = 18.0
V_CAMINHADA = 1.2    # m/s
# Para idosos e PcD, andar custa mais (passo mais lento, mais esforço). Sem isso, nos testes, para economizar
# 3 s de carro o sistema mandava um cadeirante a 44 m da porta com a vaga PcD da frente livre.
V_CAMINHADA_PREF = 0.8   # m/s
ALFA_PREF = 1.0          # peso da caminhada para IDOSO/PCD (os demais usam alfa_caminhada = 0,3)


@dataclass
class Reserva:
    vaga: str
    arestas: list[tuple[str, str]]
    instante: float


@dataclass
class EstadoPatio:
    agora: float
    livres: set[str]                                  # vagas livres segundo os sensores e não reservadas
    em_transito: list[Reserva] = field(default_factory=list)
    previsao_5min: float | None = None                # veículos esperados nos próximos 5 min


@dataclass
class Decisao:
    vaga: str | None
    arestas: list[tuple[str, str]]
    offset_final: float
    custo: float
    instrucoes: list[str]
    motivo: str = ""
    pontos: list = field(default_factory=list)   # rota em coordenadas, para o mapa


def _chave(a, b):
    return (a, b) if a < b else (b, a)


class Alocador:
    def __init__(self, layout: Layout, estrategia: str = "preditiva", alfa_caminhada: float = 0.3,
                 w_base: float = 0.4, w_escala: float = 4.0, w_max: float = 4.0):
        if estrategia not in ("mais_proxima", "reativa", "preditiva"):
            raise ValueError(estrategia)
        self.layout = layout
        self.estrategia = estrategia
        self.alfa = alfa_caminhada
        # w = w_base + previsão / w_escala. Calibrei esses valores em cenários de validação,
        # separados dos cenários de teste, para não "treinar na prova" (ver simulador/calibrar.py)
        self.w_base, self.w_escala, self.w_max = w_base, w_escala, w_max

    # ------------------------------------------------------------ pesos
    def peso_congestionamento(self, estado: EstadoPatio) -> float:
        if self.estrategia == "reativa":
            return 1.0
        if self.estrategia == "preditiva":
            lam = estado.previsao_5min or 0.0
            # Se vem muita gente, vale "espalhar" os carros já, antes de a fila se formar.
            # Se vem pouca gente, priorizo a vaga mais perto da porta.
            return min(self.w_max, self.w_base + lam / self.w_escala)
        return 0.0

    # --------------------------------------------------------- estimativas
    def _carga_arestas(self, estado: EstadoPatio) -> dict:
        carga = {}
        for r in estado.em_transito:
            for a, b in r.arestas:
                k = _chave(a, b)
                carga[k] = carga.get(k, 0) + 1
        return carga

    def _vmax(self, a, b):
        return V_CORREDOR if self.layout.aresta(a, b).tipo == "corredor" else V_VIA

    def _t_greenshields(self, a, b, comprimento, n_carros):
        vmax = self._vmax(a, b)
        k = n_carros / max(comprimento, 1.0)
        v = max(0.15 * vmax, vmax * (1 - k / DENS_CONGEST))
        return comprimento / v, comprimento / vmax

    # --------------------------------------------------------------- decisão
    def decidir(self, categoria: str, estado: EstadoPatio) -> Decisao:
        lay = self.layout
        livres = [v for v in lay.vagas if v.id in estado.livres]
        comuns = [v for v in livres if v.tipo == "comum"]
        # cada vaga preferencial é de quem tem direito a ela (idoso -> idoso, PcD -> PcD);
        # se as dele acabarem, uso a outra preferencial e, por último, uma comum
        if categoria in ("IDOSO", "PCD"):
            propria = "idoso" if categoria == "IDOSO" else "pcd"
            outra = "pcd" if propria == "idoso" else "idoso"
            candidatas = ([v for v in livres if v.tipo == propria] or [v for v in livres if v.tipo == outra] or comuns)
        else:
            candidatas = comuns
        if not candidatas:
            return Decisao(None, [], 0.0, float("inf"), ["ESTACIONAMENTO LOTADO"], "sem vagas")

        w = self.peso_congestionamento(estado)
        carga = self._carga_arestas(estado)
        reservas_corredor = {}
        for r in estado.em_transito:
            v = lay.vaga(r.vaga)
            reservas_corredor.setdefault(_chave(*v.aresta), []).append((v, r.arestas[-1]))

        melhor = None
        for v in candidatas:
            dec = self._avaliar(v, categoria, w, carga, reservas_corredor)
            if melhor is None or dec.custo < melhor.custo:
                melhor = dec
        v = lay.vaga(melhor.vaga)
        melhor.instrucoes = descrever_rota(lay, melhor.arestas, v)
        melhor.pontos = pontos_rota(lay, melhor.arestas, melhor.offset_final, v)
        return melhor

    def _avaliar(self, v: Vaga, categoria, w, carga, reservas_corredor) -> Decisao:
        lay = self.layout
        estatico = self.estrategia == "mais_proxima"

        def custo(a, b):
            e = lay.aresta(a, b)
            if estatico:
                return e.comprimento
            t_cong, t_livre = self._t_greenshields(a, b, e.comprimento, carga.get(_chave(a, b), 0))
            return t_livre + w * (t_cong - t_livre)

        def parcial(a, b, off):
            e = lay.aresta(a, b)
            if estatico:
                return off
            t_cong, t_livre = self._t_greenshields(a, b, off, carga.get(_chave(a, b), 0))
            # conto as manobras previstas à frente no mesmo corredor, vindo pelo mesmo lado
            bloq = 0
            for outra, ultima in reservas_corredor.get(_chave(a, b), []):
                off_outra = outra.offset if ultima[0] == outra.aresta[0] else e.comprimento - outra.offset
                if ultima == (a, b) and off_outra < off:
                    bloq += 1
            return t_livre + w * ((t_cong - t_livre) + bloq * MANOBRA_MEDIA_S * 0.5)

        c, arestas, off = rota_ate_vaga(lay, v, custo, parcial, v_max=1.0 if estatico else V_VIA)
        if not estatico:
            if categoria in ("IDOSO", "PCD"):
                c += ALFA_PREF * lay.distancia_caminhada(v) / V_CAMINHADA_PREF
            else:
                c += self.alfa * lay.distancia_caminhada(v) / V_CAMINHADA
        # Regra da igreja para quem fica mais perto do templo: PcD, idosos e visitantes primeiro, depois
        # membros e, por último, equipe e voluntários (que chegam cedo e deixam a frente para os outros).
        if categoria == "EQUIPE":
            pen = lay.penalidade_equipe.get(v.zona, 0.0)
        elif categoria == "MEMBRO":
            pen = lay.penalidade_membro.get(v.zona, 0.0)
        else:
            pen = 0.0                       # IDOSO, PCD e VISITANTE não têm penalidade
        if pen:
            # na estratégia "mais próxima" o custo está em metros: converto a penalidade pela velocidade
            # na via, para que a regra de prioridade pese igual nas três estratégias
            c += pen if not estatico else pen * V_VIA
        return Decisao(v.id, arestas, off, c, [])
