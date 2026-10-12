"""Troco a senha da área administrativa.

    python scripts/senha_admin.py            # pede a senha no terminal
"""
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from smartpark.admin import Autenticacao  # noqa: E402

arquivo = RAIZ / "smartpark" / "dados" / "admin_senha.txt"
s1 = getpass.getpass("Nova senha do admin (mínimo 4 caracteres): ")
s2 = getpass.getpass("Repita a senha: ")
if s1 != s2:
    sys.exit("As senhas não conferem.")
a = Autenticacao(arquivo)
try:
    a.definir(s1)
except ValueError as e:
    sys.exit(str(e))
print("Senha alterada. Reinicie o painel para encerrar as sessões abertas.")
