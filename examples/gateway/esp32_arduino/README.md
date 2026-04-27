# Gateway ESP32 hardware-to-HTTP per fitosim

Questo è un firmware ESP32 di esempio che fa da ponte tra sensori
industriali ATO 7-in-1 (collegati via Modbus RTU su bus RS485) e
fitosim, esponendo le letture come endpoint HTTP REST conformi allo
schema JSON V1 documentato in `fitosim.io.sensors.HttpJsonSchemaV1`.

È pensato come **punto di partenza didattico** da cui forkare il tuo
side project, non come prodotto finito. Il codice è strutturato per
essere chiaro più che per essere ottimizzato: tre strati ben separati
(Modbus, cache, HTTP), commenti estesi, configurazione tramite file
`.h` separato dal codice sorgente. Sentiti libero di modificarlo,
estenderlo, aggiungere funzionalità (OTA, mDNS, web UI, gestione di
più reti WiFi) man mano che il tuo side project evolve.

## Cosa serve per costruirlo

Sul piano hardware ti serve un ESP32 originale (qualsiasi devkit DEVKIT
V1 o WROOM-32 da pochi euro va bene), un modulo convertitore MAX485
(cerca "MAX485 TTL to RS485 module" su Amazon o AliExpress, costano
2-3 euro), un cavo schermato a doppia coppia twistata (CAT5e va bene
oppure cavo industriale RS485 specifico), due resistenze da 120 ohm
per la terminazione del bus, e ovviamente i sensori ATO 7-in-1 che hai
già pianificato di acquistare. I sensori ATO sono alimentati a 12V
DC: l'USB del computer non basta, ti serve un alimentatore esterno o
un convertitore DC-DC step-up dal 5V dell'ESP32.

Sul piano software ti serve **Arduino IDE** (versione 2.x consigliata)
con il **core ESP32 di Espressif** installato dal Boards Manager
(cerca "esp32" e installa "esp32 by Espressif Systems"). Inoltre
servono due librerie Arduino specifiche da installare dal Library
Manager: `ModbusMaster` di Doc Walker e `ArduinoJson` di Benoît Blanchon
versione 6.x. Tutte le altre librerie usate dal firmware (`WiFi`,
`WebServer`, `time.h`) sono incluse nel core ESP32 e non richiedono
installazione separata.

## Cablaggio del bus RS485

Il cablaggio è la parte più delicata di tutto il setup, perché un bus
RS485 mal cablato produce errori di comunicazione intermittenti che
sono frustranti da debuggare. Lascia che ti guidi attraverso il
collegamento corretto in modo che tutto funzioni al primo tentativo.

Il convertitore MAX485 ha tipicamente sei pin: VCC (alimentazione),
GND (massa), DI (Driver Input, dati che vanno verso il bus), RO
(Receiver Output, dati che vengono dal bus), DE+RE (controllo
direzione, spesso uniti su un singolo pin), e i due fili del bus
differenziale chiamati A e B (a volte etichettati Y e Z). Il
collegamento al tuo ESP32 segue questa logica: VCC del MAX485 va al
3.3V dell'ESP32, GND a GND, RO al pin GPIO 16 dell'ESP32 (che è il RX
di Serial2), DI al pin GPIO 17 (TX di Serial2), e DE+RE al pin GPIO 4
che il firmware usa per pilotare la direzione di trasmissione.

Sul lato sensori, ogni ATO 7-in-1 ha quattro fili che escono dal cavo:
rosso (alimentazione 12V), nero (massa), giallo (filo A del bus RS485),
e blu o bianco (filo B del bus). Tutti i fili A dei sensori vanno
collegati insieme al filo A del bus (che parte dal MAX485), tutti i
fili B insieme al filo B del bus, tutti i rossi all'alimentazione 12V,
e tutti i neri alla massa comune.

La parte cruciale sono le **resistenze di terminazione**. RS485 è uno
standard che richiede due resistenze da 120 ohm posizionate alle due
estremità fisiche del bus (NON in mezzo, NON ad ogni sensore). La
prima resistenza la metti tra il filo A e il filo B vicino al MAX485
(molti moduli MAX485 ne hanno una integrata controllabile da un
jumper); la seconda la metti tra il filo A e il filo B del sensore
fisicamente più lontano dal MAX485. Se il bus è corto (meno di 5
metri) e hai pochi sensori, in pratica funzionerà anche senza
terminazione, ma per affidabilità a lungo termine non saltare mai
questo passo.

## Configurazione degli indirizzi Modbus dei sensori

Tutti i sensori ATO 7-in-1 escono di fabbrica con lo stesso indirizzo
Modbus, tipicamente 1. Se metti due sensori sul bus con lo stesso
indirizzo, parlerebbero sopra e nessuno risponderebbe in modo
affidabile, quindi devi cambiare l'indirizzo di tutti i sensori
tranne uno prima di metterli in produzione. Hai due strade per farlo.

La prima è di usare il software ATO ufficiale per Windows che ti
permette di collegare un sensore alla volta via USB-RS485 e cambiarne
l'indirizzo dall'interfaccia grafica. È il metodo raccomandato dal
costruttore e probabilmente il più rapido se hai un PC Windows a
disposizione.

La seconda è di farlo via Modbus RTU mandando il comando di cambio
indirizzo direttamente dal tuo ESP32 con uno sketch dedicato. Il
registro da scrivere è tipicamente 0x07D0 (varia leggermente per
modello, controlla il manuale del tuo sensore specifico). Il vantaggio
di questa strada è che non ti serve hardware aggiuntivo; lo svantaggio
è che lo sketch di configurazione è separato dallo sketch principale
e devi flashearlo prima e dopo l'operazione, che è scomodo se hai
molti sensori.

In ogni caso, ricorda che ogni sensore una volta configurato si
ricorda dell'indirizzo nuovo nella sua memoria non volatile, quindi
anche dopo che lo scolleghi e lo ricolleghi mantiene il suo indirizzo.
Annotati su un foglio quale sensore ha quale indirizzo (ad esempio
con un'etichetta sul cavo di ogni sensore), perché dopo qualche
settimana è facile dimenticarsene.

## Configurazione del firmware

Una volta che l'hardware è cablato e gli indirizzi Modbus dei sensori
sono settati, devi configurare il firmware con i tuoi parametri
specifici prima di compilarlo. Apri Arduino IDE, vai nella directory
`examples/gateway/esp32_arduino/` di fitosim, e fai una copia del
file `config.h.example` rinominandola in `config.h`. Il file `config.h`
non finirà in git (è già nel `.gitignore` del progetto) perché
contiene la password della tua rete WiFi.

Apri `config.h` e modifica le sezioni rilevanti. La sezione 1 contiene
le credenziali WiFi: metti l'SSID e la password della tua rete a 2.4
GHz (l'ESP32 originale non supporta 5 GHz). La sezione 3 contiene la
mappa degli indirizzi Modbus dei tuoi sensori: l'array
`MODBUS_ADDRESSES` ha quattro slot numerati da 0 a 3 che corrispondono
ai canali 1, 2, 3, 4 lato HTTP. Mettici gli indirizzi Modbus dei tuoi
sensori in ordine, usando 0 per gli slot non utilizzati.

La sezione 5 contiene il bearer token opzionale per l'autenticazione.
Se lasci `HTTP_BEARER_TOKEN` come stringa vuota, il gateway accetta
richieste senza autenticazione: è il caso d'uso "LAN domestica
affidabile". Se vuoi aggiungere un livello di sicurezza in più (per
esempio se condividi la tua rete WiFi con ospiti o se in futuro
esporrai il gateway via Tailscale), valorizza il token con una stringa
casuale lunga (almeno 32 caratteri) e configura fitosim per inviarlo
via la variabile d'ambiente `FITOSIM_HTTP_GATEWAY_TOKEN`.

Le altre sezioni del file contengono parametri che raramente devi
toccare: pin GPIO del MAX485, baud rate del bus Modbus, intervallo
di polling, server NTP. I default sono sensati per il setup descritto
in questo README; cambiali solo se hai una ragione specifica.

## Flashing del firmware

Apri lo sketch `esp32_soil_gateway.ino` in Arduino IDE. Verifica che
nella barra in alto siano selezionati la board "ESP32 Dev Module" e
la porta seriale corretta dove l'ESP32 è collegato (tipicamente
qualcosa come `/dev/ttyUSB0` su Linux, `COM3` su Windows). Premi il
pulsante "Verify" (icona della spunta in alto a sinistra) per
compilare il codice; al primo tentativo l'IDE potrebbe lamentarsi che
mancano librerie, in quel caso vai nel Library Manager (Tools →
Manage Libraries) e installa le due librerie elencate nel commento
in cima allo sketch (`ModbusMaster` e `ArduinoJson` 6.x).

Una volta che la compilazione va a buon fine, premi "Upload" (icona
della freccia) per flashare il firmware sull'ESP32. Il processo dura
una decina di secondi. Quando finisce, apri il "Serial Monitor"
(Tools → Serial Monitor) impostando il baud rate a 115200; vedrai
i messaggi di log dell'ESP32 che si avvia, si connette al WiFi,
sincronizza l'orologio via NTP, inizializza il bus Modbus, fa il
primo ciclo di polling dei sensori, e mette in ascolto il server
HTTP. Se tutto funziona correttamente, dopo una decina di secondi
dovresti vedere righe di log tipo `[Polling] Canale 1 (Modbus addr
1): θ=0.342 T=18.5°C EC=1.85 mS/cm pH=6.4`.

Annotati l'indirizzo IP locale che il log mostra al momento della
connessione WiFi: è quello con cui fitosim parlerà con il gateway.
È buona idea anche assegnare al tuo ESP32 un IP statico nel router
in modo che non cambi al riavvio del router, oppure di usare il
nome mDNS che alcuni router risolvono automaticamente (per esempio
se il router lo registra come `esp32-soil.local`).

## Test della prima lettura

Prima di collegare fitosim, fai un test diretto del gateway dal tuo
computer per essere sicuro che le letture arrivino correttamente.
Apri un terminale e lancia un comando `curl` puntando all'indirizzo
IP che il gateway ti ha mostrato:

```bash
curl http://192.168.1.42/api/soil/1
```

Sostituisci `192.168.1.42` con l'IP effettivo del tuo gateway.
Dovresti ricevere come risposta un JSON conforme allo schema V1, con
i campi `schema_version`, `timestamp`, `theta_volumetric`,
`temperature_c`, `ec_mscm`, `ph`, `provider_specific`, e `quality`
tutti popolati. Se ricevi 503, il gateway è ancora avviato ma non ha
fatto il primo ciclo di polling: aspetta una sessantina di secondi e
riprova. Se ricevi 404, controlla che il channel_id richiesto (1 nel
nostro caso) abbia un sensore configurato in `MODBUS_ADDRESSES`.

Una volta che `curl` restituisce dati corretti, puoi collegare fitosim
al gateway con poche righe di Python:

```python
from fitosim.io.sensors import HttpJsonSoilSensor

sensor = HttpJsonSoilSensor(
    base_url="http://192.168.1.42",
    endpoint_pattern="/api/soil/{channel_id}",
)
reading = sensor.current_state(channel_id="1")
print(f"θ del vaso 1: {reading.theta_volumetric:.3f}")
print(f"Temperatura substrato: {reading.temperature_c} °C")
print(f"EC: {reading.ec_mscm} mS/cm, pH: {reading.ph}")
```

Se il bearer token è valorizzato in `config.h`, configura fitosim per
inviarlo settando la variabile d'ambiente
`FITOSIM_HTTP_GATEWAY_TOKEN` con lo stesso valore (vedi `.env.example`
nella root del progetto fitosim) e usa il pattern `from_env()`:

```python
sensor = HttpJsonSoilSensor.from_env(base_url="http://192.168.1.42")
```

A questo punto il loop completo è chiuso: i tuoi sensori ATO leggono
il substrato dei vasi, l'ESP32 li interroga via Modbus ogni minuto,
fitosim consuma le letture via HTTP, e il modello agronomico può
chiudere il feedback loop con `Pot.update_from_sensor(reading=reading)`
per allineare la simulazione alla realtà fisica del balcone.

## Risoluzione dei problemi comuni

Se il gateway non si connette al WiFi (rimane bloccato sui puntini
nel log), verifica che SSID e password in `config.h` siano corretti
(case-sensitive!) e che la rete sia effettivamente a 2.4 GHz. Le
reti dual-band moderne tipo Wi-Fi 6 a volte espongono solo il 5 GHz
sotto lo stesso SSID; in quel caso devi creare una rete separata a
2.4 GHz nel router, oppure passare a un ESP32-S3 che supporta entrambe
le bande.

Se il bus Modbus mostra "ERRORE comunicazione" su tutti i canali,
controlla in ordine queste cose: il MAX485 è alimentato (LED acceso
se ne ha uno), i fili A e B non sono invertiti (provare a scambiarli
spesso risolve il problema), le resistenze di terminazione sono
presenti alle due estremità del bus, l'alimentazione 12V dei sensori
è effettivamente attiva e fornisce corrente sufficiente, gli
indirizzi Modbus dei sensori sono effettivamente quelli che hai
configurato in `MODBUS_ADDRESSES`. Un test utile è di staccare tutti
i sensori tranne uno e provare a leggerlo: se così funziona ma
collegando gli altri smette, probabilmente c'è una collisione di
indirizzi o un problema fisico di cablaggio in un punto specifico
del bus.

Se NTP non si sincronizza (vedi messaggio "Sincronizzazione fallita"
nel log), controlla che il tuo router non blocchi le richieste DNS
o le richieste verso pool.ntp.org. Alcune reti aziendali o ospedaliere
hanno firewall che bloccano il traffico NTP; in quel caso cambia
`NTP_SERVER` in `config.h` mettendo l'IP di un server NTP che la tua
rete consente, oppure l'IP del tuo router se questo offre il servizio
NTP locale.

Se le letture HTTP funzionano da `curl` ma fitosim solleva
`SensorPermanentError` con messaggi tipo "schema_version non
riconosciuta", verifica che il firmware sia aggiornato all'ultima
versione e che `ArduinoJson` sia la versione 6.x (la versione 5.x
ha API diverse e non compila con questo sketch). Se vedi
`SensorTemporaryError` con messaggi tipo "Gateway non raggiungibile",
controlla che fitosim e il gateway siano sulla stessa rete e che
nessun firewall locale stia bloccando le connessioni in uscita.

## Cosa puoi aggiungere in futuro

Questo firmware copre il caso d'uso essenziale: leggere sensori ATO
e esporli come HTTP REST. Quando il tuo side project crescerà, ci
sono diverse direzioni naturali in cui può evolvere. La prima è
**l'aggiornamento OTA (over-the-air)** che ti permette di aggiornare
il firmware senza ricollegare il cavo USB, particolarmente utile
quando l'ESP32 è installato in un punto difficile da raggiungere
fisicamente. La libreria `ArduinoOTA` lo rende relativamente semplice.
La seconda è una **web UI di configurazione** che evita di dover
modificare `config.h` e riflascare ogni volta che cambi un sensore;
servono altre cento righe di codice e un piccolo HTML servito dallo
stesso `WebServer` già attivo. La terza è **mDNS discovery** che
permette di raggiungere il gateway con un nome simbolico tipo
`esp32-soil.local` invece dell'IP, gestita dalla libreria `ESPmDNS`.
La quarta è il **supporto per più reti WiFi** in fallback (ad esempio
casa e mobile hotspot) tramite la libreria `WiFiManager`. Tutte
queste funzionalità si integrano bene con l'architettura a tre strati
del firmware senza richiedere riprogettazioni.
