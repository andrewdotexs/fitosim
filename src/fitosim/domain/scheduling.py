"""
Strutture per la pianificazione di eventi futuri e per le previsioni
meteorologiche utilizzate dal forecast.

Il modulo introduce nella sotto-tappa D della tappa 4 della fascia 2
due dataclass frozen che vivono nel layer del dominio:

  * ``ScheduledEvent``: un evento futuro pianificato per un vaso
    specifico (fertirrigazione del lunedì, trattamento del 15 maggio,
    rinvaso a fine giugno). È il duale "futuro" della tabella
    ``events`` della sotto-tappa B che invece registra la storia di
    eventi avvenuti.

  * ``WeatherDayForecast``: una previsione meteorologica per un
    singolo giorno futuro, con evapotraspirazione e pioggia.
    Il chiamante che usa Open-Meteo o un altro provider costruisce
    esplicitamente queste strutture dai dati grezzi del provider —
    fitosim non si lega a nessuna API specifica.

Filosofia di design
-------------------

Entrambe le dataclass sono **frozen** e quindi immutabili una volta
costruite. Per modificare un evento pianificato (per esempio
spostare una fertirrigazione di un giorno) il chiamante crea un
nuovo ``ScheduledEvent`` e sostituisce quello vecchio.

Queste strutture **non hanno un campo "status"**: un evento
pianificato esiste o non esiste. Quando il giardiniere reale fa
l'azione, può chiamare ``cancel_scheduled_event(...)`` per rimuovere
l'evento dal piano e poi ``record_event(...)`` per registrarlo come
storico. La separazione netta tra pianificato e storico è una
proprietà di design importante: i due concetti sono semanticamente
diversi e abitano tabelle/strutture diverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict


@dataclass(frozen=True)
class ScheduledEvent:
    """
    Evento futuro pianificato per un vaso specifico.

    Attributi
    ---------
    event_id : str
        Identificatore dell'evento. Il chiamante è libero di scegliere
        il formato: identificatore semantico (``"fertigation-basilico-1-2026-05-15"``),
        UUID, hash, ecc. Deve essere univoco all'interno del singolo
        vaso (vincolo di unicità ``UNIQUE(pot_id, event_id)`` nella
        persistenza SQLite). Lo stesso event_id può apparire in vasi
        diversi.

    pot_label : str
        La label del vaso a cui l'evento si riferisce. Deve essere
        una label di un vaso del giardino al momento in cui l'evento
        viene aggiunto, ma fitosim non controlla che il vaso continui
        a esistere quando l'evento "matura" — è responsabilità del
        chiamante mantenere coerenti vasi e piani.

    event_type : str
        Categoria dell'evento. Stringhe canoniche riconosciute dal
        ``Garden.forecast`` per la simulazione automatica:

          * ``"fertigation"`` — fertirrigazione, applicata dal forecast
          * ``"leaching"`` — bagnatura di lavaggio, applicata dal forecast

        Stringhe categoriali ammesse ma non simulate dal forecast
        (l'effetto fisiologico non è modellato in fitosim corrente):

          * ``"treatment"`` — trattamento antiparassitario o preventivo
          * ``"pruning"`` — potatura
          * ``"repotting"`` — rinvaso

        Il chiamante può usare event_type custom: il forecast li
        ignorerà (continuerà solo con et_0 e pioggia del meteo) ma
        ``events_due_today`` li riporterà comunque per il giardiniere.

    scheduled_date : date
        Data alla quale l'evento è pianificato. Eventi puntuali, una
        data per evento. Per modellare ricorrenze (es. ogni lunedì
        per 4 settimane) il chiamante crea N ScheduledEvent
        indipendenti — un helper di generazione di ricorrenze è una
        possibile estensione futura ma non è richiesto da fitosim
        corrente.

    payload : Dict[str, Any]
        Parametri specifici dell'evento. La struttura dipende
        dall'event_type:

          * ``fertigation`` richiede ``volume_l``, ``ec_mscm``, ``ph``;
            opzionale ``product`` (es. "BioBizz Bio-Grow").
          * ``leaching`` richiede ``volume_l`` e ``ec_mscm``;
            tipicamente acqua quasi pura (EC ~0.1 mS/cm).
          * Altri tipi: il payload è arbitrario, fitosim non lo
            interpreta ma lo conserva nelle strutture di persistenza.

        Il payload deve essere serializzabile in JSON (chiavi
        stringa, valori scalari/liste/dict annidati).
    """

    event_id: str
    pot_label: str
    event_type: str
    scheduled_date: date
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_id.strip():
            raise ValueError(
                "ScheduledEvent.event_id non può essere vuoto."
            )
        if not self.pot_label or not self.pot_label.strip():
            raise ValueError(
                "ScheduledEvent.pot_label non può essere vuoto."
            )
        if not self.event_type or not self.event_type.strip():
            raise ValueError(
                "ScheduledEvent.event_type non può essere vuoto."
            )


@dataclass(frozen=True)
class WeatherDayForecast:
    """
    Previsione meteorologica per un singolo giorno futuro.

    È la "valuta" che il chiamante passa al ``Garden.forecast`` per
    descrivere come si presume il meteo evolverà nei giorni di
    proiezione. Il chiamante costruisce queste strutture
    direttamente dai dati del provider meteo che usa (Open-Meteo,
    Ecowitt forecast, modelli locali), senza che fitosim si leghi a
    nessuna API specifica.

    Attributi
    ---------
    date_ : date
        Il giorno della previsione. Volutamente con underscore finale
        per non collidere con il modulo built-in `date`.

    et_0_mm : float
        Evapotraspirazione di riferimento prevista per il giorno, in
        mm. Non-negativa. Per il calcolo di un giorno tipico
        milanese può oscillare tra 1-2 mm (giorno coperto, basse
        temperature) e 6-8 mm (giorno estivo soleggiato e ventoso).

    rainfall_mm : float
        Pioggia prevista per il giorno, in mm. Non-negativa.
        Default 0.0 (giorno asciutto). Per Milano la media annua è
        circa 900 mm/anno, ma distribuita molto irregolarmente: la
        previsione di un singolo giorno è un dato volatile.
    """

    date_: date
    et_0_mm: float
    rainfall_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.et_0_mm < 0:
            raise ValueError(
                f"WeatherDayForecast.et_0_mm deve essere non-negativa "
                f"(ricevuto {self.et_0_mm})."
            )
        if self.rainfall_mm < 0:
            raise ValueError(
                f"WeatherDayForecast.rainfall_mm deve essere non-negativa "
                f"(ricevuto {self.rainfall_mm})."
            )
