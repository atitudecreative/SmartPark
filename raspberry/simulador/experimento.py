"""
Experimento principal do meu TCC: comparo as 4 estratégias em 5 cenários.

    python -m simulador.experimento            # 20 repetições por cenário
    python -m simulador.experimento --rep 5    # rápido, para conferir

Saídas em ../resultados/:
    experimento_bruto.csv      uma linha por (cenário, repetição, estratégia)
    experimento_resumo.json    médias e desvios
    grafico_porta_a_porta.png  tempo da chegada à guarita até a porta da igreja
    grafico_tempo_parado.png   tempo médio parado em fila dentro do estacionamento

Usei sementes aleatórias de TESTE (2026+) diferentes das da calibração (555)
e do treino do preditor (100), para não haver vazamento entre treino e teste.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import warnings
from pathlib import Path

from smartpark.layout import layout_igreja
from smartpark.preditor import Preditor
from .chegadas import CULTOS, PerfilCulto, gerar_chegadas
from .motor import Simulacao
from .treinar_preditor import MODELO

warnings.simplefilter("ignore")
RES = Path(__file__).resolve().parents[2] / "resultados"
ESTRATEGIAS = ["sem_sistema", "mais_proxima", "reativa", "preditiva"]
ROTULOS = {"sem_sistema": "Sem sistema", "mais_proxima": "Mais próxima", "reativa": "Reativa", "preditiva": "Preditiva (IA)"}
CENARIOS = [(i, p) for i, p in enumerate(CULTOS)] + [
    (1, PerfilCulto("Evento especial (estresse)", 47, -8, 3.0, 0.05, CULTOS[1].mix)),
]
METRICAS = ["tempo_medio_s", "tempo_p95_s", "tempo_parado_medio_s", "caminhada_media_s",
            "porta_a_porta_medio_s", "fila_max_cancela", "rejeitados_ou_desistiram",
            "porta_a_porta_visitante_s", "porta_a_porta_membro_s", "caminhada_visitante_s", "caminhada_membro_s"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rep", type=int, default=20)
    args = ap.parse_args()
    lay = layout_igreja()
    pred = Preditor.carregar(MODELO)
    RES.mkdir(exist_ok=True)
    linhas = []
    for ci, (culto_idx, perfil) in enumerate(CENARIOS):
        rng = random.Random(2026 + ci)
        for rep in range(args.rep):
            chegadas = gerar_chegadas(perfil, rng)
            for est in ESTRATEGIAS:
                m = Simulacao(lay, chegadas, est, culto_idx, preditor=pred, seed=rep).rodar()
                linhas.append({"cenario": perfil.nome, "rep": rep, **{k: m[k] for k in ["estrategia", *METRICAS]}})
        print(f"✓ {perfil.nome}")

    with open(RES / "experimento_bruto.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)

    resumo = {}
    for _, perfil in CENARIOS:
        resumo[perfil.nome] = {}
        for est in ESTRATEGIAS:
            sel = [l for l in linhas if l["cenario"] == perfil.nome and l["estrategia"] == est]
            resumo[perfil.nome][est] = {
                k: {"media": statistics.mean(l[k] for l in sel), "dp": statistics.pstdev(l[k] for l in sel)}
                for k in METRICAS
            }
    (RES / "experimento_resumo.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False))
    imprimir(resumo)
    graficos(resumo)


def imprimir(resumo):
    print(f"\n{'Cenário':<28}{'Estratégia':<16}{'Porta-a-porta':>14}{'P95 até vaga':>14}{'Parado':>9}")
    for cen, d in resumo.items():
        for est in ESTRATEGIAS:
            m = d[est]
            print(f"{cen:<28}{ROTULOS[est]:<16}{m['porta_a_porta_medio_s']['media']:>12.1f} s"
                  f"{m['tempo_p95_s']['media']:>12.1f} s{m['tempo_parado_medio_s']['media']:>7.1f} s")
        base = d["sem_sistema"]["porta_a_porta_medio_s"]["media"]
        melhor = d["preditiva"]["porta_a_porta_medio_s"]["media"]
        print(f"{'':<28}→ redução com o sistema: {100 * (1 - melhor / base):.0f}%\n")


def graficos(resumo):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cores = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # paleta categórica validada (ordem fixa)
    cens = list(resumo)
    for metrica, titulo, arquivo in [
        ("porta_a_porta_medio_s", "Tempo médio da guarita até a porta da igreja (s)", "grafico_porta_a_porta.png"),
        ("tempo_parado_medio_s", "Tempo médio parado em fila dentro do estacionamento (s)", "grafico_tempo_parado.png"),
    ]:
        fig, ax = plt.subplots(figsize=(11, 4.8), dpi=150)
        larg = 0.2
        for j, est in enumerate(ESTRATEGIAS):
            xs = [i + (j - 1.5) * larg for i in range(len(cens))]
            ys = [resumo[c][est][metrica]["media"] for c in cens]
            barras = ax.bar(xs, ys, larg * 0.9, color=cores[j], label=ROTULOS[est])
            for b, y in zip(barras, ys):
                ax.text(b.get_x() + b.get_width() / 2, y + 1, f"{y:.0f}", ha="center", va="bottom", fontsize=7, color="#52514e")
        ax.set_xticks(range(len(cens)))
        ax.set_xticklabels([c.replace(" (", "\n(") for c in cens], fontsize=8)
        ax.set_title(titulo, fontsize=11, loc="left", color="#0b0b0b")
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#c3c2b7")
        ax.tick_params(colors="#52514e")
        ax.yaxis.grid(True, color="#ecebe7")
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.14))
        fig.tight_layout()
        fig.savefig(RES / arquivo)
        plt.close(fig)


if __name__ == "__main__":
    main()
