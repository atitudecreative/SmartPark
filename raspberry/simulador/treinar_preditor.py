"""
Treino e avalio o preditor de demanda.

Uso:
    python -m simulador.treinar_preditor            # dados sintéticos (minhas hipóteses iniciais)
    python -m simulador.treinar_preditor --csv chegadas_reais.csv   # dados que eu coletar em campo

Formato do CSV real (uma linha por veículo que passou pela guarita):
    culto_idx,t_min
    0,-14.5
    0,-13.9
    ...
    (cada culto observado precisa também de uma coluna 'ocorrencia' para separar dias diferentes)
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from smartpark.preditor import treinar, avaliar
from .chegadas import CULTOS, gerar_chegadas

RAIZ = Path(__file__).resolve().parents[1]
MODELO = RAIZ / "smartpark" / "dados" / "preditor.joblib"


def historico_sintetico(n_por_culto: int, seed: int):
    rng = random.Random(seed)
    hist = []
    for _ in range(n_por_culto):
        for i, p in enumerate(CULTOS):
            hist.append((i, [c.t_min for c in gerar_chegadas(p, rng)]))
    return hist


def historico_csv(caminho):
    grupos = {}
    with open(caminho, newline="") as f:
        for row in csv.DictReader(f):
            k = (int(row["culto_idx"]), row.get("ocorrencia", "0"))
            grupos.setdefault(k, []).append(float(row["t_min"]))
    return [(k[0], v) for k, v in grupos.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="arquivo com chegadas reais observadas")
    ap.add_argument("--semanas", type=int, default=26, help="semanas sintéticas de treino")
    args = ap.parse_args()

    if args.csv:
        hist = historico_csv(args.csv)
        random.Random(0).shuffle(hist)
        corte = int(len(hist) * 0.75)
        treino, teste = hist[:corte], hist[corte:]
    else:
        treino = historico_sintetico(args.semanas, seed=100)   # ~6 meses de cultos
        teste = historico_sintetico(8, seed=999)               # 2 meses que o modelo nunca viu

    pred = treinar(treino)
    res = avaliar(pred, teste)
    MODELO.parent.mkdir(parents=True, exist_ok=True)
    pred.salvar(MODELO)

    print(f"Cultos no treino: {len(treino)} | no teste: {len(teste)}")
    print(f"{'Modelo':<28}{'MAE (veíc./5min)':>18}{'R²':>8}")
    for nome, m in res.items():
        print(f"{nome:<28}{m['MAE']:>18.2f}{m['R2']:>8.3f}")
    out = RAIZ.parent / "resultados" / "preditor_metricas.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"Modelo salvo em {MODELO}")


if __name__ == "__main__":
    main()
