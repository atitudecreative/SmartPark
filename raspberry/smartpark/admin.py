"""
Área administrativa: autenticação e indicadores agregados por culto.

Os indicadores que mostro são de USO DO ESPAÇO (lotação, tempo estacionado, quem seguiu
a orientação, uso de cada vaga). Decidi não fazer ranking de pessoas: a consulta por placa
existe para atender pedidos do titular e conferir ocorrências, não para medir
a frequência de membros na igreja (ver docs/termo_consentimento.md).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import statistics
import time
from pathlib import Path

from .controlador import HORARIOS_CULTO, culto_de_referencia
from .layout import Layout

NOMES_CULTO = ["Domingo 8h30", "Domingo 11h", "Domingo 17h", "Domingo 19h30"]
JANELA_ANTES_MIN = 90     # uma permanência que começa até 90 min antes do culto conta para ele
JANELA_DEPOIS_MIN = 90    # ... e até 90 min depois do início
CURVA_DE, CURVA_ATE, CURVA_PASSO = -60, 150, 5   # minutos relativos ao início do culto


# ============================================================== autenticação
class Autenticacao:
    """A senha é numérica e fica guardada só como hash (PBKDF2); as sessões ficam em memória, com cookie."""

    def __init__(self, arquivo: Path, validade_h: float = 12):
        self.arquivo = Path(arquivo)
        self.validade_s = validade_h * 3600
        self.sessoes: dict[str, float] = {}
        self.falhas: list[float] = []
        self.senha_gerada: str | None = None
        if not self.arquivo.exists():
            self.senha_gerada = f"{secrets.randbelow(10**6):06d}"
            self.definir(self.senha_gerada)

    @staticmethod
    def _hash(senha: str, sal: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, 200_000)

    def definir(self, senha: str):
        if len(senha) < 4:
            raise ValueError("A senha precisa ter pelo menos 4 caracteres.")
        sal = secrets.token_bytes(16)
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo.write_text(sal.hex() + ":" + self._hash(senha, sal).hex())
        self.sessoes.clear()

    def entrar(self, senha: str) -> str | None:
        agora = time.time()
        self.falhas = [t for t in self.falhas if agora - t < 60]
        if len(self.falhas) >= 5:
            return None  # bloqueio de 1 minuto depois de 5 tentativas erradas
        sal_hex, h_hex = self.arquivo.read_text().strip().split(":")
        if not hmac.compare_digest(self._hash(senha, bytes.fromhex(sal_hex)).hex(), h_hex):
            self.falhas.append(agora)
            return None
        token = secrets.token_urlsafe(32)
        self.sessoes[token] = agora + self.validade_s
        return token

    def bloqueado(self) -> bool:
        agora = time.time()
        return len([t for t in self.falhas if agora - t < 60]) >= 5

    def valido(self, token: str | None) -> bool:
        exp = self.sessoes.get(token or "")
        if exp and exp > time.time():
            return True
        self.sessoes.pop(token or "", None)
        return False

    def sair(self, token: str | None):
        self.sessoes.pop(token or "", None)


# ============================================================== indicadores
def _culto_da_permanencia(p) -> tuple[int, dt.datetime] | None:
    idx, rel, inicio = culto_de_referencia(dt.datetime.fromtimestamp(p["entrada"]))
    if -JANELA_ANTES_MIN <= rel <= JANELA_DEPOIS_MIN:
        return idx, inicio
    return None


def _ocupadas_em(perms, t) -> int:
    return sum(1 for p in perms if p["entrada"] <= t and (p["saida"] is None or p["saida"] > t))


def agrupar_por_culto(perms: list[dict], layout: Layout, agora: float) -> tuple[list[dict], int]:
    """Agrupo as permanências por culto. Devolvo (cultos, permanências fora de culto)."""
    grupos: dict[tuple, list] = {}
    fora = 0
    for p in perms:
        c = _culto_da_permanencia(p)
        if c is None:
            fora += 1
            continue
        grupos.setdefault((c[1], c[0]), []).append(p)

    n_vagas = len(layout.vagas)
    zona_de = {v.id: v.zona for v in layout.vagas}
    vagas_zona = {z: sum(1 for v in layout.vagas if v.zona == z) for z in layout.zonas()}
    cultos = []
    for (inicio, idx), ps in sorted(grupos.items()):
        t0 = inicio.timestamp()
        curva = []
        lotou = None
        for m in range(CURVA_DE, CURVA_ATE + 1, CURVA_PASSO):
            t = t0 + m * 60
            n = _ocupadas_em(ps, t) if t <= agora else None
            curva.append(None if n is None else round(100 * n / n_vagas, 1))
        # acho o instante exato em que lotou (varrendo as chegadas)
        for p in sorted(ps, key=lambda p: p["entrada"]):
            if _ocupadas_em(ps, p["entrada"]) >= n_vagas:
                lotou = (p["entrada"] - t0) / 60
                break
        lot_zona = {}
        for z, nz in vagas_zona.items():
            pz = [p for p in ps if zona_de.get(p["vaga"]) == z]
            lot_zona[z] = next(((p["entrada"] - t0) / 60 for p in sorted(pz, key=lambda p: p["entrada"])
                                if _ocupadas_em(pz, p["entrada"]) >= nz), None)
        cats = {}
        for p in ps:
            cats[p["categoria"] or "SEM IDENTIFICAÇÃO"] = cats.get(p["categoria"] or "SEM IDENTIFICAÇÃO", 0) + 1
        chegadas_rel = [(p["entrada"] - t0) / 60 for p in ps]
        cultos.append({
            "data": inicio.strftime("%Y-%m-%d"),
            "inicio": t0,
            "culto_idx": idx,
            "culto": NOMES_CULTO[idx],
            "carros": len(ps),
            "tempo_medio_s": statistics.mean(p["duracao_s"] for p in ps),
            "ocupacao_max_pct": max((c for c in curva if c is not None), default=0),
            "lotou_min": lotou,
            "lotou_zona_min": lot_zona,
            "fora_da_vaga": sum(p["origem"] == "desconhecida" for p in ps),
            "chegada_mediana_min": statistics.median(chegadas_rel),
            "categorias": cats,
            "curva": curva,
            "em_andamento": any(p["em_andamento"] for p in ps),
        })
    return cultos, fora


def visao_geral(perms: list[dict], layout: Layout, agora: float, dias: int) -> dict:
    cultos, fora = agrupar_por_culto(perms, layout, agora)
    n_perm = sum(c["carros"] for c in cultos)

    # curva média por tipo de culto
    curvas_tipo = {}
    for idx in range(len(NOMES_CULTO)):
        cs = [c["curva"] for c in cultos if c["culto_idx"] == idx]
        if not cs:
            continue
        media = []
        for i in range(len(cs[0])):
            vals = [c[i] for c in cs if c[i] is not None]
            media.append(round(statistics.mean(vals), 1) if vals else None)
        curvas_tipo[NOMES_CULTO[idx]] = {"curva": media, "n": len(cs)}

        # uso de cada vaga: fração do tempo em que ficou ocupada entre -30 e +120 min de cada culto
    uso = {v.id: 0.0 for v in layout.vagas}
    janela_total = 0.0
    for c in cultos:
        a, b = c["inicio"] - 30 * 60, min(c["inicio"] + 120 * 60, agora)
        if b <= a:
            continue
        janela_total += b - a
        for p in perms:
            if p["vaga"] not in uso:
                continue
            ini, fim = p["entrada"], p["saida"] if p["saida"] is not None else agora
            sobre = min(fim, b) - max(ini, a)
            if sobre > 0:
                uso[p["vaga"]] += sobre
    uso_pct = {v: (round(100 * s / janela_total, 1) if janela_total else 0) for v, s in uso.items()}

    cats = {}
    for c in cultos:
        for k, n in c["categorias"].items():
            cats[k] = cats.get(k, 0) + n

    zonas = layout.zonas()
    lot_zona_media = {}
    for z in zonas:
        vals = [c["lotou_zona_min"][z] for c in cultos if c["lotou_zona_min"].get(z) is not None]
        lot_zona_media[z] = {"cultos_que_lotou": len(vals), "minuto_medio": statistics.mean(vals) if vals else None}

    return {
        "dias": dias,
        "total_vagas": len(layout.vagas),
        "kpis": {
            "cultos": len(cultos),
            "carros_por_culto": (n_perm / len(cultos)) if cultos else 0,
            "tempo_medio_s": statistics.mean([c["tempo_medio_s"] for c in cultos]) if cultos else 0,
            "cultos_que_lotaram": sum(c["lotou_min"] is not None for c in cultos),
            "adesao_pct": round(100 * (1 - sum(c["fora_da_vaga"] for c in cultos) / n_perm), 1) if n_perm else None,
            "permanencias_fora_de_culto": fora,
        },
        "cultos": cultos,
        "curvas_tipo": curvas_tipo,
        "curva_minutos": list(range(CURVA_DE, CURVA_ATE + 1, CURVA_PASSO)),
        "uso_vagas_pct": uso_pct,
        "categorias": cats,
        "lotacao_corredores": lot_zona_media,
        "nomes_culto": NOMES_CULTO,
    }


def filtrar_por_culto(perms, culto_idx: int | None):
    if culto_idx is None:
        return perms
    out = []
    for p in perms:
        c = _culto_da_permanencia(p)
        if c and c[0] == culto_idx:
            out.append(p)
    return out


def horarios_legiveis():
    dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    return [f"{dias[d]} {h}" for d, h, _ in HORARIOS_CULTO]


def avisos_por_culto(eventos: list[dict], agora: float | None = None) -> dict:
    """
    Junto, por culto, o primeiro aviso de lotação e o momento em que o
    estacionamento lotou de fato, para medir se o aviso chegou a tempo.
    """
    import json as _json
    agora = agora or time.time()
    cultos: dict[float, dict] = {}
    for e in sorted(eventos, key=lambda e: e["instante"]):
        if e["tipo"] not in ("ALERTA_LOTACAO", "LOTOU") or not e.get("detalhe"):
            continue
        try:
            d = _json.loads(e["detalhe"])
        except ValueError:
            continue
        t0 = d.get("culto_inicio")
        if t0 is None:
            continue
        c = cultos.setdefault(t0, {"culto_inicio": t0, "aviso": None, "nivel_aviso": None, "previsto_min": None,
                                   "lotou": None, "niveis": []})
        if e["tipo"] == "LOTOU":
            c["lotou"] = c["lotou"] or e["instante"]
        else:
            c["niveis"].append(d.get("nivel"))
            if c["aviso"] is None and d.get("nivel") in ("atencao", "critico"):
                c["aviso"], c["nivel_aviso"], c["previsto_min"] = e["instante"], d.get("nivel"), d.get("minutos")

    lista = []
    for t0, c in sorted(cultos.items(), reverse=True):
        idx, _, _ = culto_de_referencia(dt.datetime.fromtimestamp(t0))
        ant = (c["lotou"] - c["aviso"]) / 60 if (c["lotou"] and c["aviso"] and c["aviso"] < c["lotou"]) else None
        if c["lotou"] and ant is not None:
            resultado = "avisou a tempo" if ant >= 5 else "avisou em cima da hora"
        elif c["lotou"]:
            resultado = "lotou sem aviso"
        elif c["aviso"] and agora > t0 + JANELA_DEPOIS_MIN * 60:
            resultado = "alarme falso"
        else:
            resultado = "aguardando"
        lista.append({
            "data": dt.datetime.fromtimestamp(t0).strftime("%Y-%m-%d"), "culto": NOMES_CULTO[idx], "culto_idx": idx,
            "aviso_rel_min": (c["aviso"] - t0) / 60 if c["aviso"] else None,
            "lotou_rel_min": (c["lotou"] - t0) / 60 if c["lotou"] else None,
            "previsto_min": c["previsto_min"], "antecedencia_min": ant, "resultado": resultado,
        })
    antecedencias = [x["antecedencia_min"] for x in lista if x["antecedencia_min"] is not None]
    return {
        "cultos": lista,
        "resumo": {
            "lotaram": sum(1 for x in lista if x["lotou_rel_min"] is not None),
            "avisados_a_tempo": sum(1 for x in lista if x["resultado"] == "avisou a tempo"),
            "sem_aviso": sum(1 for x in lista if x["resultado"] == "lotou sem aviso"),
            "alarmes_falsos": sum(1 for x in lista if x["resultado"] == "alarme falso"),
            "antecedencia_media_min": statistics.mean(antecedencias) if antecedencias else None,
        },
    }
