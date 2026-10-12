"""
Relatórios de permanência e ocupação.

Perguntas que eu queria conseguir responder com os dados:
    - Quais carros estiveram em quais vagas, e por quanto tempo?
    - Quanto tempo, em média, os carros ficam estacionados num culto?
    - A que horas o estacionamento lotou? Qual foi a ocupação máxima?
    - Qual corredor enche primeiro?
"""
from __future__ import annotations

import datetime as dt
import statistics

from .layout import Layout


def fmt_duracao(s: float) -> str:
    s = int(round(s))
    h, resto = divmod(s, 3600)
    m, seg = divmod(resto, 60)
    if h:
        return f"{h}h{m:02d}"
    if m:
        return f"{m}min{seg:02d}s"
    return f"{seg}s"


def fmt_hora(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%H:%M:%S") if t else "--"


def curva_ocupacao(perms: list[dict], agora: float) -> list[tuple[float, int]]:
    """Pontos (instante, vagas ocupadas) a cada mudança — é a base do gráfico de ocupação."""
    eventos = []
    for p in perms:
        eventos.append((p["entrada"], +1))
        if p["saida"] is not None:          # vagas ainda ocupadas não "saem" no gráfico
            eventos.append((p["saida"], -1))
    eventos.sort(key=lambda e: (e[0], e[1]))  # no mesmo instante, conto as saídas antes das entradas
    n, curva = 0, []
    for t, d in eventos:
        n += d
        curva.append((t, n))
    return curva


def resumo(perms: list[dict], layout: Layout, agora: float) -> dict:
    total_vagas = len(layout.vagas)
    zona_de = {v.id: v.zona for v in layout.vagas}
    duracoes = [p["duracao_s"] for p in perms]
    concluidas = [p["duracao_s"] for p in perms if not p["em_andamento"]]
    curva = curva_ocupacao(perms, agora)
    pico = max((n for _, n in curva), default=0)
    t_pico = next((t for t, n in curva if n == pico), None) if pico else None
    t_lotou = next((t for t, n in curva if n >= total_vagas), None)

    por_zona = {}
    for z in layout.zonas():
        ps = [p for p in perms if zona_de.get(p["vaga"]) == z]
        cheia = None
        vagas_z = [v.id for v in layout.vagas if v.zona == z]
        if ps:
            sub = curva_ocupacao(ps, agora)
            cheia = next((t for t, n in sub if n >= len(vagas_z)), None)
        por_zona[z] = {
            "permanencias": len(ps),
            "duracao_media_s": statistics.mean(p["duracao_s"] for p in ps) if ps else 0,
            "lotou_em": cheia,
        }

    return {
        "permanencias": len(perms),
        "em_andamento": sum(p["em_andamento"] for p in perms),
        "identificadas": sum(p["placa"] is not None for p in perms),
        "fora_da_vaga_indicada": sum(p["origem"] == "desconhecida" for p in perms),
        "duracao_media_s": statistics.mean(duracoes) if duracoes else 0,
        "duracao_mediana_s": statistics.median(concluidas) if concluidas else 0,
        "duracao_max_s": max(duracoes, default=0),
        "ocupacao_maxima": pico,
        "ocupacao_maxima_em": t_pico,
        "total_vagas": total_vagas,
        "lotou_em": t_lotou,
        "por_zona": por_zona,
        "curva": curva,
    }


def texto(perms: list[dict], r: dict, titulo: str) -> str:
    linhas = [titulo, "=" * len(titulo), ""]
    linhas.append(f"{'Vaga':<6}{'Placa':<10}{'Categoria':<11}{'Chegou':<10}{'Saiu':<10}{'Tempo':>9}  Obs.")
    for p in perms:
        obs = []
        if p["origem"] == "desconhecida":
            obs.append("parou fora da vaga indicada")
        if p["em_andamento"]:
            obs.append("ainda estacionado")
        linhas.append(f"{p['vaga']:<6}{(p['placa'] or '—'):<10}{(p['categoria'] or '—'):<11}"
                      f"{fmt_hora(p['entrada']):<10}{fmt_hora(p['saida']):<10}{fmt_duracao(p['duracao_s']):>9}  {'; '.join(obs)}")
    linhas += [
        "",
        f"Permanências: {r['permanencias']} ({r['em_andamento']} em andamento)",
        f"Com placa identificada: {r['identificadas']}  |  Pararam fora da vaga indicada: {r['fora_da_vaga_indicada']}",
        f"Tempo médio estacionado: {fmt_duracao(r['duracao_media_s'])}  |  mediana: {fmt_duracao(r['duracao_mediana_s'])}"
        f"  |  máximo: {fmt_duracao(r['duracao_max_s'])}",
        f"Ocupação máxima: {r['ocupacao_maxima']}/{r['total_vagas']} vagas às {fmt_hora(r['ocupacao_maxima_em'])}",
        f"Estacionamento lotou: {fmt_hora(r['lotou_em']) if r['lotou_em'] else 'não lotou'}",
    ]
    for z, d in r["por_zona"].items():
        linhas.append(f"  Corredor {z}: {d['permanencias']} carros, média {fmt_duracao(d['duracao_media_s'])}, "
                      f"{'lotou às ' + fmt_hora(d['lotou_em']) if d['lotou_em'] else 'não lotou'}")
    return "\n".join(linhas)
