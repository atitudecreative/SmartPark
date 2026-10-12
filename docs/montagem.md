# Como monto a maquete e o Raspberry Pi

## Ligações do ESP32

| Componente | Pino do componente | ESP32 | Observação |
|---|---|---|---|
| HC-SR04 (cancela) | VCC / GND | VIN (5 V) / GND | |
| | TRIG | GPIO 5 | |
| | ECHO | GPIO 18 | **uso divisor de tensão** (1 kΩ + 2 kΩ): o ECHO sai em 5 V e o ESP32 só aceita 3,3 V |
| Servo SG90 (cancela) | V+ / GND / sinal | VIN / GND / GPIO 13 | se o servo travar o ESP32, alimento por uma fonte 5 V externa |
| OLED SSD1306 128×64 | VCC / GND / SDA / SCL | 3V3 / GND / GPIO 21 / GPIO 22 | endereço I²C 0x3C |
| Sensor IR vaga A01…A03 | OUT | GPIO 32, 33, 25 | saída LOW quando há obstáculo |
| Sensor IR vaga B01…B03 | OUT | GPIO 26, 27, 14 | |
| LED vaga A01…A03 | anodo (via 220 Ω) | GPIO 15, 2, 4 | aceso = ocupada, piscando = reservada |
| LED vaga B01…B03 | anodo (via 220 Ω) | GPIO 16, 17, 19 | |

Ajusto a sensibilidade de cada sensor IR (trimpot azul) com um carrinho parado na vaga. No firmware, `DIST_DETECTA_CM` define a distância de detecção na cancela (15 cm na maquete).

## Maquete

- Base de MDF 3 mm, uns 60 × 40 cm, na escala 1:43 (carrinhos de 10 cm).
- Uma via principal, dois corredores (A e B) com 3 vagas cada e uma via de fundo ligando os corredores. A geometria é a mesma de `layout_maquete()` em `raspberry/smartpark/layout.py`.
- A vaga A01 é preferencial (PcD): pinto de azul.
- Faço furos de 3 mm sob cada vaga para o sensor IR apontar para cima (ou coloco o sensor na lateral da vaga).
- A câmera fica acima da cancela, a uns 15 cm, apontada para a frente do carrinho. Imprimo placas Mercosul em papel (fonte FE-Schrift ou parecida) e colo nos carrinhos.

## Raspberry Pi 5

```bash
sudo apt update && sudo apt install -y mosquitto mosquitto-clients python3-venv tesseract-ocr
# broker acessível na rede local (maquete)
echo -e "listener 1883\nallow_anonymous true" | sudo tee /etc/mosquitto/conf.d/smartpark.conf
sudo systemctl restart mosquitto

python3 -m venv ~/smartpark-venv && source ~/smartpark-venv/bin/activate
cd smartpark/raspberry
pip install -r requirements.txt opencv-python pytesseract
python -m simulador.treinar_preditor
python scripts/cadastrar.py demo
python scripts/ponte_guarita.py --broker localhost --camera 0 --layout maquete
```

No firmware, troco `WIFI_SSID`, `WIFI_SENHA`, `BROKER` (IP do Pi) e `PREFIXO` (`"smartpark"`).

Tablet da guarita (motorista), em modo quiosque: abro `http://<IP do Pi>:8080/guarita` e toco na tela para ocupar a tela inteira. Com um monitor HDMI no próprio Pi: `chromium-browser --kiosk http://localhost:8080/guarita`.

Painel da equipe (computador da recepção): `http://<IP do Pi>:8080/equipe`. Celulares dos funcionários de corredor: `http://<IP do Pi>:8080/corredor`.

Para testar o broker rapidamente: `mosquitto_sub -t 'smartpark/#' -v` num terminal, e chego com um carrinho na cancela.

## Meu checklist para a defesa

- [ ] Rodar `python -m pytest -q` na véspera
- [ ] Bateria/fonte do Pi e do ESP32 separadas; levar fonte reserva
- [ ] Roteador próprio (não depender do Wi-Fi da faculdade)
- [ ] Simulador visual aberto numa aba, como plano B se o hardware falhar
- [ ] Mostrar o modo degradado: desligar o Pi e chegar com um carro (a cancela abre e o OLED avisa)
- [ ] Mostrar um idoso cadastrado recebendo vaga preferencial e um visitante recebendo vaga comum
- [ ] Mostrar um visitante tocando "Pessoa com deficiência" no tablet e recebendo a vaga PcD na hora
- [ ] Mostrar o app do corredor recebendo o carro e o aviso de 3ª visita ("Simular 3ª visita")
