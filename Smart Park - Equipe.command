#!/bin/bash
# Smart Park — PAINEL DA EQUIPE do estacionamento (clique duplo no Mac).
# Abre o painel que a equipe usa: pátio inteiro, o carro que acabou de chegar, avisos de lotação, histórico e admin.
clear; echo "==============================================="; echo "   SMART PARK · PAINEL DA EQUIPE"; echo "==============================================="
exec bash "$(cd "$(dirname "$0")" && pwd)/raspberry/scripts/iniciar_mac.sh" equipe
