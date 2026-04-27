// =====================================================================
//  modbus_layer.h — Strato di lettura sensori ATO via Modbus RTU
// =====================================================================
//
// Questo header isola il codice Modbus dal resto del firmware. Espone
// una sola funzione pubblica `readSensorChannel(address, output)` che
// interroga un sensore ATO 7-in-1 sul bus RS485 e popola una struct
// con le letture, o ritorna false in caso di errore di comunicazione.
//
// Mappa dei registri Modbus dell'ATO 7-in-1
// -----------------------------------------
//
// I sensori ATO 7-in-1 espongono le loro misure come registri di
// holding (function code 0x03 = Read Holding Registers). La mappa
// esatta dei registri dipende dal modello specifico — verifica
// sempre il manuale Modbus del tuo sensore. Quella tipica è:
//
//   Registro 0x0000 → Umidità del suolo (× 10, intero, %)
//   Registro 0x0001 → Temperatura del suolo (× 10, intero con segno, °C)
//   Registro 0x0002 → Conducibilità (μS/cm, intero)
//   Registro 0x0003 → pH (× 10, intero)
//   Registro 0x0004 → N (mg/kg, intero) — derivato dalla EC, non
//                     una misura diretta, da usare con cautela
//   Registro 0x0005 → P (mg/kg, intero) — idem
//   Registro 0x0006 → K (mg/kg, intero) — idem
//
// Tutti i valori sono interi e devono essere divisi per il fattore
// di scala documentato sopra per ottenere il valore "fisico".
// Esempio: registro umidità = 342 → 34.2% in percentuale → 0.342 in
// frazione (la conversione finale a frazione la facciamo qui per
// rispettare la convenzione del SoilReading di fitosim).

#ifndef MODBUS_LAYER_H
#define MODBUS_LAYER_H

#include <Arduino.h>
#include <ModbusMaster.h>
#include "config.h"

// Struttura che ospita una lettura completa di un sensore ATO. Tutti
// i valori sono nelle unità canoniche di fitosim (vedi commenti nei
// campi). Il flag `valid` indica se la lettura è andata a buon fine.
struct SensorReading {
  // Flag di validità della lettura. Se false, gli altri campi sono
  // indefiniti e il chiamante non deve usarli.
  bool valid;

  // Dati canonici nelle unità di fitosim.
  float theta_volumetric;  // 0..1 (frazione, NON percentuale)
  float temperature_c;     // °C del substrato
  float ec_mscm;           // mS/cm a 25°C
  float ph;                // 0..14

  // Dati "di secondo livello" che vanno in provider_specific.
  // Sono interi mg/kg derivati dalla EC dal firmware del sensore;
  // li passiamo opachi a fitosim che li conserva ma non li usa per
  // il modello.
  uint16_t npk_n_mg_kg;
  uint16_t npk_p_mg_kg;
  uint16_t npk_k_mg_kg;
  uint16_t ec_raw_uscm;    // EC grezza in μS/cm (prima della
                           //   conversione a mS/cm canonica)
};

// Istanza globale del client Modbus master. Una sola per il bus.
extern ModbusMaster modbus_node;

// Inizializza il convertitore MAX485 e la libreria ModbusMaster.
// Va chiamata una sola volta nel setup() di Arduino.
void initModbus();

// Legge un sensore ATO al dato indirizzo Modbus e popola `output`.
// Ritorna true se la lettura è andata a buon fine, false altrimenti.
// In caso di errore, `output->valid` è settato a false.
bool readSensorChannel(uint8_t address, SensorReading* output);

// =====================================================================
//  Implementazione (header-only per semplicità del progetto Arduino)
// =====================================================================

ModbusMaster modbus_node;

// Pre/post-trasmissione: pilotaggio del pin DE/RE del MAX485 per
// alternare tra modalità trasmissione e ricezione. Il MAX485 è
// half-duplex, quindi va commutato esplicitamente.

void preTransmission() {
  digitalWrite(MODBUS_DE_PIN, HIGH);  // attiva trasmissione
}

void postTransmission() {
  digitalWrite(MODBUS_DE_PIN, LOW);   // torna in ricezione
}

void initModbus() {
  // Pin DE/RE configurato come output. Default LOW = ricezione.
  pinMode(MODBUS_DE_PIN, OUTPUT);
  digitalWrite(MODBUS_DE_PIN, LOW);

  // UART2 dell'ESP32 collegato al MAX485 (RX/TX dati).
  Serial2.begin(MODBUS_BAUD, SERIAL_8N1, MODBUS_RX_PIN, MODBUS_TX_PIN);

  // Inizializzazione del client Modbus. L'indirizzo viene impostato
  // di volta in volta in readSensorChannel() prima della richiesta.
  modbus_node.begin(1, Serial2);
  modbus_node.preTransmission(preTransmission);
  modbus_node.postTransmission(postTransmission);
}

bool readSensorChannel(uint8_t address, SensorReading* output) {
  output->valid = false;
  if (address == 0) {
    // Indirizzo 0 = canale non configurato (vedi config.h).
    return false;
  }

  // Riconfiguriamo l'indirizzo del slave da interrogare.
  modbus_node.begin(address, Serial2);

  // Leggiamo 7 registri consecutivi a partire dall'indirizzo 0x0000.
  // Il valore di ritorno è ku8MBSuccess (0) se la transazione
  // è andata a buon fine, altrimenti un codice errore della libreria.
  uint8_t result = modbus_node.readHoldingRegisters(0x0000, 7);

  if (result != modbus_node.ku8MBSuccess) {
    // Sensore offline, timeout, checksum errato, o indirizzo
    // sbagliato. Lasciamo il chiamante gestire il caso (tipicamente
    // marca la cache come "stale" per quel canale).
    return false;
  }

  // Estrazione dei registri letti dal buffer interno della libreria.
  uint16_t humidity_raw    = modbus_node.getResponseBuffer(0);
  int16_t  temp_raw        = (int16_t)modbus_node.getResponseBuffer(1);
  uint16_t ec_raw_uscm     = modbus_node.getResponseBuffer(2);
  uint16_t ph_raw          = modbus_node.getResponseBuffer(3);
  uint16_t n_raw           = modbus_node.getResponseBuffer(4);
  uint16_t p_raw           = modbus_node.getResponseBuffer(5);
  uint16_t k_raw           = modbus_node.getResponseBuffer(6);

  // Conversione in unità canoniche fitosim. Le scale dipendono dal
  // firmware ATO; quelle qui sono i valori tipici, verifica nel
  // manuale del tuo modello specifico.
  output->theta_volumetric = (float)humidity_raw / 1000.0f;  // %→frazione
  output->temperature_c    = (float)temp_raw     / 10.0f;
  output->ec_mscm          = (float)ec_raw_uscm  / 1000.0f;  // μS→mS
  output->ph               = (float)ph_raw       / 10.0f;
  output->npk_n_mg_kg      = n_raw;
  output->npk_p_mg_kg      = p_raw;
  output->npk_k_mg_kg      = k_raw;
  output->ec_raw_uscm      = ec_raw_uscm;
  output->valid            = true;

  return true;
}

#endif // MODBUS_LAYER_H
