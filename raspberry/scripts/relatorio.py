"""
Relatório de permanência: quais carros estiveram em quais vagas e por quanto tempo.

    python scripts/relatorio.py                       # hoje
    python scripts/relatorio.py --dia 2026-11-08      # um dia específico
    python scripts/relatorio.py --placa ABC1D23       # histórico de uma placa (últimos 30 dias)
    python scripts/relatorio.py --vaga B04            # quem usou a vaga B04 hoje
    python scripts/relatorio.py --dia 2026-11-08 --csv culto.csv   # exporta para planilha

As placas ficam disponíveis por 30 dias (LGPD). Depois disso o relatório
continua mostrando vagas, horários e tempos, mas sem identificar o carro.
"""
import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from smartpark.banco import Banco  # noqa: E402
from smartpark.layout import LAYOUTS  # noqa: E402
from smartpark.relatorio import resumo, texto, fmt_hora  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--dia", help="AAAA-MM-DD (padrão: hoje)")
ap.add_argument("--placa")
ap.add_argument("--vaga")
ap.add_argument("--csv", help="salvar as permanências neste arquivo CSV")
ap.add_argument("--layout", choices=list(LAYOUTS), default="maquete")
ap.add_argument("--banco", default=str(RAIZ / "smartpark" / "dados" / "smartpark.db"))
a = ap.parse_args()

banco = Banco(a.banco)
layout = LAYOUTS[a.layout]()
agora = time.time()

if a.placa and not a.dia:
    desde, ate = agora - 30 * 86400, None
    titulo = f"Histórico da placa {a.placa.upper()} (últimos 30 dias)"
else:
    dia = dt.date.fromisoformat(a.dia) if a.dia else dt.date.today()
    desde = dt.datetime.combine(dia, dt.time()).timestamp()
    ate = desde + 86400
    titulo = f"Permanências de {dia.strftime('%d/%m/%Y')}" + (f" · vaga {a.vaga.upper()}" if a.vaga else "") \
        + (f" · placa {a.placa.upper()}" if a.placa else "")

perms = banco.permanencias(desde, ate, placa=a.placa, vaga=a.vaga, agora=agora)
if not perms:
    print(f"{titulo}\n\nNenhum registro encontrado.")
    sys.exit(0)
print(texto(perms, resumo(perms, layout, agora), titulo))

if a.csv:
    with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: abre certo no Excel
        w = csv.writer(f, delimiter=";")
        w.writerow(["data", "vaga", "placa", "categoria", "chegou", "saiu", "minutos", "origem"])
        for p in perms:
            w.writerow([dt.datetime.fromtimestamp(p["entrada"]).strftime("%d/%m/%Y"), p["vaga"], p["placa"] or "",
                        p["categoria"] or "", fmt_hora(p["entrada"]), fmt_hora(p["saida"]) if p["saida"] else "",
                        f"{p['duracao_s'] / 60:.1f}".replace(".", ","), p["origem"]])
    print(f"\nCSV salvo em {a.csv}")
