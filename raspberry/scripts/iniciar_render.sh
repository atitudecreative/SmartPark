#!/bin/bash
# Início do Smart Park no Render. O disco do plano gratuito é apagado a cada reinício,
# então começo de um banco de demonstração preparado no build (cadastro + histórico).
set -e
cd "$(dirname "$0")/.."
BANCO="smartpark/dados/smartpark.db"
LAYOUT=planta
MQTT=(--sem-mqtt)
if [ -n "$SMARTPARK_BROKER" ]; then
  # Integração com o ESP32 simulado no Wokwi: mesmo broker e prefixo do sketch, maquete de 6 vagas
  BANCO="smartpark/dados/wokwi.db"
  LAYOUT=maquete
  MQTT=(--broker "$SMARTPARK_BROKER" --prefixo "${SMARTPARK_PREFIXO:-smartpark-ibatitude}")
  [ -f "$BANCO" ] || python scripts/cadastrar.py demo --banco "$BANCO"
fi
if [ ! -f "$BANCO" ]; then
  if [ -f smartpark/dados/demo_base.db ]; then
    cp smartpark/dados/demo_base.db "$BANCO"        # banco de demonstração preparado no build
  else
    python scripts/cadastrar.py demo --banco "$BANCO"
  fi
fi
exec python -W ignore scripts/ponte_guarita.py "${MQTT[@]}" --layout "$LAYOUT" --banco "$BANCO" --porta-web "${PORT:-8080}"
