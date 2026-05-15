"""
Interfacce astratte (Protocol) per i sensori di fitosim.

Questo modulo definisce i due Protocol che descrivono la "forma" che un
adapter di sensore deve avere per essere utilizzabile come sorgente di
dati da fitosim. Usiamo `typing.Protocol` invece di `abc.ABC` per due
ragioni architetturali importanti:

1. **Duck typing strutturale**: chi sviluppa un adapter custom può farlo
   senza dover importare nulla da fitosim. Basta esporre i metodi giusti
   con le firme giuste e l'oggetto è automaticamente compatibile. Questo
   minimizza l'accoppiamento tra fitosim e i suoi consumatori.

2. **Compatibilità con il type checker**: i Protocol sono verificati
   staticamente da mypy/pyright al momento dello sviluppo, ma a runtime
   non impongono alcun vincolo. Un adapter scritto da terze parti viene
   "riconosciuto" come SoilSensor o EnvironmentSensor automaticamente,
   senza ereditarietà esplicita.

Le due interfacce sono asimmetriche per design, perché riflettono due
cardinalità diverse rispetto al sistema di vasi:

  - Un singolo `EnvironmentSensor` serve potenzialmente molti vasi
    (la stazione meteo del balcone è la stessa per tutti i vasi del
    balcone). Il sensore ambientale è un'entità "uno per giardino" o
    "uno per microclima" e fornisce dati che valgono per più vasi.

  - Un singolo `SoilSensor` serve un singolo vaso identificato da un
    `channel_id`. Lo stato del substrato del vaso A non è trasferibile
    al vaso B anche se i due sono adiacenti, perché ogni vaso ha la
    propria storia idrica e nutrizionale specifica.

Questa asimmetria si riflette nelle firme dei metodi: l'EnvironmentSensor
prende coordinate geografiche per identificare *quale microclima* leggere,
il SoilSensor prende un identificativo di canale per identificare
*quale vaso* leggere.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fitosim.io.sensors.measurement import Measurement


@runtime_checkable
class EnvironmentSensor(Protocol):
    """
    Interfaccia per le sorgenti di dati meteorologici.

    Un EnvironmentSensor è qualunque oggetto che sa fornire dati meteo
    per un determinato microclima identificato da coordinate
    geografiche. Esempi di implementazioni concrete sono:

      - `OpenMeteoEnvironmentSensor`: legge da API Open-Meteo (cloud,
        no auth, copertura globale).
      - `EcowittEnvironmentSensor`: legge dalla stazione meteo Ecowitt
        dell'utente via Ecowitt Cloud.
      - `CsvEnvironmentFixture`: replica scenari storici da CSV (test).
      - Sensore indoor su Raspberry Pi che espone le proprie misure
        come endpoint HTTP locale.

    Formato di ritorno: la spec sensori v1 (vedi
    `the_pot_sensors_spec.md` nel repo The Pot) richiede che ogni
    adapter produca **liste piatte di `Measurement` canoniche** —
    tuple immutabili `(sensor_id, timestamp, parameter, value)` con
    vocabolario controllato (`air_temperature_c`, `rainfall_mm`,
    `air_humidity`, ecc.) e namespace `custom:*` per estensioni.

    Un singolo "tick" di lettura di una stazione meteo che misura
    temperatura, umidità, vento e pioggia produce quindi **quattro
    Measurement** con lo stesso `sensor_id` e lo stesso `timestamp`,
    una per parametro. Una `forecast()` su 7 giorni produce 4 × 7 = 28
    Measurement (un'unica lista piatta, ordinata per timestamp
    crescente, poi per parametro).

    Il decoratore `@runtime_checkable` permette di usare `isinstance(x,
    EnvironmentSensor)` a runtime per verificare conformità, utile per
    diagnostica e logging. La verifica a runtime guarda solo che i
    metodi esistano, non controlla le firme; per il controllo completo
    ci si affida al type checker statico.

    Metodi richiesti
    ----------------
    current_conditions(latitude, longitude) -> list[Measurement]
        Restituisce le condizioni meteo correnti (o le più recenti
        disponibili) per la posizione geografica indicata. Tutte le
        Measurement condividono lo stesso `timestamp` (quello della
        misura effettiva, non della richiesta).

    forecast(latitude, longitude, days) -> list[Measurement]
        Restituisce la previsione meteo a `days` giorni futuri come
        lista piatta di Measurement. Per ogni giorno della finestra
        e per ogni parametro disponibile sull'adapter, una
        Measurement. La lista è ordinata per timestamp crescente.

    Eccezioni sollevate
    -------------------
    SensorTemporaryError
        Per errori di rete, timeout, o problemi recuperabili. Il
        chiamante può ritentare o usare cache.
    SensorPermanentError
        Per credenziali sbagliate, URL deprecati, o problemi che
        richiedono intervento esterno.
    SensorDataQualityError
        Quando il provider risponde ma con dati non plausibili (per
        esempio temperatura di -200 °C, umidità del 250%). Anche la
        validazione interna di `Measurement.__post_init__` (range
        fisici, timestamp tz-aware, parameter canonico/custom) può
        sollevare `MeasurementValidationError` come errore di qualità.
    """

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> list[Measurement]:
        """
        Restituisce le condizioni meteo correnti per le coordinate.

        Parametri
        ---------
        latitude : float
            Latitudine in gradi decimali, range [-90, 90].
        longitude : float
            Longitudine in gradi decimali, range [-180, 180].

        Ritorna
        -------
        list[Measurement]
            Una Measurement per ciascun parametro che l'adapter sa
            misurare in questo momento, tutte con lo stesso
            `timestamp`. Lista vuota possibile se nessuna lettura è
            disponibile (caso raro; più tipicamente l'adapter solleva
            `SensorTemporaryError`).
        """
        ...

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[Measurement]:
        """
        Restituisce la previsione meteo per i prossimi `days` giorni.

        Parametri
        ---------
        latitude : float
            Latitudine in gradi decimali.
        longitude : float
            Longitudine in gradi decimali.
        days : int
            Numero di giorni di previsione richiesti, tipicamente 1-16
            a seconda del provider. I provider impongono un loro
            limite massimo: oltre quel limite, il metodo solleva
            ValueError.

        Ritorna
        -------
        list[Measurement]
            Lista piatta di Measurement per i `days` giorni richiesti,
            con N parametri per giorno (dove N dipende dalle capacità
            dell'adapter). Ordinata per `timestamp` crescente; per
            timestamp uguale, l'ordine tra parametri non è garantito.
        """
        ...


@runtime_checkable
class SoilSensor(Protocol):
    """
    Interfaccia per i sensori di stato del substrato in un singolo vaso.

    Un SoilSensor rappresenta un sensore (o un canale di un sensore
    multi-canale) che misura le condizioni del substrato di un singolo
    vaso. Esempi di implementazioni concrete sono:

      - `EcowittWH51SoilSensor`: legge la θ del WH51 via Ecowitt Cloud,
        un canale per WH51 collegato alla base station.
      - `HttpJsonSoilSensor`: legge θ + T + EC + pH da un gateway HTTP
        custom (ATO, ESP32 con Modbus).
      - `CsvSoilFixture`: replica scenari storici da CSV (test).
      - `XiaomiMiFloraSoilSensor` (futuro): legge da Xiaomi MiFlora
        Bluetooth.

    A differenza di EnvironmentSensor, qui il parametro `channel_id` è
    obbligatorio perché molti hardware multi-canale servono più vasi
    simultaneamente: la base station Ecowitt riceve fino a 8 WH51,
    l'ATO 7-in-1 può avere più sonde su bus RS485. La tabella di
    routing del backend (`sensor_routing` nella spec sensori v1)
    manterrà la mappa "quale `(sensor_id, channel_id)` appartiene a
    quale Pot".

    Per sensori a canale singolo (un sensore Bluetooth dedicato a un
    solo vaso), `channel_id` può essere ignorato dall'implementazione
    o usato come identificativo simbolico.

    Formato di ritorno: la spec sensori v1 richiede liste piatte di
    `Measurement` canoniche. Un singolo "tick" di lettura di un
    sensore di suolo che misura θ, T, EC e pH produce **fino a quattro
    Measurement** con lo stesso `sensor_id` e `timestamp`, una per
    parametro (i parametri non misurati semplicemente non producono
    una Measurement, anziché produrre una Measurement con value=None).

    Metodo richiesto
    ----------------
    current_state(channel_id) -> list[Measurement]
        Restituisce lo stato corrente del substrato per il canale
        indicato come lista di Measurement canoniche
        (`soil_theta`, `soil_temperature_c`, `soil_ec_mscm`,
        `soil_ph` secondo le capacità del sensore). Il `timestamp`
        è quello della misura effettiva del sensore (non quello
        della richiesta del chiamante).

    Eccezioni sollevate
    -------------------
    SensorTemporaryError
        Per errori di rete, timeout, batteria temporaneamente debole.
    SensorPermanentError
        Per canale inesistente, credenziali sbagliate, sensore
        scollegato dalla base station.
    SensorDataQualityError
        Per letture fuori range fisico (θ negativo, pH > 14, ecc.).
        Anche la validazione interna di `Measurement.__post_init__`
        (range plausibili) può sollevare `MeasurementValidationError`
        come errore di qualità.
    """

    def current_state(self, channel_id: str) -> list[Measurement]:
        """
        Restituisce lo stato corrente del substrato per il canale.

        Parametri
        ---------
        channel_id : str
            Identificativo del canale del sensore, specifico del
            provider. Per Ecowitt è tipicamente "soilmoisture_ch1"..
            "soilmoisture_ch8". Per ATO è il numero di sonda su bus
            RS485. Per Bluetooth diretto può essere il MAC del device.

        Ritorna
        -------
        list[Measurement]
            Una Measurement per ciascun parametro che il sensore sa
            misurare al timestamp corrente. Almeno `soil_theta` è
            tipicamente presente (è la grandezza primaria di tutti i
            sensori di suolo); gli altri parametri (T, EC, pH)
            dipendono dalle capacità del sensore specifico.
        """
        ...
