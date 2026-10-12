"""
Preencho o banco com um histórico FICTÍCIO dos cultos dos últimos 30 dias, para
conseguir demonstrar o histórico e a área administrativa sem esperar cultos reais.

    python scripts/gerar_historico_demo.py                 # layout da maquete
    python scripts/gerar_historico_demo.py --layout igreja

O padrão de chegada de cada culto segue os perfis de simulador/chegadas.py.
Todas as placas são sorteadas e não pertencem a ninguém.
"""
import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from smartpark.banco import Banco  # noqa: E402
from smartpark.controlador import HORARIOS_CULTO  # noqa: E402
from smartpark.layout import LAYOUTS  # noqa: E402
from smartpark.lpr import placa_aleatoria  # noqa: E402
from simulador.chegadas import CULTOS  # noqa: E402

# quanto do estacionamento cada culto costuma encher (fração das vagas, antes de sobrar gente sem vaga)
DEMANDA = {0: 0.95, 1: 1.15, 2: 0.70, 3: 0.85}

ap = argparse.ArgumentParser()
ap.add_argument("--layout", choices=list(LAYOUTS), default="maquete")
ap.add_argument("--dias", type=int, default=30)
ap.add_argument("--banco", default=str(RAIZ / "smartpark" / "dados" / "smartpark.db"))
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--sem-falhas", action="store_true", help="não simular sensores com defeito")
a = ap.parse_args()

rng = random.Random(a.seed)
layout = LAYOUTS[a.layout]()
banco = Banco(a.banco)
vagas_pref = [v for v in layout.vagas if v.tipo != "comum"]
vagas_comuns = [v for v in layout.vagas if v.tipo == "comum"]

# frota fictícia, parte cadastrada
frota = []
for _ in range(max(30, len(layout.vagas) * 3)):
    cat = rng.choices(["MEMBRO", "IDOSO", "PCD", "EQUIPE", "VISITANTE"], [60, 13, 3, 9, 15])[0]
    p = placa_aleatoria(rng)
    if cat != "VISITANTE":
        banco.cadastrar(p, cat)
    frota.append((p, cat))

agora = dt.datetime.now()
ocorrencias = []
for d in range(a.dias, -1, -1):
    dia = (agora - dt.timedelta(days=d)).date()
    for wd, hhmm, idx in HORARIOS_CULTO:
        if dia.weekday() == wd:
            h, m = map(int, hhmm.split(":"))
            ini = dt.datetime.combine(dia, dt.time(h, m))
            if ini + dt.timedelta(hours=2, minutes=30) < agora:
                ocorrencias.append((ini, idx))

total = 0
for ini, idx in ocorrencias:
    perfil = CULTOS[idx]
    t0 = ini.timestamp()
    deslocamento = rng.gauss(0, 3)
    n = max(1, round(len(layout.vagas) * DEMANDA[idx] * rng.lognormvariate(0, 0.12)))
    carros = rng.sample(frota, k=min(n, len(frota)))
    chegadas = []
    for placa, cat in carros:
        if cat == "EQUIPE":
            t = rng.gauss(-40, 5)
        elif rng.random() < perfil.frac_atrasados:
            t = rng.uniform(0, 15)
        else:
            t = rng.gauss(perfil.pico_min + deslocamento, perfil.dispersao_min)
        chegadas.append((t, placa, cat))
    chegadas.sort()
    livres_pref, livres_com = vagas_pref[:], vagas_comuns[:]
    entradas_culto = []
    # o sistema enche primeiro o corredor mais perto da porta (A), depois B, C...
    livres_com.sort(key=lambda v: (v.zona, rng.random()))
    for t, placa, cat in chegadas:
        if cat in ("IDOSO", "PCD") and livres_pref:
            vaga = livres_pref.pop(0)
        elif livres_com:
            vaga = livres_com.pop(0) if cat != "EQUIPE" else livres_com.pop()
        else:
            continue                                    # chegou e não havia vaga
        entrada = t0 + 60 * (t + rng.uniform(0.5, 1.5))  # cancela + deslocamento até a vaga
        saida = t0 + 60 * rng.uniform(100, 135)
        fora = rng.random() < 0.08
        placa_reg = None if (fora or cat == "VISITANTE") else placa
        banco.abrir_permanencia(vaga.id, entrada, placa_reg, None if fora else cat, atribuida=not fora)
        banco.fechar_permanencia(vaga.id, saida)
        banco.registrar("ENTRADA", placa=placa_reg, categoria=cat, instante=t0 + 60 * t)
        entradas_culto.append(entrada)
        total += 1

    # avisos de lotação e lotação real (do jeito que o controlador registraria)
    entradas_culto.sort()
    lotou = entradas_culto[len(layout.vagas) - 1] if len(entradas_culto) >= len(layout.vagas) else None
    def alerta(instante, nivel, minutos):
        msg = ("Estacionamento deve lotar em ~{} min" if nivel == "atencao" else "Estacionamento lota em ~{} min").format(max(1, round(minutos)))
        banco.registrar("ALERTA_LOTACAO", instante=instante, detalhe=json.dumps(
            {"nivel": nivel, "minutos": round(minutos, 1), "livres": 0, "culto_inicio": t0,
             "rel_min": round((instante - t0) / 60, 1), "msg": msg}, ensure_ascii=False))
    sorteio = rng.random()
    if lotou:
        if sorteio < 0.72:                                   # avisou a tempo
            antes = rng.uniform(7, 16)
            alerta(lotou - antes * 60, "atencao", antes * rng.uniform(0.75, 1.25))
            critico = rng.uniform(2, 5)
            alerta(lotou - critico * 60, "critico", critico * rng.uniform(0.7, 1.3))
        elif sorteio < 0.86:                                 # avisou em cima da hora
            antes = rng.uniform(1.5, 4)
            alerta(lotou - antes * 60, "critico", antes)
        banco.registrar("LOTOU", instante=lotou, detalhe=json.dumps({"culto_inicio": t0, "rel_min": round((lotou - t0) / 60, 1)}))
    elif sorteio < 0.15:                                     # alarme falso
        alerta(t0 - rng.uniform(8, 14) * 60, "atencao", rng.uniform(9, 14))
    print(f"{ini:%d/%m/%Y %H:%M}  {perfil.nome:<24} ✓")

if not a.sem_falhas and len(layout.vagas) >= 6:
    # sensor oscilando (mau contato): 9 trocas em 5 min, ontem à noite
    vaga_osc = layout.vagas[2].id
    base = (agora - dt.timedelta(hours=20)).timestamp()
    for i in range(9):
        banco.registrar("VAGA_OCUPADA" if i % 2 == 0 else "VAGA_LIVRE", vaga=vaga_osc, instante=base + i * 33)
    # sensor sensível demais: ocupações de segundos fora de horário de culto
    vaga_curta = layout.vagas[-1].id
    for d in (3, 6, 9, 11):
        t = (agora - dt.timedelta(days=d)).replace(hour=14, minute=rng.randint(0, 50)).timestamp()
        banco.abrir_permanencia(vaga_curta, t, None, None, atribuida=False)
        banco.fechar_permanencia(vaga_curta, t + rng.uniform(4, 25))
    print(f"Sensores com defeito simulado: {vaga_osc} (oscilando) e {vaga_curta} (leituras curtas)")

# histórico de visitantes (só o código pseudônimo e os dias, como o sistema real guarda):
# a maioria vem uma vez e alguns voltam. Deixo alguns com 2 visitas para demonstrar
# da 3ª visita ("Simular 3ª visita" no painel ao vivo).
dias_culto = sorted({ini.date().isoformat() for ini, _ in ocorrencias if ini.date() < agora.date()})
placas_visitantes = [p for p, c in frota if c == "VISITANTE"]
if dias_culto and placas_visitantes:
    for i, placa in enumerate(placas_visitantes):
        k = 2 if i < 6 else rng.choices([1, 2, 3, 4, 5], [62, 20, 9, 5, 4])[0]
        for dia in rng.sample(dias_culto, k=min(k, len(dias_culto))):
            banco.registrar_visita(placa, dia)
    # algumas ofertas já feitas pelos corredores
    for placa in placas_visitantes[6:]:
        h = banco.con.execute("SELECT visitas FROM visitantes_hist WHERE id=?", (banco.id_visitante(placa),)).fetchone()
        if h and h[0] >= 3 and rng.random() < 0.5:
            resultado = "aceitou" if rng.random() < 0.15 else "recusou"
            banco.registrar_oferta(placa, resultado, agora.timestamp() - rng.uniform(1, 20) * 86400)
    # placas fictícias dos visitantes, só para o botão de demonstração (isso não existe no sistema real)
    Path(a.banco).with_name("visitantes_demo.json").write_text(json.dumps(placas_visitantes))
    print(f"Histórico de {len(placas_visitantes)} visitantes fictícios (6 deles com 2 visitas, prontos para a 3ª)")

banco.anonimizar_antigos()
print(f"{total} permanências fictícias em {len(ocorrencias)} cultos gravadas em {a.banco}")
