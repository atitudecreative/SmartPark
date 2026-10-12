"""
Motor de simulação microscópica do estacionamento (passo de tempo fixo).

Como modelei o tráfego:
  - cada aresta dirigida é uma faixa única; não há ultrapassagem
  - distância mínima entre carros: 7 m (seguimento de veículo)
  - velocidades livres: 4 m/s nas vias, 2,5 m/s nos corredores, 1,8 m/s procurando vaga
  - um carro MANOBRANDO bloqueia o corredor nos dois sentidos (é isso que gera o efeito
    "manada": quem é mandado para o mesmo corredor espera as manobras à frente)
  - cancela: fila FIFO, 6 s de atendimento (leitura da placa + abertura)

Estratégias que comparo:
  sem_sistema  : como é hoje na igreja — o motorista entra no corredor A e procura;
                 se não achar, segue para B e depois C (busca sequencial)
  mais_proxima / reativa / preditiva : guiadas pelo Alocador (ver smartpark/alocador.py)
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field

from smartpark.alocador import Alocador, EstadoPatio, Reserva, V_VIA, V_CORREDOR
from smartpark.banco import Banco
from smartpark.layout import Layout
from smartpark.lpr import LPRSimulado

from .chegadas import Chegada

DT = 0.5
GAP = 7.0
V_BUSCA = 1.8
T_CANCELA = 6.0


@dataclass
class Carro:
    id: int
    chegada: Chegada
    t_chegada: float               # segundos (relativo ao culto)
    estado: str = "fila"           # fila, atendimento, movendo, manobrando, estacionado, rejeitado, desistiu
    rota: list = field(default_factory=list)
    i_aresta: int = 0
    pos: float = 0.0
    alvo_off: float | None = None  # posição da vaga na última aresta
    vaga: str | None = None
    buscando: bool = False
    t_fim_manobra: float = 0.0
    t_saida_cancela: float | None = None
    t_estacionado: float | None = None
    categoria_lida: str | None = None
    parado_s: float = 0.0
    x: float = 0.0
    y: float = 0.0

    @property
    def aresta(self):
        return self.rota[self.i_aresta] if self.rota and self.i_aresta < len(self.rota) else None


class Simulacao:
    def __init__(self, layout: Layout, chegadas: list[Chegada], estrategia: str, culto_idx: int = 0,
                 preditor=None, banco: Banco | None = None, lpr: LPRSimulado | None = None, seed: int = 0,
                 registrar_trajetoria: bool = False, params_alocador: dict | None = None):
        self.lay = layout
        self.estrategia = estrategia
        self.culto_idx = culto_idx
        self.rng = random.Random(seed)
        self.preditor = preditor
        self.lpr = lpr or LPRSimulado(seed=seed)
        self._banco_proprio = banco is None
        self.banco = banco or self._banco_padrao(chegadas)
        self.alocador = Alocador(layout, estrategia, **(params_alocador or {})) if estrategia != "sem_sistema" else None
        self.carros = [Carro(i, c, c.t_min * 60) for i, c in enumerate(chegadas)]
        self.t = min(c.t_chegada for c in self.carros) - 1 if self.carros else 0
        self.ocupada: dict[str, bool] = {v.id: False for v in layout.vagas}     # sensor
        self.reservada: dict[str, int] = {}                                      # vaga -> carro
        self.reservas: dict[int, Reserva] = {}
        self.fila: list[Carro] = []
        self.atendendo: Carro | None = None
        self.t_fim_atendimento = 0.0
        self.entradas_min: list[float] = []
        self.max_fila = 0
        self.max_corredor = {z: 0 for z in layout.zonas()}
        self.previsoes: list[tuple[float, float]] = []
        self.registrar = registrar_trajetoria
        self.quadros: list = []
        self._aresta_entrada = (layout.entrada, layout.vizinhos(layout.entrada)[0][0])
        self._comp = {}
        for e in layout.arestas:
            self._comp[(e.a, e.b)] = self._comp[(e.b, e.a)] = e.comprimento
        self._tipo = {}
        for e in layout.arestas:
            self._tipo[(e.a, e.b)] = self._tipo[(e.b, e.a)] = (e.tipo, e.zona)

    def _banco_padrao(self, chegadas):
        """Cadastro os veículos (menos os visitantes), como a secretaria faria."""
        b = Banco()
        for c in chegadas:
            if c.categoria != "VISITANTE":
                b.cadastrar(c.placa, c.categoria)
        return b

    # =============================================================== cancela
    def _estado_patio(self) -> EstadoPatio:
        livres = {v for v, oc in self.ocupada.items() if not oc and v not in self.reservada}
        prev = None
        if self.estrategia == "preditiva" and self.preditor is not None:
            # rodo o preditor no máximo a cada 30 s (igual ao sistema real)
            if not self.previsoes or self.t - self.previsoes[-1][0] >= 30:
                ocup = sum(self.ocupada.values()) / len(self.ocupada)
                p = self.preditor.prever(self.t / 60, self.entradas_min, self.culto_idx, ocup)
                self.previsoes.append((self.t, p))
            prev = self.previsoes[-1][1]
        return EstadoPatio(self.t, livres, list(self.reservas.values()), prev)

    def _atender(self, carro: Carro):
        leitura = self.lpr.ler(carro.chegada.placa)
        cat, _ = self.banco.categoria_de(leitura.placa)
        carro.categoria_lida = cat
        if self.alocador is None:  # sem sistema: o motorista segue o roteiro de busca
            carro.buscando = True
            carro.rota = self._roteiro_busca()
            return True
        dec = self.alocador.decidir(cat, self._estado_patio())
        if dec.vaga is None:
            carro.estado = "rejeitado"
            return False
        carro.vaga = dec.vaga
        carro.rota = dec.arestas
        carro.alvo_off = dec.offset_final
        self.reservada[dec.vaga] = carro.id
        self.reservas[carro.id] = Reserva(dec.vaga, dec.arestas, self.t)
        return True

    def _roteiro_busca(self):
        """Motorista sem informação nenhuma: percorre os corredores em ordem."""
        if self.lay.roteiro_busca:
            return [tuple(e) for e in self.lay.roteiro_busca]
        if "J3" in self.lay.nos:
            return [("G", "J1"), ("J1", "TA"), ("TA", "TB"), ("TB", "J2"), ("J2", "J3"), ("J3", "TC"),
                    ("TC", "TB"), ("TB", "TA"), ("TA", "J1")]
        return [("G", "J1"), ("J1", "TA"), ("TA", "TB"), ("TB", "J2"), ("J2", "J1")]

    # ================================================================= passo
    def _carros_na(self, aresta):
        return [c for c in self.carros if c.estado in ("movendo", "manobrando") and c.aresta == aresta]

    def _vmax(self, carro):
        tipo, _ = self._tipo[carro.aresta]
        if carro.buscando and tipo == "corredor":
            return V_BUSCA
        return V_CORREDOR if tipo == "corredor" else V_VIA

    def _cancela(self):
        for c in self.carros:
            if c.estado == "fila" and c.t_chegada <= self.t and c not in self.fila:
                self.fila.append(c)
                self.entradas_min.append(c.t_chegada / 60)
                self.banco.registrar("ENTRADA", instante=c.t_chegada)
        self.max_fila = max(self.max_fila, len(self.fila))
        if self.atendendo and self.t >= self.t_fim_atendimento:
            c = self.atendendo
            entrada = self._aresta_entrada
            ocupantes = self._carros_na(entrada)
            if all(o.pos >= GAP for o in ocupantes):
                if self._atender(c):
                    c.estado = "movendo"
                    c.i_aresta, c.pos = 0, 0.0
                    c.t_saida_cancela = self.t
                self.atendendo = None
        if self.atendendo is None and self.fila:
            self.atendendo = self.fila.pop(0)
            self.atendendo.estado = "atendimento"
            self.t_fim_atendimento = self.t + self.lay.tempo_cancela

    def _bloqueio_reverso(self, aresta):
        """Posições (no referencial de 'aresta') dos carros manobrando na aresta oposta."""
        rev = (aresta[1], aresta[0])
        L = self._comp[aresta]
        return [L - c.pos for c in self.carros if c.estado == "manobrando" and c.aresta == rev]

    def _mover(self):
        por_aresta = {}
        for c in self.carros:
            if c.estado in ("movendo", "manobrando"):
                por_aresta.setdefault(c.aresta, []).append(c)
        for c in self.carros:
            if c.estado == "manobrando" and self.t >= c.t_fim_manobra:
                c.estado = "estacionado"
                c.t_estacionado = self.t
                self.ocupada[c.vaga] = True          # sensor detecta o carro
                self.reservada.pop(c.vaga, None)
                self.reservas.pop(c.id, None)
                por_aresta[c.aresta].remove(c)
        entrou = set()
        for aresta, lista in list(por_aresta.items()):
            L = self._comp[aresta]
            bloqueios = self._bloqueio_reverso(aresta)
            lista.sort(key=lambda c: -c.pos)
            lider_pos = None
            for c in lista:
                if c.estado == "manobrando":
                    lider_pos = c.pos
                    continue
                antes = c.pos
                desejado = c.pos + self._vmax(c) * DT
                if lider_pos is not None:
                    desejado = min(desejado, lider_pos - GAP)
                for b in bloqueios:
                    if b > c.pos:
                        desejado = min(desejado, b - GAP / 2)
                ultima = c.i_aresta == len(c.rota) - 1
                if (ultima or c.buscando) and c.alvo_off is not None:
                    desejado = min(desejado, c.alvo_off)
                desejado = max(desejado, c.pos)
                # procurando vaga (sem sistema): olha as vagas por onde está passando
                if c.buscando and c.vaga is None and self._tipo[aresta][0] == "corredor":
                    achou = self._procurar(c, aresta, antes, desejado)
                    if achou is not None:
                        c.alvo_off = achou
                        desejado = min(desejado, achou)
                c.pos = min(desejado, L)
                if c.pos - antes < 0.05:
                    c.parado_s += DT
                # chegou à vaga?
                if c.alvo_off is not None and (ultima or c.buscando) and abs(c.pos - c.alvo_off) < 0.05:
                    c.estado = "manobrando"
                    c.t_fim_manobra = self.t + self.rng.uniform(12, 24)
                    lider_pos = c.pos
                    continue
                # fim da aresta: tento passar para a próxima
                if c.pos >= L - 1e-6:
                    if ultima:
                        c.estado = "desistiu"  # rodou o estacionamento todo e não achou vaga
                        if c.vaga:
                            self.reservada.pop(c.vaga, None)
                        self.reservas.pop(c.id, None)
                        continue
                    prox = c.rota[c.i_aresta + 1]
                    ocup = [o for o in self._carros_na(prox) if o is not c]
                    rev_b = self._bloqueio_reverso(prox)
                    if prox not in entrou and all(o.pos >= GAP for o in ocup) and all(b >= GAP for b in rev_b):
                        entrou.add(prox)
                        c.i_aresta += 1
                        c.pos = 0.0
                        continue
                lider_pos = c.pos

    def _procurar(self, c, aresta, de, ate):
        lay = self.lay
        L = self._comp[aresta]
        candidatas = []
        for v in lay.vagas:
            if v.aresta == aresta:
                off = v.offset
            elif v.aresta == (aresta[1], aresta[0]):
                off = L - v.offset
            else:
                continue
            if de - 0.01 <= off <= ate + 2.6 and not self.ocupada[v.id] and v.id not in self.reservada:
                if v.tipo != "comum" and c.chegada.categoria not in ("IDOSO", "PCD"):
                    continue
                candidatas.append((off, v.id))
        if not candidatas:
            return None
        off, vid = min(candidatas)
        c.vaga = vid
        self.reservada[vid] = c.id  # o motorista "viu" a vaga e foi para ela
        return off

    def livres(self) -> int:
        """Vagas livres e não reservadas — exatamente o que o controlador real enxerga."""
        return sum(1 for v, oc in self.ocupada.items() if not oc and v not in self.reservada)

    def livres_comuns(self) -> int:
        """Só as vagas comuns livres: é o que define a lotação para a maioria dos motoristas."""
        return sum(1 for v, oc in self.ocupada.items()
                   if not oc and v not in self.reservada and self.lay.vaga(v).tipo == "comum")

    def _medir(self):
        for z in self.max_corredor:
            n = sum(1 for c in self.carros if c.estado in ("movendo", "manobrando") and self._tipo[c.aresta][1] == z)
            self.max_corredor[z] = max(self.max_corredor[z], n)

    def _quadro(self):
        lay = self.lay
        carros = []
        for c in self.carros:
            if c.estado in ("movendo", "manobrando"):
                a, b = c.aresta
                na, nb = lay.nos[a], lay.nos[b]
                f = c.pos / self._comp[c.aresta]
                carros.append((c.id, round(na.x + (nb.x - na.x) * f, 1), round(na.y + (nb.y - na.y) * f, 1), c.estado[0]))
        self.quadros.append((self.t, carros, len(self.fila), sum(self.ocupada.values())))

    def rodar(self, t_max_s: float = 25 * 60, ao_passo=None):
        """ao_passo(sim) é chamado a cada passo (uso para avaliar o aviso de lotação)."""
        while self.t < t_max_s:
            self._cancela()
            self._mover()
            self._medir()
            if ao_passo:
                ao_passo(self)
            if self.registrar and int(self.t * 2) % 2 == 0:
                self._quadro()
            if all(c.estado in ("estacionado", "rejeitado", "desistiu") for c in self.carros):
                break
            self.t += DT
        m = self.metricas()
        if self._banco_proprio:
            self.banco.con.close()
        return m

    # ============================================================== métricas
    def metricas(self) -> dict:
        est = [c for c in self.carros if c.estado == "estacionado"]
        t_total = [c.t_estacionado - c.t_chegada for c in est]
        t_interno = [c.t_estacionado - c.t_saida_cancela for c in est]
        caminhada = [self.lay.distancia_caminhada(self.lay.vaga(c.vaga)) / 1.2 for c in est]
        prio = [c for c in est if c.chegada.categoria in ("IDOSO", "PCD")]
        def porta_cat(*cats):   # tempo porta a porta só de uma categoria (para conferir a ordem de prioridade)
            x = [a + b for c, a, b in zip(est, t_total, caminhada) if c.chegada.categoria in cats]
            return statistics.mean(x) if x else 0
        prio_ok = [c for c in prio if self.lay.vaga(c.vaga).tipo != "comum"]
        parados = [c.parado_s for c in est]
        def p95(x):
            return sorted(x)[int(0.95 * (len(x) - 1))] if x else 0
        return {
            "estrategia": self.estrategia,
            "veiculos": len(self.carros),
            "estacionados": len(est),
            "rejeitados_ou_desistiram": len(self.carros) - len(est),
            "tempo_medio_s": statistics.mean(t_total) if t_total else 0,
            "tempo_p95_s": p95(t_total),
            "tempo_interno_medio_s": statistics.mean(t_interno) if t_interno else 0,
            "tempo_parado_medio_s": statistics.mean(parados) if parados else 0,
            "caminhada_media_s": statistics.mean(caminhada) if caminhada else 0,
            "porta_a_porta_medio_s": statistics.mean([a + b for a, b in zip(t_total, caminhada)]) if est else 0,
            "porta_a_porta_visitante_s": porta_cat("VISITANTE"),
            "porta_a_porta_membro_s": porta_cat("MEMBRO"),
            "caminhada_visitante_s": statistics.mean([b for c, b in zip(est, caminhada) if c.chegada.categoria == "VISITANTE"] or [0]),
            "caminhada_membro_s": statistics.mean([b for c, b in zip(est, caminhada) if c.chegada.categoria == "MEMBRO"] or [0]),
            "fila_max_cancela": self.max_fila,
            "pico_corredor": dict(self.max_corredor),
            "prioritarios_em_vaga_preferencial": f"{len(prio_ok)}/{len(prio)}",
        }


def ultima_ou_alvo(c: Carro) -> bool:
    return c.i_aresta == len(c.rota) - 1
