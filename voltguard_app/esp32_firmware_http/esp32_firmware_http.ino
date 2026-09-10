/*
 * esp32_firmware_http.ino — VoltGuard (Panificadora Shekinah)
 * ------------------------------------------------------------
 * Firmware de referência: ESP32 + ACS712 (corrente) + ZMPT101B (tensão)
 * + DHT22 (temperatura do quadro, opcional) + módulo RELÉ (proteção).
 *
 * Envia as leituras por HTTP POST para o VoltGuard (na rede local OU no
 * link público da nuvem) e usa a RESPOSTA do servidor para acionar o relé:
 *   { "status": "NORMAL", "rele": "desligado", ... }  ->  abre o relé
 *
 * Vantagem do HTTP: funciona direto com a URL pública (https://...) sem
 * precisar de broker. Se preferirem MQTT, veja esp32_firmware_mqtt/.
 *
 * Bibliotecas (Arduino IDE > Gerenciador de Bibliotecas):
 *   - ArduinoJson (Benoit Blanchon)
 *   - DHT sensor library (Adafruit) + Adafruit Unified Sensor  [se usar DHT22]
 *
 * SEGURANÇA: o ACS712 e o ZMPT101B isolam o ESP32 da rede. NUNCA ligue
 * 127/220 V em um pino do ESP32. O relé deve ser de potência compatível com
 * a carga (forno/geladeira -> use contator). Montagem na rede real só com
 * supervisão de pessoa habilitada (NR-10).
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ----------------------- CONFIGURAÇÃO -----------------------
const char* WIFI_SSID     = "NOME_DA_REDE";
const char* WIFI_PASSWORD = "SENHA_DA_REDE";

// Copie de "⚙ Configurações > Conexão do ESP32" no painel:
//   rede local : "http://10.101.29.99:5000/api/leitura"
//   nuvem      : "https://voltguard-shekinah.onrender.com/api/leitura"
const char* SERVER_URL = "https://SEU-APP.onrender.com/api/leitura";
const char* API_KEY    = "";                  // só se o app exigir X-Api-Key

const char* DISPOSITIVO_ID = "VG001";
const char* APARELHO       = "Forno elétrico"; // mesmo nome do cadastro no painel

const int PINO_ACS712   = 34;   // ADC — saída OUT do ACS712
const int PINO_ZMPT101B = 35;   // ADC — saída OUT do ZMPT101B
const int PINO_DHT22    = 4;    // DATA do DHT22 (deixe -1 se não tiver)
const int PINO_RELE     = 26;   // IN do módulo relé
const bool RELE_ATIVO_EM_LOW = true;  // maioria dos módulos liga com LOW

// Calibração — ajuste com o multímetro (ver README "Calibração")
const float SENSIBILIDADE_ACS712 = 0.100;  // V/A: 5A=0.185, 20A=0.100, 30A=0.066
const float ADC_REF_V   = 3.3;
const int   ADC_MAX     = 4095;
const int   AMOSTRAS    = 400;             // ~ alguns ciclos de 60 Hz
const float FATOR_ZMPT  = 250.0;           // multiplica o RMS lido -> volts da rede (calibrar!)
const unsigned long INTERVALO_MS = 3000;

DHT dht(PINO_DHT22, DHT22);
bool releLigado = true;

// --------------- leitura RMS de um sensor analógico ---------------
// Lê N amostras, remove o offset (média) e calcula o RMS — serve para o
// ACS712 (corrente AC) e para o ZMPT101B (tensão AC).
float lerRMS(int pino) {
  long soma = 0;
  int amostras[AMOSTRAS];
  for (int i = 0; i < AMOSTRAS; i++) { amostras[i] = analogRead(pino); soma += amostras[i]; delayMicroseconds(100); }
  float media = (float)soma / AMOSTRAS;
  double somaQuad = 0;
  for (int i = 0; i < AMOSTRAS; i++) { double d = amostras[i] - media; somaQuad += d * d; }
  float rmsADC = sqrt(somaQuad / AMOSTRAS);
  return rmsADC * ADC_REF_V / ADC_MAX;      // volts RMS na saída do sensor
}

float lerCorrente()  { return lerRMS(PINO_ACS712) / SENSIBILIDADE_ACS712; }
float lerTensao()    { return lerRMS(PINO_ZMPT101B) * FATOR_ZMPT; }

void acionarRele(bool ligar) {
  releLigado = ligar;
  digitalWrite(PINO_RELE, (ligar != RELE_ATIVO_EM_LOW) ? HIGH : LOW);
  Serial.printf("[RELE] %s\n", ligar ? "LIGADO" : "DESLIGADO (proteção)");
}

void conectarWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Conectando ao Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nConectado! IP: %s\n", WiFi.localIP().toString().c_str());
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(PINO_RELE, OUTPUT);
  acionarRele(true);
  if (PINO_DHT22 >= 0) dht.begin();
  conectarWiFi();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) conectarWiFi();

  float corrente = lerCorrente();
  float tensao   = lerTensao();
  float temp     = (PINO_DHT22 >= 0) ? dht.readTemperature() : NAN;

  StaticJsonDocument<256> doc;
  doc["dispositivo_id"] = DISPOSITIVO_ID;
  doc["aparelho"]       = APARELHO;
  doc["corrente"]       = round(corrente * 100) / 100.0;
  doc["tensao"]         = round(tensao * 10) / 10.0;
  if (!isnan(temp)) doc["temperatura"] = round(temp * 10) / 10.0;
  String corpo; serializeJson(doc, corpo);

  HTTPClient http;
  bool https = String(SERVER_URL).startsWith("https");
  WiFiClientSecure clienteSeguro; clienteSeguro.setInsecure();   // aceita o certificado da nuvem
  WiFiClient cliente;
  if (https) http.begin(clienteSeguro, SERVER_URL); else http.begin(cliente, SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  if (strlen(API_KEY)) http.addHeader("X-Api-Key", API_KEY);

  int codigo = http.POST(corpo);
  if (codigo == 201) {
    StaticJsonDocument<512> resp;
    if (deserializeJson(resp, http.getString()) == DeserializationError::Ok) {
      const char* status = resp["status"] | "?";
      const char* rele   = resp["rele"]   | "ligado";
      Serial.printf("%.2f A  %.1f V  %.1f C -> %s | rele=%s\n", corrente, tensao, temp, status, rele);
      bool deveLigar = (strcmp(rele, "desligado") != 0);
      if (deveLigar != releLigado) acionarRele(deveLigar);   // o servidor decide, o ESP32 executa
    }
  } else {
    Serial.printf("Falha HTTP %d ao enviar para %s\n", codigo, SERVER_URL);
  }
  http.end();
  delay(INTERVALO_MS);
}
