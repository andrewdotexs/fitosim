// =====================================================================
//  esp32_soil_gateway.ino — Gateway ESP32 hardware-to-HTTP per fitosim
// =====================================================================
//
// Sketch principale del gateway ESP32. Orchestra i tre strati:
//
//   1. Modbus (modbus_layer.h): legge i sensori ATO 7-in-1 sul bus
//      RS485 attraverso il convertitore MAX485.
//
//   2. Cache (cache_layer.h): mantiene in RAM le ultime letture
//      di ogni canale con timestamp UTC sincronizzato via NTP.
//
//   3. HTTP server (http_server_layer.h): espone gli endpoint REST
//      che fitosim consuma via HttpJsonSoilSensor.
//
// Il setup() inizializza tutti i sottosistemi nell'ordine giusto
// (WiFi prima, NTP dopo, infine Modbus e HTTP). Il loop() esegue
// due cose alternate: serve le richieste HTTP pendenti (operazione
// rapida, sub-millisecondo nella maggior parte dei casi), e periodi-
// camente innesca un ciclo di polling Modbus che aggiorna la cache.
//
// Il polling è schedulato via `millis()` non via `delay()`: questo
// permette al server HTTP di restare reattivo anche durante un ciclo
// di polling che può durare diversi secondi (transazioni Modbus
// sequenziali su tutti i canali).
//
// HARDWARE RICHIESTO
// ------------------
//
//   - ESP32 originale (qualsiasi devkit con almeno 4MB flash)
//   - Convertitore MAX485 (TTL ↔ RS485)
//   - Cavo schermato a doppia coppia per il bus RS485
//   - Resistenze di terminazione 120 ohm alle due estremità del bus
//   - Sensori ATO 7-in-1 con indirizzi Modbus configurati univoci
//   - Alimentazione 12V per i sensori (USB 5V dell'ESP32 non basta)
//
// LIBRERIE ARDUINO RICHIESTE
// --------------------------
//
//   - WiFi (incluso nel core ESP32)
//   - WebServer (incluso nel core ESP32)
//   - ModbusMaster (di Doc Walker, da Library Manager)
//   - ArduinoJson (di Benoît Blanchon, da Library Manager, v6.x)
//
// PRIMA DELLA COMPILAZIONE
// ------------------------
//
//   1. Copia config.h.example in config.h e personalizza i valori.
//   2. Installa le librerie sopra elencate dal Library Manager di
//      Arduino IDE.
//   3. Seleziona la board "ESP32 Dev Module" e la porta seriale
//      corretta in Arduino IDE.
//   4. Compila e flasha.

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"
#include "modbus_layer.h"
#include "cache_layer.h"
#include "http_server_layer.h"

// Timestamp dell'ultimo polling Modbus completato. Usato per
// schedulare il prossimo polling tramite confronto con millis().
static unsigned long last_polling_ms = 0;

// =====================================================================
//  Setup: inizializzazione una tantum all'avvio
// =====================================================================

void connectWifi() {
  Serial.print("[WiFi] Connessione a ");
  Serial.print(WIFI_SSID);
  Serial.print(" ...");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Aspettiamo fino a 30 secondi la connessione. Se dopo questo
  // tempo non c'è ancora, riavviamo l'ESP32 — è la strategia più
  // semplice contro problemi temporanei del router (e funziona
  // sempre).
  uint32_t start_ms = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - start_ms > 30000UL) {
      Serial.println();
      Serial.println("[WiFi] Timeout. Riavvio dell'ESP32.");
      ESP.restart();
    }
  }

  Serial.println();
  Serial.print("[WiFi] Connesso. IP locale: ");
  Serial.println(WiFi.localIP());
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== fitosim ESP32 gateway ===");
  Serial.print("MAX_CHANNELS configurati: ");
  Serial.println(MAX_CHANNELS);

  // 1. WiFi: deve essere prima di tutto perché NTP, server HTTP
  //    e potenzialmente OTA dipendono dalla rete.
  connectWifi();

  // 2. Cache + NTP: la cache configura NTP internamente e aspetta
  //    qualche secondo che si sincronizzi. È importante che NTP sia
  //    sincronizzato prima delle prime letture Modbus, altrimenti
  //    i timestamp delle letture saranno errati.
  initCache();

  // 3. Modbus: configurazione del MAX485 e della libreria.
  initModbus();
  Serial.println("[Modbus] Bus RS485 inizializzato.");

  // 4. HTTP server: registra gli endpoint e mette in ascolto.
  initHttpServer();

  Serial.println("[Setup] Avvio completato. In attesa di richieste...");
  Serial.println();
}

// =====================================================================
//  Polling Modbus: itera attraverso i canali configurati
// =====================================================================

void runPollingCycle() {
  Serial.println("[Polling] Inizio ciclo di polling Modbus...");
  uint8_t successes = 0;
  uint8_t failures = 0;

  for (uint8_t i = 0; i < MAX_CHANNELS; i++) {
    uint8_t address = MODBUS_ADDRESSES[i];
    if (address == 0) continue;  // canale non configurato

    SensorReading reading;
    bool ok = readSensorChannel(address, &reading);
    if (ok) {
      updateCacheEntry(i, reading);
      successes++;
      Serial.print("[Polling]   Canale ");
      Serial.print(i + 1);
      Serial.print(" (Modbus addr ");
      Serial.print(address);
      Serial.print("): θ=");
      Serial.print(reading.theta_volumetric, 3);
      Serial.print(" T=");
      Serial.print(reading.temperature_c, 1);
      Serial.print("°C EC=");
      Serial.print(reading.ec_mscm, 2);
      Serial.print(" mS/cm pH=");
      Serial.println(reading.ph, 1);
    } else {
      failures++;
      Serial.print("[Polling]   Canale ");
      Serial.print(i + 1);
      Serial.print(" (Modbus addr ");
      Serial.print(address);
      Serial.println("): ERRORE comunicazione");
    }

    // Piccola pausa tra le letture sequenziali sul bus per evitare
    // collisioni ai limiti del timing Modbus.
    delay(50);
  }

  Serial.print("[Polling] Ciclo completato. Successi: ");
  Serial.print(successes);
  Serial.print(", errori: ");
  Serial.println(failures);
}

// =====================================================================
//  Loop principale
// =====================================================================

void loop() {
  // 1. Servi le richieste HTTP pendenti. Operazione non-bloccante:
  //    se non ci sono richieste in coda, ritorna immediatamente.
  handleHttpRequests();

  // 2. Verifica se è ora di un nuovo ciclo di polling Modbus.
  //    Usiamo millis() invece di delay() per non bloccare il server.
  //    Caso speciale: al primo avvio (last_polling_ms = 0) eseguiamo
  //    il polling immediatamente per popolare la cache prima che
  //    fitosim possa fare richieste.
  unsigned long now_ms = millis();
  bool first_run = (last_polling_ms == 0);
  bool interval_elapsed = (now_ms - last_polling_ms) >= POLLING_INTERVAL_MS;

  if (first_run || interval_elapsed) {
    runPollingCycle();
    last_polling_ms = now_ms;
  }

  // Piccolo delay per non saturare la CPU. Il server HTTP è comunque
  // gestito da un task separato dell'ESP32 quindi non c'è impatto
  // sulla latenza delle risposte.
  delay(10);
}
