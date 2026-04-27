// =====================================================================
//  cache_layer.h — Cache RAM delle letture e timestamp UTC
// =====================================================================
//
// Questo strato è il cuore architetturale del gateway: separa il
// polling Modbus (lento, vincolato dal bus seriale) dalle risposte
// HTTP (rapide, servite immediatamente dalla cache). Senza questa
// separazione, ogni richiesta HTTP innescherebbe una transazione
// Modbus che bloccherebbe l'ESP32 per centinaia di millisecondi.
//
// Filosofia
// ---------
//
// Il polling Modbus è programmato per girare ogni POLLING_INTERVAL_MS
// (60 secondi di default) attraverso tutti i canali configurati.
// Ogni lettura riuscita aggiorna la slot della cache corrispondente
// con la nuova lettura e il timestamp UTC al momento della lettura.
// Le richieste HTTP sono servite sempre dalla cache, indipendentemente
// dal momento esatto di ricezione.
//
// Il campo "staleness_seconds" del JSON V1 di fitosim viene calcolato
// al momento della risposta HTTP come differenza tra "now()" e il
// timestamp salvato nella cache. Questo dice esplicitamente al
// chiamante quanto è recente la lettura, in modo che possa decidere
// autonomamente se è abbastanza fresca o se segnalare staleness.
//
// Sincronizzazione NTP
// --------------------
//
// All'avvio dell'ESP32 e ogni ora successiva, il firmware sincronizza
// l'orologio interno via NTP. Questo è essenziale per emettere
// timestamp UTC corretti nel JSON: senza NTP, l'orologio dell'ESP32
// drift di parecchi secondi al giorno e i timestamp diventerebbero
// inattendibili.

#ifndef CACHE_LAYER_H
#define CACHE_LAYER_H

#include <Arduino.h>
#include <time.h>
#include "config.h"
#include "modbus_layer.h"

// Una entry nella cache: la lettura più recente di un canale, più
// il timestamp UTC al momento della lettura. Il flag `populated`
// indica se la slot è stata mai popolata (false fino alla prima
// lettura riuscita).
struct CacheEntry {
  bool       populated;
  time_t     last_reading_utc;  // epoch UTC del momento della lettura
  SensorReading reading;
};

// Array di cache: una slot per canale. Vivono in RAM globale per
// semplicità (l'ESP32 ha 520 KB di RAM, MAX_CHANNELS slot occupano
// pochi KB).
extern CacheEntry cache[MAX_CHANNELS];

// Inizializza la cache (tutte le slot non popolate) e configura NTP.
// Va chiamata una sola volta nel setup() di Arduino, dopo che il WiFi
// è già connesso.
void initCache();

// Aggiorna la cache di un canale con una nuova lettura. Va chiamata
// dal polling Modbus quando una transazione va a buon fine.
void updateCacheEntry(uint8_t channel_index, const SensorReading& reading);

// Ottiene una entry della cache per indice di canale (0..MAX_CHANNELS-1).
// Ritorna nullptr se l'indice è fuori range o se la slot non è mai stata
// popolata.
const CacheEntry* getCacheEntry(uint8_t channel_index);

// Calcola lo staleness in secondi rispetto a ora UTC.
// Ritorna 0 se la cache è stata aggiornata "ora", oppure il numero
// di secondi trascorsi dall'ultima lettura riuscita.
uint32_t computeStalenessSeconds(const CacheEntry& entry);

// Ritorna il timestamp UTC corrente come time_t (epoch).
// Se NTP non si è ancora sincronizzato, ritorna 0 (Unix epoch
// origin), che è un valore riconoscibile come "non sincronizzato".
time_t getCurrentUtcEpoch();

// Formatta un time_t UTC come stringa ISO8601 con suffisso "Z".
// Esempio: 1714248900 → "2026-04-27T19:55:00Z".
// Il buffer fornito deve essere almeno 25 bytes.
void formatIsoTimestamp(time_t epoch, char* buffer, size_t buffer_size);

// =====================================================================
//  Implementazione
// =====================================================================

CacheEntry cache[MAX_CHANNELS];

void initCache() {
  // Inizializzazione: tutte le slot non popolate.
  for (uint8_t i = 0; i < MAX_CHANNELS; i++) {
    cache[i].populated = false;
    cache[i].last_reading_utc = 0;
  }

  // Configurazione NTP. configTime() è una funzione standard di
  // ESP-IDF/Arduino che configura il sync NTP in background.
  // Da questo momento in poi, time(NULL) ritorna l'UTC corretto
  // (entro qualche secondo dall'avvio).
  configTime(NTP_GMT_OFFSET, NTP_DST_OFFSET, NTP_SERVER);
  Serial.println("[NTP] Sincronizzazione orologio in corso...");

  // Aspettiamo fino a 10 secondi che NTP si sincronizzi: senza
  // questo wait, la prima lettura potrebbe avere timestamp errato.
  uint32_t start_ms = millis();
  while (time(nullptr) < 1700000000 && (millis() - start_ms) < 10000UL) {
    delay(100);
  }

  if (time(nullptr) >= 1700000000) {
    Serial.println("[NTP] Sincronizzazione completata.");
  } else {
    Serial.println("[NTP] Sincronizzazione fallita; timestamp non saranno");
    Serial.println("[NTP] affidabili finché NTP non si sincronizzerà.");
  }
}

void updateCacheEntry(uint8_t channel_index, const SensorReading& reading) {
  if (channel_index >= MAX_CHANNELS) return;
  cache[channel_index].populated = true;
  cache[channel_index].last_reading_utc = getCurrentUtcEpoch();
  cache[channel_index].reading = reading;
}

const CacheEntry* getCacheEntry(uint8_t channel_index) {
  if (channel_index >= MAX_CHANNELS) return nullptr;
  if (!cache[channel_index].populated) return nullptr;
  return &cache[channel_index];
}

uint32_t computeStalenessSeconds(const CacheEntry& entry) {
  time_t now = getCurrentUtcEpoch();
  if (now < entry.last_reading_utc) {
    // Edge case: clock skew (improbabile dopo NTP sync ma possibile
    // ai primi istanti dopo l'avvio). Ritorniamo 0 per non confondere
    // fitosim con valori negativi.
    return 0;
  }
  return (uint32_t)(now - entry.last_reading_utc);
}

time_t getCurrentUtcEpoch() {
  return time(nullptr);
}

void formatIsoTimestamp(time_t epoch, char* buffer, size_t buffer_size) {
  struct tm gm;
  gmtime_r(&epoch, &gm);
  strftime(buffer, buffer_size, "%Y-%m-%dT%H:%M:%SZ", &gm);
}

#endif // CACHE_LAYER_H
