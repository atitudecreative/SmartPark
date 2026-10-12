/*
 * SMART PARK — Firmware do ESP32 (controle físico)
 * ------------------------------------------------------------------
 * Divisão de papéis que escolhi:  Raspberry Pi = processamento (placa, banco, IA)
 *                                 ESP32        = sensores e atuadores, em tempo real
 *
 *  Entradas
 *    - HC-SR04 na cancela  -> detecta veículo chegando
 *    - 6 sensores IR (um por vaga da maquete), saída digital ativa em LOW
 *  Saídas
 *    - Servo SG90 = cancela
 *    - 6 LEDs (aceso = ocupada, piscando = reservada para alguém a caminho)
 *    - OLED SSD1306 = painel local da guarita (vaga + seta)
 *  Comunicação (MQTT)
 *    publica  <PREFIXO>/entrada/presenca      "1"
 *             <PREFIXO>/vagas/<ID>            "OCUPADA" | "LIVRE"
 *             <PREFIXO>/esp32/status          "online"  (LWT "offline")
 *    assina   <PREFIXO>/cancela/cmd           "ABRIR"
 *             <PREFIXO>/guarita/painel        JSON {"vaga","seta","msg",...}
 *             <PREFIXO>/vagas/+/reserva       "1" | "0"
 *             <PREFIXO>/alertas/lotacao       JSON {"nivel","msg",...}  aviso antecipado de lotação
 *
 *  Modo degradado: se o MQTT cair, a cancela passa a abrir por presença e o OLED
 *  mostra "SISTEMA OFFLINE - SIGA A SINALIZACAO". Fiz assim para o estacionamento nunca travar.
 *
 *  Bibliotecas: PubSubClient, ESP32Servo, Adafruit SSD1306, Adafruit GFX, ArduinoJson
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// ======================= CONFIGURAÇÃO =======================
// Para simular no Wokwi: rede "Wokwi-GUEST" + broker público.
// Na maquete real: rede Wi-Fi do Raspberry Pi e o IP do Pi como broker; PREFIXO "smartpark".
#define WIFI_SSID   "Wokwi-GUEST"
#define WIFI_SENHA  ""
#define BROKER      "broker.hivemq.com"
#define BROKER_PORTA 1883
#define PREFIXO     "smartpark-ibatitude"

// ======================= PINAGEM ============================
const int PINO_TRIG = 5;
const int PINO_ECHO = 18;
const int PINO_SERVO = 13;
const int N_VAGAS = 6;
const char* VAGA_ID[N_VAGAS]   = {"A01", "A02", "A03", "B01", "B02", "B03"};
const int   VAGA_SENSOR[N_VAGAS] = {32, 33, 25, 26, 27, 14};
const int   VAGA_LED[N_VAGAS]    = {15, 2, 4, 16, 17, 19};

// ======================= PARÂMETROS =========================
const float DIST_DETECTA_CM = 15.0;   // maquete: carrinho a menos de 15 cm
const float DIST_LIVRE_CM   = 25.0;   // histerese para considerar que saiu
const int   LEITURAS_CONFIRMA = 3;    // leituras seguidas para confirmar presença
const unsigned long DEBOUNCE_MS = 300;
const unsigned long CANCELA_MAX_ABERTA_MS = 8000;
const int SERVO_FECHADA = 0, SERVO_ABERTA = 90;

// ======================= ESTADO =============================
WiFiClient wifi;
PubSubClient mqtt(wifi);
Servo cancela;
Adafruit_SSD1306 oled(128, 64, &Wire, -1);

bool vagaOcupada[N_VAGAS];
bool vagaLeituraAnterior[N_VAGAS];
unsigned long vagaMudouEm[N_VAGAS];
bool vagaReservada[N_VAGAS];

bool veiculoPresente = false;
int contagemPresenca = 0;
bool cancelaAberta = false;
unsigned long cancelaAbertaEm = 0;
bool veiculoPassou = false;

String telaVaga = "--", telaSeta = "", telaMsg = "Bem-vindo!";
String alertaMsg = "";            // aviso de lotação vindo do Raspberry Pi
unsigned long alertaEm = 0;

// ======================= SENSORES ===========================
float medirDistanciaCm() {
  digitalWrite(PINO_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PINO_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PINO_TRIG, LOW);
  unsigned long dur = pulseIn(PINO_ECHO, HIGH, 30000UL);  // timeout ~5 m
  if (dur == 0) return 999.0;
  return dur * 0.0343 / 2.0;  // velocidade do som 343 m/s, ida e volta
}

void publicar(const String& sub, const char* payload, bool reter) {
  if (mqtt.connected()) mqtt.publish((String(PREFIXO) + "/" + sub).c_str(), payload, reter);
}

void lerVagas() {
  unsigned long agora = millis();
  for (int i = 0; i < N_VAGAS; i++) {
    bool leitura = digitalRead(VAGA_SENSOR[i]) == LOW;  // LOW = obstáculo (carro)
    if (leitura != vagaLeituraAnterior[i]) {
      vagaLeituraAnterior[i] = leitura;
      vagaMudouEm[i] = agora;
    }
    // só aceito a mudança se ela ficar estável pelo tempo de debounce
    if (leitura != vagaOcupada[i] && agora - vagaMudouEm[i] > DEBOUNCE_MS) {
      vagaOcupada[i] = leitura;
      if (leitura) vagaReservada[i] = false;
      publicar(String("vagas/") + VAGA_ID[i], leitura ? "OCUPADA" : "LIVRE", true);
      Serial.printf("[vaga] %s -> %s\n", VAGA_ID[i], leitura ? "OCUPADA" : "LIVRE");
    }
  }
}

void atualizarLeds() {
  bool pisca = (millis() / 300) % 2;
  for (int i = 0; i < N_VAGAS; i++) {
    bool aceso = vagaOcupada[i] || (vagaReservada[i] && pisca);
    digitalWrite(VAGA_LED[i], aceso ? HIGH : LOW);
  }
}

// ======================= CANCELA ============================
void abrirCancela() {
  cancela.write(SERVO_ABERTA);
  cancelaAberta = true;
  cancelaAbertaEm = millis();
  veiculoPassou = false;
  Serial.println("[cancela] ABERTA");
}

void controlarCancela(float dist) {
  if (!cancelaAberta) return;
  if (dist > DIST_LIVRE_CM) veiculoPassou = true;
  bool tempoEsgotado = millis() - cancelaAbertaEm > CANCELA_MAX_ABERTA_MS;
  // segurança: a cancela nunca fecha com um carro embaixo
  if ((veiculoPassou || tempoEsgotado) && dist > DIST_LIVRE_CM) {
    delay(500);
    cancela.write(SERVO_FECHADA);
    cancelaAberta = false;
    Serial.println("[cancela] FECHADA");
  }
}

void verificarEntrada() {
  float dist = medirDistanciaCm();
  if (!veiculoPresente) {
    contagemPresenca = (dist < DIST_DETECTA_CM) ? contagemPresenca + 1 : 0;
    if (contagemPresenca >= LEITURAS_CONFIRMA) {
      veiculoPresente = true;
      Serial.printf("[entrada] veiculo detectado a %.1f cm\n", dist);
      if (mqtt.connected()) {
        publicar("entrada/presenca", "1", false);
        telaVaga = "...";
        telaSeta = "";
        telaMsg = "Lendo a placa...";
      } else {
        // modo degradado: o sistema central está fora do ar
        telaVaga = "--";
        telaSeta = "";
        telaMsg = "SISTEMA OFFLINE - SIGA A SINALIZACAO";
        abrirCancela();
      }
    }
  } else if (dist > DIST_LIVRE_CM) {
    veiculoPresente = false;
    contagemPresenca = 0;
  }
  controlarCancela(dist);
}

// ======================= OLED ===============================
void desenharSeta(const String& seta, int cx, int cy) {
  if (seta == "FRENTE") {
    oled.fillTriangle(cx, cy - 14, cx - 12, cy, cx + 12, cy, SSD1306_WHITE);
    oled.fillRect(cx - 5, cy, 10, 14, SSD1306_WHITE);
  } else if (seta == "DIREITA") {
    oled.fillTriangle(cx + 14, cy, cx, cy - 12, cx, cy + 12, SSD1306_WHITE);
    oled.fillRect(cx - 14, cy - 5, 14, 10, SSD1306_WHITE);
  } else if (seta == "ESQUERDA") {
    oled.fillTriangle(cx - 14, cy, cx, cy - 12, cx, cy + 12, SSD1306_WHITE);
    oled.fillRect(cx, cy - 5, 14, 10, SSD1306_WHITE);
  } else if (seta == "PARE") {
    oled.drawCircle(cx, cy, 13, SSD1306_WHITE);
    oled.drawLine(cx - 9, cy - 9, cx + 9, cy + 9, SSD1306_WHITE);
  }
}

void desenharTela() {
  static unsigned long ultimo = 0;
  if (millis() - ultimo < 150) return;
  ultimo = millis();
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(1);
  oled.setCursor(0, 0);
  oled.print("SMART PARK");
  oled.setCursor(84, 0);
  oled.print(mqtt.connected() ? "online" : "OFF");
  oled.setTextSize(3);
  oled.setCursor(0, 16);
  oled.print(telaVaga);
  desenharSeta(telaSeta, 108, 28);
  oled.setTextSize(1);
  oled.setCursor(0, 48);
  // o aviso de lotação tem prioridade por 2 min, alternando com a mensagem normal
  bool mostrarAlerta = alertaMsg.length() && millis() - alertaEm < 120000 && (millis() / 2000) % 2 == 0;
  if (mostrarAlerta) {
    oled.fillRect(0, 46, 128, 18, SSD1306_WHITE);
    oled.setTextColor(SSD1306_BLACK);
    oled.setCursor(2, 48);
    oled.print(alertaMsg.substring(0, 42));
    oled.setTextColor(SSD1306_WHITE);
  } else {
    oled.print(telaMsg.substring(0, 42));
  }
  oled.display();
}

// ======================= MQTT ===============================
void aoReceber(char* topico, byte* payload, unsigned int len) {
  String t(topico), p;
  for (unsigned int i = 0; i < len; i++) p += (char)payload[i];
  String base = String(PREFIXO) + "/";

  if (t == base + "cancela/cmd" && p == "ABRIR") {
    abrirCancela();
  } else if (t == base + "guarita/painel") {
    JsonDocument doc;
    if (deserializeJson(doc, p) == DeserializationError::Ok) {
      telaVaga = doc["vaga"] | "--";
      telaSeta = doc["seta"] | "";
      telaMsg = doc["msg"] | "";
    }
  } else if (t == base + "alertas/lotacao") {
    JsonDocument doc;
    if (deserializeJson(doc, p) == DeserializationError::Ok) {
      alertaMsg = doc["msg"] | "";
      alertaEm = millis();
      Serial.printf("[alerta] %s\n", alertaMsg.c_str());
    }
  } else if (t.startsWith(base + "vagas/") && t.endsWith("/reserva")) {
    String id = t.substring(base.length() + 6, t.length() - 8);
    for (int i = 0; i < N_VAGAS; i++)
      if (id == VAGA_ID[i]) vagaReservada[i] = (p == "1");
  }
}

void conectar() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_SENHA, 6);
    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 10000) delay(200);
    Serial.println(WiFi.status() == WL_CONNECTED ? "[wifi] conectado" : "[wifi] falhou");
  }
  if (WiFi.status() == WL_CONNECTED && !mqtt.connected()) {
    String id = "esp32-smartpark-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    String lwt = String(PREFIXO) + "/esp32/status";
    if (mqtt.connect(id.c_str(), lwt.c_str(), 1, true, "offline")) {
      mqtt.publish(lwt.c_str(), "online", true);
      mqtt.subscribe((String(PREFIXO) + "/cancela/cmd").c_str());
      mqtt.subscribe((String(PREFIXO) + "/guarita/painel").c_str());
      mqtt.subscribe((String(PREFIXO) + "/vagas/+/reserva").c_str());
      mqtt.subscribe((String(PREFIXO) + "/alertas/lotacao").c_str());
      // publico de novo o estado de todas as vagas (depois de reconectar)
      for (int i = 0; i < N_VAGAS; i++)
        publicar(String("vagas/") + VAGA_ID[i], vagaOcupada[i] ? "OCUPADA" : "LIVRE", true);
      Serial.println("[mqtt] conectado");
    }
  }
}

// ======================= SETUP / LOOP =======================
void setup() {
  Serial.begin(115200);
  pinMode(PINO_TRIG, OUTPUT);
  pinMode(PINO_ECHO, INPUT);
  for (int i = 0; i < N_VAGAS; i++) {
    pinMode(VAGA_SENSOR[i], INPUT_PULLUP);
    pinMode(VAGA_LED[i], OUTPUT);
    vagaOcupada[i] = vagaLeituraAnterior[i] = digitalRead(VAGA_SENSOR[i]) == LOW;
    vagaMudouEm[i] = 0;
    vagaReservada[i] = false;
  }
  cancela.attach(PINO_SERVO);
  cancela.write(SERVO_FECHADA);
  Wire.begin(21, 22);
  if (!oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) Serial.println("[oled] nao encontrado");
  mqtt.setServer(BROKER, BROKER_PORTA);
  mqtt.setCallback(aoReceber);
  mqtt.setBufferSize(512);
  conectar();
}

void loop() {
  static unsigned long ultimaConexao = 0, ultimaMedida = 0;
  if (!mqtt.connected() && millis() - ultimaConexao > 5000) {
    ultimaConexao = millis();
    conectar();
  }
  mqtt.loop();
  if (millis() - ultimaMedida >= 100) {  // 10 medições por segundo
    ultimaMedida = millis();
    verificarEntrada();
  }
  lerVagas();
  atualizarLeds();
  desenharTela();
}
