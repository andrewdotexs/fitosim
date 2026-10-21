"""
Strutture di dato per i dati meteo grezzi di un singolo giorno.

Questo modulo introduce la dataclass `WeatherDay`, che incapsula gli
ingredienti meteo che il modello scientifico consuma per calcolare
l'evapotraspirazione attraverso il selettore "best available" del
modulo `science/et0.py`.

La distinzione tra `WeatherDay` e `WeatherDayForecast` (che vive in
`scheduling.py`) merita un po' di attenzione perché le due dataclass
si somigliano in superficie ma servono scopi concettualmente diversi.

`WeatherDayForecast` è "previsione meteo aggregata per il forecast a
N giorni del Garden". Ha solo tre campi (data, ET₀ pre-calcolata,
pioggia) perché chi la usa è già in possesso di ET₀ pronta da
applicare al bilancio idrico, tipicamente dal forecast Open-Meteo
che la calcola al posto suo.

`WeatherDay` è invece "dati meteo grezzi di un singolo giorno", quelli
che la stazione Ecowitt sul balcone produce direttamente: temperature
minima e massima, umidità relativa, velocità del vento, radiazione
solare globale. Il chiamante che usa `WeatherDay` lascia al modello
scientifico (attraverso il selettore della sotto-tappa B) il compito
di trasformare questi dati grezzi in ET, scegliendo automaticamente
la formula migliore applicabile in funzione di quali dati sono
effettivamente disponibili.

Le due dataclass sono complementari, non concorrenti: il chiamante
sceglie quella adatta al proprio contesto. Chi ha già ET₀ calcolata
da un'altra fonte usa `WeatherDayForecast`. Chi ha dati meteo grezzi
e vuole che la libreria scelga la formula migliore usa `WeatherDay`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import pairwise
from typing import Optional


@dataclass(frozen=True)
class WeatherDay:
    """
    Dati meteo grezzi di un singolo giorno.

    Incapsula gli ingredienti che la stazione meteo (Ecowitt sul
    balcone, Open-Meteo come forecast, qualunque altra fonte) produce
    direttamente, in una struttura immutabile e facile da passare in
    giro tra i livelli applicativi della libreria.

    Le temperature minima e massima sono sempre obbligatorie perché
    sono il minimo richiesto dal fallback Hargreaves del selettore.
    I tre dati meteo aggiuntivi (umidità, vento, radiazione solare)
    sono opzionali: quando sono tutti presenti il selettore userà
    Penman-Monteith; quando uno o più mancano ricadrà su Hargreaves.

    Il campo `solar_radiation_mj_m2_day` contiene la radiazione globale
    Rs misurata dal piranometro (la quantità che la stazione meteo
    riporta direttamente), non la radiazione netta Rn richiesta da
    Penman-Monteith. La conversione da Rs a Rn richiede temperatura,
    umidità e quota del sito, ed è eseguita internamente dal codice
    che consuma `WeatherDay` (per esempio dal `Pot.apply_balance_step_from_weather`)
    invece di essere richiesta al chiamante.

    Campi
    -----
    date_ : date
        La data del giorno cui si riferiscono i dati meteo. Usata per
        derivare il giorno dell'anno (1-366) richiesto dai calcoli
        astronomici della radiazione extra-atmosferica.
    t_min : float
        Temperatura minima giornaliera, in °C. Tipicamente registrata
        poco prima dell'alba.
    t_max : float
        Temperatura massima giornaliera, in °C. Tipicamente registrata
        nel primo pomeriggio.
    humidity_relative : float, opzionale
        Umidità relativa media giornaliera come frazione 0..1 (NON
        percentuale). Esempio: 65% di umidità si esprime come 0.65.
        Se None, il selettore non potrà usare Penman-Monteith e
        ricadrà su Hargreaves.
    wind_speed_m_s : float, opzionale
        Velocità del vento a 2 metri di altezza, in m/s. Stesso
        comportamento di humidity_relative quando assente.
    solar_radiation_mj_m2_day : float, opzionale
        Radiazione solare globale Rs, in MJ/m²/giorno. È la grandezza
        misurata direttamente dal piranometro. Stesso comportamento
        delle altre due quando assente.
    humidity_min, humidity_max : float, opzionali
        Le umidità relative minima e massima del giorno, frazioni 0..1
        (A9, 2026-10-21). Vanno insieme, o nessuna. Con loro la
        pressione di vapore attuale segue FAO-56 eq. 17; senza, l'eq. 19
        dalla media. Una stazione che campiona ogni quarto d'ora le ha;
        Open-Meteo le dà come aggregati del giorno.
    """

    date_: date
    t_min: float
    t_max: float
    humidity_relative: Optional[float] = None
    wind_speed_m_s: Optional[float] = None
    solar_radiation_mj_m2_day: Optional[float] = None
    humidity_min: float | None = None
    humidity_max: float | None = None

    def __post_init__(self) -> None:
        if self.t_min > self.t_max:
            raise ValueError(
                f"t_min ({self.t_min}) non può superare t_max ({self.t_max})."
            )
        if (self.humidity_min is None) != (self.humidity_max is None):
            raise ValueError(
                "humidity_min e humidity_max vanno date insieme, o nessuna delle due."
            )
        for nome in ("humidity_relative", "humidity_min", "humidity_max"):
            valore = getattr(self, nome)
            if valore is not None and not 0.0 <= valore <= 1.0:
                raise ValueError(
                    f"{nome} ({valore}) deve essere una frazione tra 0 e 1."
                )
        if (
            self.humidity_min is not None
            and self.humidity_max is not None
            and self.humidity_min > self.humidity_max
        ):
            raise ValueError(
                f"humidity_min ({self.humidity_min}) non può superare "
                f"humidity_max ({self.humidity_max})."
            )

    @property
    def has_full_weather(self) -> bool:
        """
        True se tutti e tre i dati meteo aggiuntivi sono presenti, cioè
        se i dati sono "completi" per Penman-Monteith. Utile come
        sanity check rapido senza dover ispezionare i tre campi
        individualmente.
        """
        return (
            self.humidity_relative is not None
            and self.wind_speed_m_s is not None
            and self.solar_radiation_mj_m2_day is not None
        )


# =====================================================================
#  Il giorno fatto di blocchi (A7, 2026-09-29): il meteo di un blocco
#  di ore, e come si ottiene dai campioni di una stazione. Il giorno
#  aggregato dai blocchi (`weather_day_from_blocks`) è un WeatherDay
#  come gli altri: il cammino giornaliero non sa da dove viene. Il
#  disegno e le decisioni sono in `domain/blocks.py`.
# =====================================================================


@dataclass(frozen=True)
class WeatherBlock:
    """
    Dati meteo di un blocco [start_hour, start_hour + hours) di un
    giorno, in ore intere di tempo civile *standard* del sito — senza
    ora legale, per l'Italia CET: è l'ora che FAO-56 vuole nelle
    formule orarie (eq. 31). Le medie del blocco per temperatura,
    umidità e vento; la somma per la radiazione, in MJ/m².

    Come per `WeatherDay`, la temperatura è obbligatoria e gli altri
    tre sono opzionali: con tutti e tre in tutti i blocchi del giorno
    l'ET₀ si calcola blocco per blocco (Penman-Monteith, FAO-56 eq. 53);
    altrimenti si calcola sul giorno e si ripartisce sui blocchi.

    Campi
    -----
    date_ : date
        Il giorno civile a cui il blocco appartiene.
    start_hour : int
        Ora d'inizio, 0..23.
    hours : int
        Durata in ore, ≥ 1, con start_hour + hours ≤ 24.
    t_c : float
        Temperatura media dell'aria nel blocco, in °C.
    humidity_relative : float, opzionale
        Umidità relativa media come frazione 0..1 (NON percentuale).
    wind_speed_m_s : float, opzionale
        Vento medio a 2 m, in m/s.
    solar_radiation_mj_m2 : float, opzionale
        Radiazione globale R_s caduta nel blocco, in MJ/m² (500 W/m²
        medi per un'ora sono 1.8 MJ/m²).
    """

    date_: date
    start_hour: int
    hours: int
    t_c: float
    humidity_relative: float | None = None
    wind_speed_m_s: float | None = None
    solar_radiation_mj_m2: float | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.start_hour < 24:
            raise ValueError(f"start_hour ({self.start_hour}) deve stare in [0, 24).")
        if self.hours < 1 or self.start_hour + self.hours > 24:
            raise ValueError(
                f"Il blocco [{self.start_hour}, {self.start_hour + self.hours}) "
                f"deve durare almeno un'ora e finire entro le 24."
            )
        if self.humidity_relative is not None and not 0.0 <= self.humidity_relative <= 1.0:
            raise ValueError(
                f"humidity_relative ({self.humidity_relative}) deve essere una "
                f"frazione tra 0 e 1 (per il 65% passa 0.65, non 65)."
            )
        if self.wind_speed_m_s is not None and self.wind_speed_m_s < 0:
            raise ValueError(f"wind_speed_m_s ({self.wind_speed_m_s}) deve essere ≥ 0.")
        if self.solar_radiation_mj_m2 is not None and self.solar_radiation_mj_m2 < 0:
            raise ValueError(
                f"solar_radiation_mj_m2 ({self.solar_radiation_mj_m2}) deve essere ≥ 0."
            )

    @property
    def end_hour(self) -> int:
        return self.start_hour + self.hours

    @property
    def has_full_weather(self) -> bool:
        """True se umidità, vento e radiazione ci sono tutti: Penman-Monteith può farsi."""
        return (
            self.humidity_relative is not None
            and self.wind_speed_m_s is not None
            and self.solar_radiation_mj_m2 is not None
        )


def validate_day_blocks(blocks: Sequence[WeatherBlock]) -> None:
    """
    I blocchi di un giorno: stesso giorno, contigui, da 0 a 24.
    Altrimenti ValueError con il punto in cui la copertura si rompe.
    """
    if not blocks:
        raise ValueError("Il giorno a blocchi ha bisogno di almeno un blocco.")
    day = blocks[0].date_
    if any(b.date_ != day for b in blocks):
        raise ValueError("I blocchi di un giorno devono avere tutti la stessa data.")
    if blocks[0].start_hour != 0:
        raise ValueError(f"Il primo blocco deve iniziare a 0, non a {blocks[0].start_hour}.")
    for prev, nxt in pairwise(blocks):
        if nxt.start_hour != prev.end_hour:
            raise ValueError(
                f"Buco o sovrapposizione fra i blocchi: [{prev.start_hour}, "
                f"{prev.end_hour}) e [{nxt.start_hour}, {nxt.end_hour})."
            )
    if blocks[-1].end_hour != 24:
        raise ValueError(f"L'ultimo blocco deve finire a 24, non a {blocks[-1].end_hour}.")


def weather_day_from_blocks(blocks: Sequence[WeatherBlock]) -> WeatherDay:
    """
    Il `WeatherDay` di un giorno fatto di blocchi: minima e massima
    delle temperature dei blocchi, medie pesate sulla durata per
    umidità e vento, somma della radiazione. Un campo opzionale che
    manca anche in un solo blocco manca nel giorno: il selettore di
    `science/et0.py` ricadrà su Hargreaves come farebbe con la
    stazione che non lo misura.

    Le temperature dei blocchi sono medie: la minima e la massima del
    giorno che ne escono sono un po' più strette degli estremi veri
    che una stazione registra a 5 minuti (qualche decimo di grado).
    Lo stesso vale per le umidità estreme (A9), che escono dai blocchi
    quando tutti hanno l'umidità: la minima e la massima delle medie
    dei blocchi.
    """
    validate_day_blocks(blocks)
    total_hours = sum(b.hours for b in blocks)

    def weighted_mean(values: list[float | None]) -> float | None:
        if any(v is None for v in values):
            return None
        return sum(v * b.hours for v, b in zip(values, blocks)) / total_hours  # type: ignore[operator]

    solar = [b.solar_radiation_mj_m2 for b in blocks]
    humidities = [b.humidity_relative for b in blocks]
    return WeatherDay(
        date_=blocks[0].date_,
        t_min=min(b.t_c for b in blocks),
        t_max=max(b.t_c for b in blocks),
        humidity_relative=weighted_mean([b.humidity_relative for b in blocks]),
        wind_speed_m_s=weighted_mean([b.wind_speed_m_s for b in blocks]),
        solar_radiation_mj_m2_day=(
            None if any(s is None for s in solar) else sum(solar)  # type: ignore[arg-type]
        ),
        humidity_min=(None if any(h is None for h in humidities) else min(humidities)),  # type: ignore[type-var]
        humidity_max=(None if any(h is None for h in humidities) else max(humidities)),  # type: ignore[type-var]
    )


@dataclass(frozen=True)
class WeatherSample:
    """
    Un campione di una stazione meteo, all'istante `timestamp`
    (timezone-aware, qualunque fuso): la temperatura, l'umidità come
    frazione, il vento a 2 m e la radiazione come flusso istantaneo in
    W/m². Ogni campo può mancare; è `weather_blocks_from_samples` che
    li media nei blocchi.
    """

    timestamp: datetime
    t_c: float | None = None
    humidity_relative: float | None = None
    wind_speed_m_s: float | None = None
    solar_w_m2: float | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError(
                "WeatherSample.timestamp deve essere timezone-aware: i blocchi "
                "sono in ora civile standard del sito e serve sapere da dove si parte."
            )
        if self.humidity_relative is not None and not 0.0 <= self.humidity_relative <= 1.0:
            raise ValueError(
                f"humidity_relative ({self.humidity_relative}) deve essere una "
                f"frazione tra 0 e 1."
            )


def weather_blocks_from_samples(
    samples: Iterable[WeatherSample],
    hours: int,
    utc_offset_hours: float,
) -> list[WeatherBlock]:
    """
    Raggruppa i campioni di una stazione in blocchi di `hours` ore
    (un divisore di 24) in tempo civile standard del sito, e ne fa i
    `WeatherBlock`: media di temperatura, umidità e vento sui campioni
    che li hanno; radiazione integrata come flusso medio × durata
    (campioni a cadenza regolare, come lo storico Ecowitt a 5 minuti).

    Un blocco nasce solo se ha almeno una temperatura; un campo che
    nessun campione del blocco ha resta None. I blocchi tornano
    ordinati per giorno e ora; se coprono il giorno intero lo decide
    chi li usa (`validate_day_blocks`).

    `utc_offset_hours` è il fuso standard del sito (1 per l'Italia),
    senza ora legale: un campione delle 23:30 UTC del 13 settembre
    finisce nel blocco delle 0 del 14.
    """
    if hours < 1 or 24 % hours != 0:
        raise ValueError(
            f"hours ({hours}) deve essere un divisore di 24: i blocchi devono "
            f"coprire il giorno senza avanzi."
        )
    groups: dict[tuple[date, int], list[WeatherSample]] = {}
    for sample in samples:
        local = sample.timestamp.astimezone(timezone.utc) + timedelta(hours=utc_offset_hours)
        key = (local.date(), (local.hour // hours) * hours)
        groups.setdefault(key, []).append(sample)

    def mean(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return sum(present) / len(present) if present else None

    blocks: list[WeatherBlock] = []
    for (day, start_hour), group in sorted(groups.items()):
        t_c = mean([s.t_c for s in group])
        if t_c is None:
            continue
        solar_w = mean([s.solar_w_m2 for s in group])
        blocks.append(WeatherBlock(
            date_=day,
            start_hour=start_hour,
            hours=hours,
            t_c=t_c,
            humidity_relative=mean([s.humidity_relative for s in group]),
            wind_speed_m_s=mean([s.wind_speed_m_s for s in group]),
            solar_radiation_mj_m2=(
                None if solar_w is None else solar_w * hours * 3600.0 / 1e6
            ),
        ))
    return blocks
