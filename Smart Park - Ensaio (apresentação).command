#!/bin/bash
# Smart Park — MODO ENSAIO, que uso para apresentar fora do horário de culto.
# Ele finge que um culto começa daqui a 10 minutos e abre as DUAS telas lado a lado:
# no painel da equipe, "Simular chegada" faz a tela do motorista mostrar a vaga.
# Uso um banco separado (ensaio.db), zerado a cada vez, para não mexer no histórico real.
clear; echo "==============================================="; echo "   SMART PARK · MODO ENSAIO"; echo "==============================================="
exec bash "$(cd "$(dirname "$0")" && pwd)/raspberry/scripts/iniciar_mac.sh" ambas --ensaio
