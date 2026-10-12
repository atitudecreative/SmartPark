"""
Avalio o aviso antecipado de lotação na simulação.

    python -m simulador.avaliar_aviso            # 20 cultos por cenário
    python -m simulador.avaliar_aviso --rep 5    # rápido

A cada 30 s de cada culto simulado, três métodos estimam "em quantos minutos
lota". Depois comparo com o instante em que a lotação de fato aconteceu.

    IA (proposto)      : Random Forest nos próximos 5 min + perfil histórico
                         corrigido pelo volume observado (smartpark/lotacao.py)
    Perfil histórico   : só a média dos cultos anteriores, sem correção
    Ritmo constante    : supõe que os próximos minutos repetem os últimos 5

Métricas que uso:
    - erro absoluto médio da previsão (min), por faixa de tempo restante
    - cultos que lotaram e foram avisados com 5+ min de antecedência
    - antecedência média do primeiro aviso de "atenção"
    - alarmes falsos: aviso de "atenção" em culto que não lotou
"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import statistics
import warnings
from pathlib import Path

from smartpark.layout import layout_igreja
from smartpark.lotacao import prever_lotacao, LIMIAR_ATENCAO, HORIZONTE_MIN, CONFIRMACOES
from smartpark.preditor import Preditor
from .chegadas import CULTOS, PerfilCulto, gerar_chegadas
from .motor import Simulacao
from .treinar_preditor import MODELO

warnings.simplefilter("ignore")
RES = Path(__file__).resolve().parents[2] / "resultados"
METODOS = ["IA (proposto)", "Perfil histórico", "Ritmo constante"]
FAIXAS = [(0, 5), (5, 10), (10, 15), (15, 20)]


def _acumular(taxas, livres):
    acc = 0.0
    for k, taxa in enumerate(taxas, start=1):
        antes = acc
        acc += taxa
        if acc >= livres and taxa > 0:
            return (k - 1) + (livres - antes) / taxa
    return None


def primeiro_aviso(registro, metodo, lot):
    """Instante do primeiro aviso de 'atenção', confirmado em 2 leituras seguidas (30 s cada),
    como faço no controlador real para não alarmar por oscilação."""
    seguidas = 0
    for t, pv in registro:
        if lot is not None and t >= lot:
            return None
        seguidas = seguidas + 1 if (pv[metodo] is not None and pv[metodo] <= LIMIAR_ATENCAO) else 0
        if seguidas >= CONFIRMACOES:
            return t
    return None


def previsoes(pred, t_min, chegadas, culto, ocup, livres):
    if livres <= 0:
        return {m: 0.0 for m in METODOS}
    ia = prever_lotacao(pred, t_min, chegadas, culto, ocup, livres)["minutos"]
    perfil = [pred.perfil_medio.get((culto, int(round(t_min + k - 1))), 0.0) / 5 for k in range(1, HORIZONTE_MIN + 1)]
    obs5 = bisect.bisect_right(chegadas, t_min) - bisect.bisect_right(chegadas, t_min - 5)
    ritmo = [obs5 / 5] * HORIZONTE_MIN
    return {"IA (proposto)": ia, "Perfil histórico": _acumular(perfil, livres), "Ritmo constante": _acumular(ritmo, livres)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep", type=int, default=20)
    a = ap.parse_args()
    lay = layout_igreja()
    pred = Preditor.carregar(MODELO)
    cenarios = [(i, p) for i, p in enumerate(CULTOS)] + [
        (1, PerfilCulto("Domingo 11h cheio (+15%)", 46 * 1.15, -12, 7, 0.10, CULTOS[1].mix)),
        (1, PerfilCulto("Evento especial (estresse)", 47, -8, 3.0, 0.05, CULTOS[1].mix)),
    ]
    erros = {m: {f: [] for f in FAIXAS} for m in METODOS}
    cultos = []
    for ci, (idx, perfil) in enumerate(cenarios):
        rng = random.Random(7000 + ci)
        for rep in range(a.rep):
            ch = gerar_chegadas(perfil, rng)
            registro = []
            estado = {"lotou": None, "prox": -1e9}

            def passo(sim):
                if estado["lotou"] is None and sim.livres_comuns() == 0:   # lotação = vagas comuns esgotadas
                    estado["lotou"] = sim.t / 60
                if sim.t - estado["prox"] >= 30 and -60 <= sim.t / 60 <= 30:
                    estado["prox"] = sim.t
                    ocup = sum(sim.ocupada.values()) / len(sim.ocupada)
                    # carros que já passaram pela cancela e ainda não receberam vaga
                    na_fila = len(sim.fila) + (1 if sim.atendendo else 0)
                    registro.append((sim.t / 60, previsoes(pred, sim.t / 60, sim.entradas_min, idx, ocup, sim.livres_comuns() - na_fila)))

            Simulacao(lay, ch, "preditiva", idx, preditor=pred, seed=rep).rodar(ao_passo=passo)
            lot = estado["lotou"]
            info = {"cenario": perfil.nome, "rep": rep, "veiculos": len(ch), "lotou_min": lot, "primeiro_aviso": {}}
            for m in METODOS:
                aviso = primeiro_aviso(registro, m, lot)
                info["primeiro_aviso"][m] = aviso
                if lot is None:
                    continue
                for t, pv in registro:
                    resta = lot - t
                    for f in FAIXAS:
                        if f[0] < resta <= f[1]:
                            prev = pv[m] if pv[m] is not None else HORIZONTE_MIN
                            erros[m][f].append(abs(prev - resta))
            cultos.append(info)
        print(f"✓ {perfil.nome}")

    lotaram = [c for c in cultos if c["lotou_min"] is not None]
    nao = [c for c in cultos if c["lotou_min"] is None]
    resumo = {"cultos": len(cultos), "lotaram": len(lotaram), "metodos": {}}
    for m in METODOS:
        ant = [c["lotou_min"] - c["primeiro_aviso"][m] for c in lotaram if c["primeiro_aviso"][m] is not None]
        resumo["metodos"][m] = {
            "mae_por_faixa": {f"{f[0]}-{f[1]} min": (statistics.mean(erros[m][f]) if erros[m][f] else None) for f in FAIXAS},
            "avisados_5min": sum(1 for x in ant if x >= 5),
            "antecedencia_media_min": statistics.mean(ant) if ant else None,
            "alarmes_falsos": sum(1 for c in nao if c["primeiro_aviso"][m] is not None),
            "cultos_sem_lotacao": len(nao),
        }
    RES.mkdir(exist_ok=True)
    (RES / "aviso_lotacao.json").write_text(json.dumps({"resumo": resumo, "cultos": cultos}, indent=2, ensure_ascii=False))

    print(f"\n{len(cultos)} cultos simulados, {len(lotaram)} lotaram.\n")
    print(f"{'Método':<20}" + "".join(f"{'erro ' + k:>15}" for k in resumo['metodos'][METODOS[0]]['mae_por_faixa']) +
          f"{'avisou 5+ min':>15}{'antecedência':>14}{'alarme falso':>14}")
    for m in METODOS:
        r = resumo["metodos"][m]
        print(f"{m:<20}" + "".join(f"{(f'{v:.1f} min' if v is not None else '–'):>15}" for v in r["mae_por_faixa"].values()) +
              f"{r['avisados_5min']:>9}/{len(lotaram):<5}{(f"{r['antecedencia_media_min']:.1f} min" if r['antecedencia_media_min'] else '–'):>12}"
              f"{r['alarmes_falsos']:>8}/{len(nao)}")
    grafico(resumo)


def grafico(resumo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cores = ["#2a78d6", "#eb6834", "#1baf7a"]
    faixas = list(resumo["metodos"][METODOS[0]]["mae_por_faixa"])
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    larg = 0.26
    for j, m in enumerate(METODOS):
        ys = [resumo["metodos"][m]["mae_por_faixa"][f] or 0 for f in faixas]
        xs = [i + (j - 1) * larg for i in range(len(faixas))]
        b = ax.bar(xs, ys, larg * 0.9, color=cores[j], label=m)
        for r, y in zip(b, ys):
            ax.text(r.get_x() + r.get_width() / 2, y + 0.1, f"{y:.1f}", ha="center", fontsize=7, color="#52514e")
    ax.set_xticks(range(len(faixas)))
    ax.set_xticklabels([f"faltando {f}" for f in faixas], fontsize=8)
    ax.set_title("Erro médio da previsão de lotação (minutos) — quanto menor, melhor", fontsize=10, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color="#ecebe7")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    fig.tight_layout()
    fig.savefig(RES / "grafico_aviso_lotacao.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
