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

from fitosim.io.sensors.types import EnvironmentReading, SoilReading


@runtime_checkable
class EnvironmentSensor(Protocol):
    """
    Interfaccia per le sorgenti di dati meteorologici.

    Un EnvironmentSensor è qualunque oggetto che sa fornire i dati
    meteo per un determinato microclima identificato da coordinate
    geografiche. Esempi di implementazioni concrete sono:

      - `OpenMeteoEnvironmentSensor`: legge da API Open-Meteo (cloud,
        no auth, copertura globale).
      - `EcowittEnvironmentSensor`: legge dalla stazione meteo Ecowitt
        dell'utente via Ecowitt Cloud.
      - Sensore indoor su Raspberry Pi che espone le proprie misure
        come endpoint HTTP locale.

    Il decoratore `@runtime_checkable` permette di usare `isinstance(x,
    EnvironmentSensor)` a runtime per verificare conformità, utile per
    diagnostica e logging. La verifica a runtime guarda solo che i
    metodi esistano, non controlla le firme; per il controllo completo
    ci si affida al type checker statico.

    Metodi richiesti
    ----------------
    current_conditions(latitude, longitude) -> EnvironmentReading
        Restituisce le condizioni meteo correnti (o le più recenti
        disponibili) per la posizione geografica indicata. Il
        timestamp del Reading restituito è quello della misura
        effettiva, non quello della richiesta.

    forecast(latitude, longitude, days) -> list[EnvironmentReading]
        Restituisce la previsione meteo a `days` giorni futuri, con
        un Reading per ogni giorno. Il primo elemento della lista
        corrisponde tipicamente a "oggi" o "domani" a seconda del
        provider; il chiamante non deve fare assunzioni e deve usare
        il timestamp di ciascun Reading.

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
        esempio temperatura di -200 °C, umidità del 250%).
    """

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> EnvironmentReading:
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
        EnvironmentReading
            Lettura strutturata con i campi disponibili dal provider.
            I campi non forniti sono None; il timestamp è sempre
            valorizzato e timezone-aware.
        """
        ...

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[EnvironmentReading]:
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
        list[EnvironmentReading]
            Lista di Reading uno per giorno, ordinati per timestamp
            crescente. La lunghezza è esattamente `days`.
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
      - `ATO7in1SoilSensor` (tappa 2): legge θ, T, EC, pH dall'ATO
        7-in-1.
      - `XiaomiMiFloraSoilSensor` (futuro): legge da Xiaomi MiFlora
        Bluetooth.

    A differenza di EnvironmentSensor, qui il parametro `channel_id` è
    obbligatorio perché molti hardware multi-canale servono più vasi
    simultaneamente: la base station Ecowitt riceve fino a 8 WH51,
    l'ATO 7-in-1 può avere più sonde su bus RS485. L'orchestratore
    della tappa 4 manterrà la mappa "quale channel_id appartiene a
    quale Pot".

    Per sensori a canale singolo (un sensore Bluetooth dedicato a un
    solo vaso), `channel_id` può essere ignorato dall'implementazione
    o usato come identificativo simbolico.

    Metodo richiesto
    ----------------
    current_state(channel_id) -> SoilReading
        Restituisce lo stato corrente del substrato per il canale
        indicato. Il timestamp è quello della misura effettiva del
        sensore (non quello della richiesta del chiamante).

    Eccezioni sollevate
    -------------------
    SensorTemporaryError
        Per errori di rete, timeout, batteria temporaneamente debole.
    SensorPermanentError
        Per canale inesistente, credenziali sbagliate, sensore
        scollegato dalla base station.
    SensorDataQualityError
        Per letture fuori range fisico (θ negativo, pH > 14, ecc.).
    """

    def current_state(self, channel_id: str) -> SoilReading:
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
        SoilReading
            Lettura strutturata con almeno θ valorizzata. Gli altri
            campi (T, EC, pH) dipendono dalle capacità del sensore
            specifico e possono essere None.
        """
        ...
