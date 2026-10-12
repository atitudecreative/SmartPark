"""
Cadastro de veículos. Na igreja quem faz é a secretaria, com o termo de consentimento assinado.

    python scripts/cadastrar.py add ABC1D23 IDOSO --apelido "Dona Maria"
    python scripts/cadastrar.py remover ABC1D23        # direito de eliminação (LGPD)
    python scripts/cadastrar.py listar
    python scripts/cadastrar.py demo                   # cadastra placas fictícias para eu testar
"""
import argparse
import random
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from smartpark.banco import Banco  # noqa: E402
from smartpark.lpr import normalizar_placa, placa_aleatoria  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("acao", choices=["add", "remover", "listar", "demo"])
ap.add_argument("placa", nargs="?")
ap.add_argument("categoria", nargs="?", choices=["MEMBRO", "IDOSO", "PCD", "EQUIPE"])
ap.add_argument("--apelido")
ap.add_argument("--banco", default=str(RAIZ / "smartpark" / "dados" / "smartpark.db"))
a = ap.parse_args()
b = Banco(a.banco)

if a.acao == "add":
    placa = normalizar_placa(a.placa or "")
    if not placa or not a.categoria:
        sys.exit("Placa inválida ou categoria ausente.")
    b.cadastrar(placa, a.categoria, a.apelido)
    print(f"Cadastrado: {placa} ({a.categoria})")
elif a.acao == "remover":
    b.remover(a.placa)
    print("Removido.")
elif a.acao == "listar":
    for row in b.con.execute("SELECT placa, categoria, apelido FROM veiculos ORDER BY categoria"):
        print(row[0], f"{row[1]:<7}", row[2] or "")
else:
    rng = random.Random(42)
    nomes = ["Dona Maria", "Seu João", "Pr. Carlos", "Ana", "Pedro", "Lúcia", "Marcos", "Rita"]
    cats = ["IDOSO", "IDOSO", "EQUIPE", "MEMBRO", "MEMBRO", "PCD", "MEMBRO", "MEMBRO"]
    for n, c in zip(nomes, cats):
        p = placa_aleatoria(rng)
        b.cadastrar(p, c, n)
        print(f"{p}  {c:<7} {n}")
