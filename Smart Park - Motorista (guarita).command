#!/bin/bash
# Smart Park — TELA DO MOTORISTA (tablet da guarita), clique duplo no Mac.
# A tela fica em espera e só mostra a vaga quando a câmera/sensor detecta o carro na cancela.
clear; echo "==============================================="; echo "   SMART PARK · TELA DO MOTORISTA (GUARITA)"; echo "==============================================="
exec bash "$(cd "$(dirname "$0")" && pwd)/raspberry/scripts/iniciar_mac.sh" guarita
