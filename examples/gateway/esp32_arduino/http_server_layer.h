// =====================================================================
//  http_server_layer.h — Server HTTP che espone gli endpoint REST
// =====================================================================
//
// Questo strato è la facciata del gateway verso fitosim. Espone gli
// endpoint REST che fitosim consuma via HttpJsonSoilSensor, costruisce
// il JSON conforme allo schema V1, e gestisce l'autenticazione
// opzionale via bearer token.
//
// Endpoint esposti
// ----------------
//
// `GET /api/soil/{channel_id}` → ritorna il JSON V1 del canale
//
// `channel_id` è un intero da 1 a MAX_CHANNELS che identifica lo
// slot della cache (NON l'indirizzo Modbus del sensore: la mappa
// channel_id ↔ indirizzo Modbus è configurata in MODBUS_ADDRESSES
// di config.h).
//
// Il server risponde con i seguenti codici HTTP:
//
//   200 OK + JSON V1: lettura disponibile dalla cache.
//   401 Unauthorized: bearer token mancante o sbagliato (se
//                     HTTP_BEARER_TOKEN è valorizzato in config.h).
//   404 Not Found: channel_id fuori range o mai popolato.
//   503 Service Unavailable: il polling Modbus non è ancora riuscito
//                             a leggere alcun sensore (avvio fresco).
//
// I codici 401 e 404 sono interpretati da fitosim come errori
// permanenti (richiedono intervento), 503 come errore temporaneo
// (recuperabile aspettando), tutto in linea con la mappatura della
// gerarchia di eccezioni della tappa 1 di fitosim.

#ifndef HTTP_SERVER_LAYER_H
#define HTTP_SERVER_LAYER_H

#include <Arduino.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include "config.h"
#include "cache_layer.h"

// Istanza globale del server HTTP. Una sola per il gateway.
extern WebServer http_server;

// Inizializza il server e registra gli handler degli endpoint.
// Va chiamata una sola volta nel setup() di Arduino, dopo che il WiFi
// è già connesso.
void initHttpServer();

// Da chiamare nel loop() di Arduino per servire le richieste pendenti.
void handleHttpRequests();

// =====================================================================
//  Implementazione
// =====================================================================

WebServer http_server(HTTP_PORT);

// Verifica l'header Authorization della richiesta corrente. Ritorna
// true se l'autenticazione passa o se è disabilitata (token vuoto in
// config.h), false altrimenti.
static bool checkAuthorization() {
  // Se il token è vuoto in config, l'auth è disabilitata: accetta
  // tutto. È il caso d'uso "LAN affidabile, niente autenticazione".
  if (strlen(HTTP_BEARER_TOKEN) == 0) {
    return true;
  }

  // Auth abilitata: cerchiamo l'header Authorization e verifichiamo
  // che inizi con "Bearer " seguito dal token configurato.
  String auth_header = http_server.header("Authorization");
  String expected = String("Bearer ") + HTTP_BEARER_TOKEN;
  return auth_header.equals(expected);
}

// Estrae il channel_id dall'URL /api/soil/{channel_id}. Ritorna -1
// se l'URL non rispetta il formato atteso o se il channel_id non è
// un intero valido.
static int extractChannelId(const String& uri) {
  // L'URL è del tipo "/api/soil/N". Cerchiamo l'ultimo "/" e
  // parsiamo quello che viene dopo come intero.
  int last_slash = uri.lastIndexOf('/');
  if (last_slash < 0) return -1;
  String id_str = uri.substring(last_slash + 1);
  if (id_str.length() == 0) return -1;
  // Parse difensivo: se non è un intero valido toInt() ritorna 0,
  // ma noi vogliamo distinguere "0 esplicito" (errore: channel_id
  // parte da 1) da "non un intero". Verifichiamo che tutti i
  // caratteri siano cifre.
  for (size_t i = 0; i < id_str.length(); i++) {
    if (!isDigit(id_str[i])) return -1;
  }
  return id_str.toInt();
}

// Handler dell'endpoint /api/soil/{channel_id}. Costruisce il JSON
// V1 di fitosim con i dati dalla cache.
static void handleSoilEndpoint() {
  if (!checkAuthorization()) {
    http_server.send(
      401,
      "application/json",
      "{\"error\":\"Unauthorized: bearer token mancante o errato\"}"
    );
    return;
  }

  int channel_id = extractChannelId(http_server.uri());
  if (channel_id < 1 || channel_id > MAX_CHANNELS) {
    http_server.send(
      404,
      "application/json",
      "{\"error\":\"channel_id fuori range\"}"
    );
    return;
  }

  // channel_id 1-based → indice 0-based dell'array cache.
  uint8_t channel_index = (uint8_t)(channel_id - 1);
  const CacheEntry* entry = getCacheEntry(channel_index);
  if (entry == nullptr) {
    http_server.send(
      503,
      "application/json",
      "{\"error\":\"Cache non ancora popolata per questo canale\"}"
    );
    return;
  }

  // Costruzione del JSON V1 con ArduinoJson. La struttura riflette
  // esattamente HttpJsonSchemaV1 documentato in fitosim.io.sensors.
  // Capacità: stimata per un payload V1 completo + margine per i
  // valori float di lunghezza variabile.
  StaticJsonDocument<512> doc;

  doc["schema_version"] = "v1";

  // Timestamp ISO8601 della lettura.
  char ts_buffer[25];
  formatIsoTimestamp(entry->last_reading_utc, ts_buffer, sizeof(ts_buffer));
  doc["timestamp"] = ts_buffer;

  // channel_id come stringa per coerenza con altri provider
  // (es. Ecowitt usa "ch1", "ch2" come channel_id).
  char channel_buffer[8];
  snprintf(channel_buffer, sizeof(channel_buffer), "%d", channel_id);
  doc["channel_id"] = channel_buffer;

  // Misure canoniche.
  doc["theta_volumetric"] = entry->reading.theta_volumetric;
  doc["temperature_c"] = entry->reading.temperature_c;
  doc["ec_mscm"] = entry->reading.ec_mscm;
  doc["ph"] = entry->reading.ph;

  // Dati di "secondo livello" nel sotto-oggetto provider_specific.
  // fitosim li conserva opachi nel SoilReading.provider_specific.
  JsonObject provider_specific = doc.createNestedObject("provider_specific");
  provider_specific["npk_n_estimate_mg_kg"] = entry->reading.npk_n_mg_kg;
  provider_specific["npk_p_estimate_mg_kg"] = entry->reading.npk_p_mg_kg;
  provider_specific["npk_k_estimate_mg_kg"] = entry->reading.npk_k_mg_kg;
  provider_specific["ec_raw_uncompensated_uscm"] = entry->reading.ec_raw_uscm;
  provider_specific["modbus_address"] = MODBUS_ADDRESSES[channel_index];

  // Sotto-oggetto quality con metadati di freschezza della lettura.
  JsonObject quality = doc.createNestedObject("quality");
  // battery_level: l'ATO 7-in-1 cablato non ha batteria, lo lasciamo
  // null. Per WH51 wireless via gateway BLE-to-HTTP si potrebbe
  // popolare.
  quality["battery_level"] = nullptr;
  quality["last_calibration"] = nullptr;
  quality["staleness_seconds"] = computeStalenessSeconds(*entry);

  // Serializzazione e invio. Content-Type esplicito per ben formato.
  String response;
  serializeJson(doc, response);
  http_server.send(200, "application/json", response);
}

// Handler per URL non riconosciuti.
static void handleNotFound() {
  http_server.send(
    404,
    "application/json",
    "{\"error\":\"Endpoint non trovato\"}"
  );
}

void initHttpServer() {
  // Pattern di URL: il server WebServer di Arduino non supporta
  // path parameters direttamente, quindi registriamo l'handler su
  // "/api/soil/" e dentro l'handler estraiamo il channel_id dall'URL.
  // Per ogni canale possibile registriamo un handler dedicato.
  for (uint8_t i = 1; i <= MAX_CHANNELS; i++) {
    char path[32];
    snprintf(path, sizeof(path), "/api/soil/%d", i);
    http_server.on(path, HTTP_GET, handleSoilEndpoint);
  }

  http_server.onNotFound(handleNotFound);

  // Necessario per leggere l'header Authorization nelle richieste:
  // di default il WebServer scarta gli header non standard.
  const char* tracked_headers[] = {"Authorization"};
  http_server.collectHeaders(tracked_headers, 1);

  http_server.begin();
  Serial.print("[HTTP] Server avviato sulla porta ");
  Serial.println(HTTP_PORT);
}

void handleHttpRequests() {
  http_server.handleClient();
}

#endif // HTTP_SERVER_LAYER_H
