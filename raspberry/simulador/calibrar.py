"""
Calibro os parâmetros da estratégia preditiva (w_base, w_escala, alfa) em
cenários de VALIDAÇÃO. Os cenários de TESTE do experimento final usam
outras sementes, para o resultado não ficar "ajustado à prova".
"""
import itertools
import random
import statistics

from smartpark.layout import layout_igreja
from smartpark.preditor import Preditor
from .chegadas import CULTOS, gerar_chegadas
from .motor import Simulacao
from .treinar_preditor import MODELO


def main():
    lay = layout_igreja()
    pred = Preditor.carregar(MODELO)
    cenarios = []
    rng = random.Random(555)  # sementes de validação
    for i, p in enumerate(CULTOS):
        for _ in range(6):
            cenarios.append((i, gerar_chegadas(p, rng)))
    grade = list(itertools.product([0.0, 0.4, 0.8], [2.0, 4.0, 8.0], [0.2, 0.3, 0.5]))
    res = []
    for wb, we, a in grade:
        tempos = []
        for k, (i, ch) in enumerate(cenarios):
            m = Simulacao(lay, ch, "preditiva", i, preditor=pred, seed=k,
                          params_alocador=dict(w_base=wb, w_escala=we, alfa_caminhada=a)).rodar()
            tempos.append(m["porta_a_porta_medio_s"])
        res.append((statistics.mean(tempos), wb, we, a))
    res.sort()
    print("Melhores combinações (porta-a-porta médio, s):")
    for r in res[:5]:
        print(f"  {r[0]:6.1f}  w_base={r[1]}  w_escala={r[2]}  alfa={r[3]}")
    # referência: estratégia reativa com cada alfa
    for a in (0.2, 0.3, 0.5):
        t = [Simulacao(lay, ch, "reativa", i, seed=k, params_alocador=dict(alfa_caminhada=a)).rodar()["porta_a_porta_medio_s"]
             for k, (i, ch) in enumerate(cenarios)]
        print(f"reativa alfa={a}: {statistics.mean(t):.1f}")


if __name__ == "__main__":
    main()
