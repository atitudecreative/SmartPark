#!/bin/bash
# Smart Park — liga o sistema conversando com o ESP32 simulado no Wokwi (clique duplo no Mac).
# Antes, deixo a simulação rodando em wokwi.com com os arquivos de firmware/wokwi/.
clear; echo "==============================================="; echo "   SMART PARK · MODO WOKWI (ESP32 SIMULADO)"; echo "==============================================="
exec bash "$(cd "$(dirname "$0")" && pwd)/raspberry/scripts/iniciar_mac.sh" ambas --wokwi
