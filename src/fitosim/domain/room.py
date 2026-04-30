"""
Modello del microclima indoor: la dataclass `Room` rappresenta lo
spazio fisico in cui vivono uno o più vasi indoor con il loro
microclima condiviso, e la dataclass `IndoorMicroclimate` incapsula
le letture meteo della stanza.

Perché esiste questo modulo
---------------------------

Il sensore WN31 di Ecowitt (e il suo gemello WH31, lo stesso prodotto
con due nomi commerciali) non è una sonda dedicata al singolo vaso
ma un trasmettitore ambientale che misura il microclima di una stanza
intera. Cinque vasi che condividono il salotto condividono lo stesso
microclima ambientale; un sesto vaso in camera da letto richiede un
secondo WN31 per quella stanza. Il modello di dominio rispecchia
questa fisica esplicitamente attraverso l'entità `Room`: una Room
rappresenta uno spazio fisico, un sensore WN31 alimenta una Room, e
i vasi indoor sono associati alla loro Room di appartenenza tramite
il campo `room_id` del Pot.

I vasi outdoor non hanno una Room e ignorano completamente questo
modulo: vivono nel meteo esterno comune al giardino e usano il
modello introdotto dalla sotto-tappa C (WeatherDay e
apply_balance_step_from_weather).

Distinzione tra `IndoorMicroclimate` e `WeatherDay`
---------------------------------------------------

Le due dataclass servono scopi paralleli ma in mondi diversi.
`WeatherDay` (in domain/weather.py) ospita i dati meteo grezzi che la
stazione Ecowitt outdoor produce: temperature minima e massima della
giornata, umidità relativa media, vento, radiazione solare globale.
`IndoorMicroclimate` ospita i dati meteo della stanza che il sensore
WN31 produce: temperatura e umidità relativa, con la possibilità di
distinguere tra dato istantaneo (per il dashboard) e dato giornaliero
(per il bilancio idrico).

La distinzione tra istantaneo e giornaliero è gestita tramite l'enum
`MicroclimateKind`: la stessa dataclass `IndoorMicroclimate` ospita
entrambi i casi, con un flag che dichiara qual è il tipo di lettura
e una validazione nel __post_init__ che assicura la coerenza tra
flag e campi popolati.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MicroclimateKind(Enum):
    """
    Tipo di lettura del microclima indoor.

    INSTANT: dato istantaneo "adesso", tipicamente recuperato dall'API
    real_time del sensore WN31. Serve principalmente al dashboard per
    mostrare lo stato corrente della stanza. I campi t_min e t_max
    devono essere None perché un singolo istante non ha minima/massima.

    DAILY: dato aggregato della giornata, tipicamente recuperato
    dall'API history o aggregation di Ecowitt. Serve al bilancio
    idrico giornaliero del Pot indoor. I campi t_min e t_max devono
    essere popolati e coerenti (t_min ≤ t_max) perché Penman-Monteith
    e Hargreaves li consumano.
    """

    INSTANT = "instant"
    DAILY = "daily"


@dataclass(frozen=True)
class IndoorMicroclimate:
    """
    Lettura del microclima di una stanza indoor.

    Incapsula i dati ambientali (temperatura, umidità) che il sensore
    WN31 produce, in una struttura immutabile e facile da passare in
    giro tra i livelli applicativi della libreria. Il flag `kind`
    distingue tra dato istantaneo (per il dashboard) e dato giornaliero
    (per il bilancio idrico), e il `__post_init__` valida la coerenza
    tra flag e campi popolati per evitare errori semantici nascosti.

    Per il caso INSTANT il chiamante popola `temperature_c` e
    `humidity_relative` con la lettura corrente, lasciando t_min e
    t_max a None. Esempio tipico:

        IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=22.3,
            humidity_relative=0.55,
        )

    Per il caso DAILY il chiamante popola tutti e quattro i campi
    termici (`temperature_c` come media giornaliera, `t_min` e `t_max`
    come estremi). Esempio tipico:

        IndoorMicroclimate(
            kind=MicroclimateKind.DAILY,
            temperature_c=21.0,
            humidity_relative=0.55,
            t_min=19.5, t_max=22.5,
        )

    Quando il chiamante recupera i dati storici dall'API Ecowitt
    (endpoint /device/history o /device/history/aggregation) ha
    naturalmente t_min e t_max disponibili. Quando invece dispone
    solo di una lettura istantanea (perché il sensore è stato
    interrogato in tempo reale), può popolare solo l'INSTANT.

    Campi
    -----
    kind : MicroclimateKind
        INSTANT o DAILY. Determina come gli altri campi devono essere
        popolati e come il consumatore deve interpretare la dataclass.
    temperature_c : float
        Temperatura, in °C. Per INSTANT è la lettura corrente; per
        DAILY è la media giornaliera (tipicamente (t_min + t_max) / 2,
        oppure la media oraria sulle 24 ore se disponibile dall'API).
    humidity_relative : float
        Umidità relativa come frazione 0..1 (NON percentuale).
    t_min : float, opzionale
        Temperatura minima giornaliera, in °C. Solo per kind=DAILY.
        Deve essere None per kind=INSTANT.
    t_max : float, opzionale
        Temperatura massima giornaliera, in °C. Solo per kind=DAILY.
        Deve essere None per kind=INSTANT.
    timestamp : datetime, opzionale
        Quando la lettura è stata effettuata. Solo per kind=INSTANT
        (per il dato giornaliero la "data" è l'intera giornata, non
        un istante). Default None.

    Solleva
    -------
    ValueError
        Nel __post_init__ se i campi popolati non sono coerenti col
        flag kind: per INSTANT non devono essere popolati t_min/t_max;
        per DAILY devono essere popolati e coerenti (t_min ≤ t_max).
        Anche se humidity_relative è fuori da [0, 1].
    """

    kind: MicroclimateKind
    temperature_c: float
    humidity_relative: float
    t_min: Optional[float] = None
    t_max: Optional[float] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Validazione dell'umidità (vincolo fisico universale,
        # indipendente dal kind).
        if not 0.0 <= self.humidity_relative <= 1.0:
            raise ValueError(
                f"humidity_relative={self.humidity_relative} deve essere "
                f"una frazione tra 0 e 1 (per il 55% passa 0.55, non 55)."
            )

        # Validazione della coerenza tra kind e campi termici.
        if self.kind == MicroclimateKind.INSTANT:
            # Per il dato istantaneo, t_min e t_max devono essere None
            # perché un singolo istante non ha minima/massima.
            if self.t_min is not None or self.t_max is not None:
                raise ValueError(
                    f"IndoorMicroclimate INSTANT non deve avere t_min/t_max "
                    f"popolati (ricevuti t_min={self.t_min}, t_max={self.t_max}). "
                    f"Per dati con minima/massima usa kind=DAILY."
                )
        elif self.kind == MicroclimateKind.DAILY:
            # Per il dato giornaliero, t_min e t_max devono essere
            # entrambi popolati e coerenti (min ≤ max).
            if self.t_min is None or self.t_max is None:
                raise ValueError(
                    f"IndoorMicroclimate DAILY richiede t_min e t_max "
                    f"popolati (ricevuti t_min={self.t_min}, t_max={self.t_max}). "
                    f"Per dati senza minima/massima usa kind=INSTANT."
                )
            if self.t_min > self.t_max:
                raise ValueError(
                    f"IndoorMicroclimate DAILY: t_min={self.t_min} deve "
                    f"essere ≤ t_max={self.t_max}."
                )


class LightExposure(Enum):
    """
    Livello qualitativo di esposizione luminosa di un vaso indoor.

    La radiazione solare che una pianta indoor riceve dipende dalla
    sua posizione rispetto alle finestre, dall'orientamento della
    finestra, da eventuali ombreggiamenti, e varia stagionalmente. Una
    modellazione a tempo continuo richiederebbe parametri che il
    giardiniere casalingo non conosce esattamente; l'enum a tre livelli
    cattura la varianza principale in modo qualitativo e attribuibile
    per osservazione diretta.

    DARK: vaso lontano dalle finestre o in stanza poco luminosa
    (esempio: Pothos in un angolo del salotto). Radiazione media
    indicativa: 1-2 MJ/m²/giorno.

    INDIRECT_BRIGHT: vaso vicino a una finestra ma senza sole diretto
    (esempio: basilico sul ripiano della cucina, lontano dalla
    finestra). Radiazione media indicativa: 3-5 MJ/m²/giorno.

    DIRECT_SUN: vaso sul davanzale di una finestra esposta a sud o
    ovest, con qualche ora di sole diretto al giorno (esempio:
    rosmarino sul davanzale del salotto). Radiazione media indicativa:
    6-10 MJ/m²/giorno.

    I valori esatti delle radiazioni medie associate ai tre livelli
    saranno definiti nella fase D2 della sotto-tappa, dove il bilancio
    idrico indoor li userà come input al selettore di evapotraspirazione.
    """

    DARK = "dark"
    INDIRECT_BRIGHT = "indirect_bright"
    DIRECT_SUN = "direct_sun"


# Vento minimo convettivo per ambienti indoor: valore di letteratura
# agronomica per evitare che Penman-Monteith con vento zero produca
# evapotraspirazione irrealisticamente bassa. Anche in stanza chiusa
# c'è sempre un piccolo movimento d'aria dovuto a convezione termica,
# stimato intorno a 0.5 m/s in condizioni standard.
DEFAULT_INDOOR_WIND_M_S = 0.5


@dataclass
class Room:
    """
    Spazio fisico indoor in cui vivono uno o più vasi con un microclima
    condiviso.

    La Room è l'entità di dominio che rappresenta una stanza (o una
    zona di una stanza) coperta da un singolo sensore WN31 ambientale.
    Tutti i vasi indoor in quella stanza condividono lo stesso
    microclima e quindi la stessa Room nel modello.

    L'identificatore univoco è il `room_id` (una stringa scelta dal
    chiamante, per esempio "salotto" o "camera-da-letto"). Il `name`
    è un'etichetta leggibile per UI e log. Il `wn31_channel_id` è
    l'eventuale ID del canale del sensore Ecowitt che alimenta questa
    Room (None se non c'è un sensore mappato).

    Il `current_microclimate` è uno stato MUTABILE che rappresenta
    l'ultima lettura istantanea del sensore (kind=INSTANT). Inizia a
    None e viene popolato dal chiamante (tipicamente il dashboard o
    l'orchestratore della libreria) quando si recuperano dati dal
    sensore. È mutabile perché evolve nel tempo, esattamente come lo
    stato idrico del Pot.

    Il `default_wind_m_s` è il vento minimo convettivo da usare per
    Penman-Monteith quando il chiamante non specifica un valore
    diverso. Il default 0.5 m/s riflette la pratica agronomica per
    ambienti indoor; il chiamante può sovrascrivere se ha un
    ventilatore acceso costantemente o se conosce il valore reale del
    vento medio della stanza.

    Attributi
    ---------
    room_id : str
        Identificatore univoco della Room nel giardino. Usato dal Pot
        per associarsi tramite il proprio campo `room_id`.
    name : str
        Nome leggibile per UI e log (es. "salotto", "camera da letto").
    wn31_channel_id : str | None, opzionale
        ID del canale del sensore Ecowitt WN31 che alimenta questa
        Room. None se non c'è un sensore mappato (la Room esiste ma
        i dati vengono dal chiamante manualmente). Default None.
    current_microclimate : IndoorMicroclimate | None, opzionale
        Ultima lettura istantanea del microclima della stanza
        (kind=INSTANT). None all'inizio, popolato dal chiamante via
        update_current_microclimate. MUTABILE.
    default_wind_m_s : float, opzionale
        Vento minimo convettivo della stanza, in m/s. Default 0.5
        (pratica agronomica indoor). Sovrascrivibile dal chiamante.

    Mutabilità
    ----------
    A differenza di Pot e Species (frozen), Room è una dataclass
    mutabile perché il campo `current_microclimate` evolve nel tempo
    a ogni nuova lettura del sensore. Il pattern di mutazione è
    centralizzato nel metodo `update_current_microclimate` per
    facilitare il tracciamento del flusso di dati.
    """

    room_id: str
    name: str
    wn31_channel_id: Optional[str] = None
    current_microclimate: Optional[IndoorMicroclimate] = None
    default_wind_m_s: float = DEFAULT_INDOOR_WIND_M_S

    def __post_init__(self) -> None:
        if not self.room_id:
            raise ValueError(
                f"Room: room_id non può essere vuoto."
            )
        if self.default_wind_m_s < 0:
            raise ValueError(
                f"Room '{self.room_id}': default_wind_m_s deve essere "
                f"non-negativo (ricevuto {self.default_wind_m_s})."
            )

    def update_current_microclimate(
        self, microclimate: IndoorMicroclimate,
    ) -> None:
        """
        Aggiorna l'ultima lettura istantanea del microclima della stanza.

        Accetta solo dataclass con kind=INSTANT, perché il
        current_microclimate rappresenta lo stato "adesso" della
        stanza, non un dato aggregato giornaliero. Per il dato
        giornaliero usato dal bilancio idrico vedi la fase D2.

        Parametri
        ---------
        microclimate : IndoorMicroclimate
            Nuova lettura della stanza. Deve avere kind=INSTANT.

        Solleva
        -------
        ValueError
            Se microclimate.kind non è INSTANT.
        """
        if microclimate.kind != MicroclimateKind.INSTANT:
            raise ValueError(
                f"Room '{self.room_id}': update_current_microclimate "
                f"richiede kind=INSTANT (ricevuto {microclimate.kind.value}). "
                f"Per dati giornalieri usa il bilancio idrico, non il "
                f"current_microclimate."
            )
        self.current_microclimate = microclimate
