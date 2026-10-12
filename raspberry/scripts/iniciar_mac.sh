#!/bin/bash
# Smart Park — rotina que os atalhos do Mac usam (escrevi uma vez só para os três).
# Uso: iniciar_mac.sh <tela> [--ensaio | --wokwi]
#   tela = equipe   -> painel da equipe do estacionamento (http://localhost:8080/equipe)
#   tela = guarita  -> tablet do motorista na cancela    (http://localhost:8080/guarita)
#   tela = ambas    -> abre as duas
#   --wokwi -> conversa com o ESP32 simulado no Wokwi pelo broker público (maquete de 6 vagas)
# Se o sistema já estiver rodando (aberto por outro atalho), só abre a tela pedida.

TELA="${1:-equipe}"
ENSAIO="$2"
RASP="$(cd "$(dirname "$0")/.." && pwd)"          # pasta raspberry/
cd "$RASP" || exit 1
URL="http://localhost:8080"

abrir_equipe()  { open "$URL/equipe"; }
abrir_guarita() {
  # Em janela própria, sem barra de endereço, quando o Chrome existe (parece um app de tablet).
  if [ -d "/Applications/Google Chrome.app" ]; then
    open -na "Google Chrome" --args --app="$URL/guarita" --window-size=1180,820
  else
    open "$URL/guarita"
  fi
}
abrir_telas() {
  case "$TELA" in
    guarita) abrir_guarita ;;
    ambas)   abrir_equipe; sleep 1; abrir_guarita ;;
    *)       abrir_equipe ;;
  esac
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "O Python 3 não está instalado. Instale em https://www.python.org/downloads/ e abra o atalho de novo."
  open "https://www.python.org/downloads/"
  read -n1 -p "Pressione uma tecla para fechar"; exit 1
fi

# Já está rodando? Então só abre a tela.
if lsof -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  if [ -n "$ENSAIO" ]; then
    echo "O Smart Park já está aberto. Feche a janela do Terminal dele e abra este atalho de novo."
    read -n1 -p "Pressione uma tecla para fechar"; exit 1
  fi
  abrir_telas
  echo "O Smart Park já estava rodando: abri a tela pedida. Pode fechar esta janela."
  exit 0
fi

if [ ! -x ".venv/bin/python" ]; then
  echo ""
  echo "Primeira execução: preparando o ambiente (só desta vez, 1 a 3 minutos)..."
  python3 -m venv .venv || { read -n1 -p "Falha ao criar o ambiente. Pressione uma tecla"; exit 1; }
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt || { read -n1 -p "Falha ao instalar as bibliotecas. Verifique a internet e pressione uma tecla"; exit 1; }
  echo "Treinando o modelo de previsão..."
  .venv/bin/python -W ignore -m simulador.treinar_preditor
fi

LAYOUT=planta
MQTT=(--sem-mqtt)
if [ "$ENSAIO" = "--wokwi" ]; then
  # Mesmo broker e prefixo definidos no sketch do Wokwi (BROKER e PREFIXO).
  BANCO="smartpark/dados/wokwi.db"
  [ -f "$BANCO" ] || .venv/bin/python scripts/cadastrar.py demo --banco "$BANCO" >/dev/null
  LAYOUT=maquete
  MQTT=(--broker broker.hivemq.com --prefixo smartpark-ibatitude)
  EXTRA=(--banco "$BANCO")
  echo "Modo Wokwi: deixe a simulação do ESP32 rodando no navegador."
  echo "No Wokwi, clique no HC-SR04 e coloque a distância abaixo de 15 cm para simular um carro chegando."
elif [ -n "$ENSAIO" ]; then
  BANCO="smartpark/dados/ensaio.db"
  : > "$BANCO"   # o ensaio usa um banco separado, zerado a cada vez
  .venv/bin/python scripts/cadastrar.py demo --banco "$BANCO" >/dev/null
  EXTRA=(--banco "$BANCO" --ensaio 10)
  echo "Culto de ensaio começa em 10 minutos."
else
  if [ ! -f "smartpark/dados/smartpark.db" ]; then
    echo "Cadastrando placas fictícias e cultos de demonstração..."
    .venv/bin/python scripts/cadastrar.py demo
    .venv/bin/python scripts/gerar_historico_demo.py --layout planta
  fi
  EXTRA=()
fi

echo ""
echo "Painel da equipe:   $URL/equipe      (Admin: $URL/admin)"
echo "Tela do motorista:  $URL/guarita"
echo "App do corredor:    $URL/corredor   (no celular de cada funcionário de corredor)"
echo "No tablet e nos celulares (mesma rede Wi-Fi), use o IP deste Mac no lugar de 'localhost':"
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"
[ -n "$IP" ] && echo "   tablet: http://$IP:8080/guarita     celulares dos corredores: http://$IP:8080/corredor"
echo ""
echo "Para encerrar, feche esta janela ou pressione Ctrl+C."
echo ""
( sleep 2; abrir_telas ) &
exec .venv/bin/python -W ignore scripts/ponte_guarita.py "${MQTT[@]}" --layout "$LAYOUT" "${EXTRA[@]}"
