"""
Tipi canonici di ritorno per il livello sensori di fitosim.

Questo modulo definisce le strutture dati che ogni adapter di sensore
restituisce. La standardizzazione di questi tipi è il punto chiave
dell'astrazione: il chiamante di fitosim lavora sempre con queste
strutture, indipendentemente dal provider sottostante.

Tipi esposti
------------

  - `ReadingQuality`: metadati di qualità di una lettura (batteria,
    calibrazione, freschezza).
  - `EnvironmentReading`: misure meteorologiche (temperatura aria,
    umidità, radiazione, vento, pioggia).
  - `SoilReading`: misure del substrato di un singolo vaso (umidità,
    temperatura, EC, pH).

Convenzione delle unità di misura
---------------------------------

Tutti i campi numerici usano unità canoniche fisse, fissate a livello
architetturale per eliminare ambiguità:

  - θ volumetrico: frazione adimensionale 0..1 (NON percentuale)
  - EC: millisiemens per centimetro (mS/cm), compensata a 25 °C
  - Temperatura: gradi Celsius (°C)
  - Radiazione globale giornaliera: MJ/m² al giorno
  - Velocità vento: metri al secondo (m/s)
  - Pioggia: millimetri cumulati nelle 24 ore precedenti
  - pH: numero adimensionale 0..14
  - Umidità relativa aria: frazione adimensionale 0..1

Gli adapter concreti convertono dalle unità native del provider a queste
unità canoniche prima di costruire il Reading. Il chiamante di fitosim
non vede mai unità "esotiche" del singolo provider.

Convenzione dei timestamp
-------------------------

Tutti i timestamp sono `datetime` aware con timezone UTC. La conversione
a fuso locale per la presentazione è responsabilità del livello che
mostra i dati al giardiniere, non delle interfacce dei sensori. Questa
regola previene una classe intera di bug subdoli legati al fuso orario.

Validazione
-----------

I `__post_init__` controllano che i valori siano in range fisicamente
plausibili. Un valore fuori range solleva `SensorDataQualityError` con
diagnostica esplicita: questo intercetta i problemi *al confine* tra
provider esterno e fitosim, prima che si propaghino al modello.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from fitosim.io.sensors.errors import SensorDataQualityError


# --------------------------------------------------------------------------
#  ReadingQuality: metadati ortogonali alle misure fisiche
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadingQuality:
    """
    Metadati di qualità di una lettura, ortogonali alle misure fisiche.

    Vivono in un sotto-oggetto separato per non inquinare il namespace
    principale di EnvironmentReading e SoilReading. Chi non ne ha
    bisogno può tranquillamente ignorarli; chi vuole logging
    diagnostico avanzato (per esempio un dashboard che mostra "il tuo
    sensore X ha batteria al 15%, sostituiscila tra qualche giorno") li
    troverà qui.

    Tutti i campi sono opzionali perché molti sensori non espongono
    queste informazioni. L'assenza di un campo significa "il sensore
    non ce lo dice", non "il valore è zero".

    Attributi
    ---------
    battery_level : float | None
        Livello batteria del sensore wireless, frazione adimensionale
        0..1. None se il sensore è cablato o non espone questo dato.
    last_calibration : date | None
        Data dell'ultima calibrazione nota del sensore. Particolarmente
        rilevante per pH (drift di 0.1 unità ogni 6 mesi è normale).
    staleness_seconds : int
        Quanti secondi sono passati tra il momento della lettura
        effettiva del sensore e il momento in cui questo Reading è
        stato costruito. Per API cloud, è la differenza tra "ora del
        timestamp Ecowitt" e "now()" del nostro processo. Default 0
        per letture istantanee.
    """

    battery_level: Optional[float] = None
    last_calibration: Optional[date] = None
    staleness_seconds: int = 0

    def __post_init__(self) -> None:
        # Validazione range battery_level se presente.
        if self.battery_level is not None:
            if not 0.0 <= self.battery_level <= 1.0:
                raise SensorDataQualityError(
                    f"battery_level fuori range [0,1]: "
                    f"{self.battery_level}"
                )
        # staleness non può essere negativo (significherebbe lettura
        # dal futuro). Usiamo questa come sanity check sui dati di
        # configurazione del sensore (orologio del provider sballato).
        if self.staleness_seconds < 0:
            raise SensorDataQualityError(
                f"staleness_seconds negativo: {self.staleness_seconds} "
                f"(orologio del sensore sballato?)"
            )


# --------------------------------------------------------------------------
#  EnvironmentReading: misure meteorologiche (forzanti del modello)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EnvironmentReading:
    """
    Lettura strutturata di un sensore ambientale (meteorologico).

    Rappresenta le forzanti meteo di un singolo istante o di un singolo
    giorno (a seconda del contesto di chi la produce). I campi
    obbligatori sono il timestamp e almeno una misura fisica; tutti gli
    altri sono opzionali per accomodare provider con dati parziali.

    Per essere effettivamente utilizzabile come input di
    `apply_balance_step`, il Reading deve esporre almeno la temperatura
    dell'aria (per calcolare ET₀ via Hargreaves-Samani come fallback)
    oppure direttamente `et0_mm` se il provider la calcola già.

    Attributi
    ---------
    timestamp : datetime
        Istante di riferimento della lettura, timezone-aware in UTC.
    temperature_c : float | None
        Temperatura aria in gradi Celsius.
    humidity_relative : float | None
        Umidità relativa, frazione 0..1. NON percentuale 0..100.
    radiation_mj_m2 : float | None
        Radiazione globale giornaliera in MJ/m²/giorno. Usato dal
        Penman-Monteith completo (tappa 5 della fascia 2).
    wind_speed_m_s : float | None
        Velocità vento a 2 metri di altezza, in m/s.
    rain_mm : float | None
        Pioggia cumulata nelle 24 ore precedenti, in mm.
    et0_mm : float | None
        ET₀ giornaliera già calcolata dal provider, in mm. Open-Meteo
        la fornisce come `et0_fao_evapotranspiration`. Se assente,
        fitosim la calcola internamente da temperatura e radiazione.
    quality : ReadingQuality
        Metadati di qualità della lettura.
    """

    timestamp: datetime
    temperature_c: Optional[float] = None
    humidity_relative: Optional[float] = None
    radiation_mj_m2: Optional[float] = None
    wind_speed_m_s: Optional[float] = None
    rain_mm: Optional[float] = None
    et0_mm: Optional[float] = None
    quality: ReadingQuality = field(default_factory=ReadingQuality)

    def __post_init__(self) -> None:
        # Il timestamp deve essere timezone-aware. Naive datetime sono
        # vietati a livello architetturale: meglio fallire ora che
        # propagare ambiguità di fuso orario nel modello.
        if self.timestamp.tzinfo is None:
            raise SensorDataQualityError(
                f"timestamp deve essere timezone-aware (UTC), "
                f"ricevuto naive: {self.timestamp}"
            )

        # Range fisicamente plausibili. Sono volutamente larghi: vogliamo
        # accomodare condizioni estreme reali (sahara estivo, polo
        # nord), ma intercettare valori chiaramente spurii dei provider.
        if self.temperature_c is not None:
            if not -60.0 <= self.temperature_c <= 60.0:
                raise SensorDataQualityError(
                    f"temperature_c fuori range plausibile [-60,60]: "
                    f"{self.temperature_c}"
                )
        if self.humidity_relative is not None:
            if not 0.0 <= self.humidity_relative <= 1.0:
                raise SensorDataQualityError(
                    f"humidity_relative fuori range [0,1]: "
                    f"{self.humidity_relative} (forse è in percentuale?)"
                )
        if self.radiation_mj_m2 is not None:
            if not 0.0 <= self.radiation_mj_m2 <= 50.0:
                raise SensorDataQualityError(
                    f"radiation_mj_m2 fuori range plausibile [0,50]: "
                    f"{self.radiation_mj_m2}"
                )
        if self.wind_speed_m_s is not None:
            if not 0.0 <= self.wind_speed_m_s <= 100.0:
                raise SensorDataQualityError(
                    f"wind_speed_m_s fuori range plausibile [0,100]: "
                    f"{self.wind_speed_m_s}"
                )
        if self.rain_mm is not None:
            if not 0.0 <= self.rain_mm <= 500.0:
                raise SensorDataQualityError(
                    f"rain_mm fuori range plausibile [0,500]: "
                    f"{self.rain_mm}"
                )
        if self.et0_mm is not None:
            if not 0.0 <= self.et0_mm <= 25.0:
                raise SensorDataQualityError(
                    f"et0_mm fuori range plausibile [0,25]: "
                    f"{self.et0_mm}"
                )


# --------------------------------------------------------------------------
#  SoilReading: stato del substrato di un singolo vaso
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SoilReading:
    """
    Lettura strutturata di un sensore del suolo nel singolo vaso.

    A differenza di EnvironmentReading che è "una per giardino",
    SoilReading è "una per vaso": ogni sensore SoilSensor è associato
    a un canale specifico di un vaso specifico, e il suo stato non è
    trasferibile ad altri vasi anche adiacenti.

    L'unico campo obbligatorio (oltre al timestamp) è
    `theta_volumetric`: è il dato minimo che ogni sensore di suolo
    fornisce e che fitosim usa nel feedback loop di base. Tutti gli
    altri campi sono opzionali perché la "ricchezza" dei sensori varia:
    un WH51 dà solo θ, un ATO 7-in-1 dà θ+T+EC+pH.

    Attributi
    ---------
    timestamp : datetime
        Istante della lettura, timezone-aware in UTC.
    theta_volumetric : float
        Contenuto idrico volumetrico del substrato, frazione 0..1.
        OBBLIGATORIO. Il campo che fitosim usa per chiudere il
        feedback loop in `Pot.update_from_sensor`.
    temperature_c : float | None
        Temperatura del substrato in °C. Diversa dalla temperatura
        aria: in vasi al sole può superarla anche di 10-15 °C.
    ec_mscm : float | None
        Conducibilità elettrica della soluzione interstiziale, in
        mS/cm, compensata a 25 °C. Variabile primaria per il bilancio
        nutrizionale (tappa 3 fascia 2).
    ph : float | None
        Acidità del substrato, scala 0..14. Modula la disponibilità
        chimica dei nutrienti tramite il coefficiente Kn.
    quality : ReadingQuality
        Metadati di qualità della lettura.
    provider_specific : dict[str, Any]
        Campo aggiunto in tappa 2 della fascia 2 per ospitare dati
        "di secondo livello" che non sono variabili di stato del
        modello ma che il provider hardware può produrre. Esempio
        canonico: gli NPK derivati dell'ATO 7-in-1, che il firmware
        del sensore stima dall'EC misurata applicando una correlazione
        proprietaria. fitosim NON usa questi valori per la simulazione
        (la fertirrigazione della tappa 3 lavora su EC e pH come
        variabili primarie), ma li conserva qui per la presentazione
        nel dashboard del giardiniere e per il logging diagnostico.
        Default: dict vuoto. Il chiamante può passare un dict arbitrario
        di chiavi → valori; nessuna validazione viene applicata su
        questo campo perché il suo contenuto dipende dal provider.
    """

    timestamp: datetime
    theta_volumetric: float
    temperature_c: Optional[float] = None
    ec_mscm: Optional[float] = None
    ph: Optional[float] = None
    quality: ReadingQuality = field(default_factory=ReadingQuality)
    provider_specific: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Timestamp aware obbligatorio (stessa regola di
        # EnvironmentReading).
        if self.timestamp.tzinfo is None:
            raise SensorDataQualityError(
                f"timestamp deve essere timezone-aware (UTC), "
                f"ricevuto naive: {self.timestamp}"
            )

        # θ è obbligatorio e deve essere fisicamente plausibile. Range
        # leggermente più largo di [0,1] per tollerare piccoli rumori
        # dei sensori sopra la saturazione (alcuni TDR riportano 1.02
        # quando il substrato è satura) ma intercettare i veri errori.
        if not 0.0 <= self.theta_volumetric <= 1.05:
            raise SensorDataQualityError(
                f"theta_volumetric fuori range plausibile [0,1.05]: "
                f"{self.theta_volumetric} "
                f"(forse è in percentuale o sensore scollegato?)"
            )

        # Temperatura del substrato: range più stretto di quello
        # dell'aria perché i vasi sono protetti dalle escursioni
        # estreme. Sotto -20 o sopra 60 è quasi certamente un errore.
        if self.temperature_c is not None:
            if not -20.0 <= self.temperature_c <= 60.0:
                raise SensorDataQualityError(
                    f"temperature_c del substrato fuori range plausibile "
                    f"[-20,60]: {self.temperature_c}"
                )

        # EC: range largo perché i fertilizzanti concentrati possono
        # legittimamente alzare l'EC oltre 10 mS/cm in casi di flushing.
        if self.ec_mscm is not None:
            if not 0.0 <= self.ec_mscm <= 20.0:
                raise SensorDataQualityError(
                    f"ec_mscm fuori range plausibile [0,20]: "
                    f"{self.ec_mscm} (forse in μS/cm? va diviso per 1000)"
                )

        # pH: range fisico assoluto. Fuori da [0,14] è errore di
        # calibrazione del sensore.
        if self.ph is not None:
            if not 0.0 <= self.ph <= 14.0:
                raise SensorDataQualityError(
                    f"ph fuori range fisico [0,14]: {self.ph}"
                )


# --------------------------------------------------------------------------
#  Helper di costruzione: timestamp UTC corrente
# --------------------------------------------------------------------------

def utc_now() -> datetime:
    """
    Restituisce il timestamp corrente come datetime aware in UTC.

    Usata dagli adapter quando il provider non espone un timestamp
    proprio della lettura e si assume che sia "adesso". È preferibile
    a `datetime.now()` (che produce naive) e a `datetime.utcnow()`
    (deprecata in Python 3.12+).
    """
    return datetime.now(timezone.utc)
