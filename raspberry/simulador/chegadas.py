"""
Gerador de chegadas de carros aos cultos.

Cada culto tem um perfil próprio (volume, horário de pico e dispersão). Os
parâmetros abaixo são as minhas HIPÓTESES INICIAIS. Vou trocá-los pelos valores
que observar em campo (contagem manual na guarita durante algumas semanas —
ver docs/protocolo_coleta.md).

Tempos em minutos em relação ao início do culto (negativo = antes).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from smartpark.lpr import placa_aleatoria


@dataclass(frozen=True)
class PerfilCulto:
    nome: str
    volume_medio: float      # veículos por culto
    pico_min: float          # minuto de maior chegada
    dispersao_min: float     # desvio-padrão da onda principal
    frac_atrasados: float    # fração que chega depois do início
    mix: dict                # proporção por categoria


# Os quatro cultos são aos domingos. Com 2h30 entre o das 8h30 e o das 11h (e entre o das 17h e o das 19h30),
# considero que o pátio já esvaziou quando começa a onda de chegada do culto seguinte; a sobreposição
# entre a saída de um culto e a chegada do outro fica como limitação até a coleta de campo.
CULTOS = [
    PerfilCulto("Domingo 8h30", 34, -10, 7, 0.12, {"MEMBRO": .64, "IDOSO": .16, "PCD": .03, "EQUIPE": .08, "VISITANTE": .09}),
    PerfilCulto("Domingo 11h", 46, -12, 7, 0.10, {"MEMBRO": .66, "IDOSO": .11, "PCD": .03, "EQUIPE": .07, "VISITANTE": .13}),
    PerfilCulto("Domingo 17h", 38, -8, 7, 0.15, {"MEMBRO": .70, "IDOSO": .09, "PCD": .03, "EQUIPE": .07, "VISITANTE": .11}),
    PerfilCulto("Domingo 19h30", 45, -6, 6, 0.18, {"MEMBRO": .72, "IDOSO": .05, "PCD": .02, "EQUIPE": .07, "VISITANTE": .14}),
]

INICIO_JANELA = -50.0  # minutos
FIM_JANELA = 20.0


@dataclass
class Chegada:
    t_min: float        # instante relativo ao culto
    placa: str
    categoria: str      # categoria REAL (o sistema só descobre pela câmera + banco)


def gerar_chegadas(perfil: PerfilCulto, rng: random.Random) -> list[Chegada]:
    # Variação de um dia para o outro (chuva, feriado, evento especial...):
    # muda o volume e adianta ou atrasa a onda inteira. É essa variação que as
    # contagens recentes mostram e que uma média fixa não pega.
    fator_volume = rng.lognormvariate(0, 0.18)
    deslocamento = rng.gauss(0, 3.0)
    n = max(5, round(rng.gauss(perfil.volume_medio * fator_volume, perfil.volume_medio * 0.05)))
    cats = list(perfil.mix)
    pesos = [perfil.mix[c] for c in cats]
    out = []
    for _ in range(n):
        cat = rng.choices(cats, pesos)[0]
        if cat == "EQUIPE":                         # voluntários chegam bem antes, como na igreja
            t = rng.gauss(-40, 5)
        elif rng.random() < perfil.frac_atrasados:  # atrasados
            t = rng.uniform(0, 15)
        else:
            t = rng.gauss(perfil.pico_min + deslocamento, perfil.dispersao_min)
        t = min(max(t, INICIO_JANELA), FIM_JANELA - 1)
        out.append(Chegada(t, placa_aleatoria(rng), cat))
    out.sort(key=lambda c: c.t_min)
    return out
