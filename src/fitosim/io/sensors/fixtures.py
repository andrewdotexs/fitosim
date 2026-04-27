"""
Fixture CSV per replicare scenari storici nei test di fitosim.

Questo modulo NON contiene adapter operativi: i due classi qui
definite, `CsvEnvironmentFixture` e `CsvSoilFixture`, sono strumenti di
**laboratorio** che leggono dati da file CSV per replicare scenari
storici controllati. La distinzione è importante:

  - Gli adapter operativi (`OpenMeteoEnvironmentSensor`,
    `EcowittEnvironmentSensor`, `EcowittWH51SoilSensor`) lavorano con
    sorgenti API live e gestiscono problemi di rete, autenticazione,
    rate limiting. Sono pensati per il sistema in esecuzione.

  - I fixture CSV invece sono **deterministici e offline**: leggono
    da un file locale, non hanno failure mode di rete, e producono
    sempre gli stessi dati ad ogni esecuzione. Sono pensati per
    test riproducibili, demo dimostrative, e backfilling di
    simulazioni storiche.

Il segnaposto "fixture" nel nome riflette questa intenzione: in pytest
le fixture sono dati di test predefiniti, e questo è esattamente lo
spirito qui. Il loro posto naturale è in test e demo, NON in produzione.

Formato dei file CSV
--------------------

`CsvEnvironmentFixture` legge file con queste colonne minime:

    date,t_min,t_max,rain_mm[,et0_mm,humidity,wind,radiation]

Tutte le colonne dopo `rain_mm` sono opzionali. Esempio::

    date,t_min,t_max,rain_mm,et0_mm
    2026-05-01,12.0,22.0,0.0,4.2
    2026-05-02,13.5,24.5,2.5,4.8

`CsvSoilFixture` legge file con queste colonne minime:

    timestamp,theta_volumetric[,temperature_c,ec_mscm,ph]

Esempio::

    timestamp,theta_volumetric,ec_mscm
    2026-05-01T08:00:00Z,0.42,1.5
    2026-05-01T09:00:00Z,0.41,1.5

Il timestamp deve essere in formato ISO8601 con suffix di timezone
(`Z` per UTC o offset esplicito tipo `+02:00`). I naive datetime sono
rifiutati per coerenza con la regola architetturale.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Optional, Union

from fitosim.io.sensors.errors import (
    SensorPermanentError,
)
from fitosim.io.sensors.types import (
    EnvironmentReading,
    ReadingQuality,
    SoilReading,
)


PROVIDER_NAME = "csv_fixture"


# --------------------------------------------------------------------------
#  Helper di parsing
# --------------------------------------------------------------------------

def _parse_float_or_none(value: str) -> Optional[float]:
    """
    Parsa un campo CSV come float, o ritorna None se vuoto/non
    interpretabile.

    Le righe CSV reali spesso hanno celle vuote per campi opzionali
    ("2026-05-01,12.0,22.0,,4.2" → niente pioggia ma c'è ET₀). Tratti
    queste celle come "dato mancante" anziché come errore.
    """
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_iso_timestamp(value: str) -> datetime:
    """
    Parsa un timestamp ISO8601 in datetime aware UTC.

    Accetta i formati:
      - "2026-05-01T12:00:00Z" (Z per UTC)
      - "2026-05-01T14:00:00+02:00" (offset esplicito)
      - "2026-05-01 12:00:00+00:00" (spazio invece di T)

    Solleva SensorPermanentError per timestamp naive (senza timezone)
    o malformati.
    """
    # Python 3.11+ accetta "Z" direttamente in fromisoformat. Per
    # compatibilità con versioni precedenti, lo sostituiamo manualmente.
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(cleaned)
    except ValueError as e:
        raise SensorPermanentError(
            f"Timestamp non parsabile: '{value}'. "
            f"Formato atteso ISO8601 con timezone (es. "
            f"'2026-05-01T12:00:00Z' o '2026-05-01T14:00:00+02:00').",
            provider=PROVIDER_NAME,
        ) from e

    if ts.tzinfo is None:
        raise SensorPermanentError(
            f"Timestamp '{value}' senza timezone: i naive datetime non "
            f"sono ammessi nei fixture CSV. Aggiungi 'Z' (UTC) o un "
            f"offset esplicito tipo '+02:00'.",
            provider=PROVIDER_NAME,
        )

    return ts


# --------------------------------------------------------------------------
#  CsvEnvironmentFixture
# --------------------------------------------------------------------------

class CsvEnvironmentFixture:
    """
    Fixture di EnvironmentSensor che legge dati meteo da file CSV.

    Strumento di test e di backfilling: dato un CSV con dati storici
    o sintetici, espone le stesse interfacce di un EnvironmentSensor
    operativo, in modo che il codice utilizzatore possa essere
    testato senza dipendere dal cloud.

    Il file viene letto interamente in memoria al momento della
    costruzione e indicizzato per data. Le chiamate successive a
    `current_conditions()` e `forecast()` lavorano sull'indice in
    memoria senza tornare a leggere il file.

    Convenzioni
    -----------

      - Le date nel CSV devono essere in formato ISO `YYYY-MM-DD`.
      - Per ogni riga, viene costruito un EnvironmentReading con
        timestamp alle 12:00 UTC del giorno (stessa convenzione di
        OpenMeteoEnvironmentSensor per coerenza).
      - I parametri `latitude` e `longitude` di `current_conditions()`
        e `forecast()` sono accettati per conformità al Protocol ma
        ignorati: il fixture restituisce sempre i dati del file,
        indipendentemente dalla posizione richiesta.

    Costruzione
    -----------

        fixture = CsvEnvironmentFixture("/path/to/weather.csv")
        # oppure con pathlib.Path:
        fixture = CsvEnvironmentFixture(Path("weather.csv"))
    """

    def __init__(self, csv_path: Union[str, Path]) -> None:
        self._csv_path = Path(csv_path)
        if not self._csv_path.exists():
            raise SensorPermanentError(
                f"File CSV non trovato: {self._csv_path}",
                provider=PROVIDER_NAME,
            )
        # Indice {date: EnvironmentReading} popolato al momento della
        # costruzione. Memoria modesta (un Reading è qualche centinaio
        # di byte; 365 giorni = ~150 KB).
        self._readings_by_date: dict[date, EnvironmentReading] = {}
        self._load()

    def _load(self) -> None:
        """Legge il CSV e popola l'indice in memoria."""
        with self._csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise SensorPermanentError(
                    f"CSV vuoto o senza header: {self._csv_path}",
                    provider=PROVIDER_NAME,
                )
            # Verifica colonne minime obbligatorie.
            required = {"date", "t_min", "t_max", "rain_mm"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise SensorPermanentError(
                    f"CSV {self._csv_path} manca colonne obbligatorie: "
                    f"{sorted(missing)}. Colonne minime richieste: "
                    f"{sorted(required)}.",
                    provider=PROVIDER_NAME,
                )

            for row in reader:
                try:
                    day = date.fromisoformat(row["date"])
                except ValueError as e:
                    raise SensorPermanentError(
                        f"Data non parsabile: '{row['date']}'. "
                        f"Formato atteso 'YYYY-MM-DD'.",
                        provider=PROVIDER_NAME,
                    ) from e

                t_min = _parse_float_or_none(row["t_min"])
                t_max = _parse_float_or_none(row["t_max"])
                # Temperatura media calcolata se entrambi presenti,
                # come per OpenMeteoEnvironmentSensor.
                temp_mean = None
                if t_min is not None and t_max is not None:
                    temp_mean = (t_min + t_max) / 2.0

                reading = EnvironmentReading(
                    timestamp=datetime.combine(
                        day, time(12, 0), tzinfo=timezone.utc,
                    ),
                    temperature_c=temp_mean,
                    rain_mm=_parse_float_or_none(row["rain_mm"]),
                    et0_mm=_parse_float_or_none(row.get("et0_mm", "")),
                    humidity_relative=_parse_float_or_none(
                        row.get("humidity", "")
                    ),
                    wind_speed_m_s=_parse_float_or_none(
                        row.get("wind", "")
                    ),
                    radiation_mj_m2=_parse_float_or_none(
                        row.get("radiation", "")
                    ),
                    quality=ReadingQuality(),
                )
                self._readings_by_date[day] = reading

        if not self._readings_by_date:
            raise SensorPermanentError(
                f"CSV {self._csv_path} non contiene righe di dati.",
                provider=PROVIDER_NAME,
            )

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> EnvironmentReading:
        """
        Restituisce il primo Reading del file (in ordine di data
        crescente).

        Per casi d'uso di test "voglio le condizioni di un giorno
        specifico" è preferibile usare `forecast()` con la data
        opportuna. `current_conditions()` qui ha un significato
        convenzionale di "il dato più antico nel file".
        """
        first_date = min(self._readings_by_date.keys())
        return self._readings_by_date[first_date]

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[EnvironmentReading]:
        """
        Restituisce i primi `days` Reading del file in ordine
        cronologico crescente.

        Solleva ValueError se `days` supera il numero di righe
        disponibili nel CSV.
        """
        sorted_dates = sorted(self._readings_by_date.keys())
        if days > len(sorted_dates):
            raise ValueError(
                f"Richiesti {days} giorni ma il CSV ne contiene "
                f"solo {len(sorted_dates)}."
            )
        return [
            self._readings_by_date[d] for d in sorted_dates[:days]
        ]


# --------------------------------------------------------------------------
#  CsvSoilFixture
# --------------------------------------------------------------------------

class CsvSoilFixture:
    """
    Fixture di SoilSensor che legge dati di umidità del substrato da
    file CSV.

    Caso d'uso paradigmatico: hai esportato dalla tua stazione Ecowitt
    sei mesi di letture WH51 in un CSV, e vuoi farci girare la
    calibrazione empirica (capitolo 8 del manuale utente) o test
    riproducibili che usano dati storici reali. Costruisci la fixture
    sul CSV e la passi al codice come un qualsiasi SoilSensor.

    A differenza di CsvEnvironmentFixture (un valore al giorno), qui
    il file può contenere letture orarie o sub-orarie. La fixture
    espone l'ultima lettura disponibile come "current_state". Per usi
    più sofisticati che vogliono iterare sulla serie storica (per
    esempio per replicare uno scenario passato), usa direttamente
    l'attributo `readings` che è una lista di tuple (timestamp,
    SoilReading) ordinate cronologicamente.

    Convenzioni di canale
    ---------------------

    Una fixture rappresenta un singolo canale (= un singolo vaso). Il
    parametro `channel_id` di `current_state()` è ignorato: la fixture
    restituisce sempre le sue letture indipendentemente da cosa il
    chiamante chiede. Per modellare più vasi, costruisci più fixture,
    una per file CSV.

    Costruzione
    -----------

        fixture = CsvSoilFixture("/path/to/wh51_export.csv")
    """

    def __init__(self, csv_path: Union[str, Path]) -> None:
        self._csv_path = Path(csv_path)
        if not self._csv_path.exists():
            raise SensorPermanentError(
                f"File CSV non trovato: {self._csv_path}",
                provider=PROVIDER_NAME,
            )
        # Lista (timestamp, SoilReading) ordinata cronologicamente.
        # Esposta come attributo pubblico per consentire iterazione.
        self.readings: list[tuple[datetime, SoilReading]] = []
        self._load()

    def _load(self) -> None:
        """Legge il CSV e popola la lista in memoria."""
        with self._csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise SensorPermanentError(
                    f"CSV vuoto o senza header: {self._csv_path}",
                    provider=PROVIDER_NAME,
                )
            required = {"timestamp", "theta_volumetric"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise SensorPermanentError(
                    f"CSV {self._csv_path} manca colonne obbligatorie: "
                    f"{sorted(missing)}. Colonne minime richieste: "
                    f"{sorted(required)}.",
                    provider=PROVIDER_NAME,
                )

            for row in reader:
                ts = _parse_iso_timestamp(row["timestamp"])
                theta = _parse_float_or_none(row["theta_volumetric"])
                if theta is None:
                    # θ è obbligatorio: una riga senza θ è dati corrotti,
                    # non "dati mancanti opzionali".
                    raise SensorPermanentError(
                        f"Riga con timestamp {row['timestamp']} ha "
                        f"theta_volumetric vuoto. θ è obbligatorio.",
                        provider=PROVIDER_NAME,
                    )

                reading = SoilReading(
                    timestamp=ts,
                    theta_volumetric=theta,
                    temperature_c=_parse_float_or_none(
                        row.get("temperature_c", "")
                    ),
                    ec_mscm=_parse_float_or_none(
                        row.get("ec_mscm", "")
                    ),
                    ph=_parse_float_or_none(row.get("ph", "")),
                    quality=ReadingQuality(),
                )
                self.readings.append((ts, reading))

        if not self.readings:
            raise SensorPermanentError(
                f"CSV {self._csv_path} non contiene righe di dati.",
                provider=PROVIDER_NAME,
            )

        # Garantiamo l'ordinamento cronologico anche se il CSV non lo
        # avesse già. Diamo all'utente una garanzia esplicita.
        self.readings.sort(key=lambda pair: pair[0])

    def current_state(self, channel_id: str) -> SoilReading:
        """
        Restituisce l'ultima lettura disponibile (la più recente).

        Il parametro `channel_id` è ignorato (vedi docstring di classe):
        ogni fixture rappresenta un singolo canale, quindi il routing
        non è necessario.
        """
        return self.readings[-1][1]
