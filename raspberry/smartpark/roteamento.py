"""
Aqui eu calculo as rotas dentro do estacionamento.

Usei o algoritmo A*, com a distância em linha reta como heurística. Ela é admissível porque
nenhuma via é mais curta que a linha reta. O custo de cada aresta vem de uma função que eu
passo de fora; assim o mesmo A* serve para todas as estratégias que comparo:
  - custo estático (distância em metros)  -> estratégia "mais próxima"
  - custo dinâmico (tempo com congestionamento) -> estratégias reativa/preditiva
"""
from __future__ import annotations

import heapq
import math
from typing import Callable

from .layout import Layout, Vaga

CustoAresta = Callable[[str, str], float]


def a_estrela(layout: Layout, origem: str, destino: str, custo: CustoAresta,
              v_max: float = 1.0) -> tuple[float, list[str]]:
    """
    Devolvo (custo_total, caminho_de_nós).
    v_max converte a heurística de metros para a unidade do custo
    (v_max=1 quando o custo é em metros; v_max em m/s quando o custo é em segundos).
    """
    alvo = layout.nos[destino]

    def h(n: str) -> float:
        no = layout.nos[n]
        return math.dist((no.x, no.y), (alvo.x, alvo.y)) / v_max

    aberto = [(h(origem), 0.0, origem)]
    g = {origem: 0.0}
    pai: dict[str, str] = {}
    while aberto:
        _, gn, n = heapq.heappop(aberto)
        if n == destino:
            caminho = [n]
            while n in pai:
                n = pai[n]
                caminho.append(n)
            return gn, caminho[::-1]
        if gn > g.get(n, math.inf):
            continue
        for viz, _e in layout.vizinhos(n):
            ng = gn + custo(n, viz)
            if ng < g.get(viz, math.inf):
                g[viz] = ng
                pai[viz] = n
                heapq.heappush(aberto, (ng + h(viz), ng, viz))
    return math.inf, []


def rota_ate_vaga(layout: Layout, vaga: Vaga, custo: CustoAresta, custo_parcial: Callable[[str, str, float], float],
                  v_max: float = 1.0):
    """
    A vaga fica no meio de um corredor (a-b), e o carro pode entrar por "a" ou por "b"
    (via de fundo). Devolvo (custo, lista_de_arestas_dirigidas, offset_final), em que offset_final
    é a posição da vaga medida a partir do começo da última aresta.
    """
    a, b = vaga.aresta
    comp = layout.aresta(a, b).comprimento
    melhores = []
    for entrada, saida, off in ((a, b, vaga.offset), (b, a, comp - vaga.offset)):
        c, caminho = a_estrela(layout, layout.entrada, entrada, custo, v_max)
        if not caminho:
            continue
        # não faz sentido ir até a outra ponta do corredor só para voltar
        if saida in caminho:
            continue
        c += custo_parcial(entrada, saida, off)
        arestas = list(zip(caminho[:-1], caminho[1:])) + [(entrada, saida)]
        melhores.append((c, arestas, off))
    return min(melhores, key=lambda t: t[0]) if melhores else (math.inf, [], 0.0)


NOMES = {"J1": "1º cruzamento", "J2": "2º cruzamento", "J3": "3º cruzamento",
         "TA": "via do fundo", "TB": "via do fundo", "TC": "via do fundo", "G": "guarita"}


def _nome(layout: Layout, no: str) -> str:
    return layout.nos[no].nome or NOMES.get(no, no)


def _virada(layout, a, b, c) -> int:
    """0 = em frente, -1 = esquerda, +1 = direita (eixo y cresce para baixo)."""
    na, nb, nc = layout.nos[a], layout.nos[b], layout.nos[c]
    v1 = (nb.x - na.x, nb.y - na.y)
    v2 = (nc.x - nb.x, nc.y - nb.y)
    cruz = v1[0] * v2[1] - v1[1] * v2[0]
    if abs(cruz) < 1e-6:
        return 0
    return -1 if cruz < 0 else 1


def descrever_rota(layout: Layout, arestas: list[tuple[str, str]], vaga=None) -> list[str]:
    """Transformo a rota em instruções curtas para o tablet da guarita: só as viradas
    e, no fim, de que lado do corredor fica a vaga. O motorista não precisa de mais que isso."""
    instr = []
    for i in range(len(arestas) - 1):
        a, b = arestas[i]
        _, c = arestas[i + 1]
        lado = _virada(layout, a, b, c)
        if lado:
            nome = _nome(layout, b)
            artigo = "Na" if nome.split()[0] in ("esquina", "via", "guarita", "saída", "entrada") else "No"
            instr.append(f"{artigo} {nome}, vire à {'esquerda' if lado < 0 else 'direita'}")
    if not instr:
        instr.append("Siga em frente")
    if vaga is not None and arestas:
        a, b = arestas[-1]
        mesmo_sentido = (a, b) == tuple(vaga.aresta)
        direita = (vaga.lado > 0) == mesmo_sentido
        instr.append(f"Vaga {vaga.id} à {'direita' if direita else 'esquerda'}")
    return instr


def pontos_rota(layout: Layout, arestas: list[tuple[str, str]], offset_final: float, vaga=None) -> list[list[float]]:
    """Coordenadas da rota para desenhar no mapa: guarita → nós → ponto do corredor ao lado da vaga."""
    if not arestas:
        return []
    pts = [[layout.nos[arestas[0][0]].x, layout.nos[arestas[0][0]].y]]
    for a, b in arestas[:-1]:
        pts.append([layout.nos[b].x, layout.nos[b].y])
    a, b = arestas[-1]
    na, nb = layout.nos[a], layout.nos[b]
    L = layout.aresta(a, b).comprimento
    f = offset_final / L if L else 0
    pts.append([round(na.x + (nb.x - na.x) * f, 2), round(na.y + (nb.y - na.y) * f, 2)])
    if vaga is not None:
        pts.append([vaga.x, vaga.y])
    return pts
