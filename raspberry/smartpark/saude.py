"""
Saúde dos sensores (manutenção preditiva do próprio sistema).

Um sensor de vaga com defeito não "avisa" que quebrou: ele simplesmente começa a
mentir. Os sintomas aparecem nos dados, e é isso que eu procuro aqui.

Diagnósticos que faço por vaga:
    PRESO_OCUPADO  ocupada há mais de 6 h seguidas (fora do normal de um culto,
                   que dura ~2 h): sensor travado em "ocupado", objeto sobre ele
                   ou carro abandonado.                                   -> falha
    OSCILANDO      6+ trocas livre/ocupada em 10 minutos: mau contato, sensor
                   desalinhado ou sol/reflexo batendo no infravermelho.   -> atenção
    SEM_USO        nenhuma ocupação nos últimos 14 dias, enquanto as outras vagas
                   tiveram em média 4+: sensor travado em "livre".        -> atenção
    LEITURAS_CURTAS 3+ ocupações de menos de 1 minuto em 14 dias: carro passando
                   por cima, pessoa ou animal, sensibilidade alta demais. -> atenção

No controlador (ESP32) eu vejo se está online ou offline pela mensagem de vida do MQTT.
"""
from __future__ import annotations

import statistics

PRESO_H = 6
OSCILA_TROCAS, OSCILA_JANELA_S = 6, 600
SEM_USO_DIAS, SEM_USO_MEDIA_MIN = 14, 4
CURTA_S, CURTAS_MIN = 60, 3

ACOES = {
    "PRESO_OCUPADO": "Verifique se há carro ou objeto na vaga. Se estiver vazia, limpe e teste o sensor.",
    "OSCILANDO": "Confira fios e conectores e o alinhamento do sensor. Ajuste a sensibilidade (trimpot).",
    "SEM_USO": "Estacione um carro na vaga e veja se o painel muda para ocupada. Se não mudar, troque o sensor.",
    "LEITURAS_CURTAS": "Reduza a sensibilidade do sensor ou reposicione para não pegar quem passa na via.",
}
TITULOS = {
    "PRESO_OCUPADO": "Ocupada há tempo demais",
    "OSCILANDO": "Leitura oscilando",
    "SEM_USO": "Nunca registra ocupação",
    "LEITURAS_CURTAS": "Ocupações muito curtas",
}
GRAVIDADE = {"PRESO_OCUPADO": "falha", "OSCILANDO": "atencao", "SEM_USO": "atencao", "LEITURAS_CURTAS": "atencao"}


def diagnosticar(layout, banco, agora: float, esp32: dict | None = None) -> dict:
    desde = agora - SEM_USO_DIAS * 86400
    perms = banco.permanencias(desde, None, agora=agora)
    abertas = {v.id: banco.permanencia_aberta(v.id) for v in layout.vagas}
    eventos = banco.con.execute(
        "SELECT vaga, instante FROM eventos WHERE tipo IN ('VAGA_OCUPADA','VAGA_LIVRE') AND instante >= ? ORDER BY instante",
        (desde,)).fetchall()
    trocas: dict[str, list[float]] = {}
    for vaga, t in eventos:
        trocas.setdefault(vaga, []).append(t)

    uso = {v.id: 0 for v in layout.vagas}
    curtas = {v.id: 0 for v in layout.vagas}
    ultima = {v.id: None for v in layout.vagas}
    for p in perms:
        if p["vaga"] not in uso:
            continue
        uso[p["vaga"]] += 1
        ultima[p["vaga"]] = max(ultima[p["vaga"]] or 0, p["saida"] or p["entrada"])
        if not p["em_andamento"] and p["duracao_s"] < CURTA_S:
            curtas[p["vaga"]] += 1

    vagas = []
    for v in layout.vagas:
        problemas = []
        ab = abertas[v.id]
        if ab and agora - ab["entrada"] > PRESO_H * 3600:
            problemas.append(("PRESO_OCUPADO", f"ocupada desde {_hora(ab['entrada'])} ({(agora - ab['entrada']) / 3600:.0f} h)"))
        ts = trocas.get(v.id, [])
        pior = _max_em_janela(ts, OSCILA_JANELA_S)
        if pior >= OSCILA_TROCAS and ts and agora - ts[-1] < 86400:
            problemas.append(("OSCILANDO", f"{pior} trocas em 10 min nas últimas 24 h"))
        outras = [n for k, n in uso.items() if k != v.id]
        media_outras = statistics.mean(outras) if outras else 0
        if uso[v.id] == 0 and media_outras >= SEM_USO_MEDIA_MIN and not ab:
            problemas.append(("SEM_USO", f"0 ocupações em {SEM_USO_DIAS} dias; média das outras vagas: {media_outras:.0f}"))
        if curtas[v.id] >= CURTAS_MIN:
            problemas.append(("LEITURAS_CURTAS", f"{curtas[v.id]} ocupações com menos de 1 min em {SEM_USO_DIAS} dias"))
        estado = "ok"
        if any(GRAVIDADE[c] == "falha" for c, _ in problemas):
            estado = "falha"
        elif problemas:
            estado = "atencao"
        vagas.append({
            "vaga": v.id, "zona": v.zona, "estado": estado,
            "ocupacoes_14d": uso[v.id], "ultima_atividade": ultima[v.id] or (ab["entrada"] if ab else None),
            "problemas": [{"codigo": c, "titulo": TITULOS[c], "detalhe": d, "gravidade": GRAVIDADE[c], "acao": ACOES[c]}
                          for c, d in problemas],
        })

    return {
        "vagas": vagas,
        "resumo": {k: sum(1 for x in vagas if x["estado"] == k) for k in ("ok", "atencao", "falha")},
        "esp32": esp32 or {"estado": "desconhecido"},
    }


def _max_em_janela(ts: list[float], janela: float) -> int:
    """Maior número de eventos dentro de qualquer janela de 'janela' segundos."""
    melhor, i = 0, 0
    for j, t in enumerate(ts):
        while t - ts[i] > janela:
            i += 1
        melhor = max(melhor, j - i + 1)
    return melhor


def _hora(t):
    import datetime as dt
    return dt.datetime.fromtimestamp(t).strftime("%d/%m %H:%M")
