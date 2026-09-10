/*
 * esp32_firmware_mqtt.ino — VoltGuard (Panificadora Shekinah)
 * ------------------------------------------------------------
 * Mesma leitura do firmware HTTP, mas usando MQTT (como no projeto):
 *   publica em  <prefixo>/sensores            (JSON com corrente/tensão/temperatura)
 *   assina      <prefixo>/comando             (JSON {"aparelho","comando"})
 *   e também    <prefixo>/comando/<aparelho>  ("ligar" / "desligar", retido)
 *
 * Broker: o Mosquitto do PC do laboratório (IP local) OU broker.hivemq.com
 * (público, funciona junto com o app na nuvem). Copie prefixo e broker de
 * "⚙ Configurações > Conexão do ESP32" no painel.
 *
 * Bibliotecas: PubSubClient (Nick O'Leary), ArduinoJson, DHT sensor library.
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

const char* WIFI_SSID     = "NOME_DA_REDE";
const char* WIFI_PASSWORD = "SENHA_DA_REDE";

const char* MQTT_BROKER   = "broker.hivemq.com";   // ou IP do PC com Mosquitto, ex: "10.101.29.99"
const int   MQTT_PORTA    = 1883;
const char* TOPICO_SENS   = "voltguard/shekinah-2026/sensores";
const char* TOPICO_CMD    = "voltguard/shekinah-2026/comando";
const char* TOPICO_CMD_AP = "voltguard/shekinah-2026/comando/forno-eletrico"; // slug do aparelho

const char* DISPOSITIVO_ID = "VG001";
const char* APARELHO       = "Forno elétrico";

const int PINO_ACS712 = 34, PINO_ZMPT101B = 35, PINO_DHT22 = 4, PINO_RELE = 26;
const bool RELE_ATIVO_EM_LOW = true;
const float SENSIBILIDADE_ACS712 = 0.100, ADC_REF_V = 3.3, FATOR_ZMPT = 250.0;
const int ADC_MAX = 4095, AMOSTRAS = 400;
const unsigned long INTERVALO_MS = 3000;

WiFiClient wifi;
PubSubClient mqtt(wifi);
DHT dht(PINO_DHT22, DHT22);
bool releLigado = true;
unsigned long ultimoEnvio = 0;

float lerRMS(int pino) {
  long soma = 0; int a[AMOSTRAS];
  for (int i = 0; i < AMOSTRAS; i++) { a[i] = analogRead(pino); soma += a[i]; delayMicroseconds(100); }
  float media = (float)soma / AMOSTRAS; double sq = 0;
  for (int i = 0; i < AMOSTRAS; i++) { double d = a[i] - media; sq += d * d; }
  return sqrt(sq / AMOSTRAS) * ADC_REF_V / ADC_MAX;
}

void acionarRele(bool ligar) {
  releLigado = ligar;
  digitalWrite(PINO_RELE, (ligar != RELE_ATIVO_EM_LOW) ? HIGH : LOW);
  Serial.printf("[RELE] %s\n", ligar ? "LIGADO" : "DESLIGADO");
}

// Chegou comando do app
void aoReceber(char* topico, byte* payload, unsigned int tam) {
  String msg; for (unsigned int i = 0; i < tam; i++) msg += (char)payload[i];
  if (String(topico) == TOPICO_CMD_AP) {            // "ligar" / "desligar"
    acionarRele(msg != "desligar");
    return;
  }
  StaticJsonDocument<256> doc;                       // JSON geral: confere se é para este aparelho
  if (deserializeJson(doc, msg) == DeserializationError::Ok && String((const char*)doc["aparelho"]) == APARELHO) {
    acionarRele(String((const char*)doc["comando"]) != "desligar");
  }
}

void conectarMQTT() {
  while (!mqtt.connected()) {
    String id = String("voltguard-esp32-") + DISPOSITIVO_ID;
    if (mqtt.connect(id.c_str())) {
      mqtt.subscribe(TOPICO_CMD); mqtt.subscribe(TOPICO_CMD_AP);
      Serial.println("MQTT conectado");
    } else { Serial.printf("MQTT falhou (%d), tentando de novo...\n", mqtt.state()); delay(2000); }
  }
}

void setup() {
  Serial.begin(115200); analogReadResolution(12);
  pinMode(PINO_RELE, OUTPUT); acionarRele(true);
  if (PINO_DHT22 >= 0) dht.begin();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nWi-Fi ok: %s\n", WiFi.localIP().toString().c_str());
  mqtt.setServer(MQTT_BROKER, MQTT_PORTA);
  mqtt.setCallback(aoReceber);
}

void loop() {
  if (!mqtt.connected()) conectarMQTT();
  mqtt.loop();
  if (millis() - ultimoEnvio < INTERVALO_MS) return;
  ultimoEnvio = millis();

  float corrente = lerRMS(PINO_ACS712) / SENSIBILIDADE_ACS712;
  float tensao   = lerRMS(PINO_ZMPT101B) * FATOR_ZMPT;
  float temp     = (PINO_DHT22 >= 0) ? dht.readTemperature() : NAN;

  StaticJsonDocument<256> doc;
  doc["dispositivo_id"] = DISPOSITIVO_ID; doc["aparelho"] = APARELHO;
  doc["corrente"] = round(corrente * 100) / 100.0; doc["tensao"] = round(tensao * 10) / 10.0;
  if (!isnan(temp)) doc["temperatura"] = round(temp * 10) / 10.0;
  char corpo[256]; serializeJson(doc, corpo);
  mqtt.publish(TOPICO_SENS, corpo);
  Serial.printf("%.2f A  %.1f V  %.1f C  rele=%s -> %s\n", corrente, tensao, temp, releLigado ? "on" : "off", TOPICO_SENS);
}
