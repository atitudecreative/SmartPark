"""
Aviso antecipado de lotação.

A pergunta que eu quero responder: "Daqui a quantos minutos não vai ter mais vaga livre?"

Método que usei (projeção da demanda acumulada):
    1. Próximos 5 minutos: uso as chegadas previstas pelo Random Forest
       (smartpark/preditor.py), divididas igualmente minuto a minuto.
    2. Do 6º minuto em diante: uso o perfil médio histórico daquele culto,
       corrigido pelo VOLUME que já observei até agora:
           f = (chegadas desde o início da janela + 2) / (chegadas esperadas até agora + 2)
       limitado a [0,6 ; 1,6] e puxado para 1 enquanto ainda tenho poucos dados
       (peso = esperadas / (esperadas + 8)).
       Assim, um culto mais cheio que o normal (chuva, evento especial)
       antecipa a previsão, e um mais vazio adia. Escolhi usar o acumulado, e não só os
       últimos minutos, porque na primeira versão o sistema confundia "a onda começou mais cedo"
       com "vai vir mais gente" e dava muito alarme falso.
    3. Somo as chegadas minuto a minuto até passar do número de vagas livres.
       O instante em que cruza (interpolado) é a previsão de lotação.

Níveis de alerta:
    ok       : não deve lotar nos próximos 30 min
    atencao  : deve lotar em até 15 min   -> avisar a equipe de recepção
    critico  : deve lotar em até 5 min    -> abrir estacionamento extra / orientar na rua
    lotado   : nenhuma vaga livre agora
"""
from __future__ import annotations

import bisect

HORIZONTE_MIN = 30
LIMIAR_ATENCAO = 15
LIMIAR_CRITICO = 5
JANELA_CULTO = (-60, 30)   # só faz sentido prever perto do começo do culto
INICIO_CONTAGEM = -50      # minuto a partir do qual as chegadas do culto são contadas
CONFIRMACOES = 2           # exijo 2 leituras seguidas (a cada 30 s) antes de disparar um aviso

MENSAGENS = {
    "ok": "",
    "atencao": "Estacionamento deve lotar em ~{m} min",
    "critico": "Estacionamento lota em ~{m} min",
    "lotado": "Estacionamento lotado",
}


def _taxa(perfil: dict, culto: int, minuto: float) -> float:
    """Chegadas por minuto esperadas em torno de 'minuto' (perfil = chegadas nos 5 min seguintes)."""
    return perfil.get((culto, int(round(minuto))), 0.0) / 5.0


def prever_lotacao(preditor, t_min: float, chegadas_min: list[float], culto_idx: int,
                   ocupacao: float, livres: int, horizonte: int = HORIZONTE_MIN, escala: float = 1.0) -> dict:
    """
    t_min        : minutos em relação ao início do culto (negativo = antes)
    chegadas_min : instantes (min, relativos ao culto) das entradas já registradas, ordenados
    ocupacao     : fração de vagas ocupadas (entrada do modelo)
    livres       : vagas livres e não reservadas agora
    escala       : razão entre o tamanho deste estacionamento e o usado no treino
                   (maquete de 6 vagas / igreja de 48 = 0,125)
    """
    base = {"minutos": None, "nivel": "ok", "chegadas_15min": None, "fator_ritmo": None, "livres": livres}
    if livres <= 0:
        return {**base, "minutos": 0.0, "nivel": "lotado"}
    if preditor is None or not (JANELA_CULTO[0] <= t_min <= JANELA_CULTO[1]):
        return base

    perfil = preditor.perfil_medio
    inicio = INICIO_CONTAGEM
    obs = bisect.bisect_right(chegadas_min, t_min) - bisect.bisect_left(chegadas_min, inicio)
    esp = escala * sum(_taxa(perfil, culto_idx, m) for m in range(int(inicio), int(round(t_min))))
    bruto = min(1.6, max(0.6, (obs + 2) / (esp + 2)))
    peso = esp / (esp + 8)
    fator = 1 + (bruto - 1) * peso
    prox5 = preditor.prever(t_min, chegadas_min, culto_idx, ocupacao) if escala == 1.0 \
        else escala * _taxa(perfil, culto_idx, t_min) * 5 * fator   # fora da escala do treino (maquete): uso o perfil

    acumulado, minutos, chegadas_15 = 0.0, None, None
    for k in range(1, horizonte + 1):
        taxa = prox5 / 5.0 if k <= 5 else escala * _taxa(perfil, culto_idx, t_min + k - 1) * fator
        antes = acumulado
        acumulado += taxa
        if minutos is None and acumulado >= livres and taxa > 0:
            minutos = (k - 1) + (livres - antes) / taxa
        if k == 15:
            chegadas_15 = acumulado

    nivel = "ok"
    if minutos is not None:
        nivel = "critico" if minutos <= LIMIAR_CRITICO else "atencao" if minutos <= LIMIAR_ATENCAO else "ok"
    return {**base, "minutos": None if minutos is None else round(minutos, 1), "nivel": nivel,
            "chegadas_15min": round(chegadas_15 or 0.0, 1), "fator_ritmo": round(fator, 2)}


def mensagem(prev: dict) -> str:
    m = prev.get("minutos")
    return MENSAGENS[prev["nivel"]].format(m=max(1, round(m)) if m else 0)
