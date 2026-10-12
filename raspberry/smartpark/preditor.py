"""
Preditor de demanda de curto prazo: é a parte de IA do projeto.

A pergunta que o modelo responde a cada minuto é:
    "Quantos veículos vão chegar à guarita nos próximos H minutos?"

Usei só entradas (features) que o sistema consegue observar em tempo real:
    - minutos até o início do culto
    - chegadas nos últimos 1, 3, 5 e 10 minutos (contadas pela guarita)
    - ocupação atual do estacionamento (sensores das vagas)
    - qual culto é (one-hot dos 4 horários fixos)

Modelo principal: Random Forest (scikit-learn), escolhido por funcionar bem com poucos dados e rodar leve no Pi.
Linha de base: a média histórica daquele culto naquele minuto ("perfil médio").
Comparo os dois para mostrar se o aprendizado agrega alguma coisa além da média.
"""
from __future__ import annotations

import bisect
from pathlib import Path

import numpy as np

HORIZONTE_MIN = 5
N_CULTOS = 4


def features(t_min: float, chegadas_min: list[float], culto_idx: int, ocupacao: float) -> list[float]:
    """chegadas_min: instantes (em min, relativos ao culto) das entradas que já aconteceram, em ordem."""
    def contar(janela):
        return bisect.bisect_right(chegadas_min, t_min) - bisect.bisect_right(chegadas_min, t_min - janela)

    oh = [0.0] * N_CULTOS
    oh[culto_idx] = 1.0
    return [t_min, contar(1), contar(3), contar(5), contar(10), ocupacao, *oh]


def alvo(t_min: float, chegadas_todas: list[float]) -> int:
    return bisect.bisect_right(chegadas_todas, t_min + HORIZONTE_MIN) - bisect.bisect_right(chegadas_todas, t_min)


class Preditor:
    def __init__(self, modelo=None, perfil_medio=None):
        self.modelo = modelo
        self.perfil_medio = perfil_medio or {}  # (culto_idx, minuto_int) -> média

    # ---------------------------------------------------------------- uso
    def prever(self, t_min, chegadas_min, culto_idx, ocupacao) -> float:
        if self.modelo is None:
            return self.prever_baseline(t_min, culto_idx)
        x = np.array([features(t_min, chegadas_min, culto_idx, ocupacao)])
        return float(max(0.0, self.modelo.predict(x)[0]))

    def prever_baseline(self, t_min, culto_idx) -> float:
        return self.perfil_medio.get((culto_idx, int(round(t_min))), 0.0)

    # ---------------------------------------------------------- persistência
    def salvar(self, caminho: str | Path):
        import joblib
        joblib.dump({"modelo": self.modelo, "perfil": self.perfil_medio}, caminho)

    @classmethod
    def carregar(cls, caminho: str | Path) -> "Preditor":
        import joblib
        d = joblib.load(caminho)
        if d["modelo"] is not None:
            d["modelo"].n_jobs = 1  # faço uma previsão por vez: paralelismo aqui só atrapalha
        return cls(d["modelo"], d["perfil"])


def montar_dataset(historico: list[tuple[int, list[float]]], passo_min: float = 1.0,
                   ocupacao_fn=None, inicio=-50, fim=15):
    """
    historico: lista de (culto_idx, instantes_de_chegada_em_min).
    Monto uma amostra por minuto de cada culto.
    """
    X, y, meta = [], [], []
    for culto_idx, chegadas in historico:
        chegadas = sorted(chegadas)
        t = inicio
        while t <= fim:
            passadas = chegadas[: bisect.bisect_right(chegadas, t)]
            ocup = ocupacao_fn(len(passadas)) if ocupacao_fn else len(passadas) / 48
            X.append(features(t, passadas, culto_idx, ocup))
            y.append(alvo(t, chegadas))
            meta.append((culto_idx, int(round(t))))
            t += passo_min
    return np.array(X), np.array(y), meta


def treinar(historico_treino, seed=0):
    from sklearn.ensemble import RandomForestRegressor
    X, y, meta = montar_dataset(historico_treino)
    modelo = RandomForestRegressor(n_estimators=200, max_depth=10, min_samples_leaf=3, random_state=seed, n_jobs=-1)
    modelo.fit(X, y)
    # perfil médio (a linha de base que o modelo precisa vencer)
    soma, cont = {}, {}
    for (k, alvo_) in zip(meta, y):
        soma[k] = soma.get(k, 0) + alvo_
        cont[k] = cont.get(k, 0) + 1
    perfil = {k: soma[k] / cont[k] for k in soma}
    return Preditor(modelo, perfil)


def avaliar(preditor: Preditor, historico_teste):
    from sklearn.metrics import mean_absolute_error, r2_score
    X, y, meta = montar_dataset(historico_teste)
    p_rf = np.maximum(0, preditor.modelo.predict(X))
    p_base = np.array([preditor.perfil_medio.get(k, 0.0) for k in meta])
    p_ingenuo = X[:, 3]  # "os próximos 5 min serão iguais aos últimos 5"
    return {
        "Random Forest": {"MAE": mean_absolute_error(y, p_rf), "R2": r2_score(y, p_rf)},
        "Perfil médio histórico": {"MAE": mean_absolute_error(y, p_base), "R2": r2_score(y, p_base)},
        "Ingênuo (últimos 5 min)": {"MAE": mean_absolute_error(y, p_ingenuo), "R2": r2_score(y, p_ingenuo)},
    }
