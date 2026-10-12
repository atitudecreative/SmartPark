"""
ESP32 virtual: publica no broker exatamente o que o firmware publicaria.
Uso para testar o Raspberry Pi sem o hardware (e sem o Wokwi).

    python scripts/simular_esp32.py --broker localhost --layout maquete

Comandos no terminal:
    c          -> carro chega à cancela (HC-SR04)
    o A01      -> vaga A01 ocupada (sensor IR)
    l A01      -> vaga A01 livre
    q          -> sair
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smartpark.barramento import BarramentoMQTT  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--broker", default="localhost")
ap.add_argument("--prefixo", default="smartpark")
a = ap.parse_args()
bus = BarramentoMQTT(a.broker, client_id="esp32-virtual")
bus.assinar(f"{a.prefixo}/cancela/cmd", lambda t, p: print(f"  [servo] cancela: {p}"))
bus.assinar(f"{a.prefixo}/guarita/painel", lambda t, p: print(f"  [OLED] {p}"))
bus.assinar(f"{a.prefixo}/vagas/+/reserva", lambda t, p: print(f"  [LED] {t.split('/')[-2]} reserva={p}"))
bus.assinar(f"{a.prefixo}/alertas/lotacao", lambda t, p: print(f"  [OLED] AVISO: {p}"))
bus.publicar(f"{a.prefixo}/esp32/status", "online")
print(__doc__)
for linha in sys.stdin:
    partes = linha.split()
    if not partes:
        continue
    if partes[0] == "q":
        break
    if partes[0] == "c":
        bus.publicar(f"{a.prefixo}/entrada/presenca", "1")
    elif partes[0] in ("o", "l") and len(partes) == 2:
        bus.publicar(f"{a.prefixo}/vagas/{partes[1].upper()}", "OCUPADA" if partes[0] == "o" else "LIVRE")
bus.fechar()
