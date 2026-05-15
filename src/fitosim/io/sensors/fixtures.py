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
from fitosim.io.sensors.measurement import (
    CUSTOM_NAMESPACE_PREFIX,
    Measurement,
    PARAM_AIR_HUMIDITY,
    PARAM_AIR_TEMPERATURE_C,
    PARAM_RAINFALL_MM,
    PARAM_SOIL_EC_MSCM,
    PARAM_SOIL_PH,
    PARAM_SOIL_TEMPERATURE_C,
    PARAM_SOIL_THETA,
    PARAM_SOLAR_RADIATION_MJ_M2,
    PARAM_WIND_SPEED_M_S,
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

    Formato di ritorno (spec sensori v1)
    ------------------------------------

    La fixture produce **liste piatte di `Measurement`** canoniche.
    Ogni riga del CSV genera 1..N Measurement (una per parametro non
    vuoto), tutte con lo stesso `sensor_id` e `timestamp`. Mappatura
    delle colonne CSV → parametri canonici:

      - `t_min` + `t_max` → un'unica Measurement `air_temperature_c`
        con valore pari alla media (coerente con il vecchio
        comportamento di `OpenMeteoEnvironmentSensor`).
      - `rain_mm` → Measurement `rainfall_mm`.
      - `humidity` (opz.) → Measurement `air_humidity` (0..1).
      - `wind` (opz.) → Measurement `wind_speed_m_s`.
      - `radiation` (opz.) → Measurement `solar_radiation_mj_m2`.
      - `et0_mm` (opz.) → Measurement `custom:et0_mm` (ET₀ è un
        valore derivato, non canonico; viene preservato come
        extension per fixture che hanno ET₀ pre-calcolato da fonte
        autorevole tipo Open-Meteo Archive).

    Convenzioni
    -----------

      - Le date nel CSV devono essere in formato ISO `YYYY-MM-DD`.
      - Per ogni riga, le Measurement portano `timestamp` alle 12:00
        UTC del giorno (stessa convenzione di
        `OpenMeteoEnvironmentSensor` per coerenza).
      - I parametri `latitude` e `longitude` di `current_conditions()`
        e `forecast()` sono accettati per conformità al Protocol ma
        ignorati: il fixture restituisce sempre i dati del file,
        indipendentemente dalla posizione richiesta.
      - `sensor_id` di default è `csv_fixture:<filename_stem>` (es.
        `csv_fixture:weather_milan_2026`); l'utente può sovrascriverlo
        passando `sensor_id=...` al costruttore.

    Costruzione
    -----------

        fixture = CsvEnvironmentFixture("/path/to/weather.csv")
        fixture = CsvEnvironmentFixture(
            "/path/to/weather.csv",
            sensor_id="csv_fixture:milan_2026",
        )
    """

    # Parametro non canonico per ET₀ pre-calcolato: vive nel namespace
    # custom:* perché ET₀ non è una misura diretta del sensore.
    _PARAM_ET0_MM = f"{CUSTOM_NAMESPACE_PREFIX}et0_mm"

    def __init__(
        self,
        csv_path: Union[str, Path],
        sensor_id: Optional[str] = None,
    ) -> None:
        self._csv_path = Path(csv_path)
        if not self._csv_path.exists():
            raise SensorPermanentError(
                f"File CSV non trovato: {self._csv_path}",
                provider=PROVIDER_NAME,
            )
        # sensor_id opaco: convenzione raccomandata dalla spec sensori
        # v1 è `<provider>:<device_type>:<instance>`. Per la fixture,
        # `csv_fixture:<filename_stem>` è una scelta semplice e
        # diagnostica (l'utente può sovrascrivere).
        self._sensor_id = sensor_id or (
            f"{PROVIDER_NAME}:{self._csv_path.stem}"
        )
        # Indice {date: list[Measurement]} popolato al momento della
        # costruzione. Le Measurement di uno stesso giorno hanno tutte
        # lo stesso timestamp e sensor_id; cambia solo (parameter, value).
        self._measurements_by_date: dict[date, list[Measurement]] = {}
        self._load()

    @property
    def sensor_id(self) -> str:
        """Identificatore opaco usato in tutte le Measurement prodotte."""
        return self._sensor_id

    def _row_to_measurements(
        self, ts: datetime, row: dict[str, str],
    ) -> list[Measurement]:
        """Converte una riga CSV in una lista di Measurement.

        Le colonne assenti o vuote producono semplicemente meno
        Measurement nella lista (non Measurement con value=None: la
        spec sensori v1 richiede value obbligatorio float).
        """
        out: list[Measurement] = []

        # Temperatura: media di t_min e t_max se entrambi presenti.
        t_min = _parse_float_or_none(row.get("t_min", ""))
        t_max = _parse_float_or_none(row.get("t_max", ""))
        if t_min is not None and t_max is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_AIR_TEMPERATURE_C,
                value=(t_min + t_max) / 2.0,
            ))

        # Pioggia (obbligatoria a livello header, ma cella vuota
        # ammessa per giorni senza misura — produce zero Measurement).
        rain = _parse_float_or_none(row.get("rain_mm", ""))
        if rain is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_RAINFALL_MM,
                value=rain,
            ))

        # ET₀ pre-calcolato (custom:et0_mm) se presente.
        et0 = _parse_float_or_none(row.get("et0_mm", ""))
        if et0 is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=self._PARAM_ET0_MM,
                value=et0,
            ))

        # Umidità relativa (0..1) — opzionale.
        humidity = _parse_float_or_none(row.get("humidity", ""))
        if humidity is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_AIR_HUMIDITY,
                value=humidity,
            ))

        # Vento (m/s) — opzionale.
        wind = _parse_float_or_none(row.get("wind", ""))
        if wind is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_WIND_SPEED_M_S,
                value=wind,
            ))

        # Radiazione solare (MJ/m²/giorno) — opzionale.
        radiation = _parse_float_or_none(row.get("radiation", ""))
        if radiation is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_SOLAR_RADIATION_MJ_M2,
                value=radiation,
            ))

        return out

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

                ts = datetime.combine(
                    day, time(12, 0), tzinfo=timezone.utc,
                )
                self._measurements_by_date[day] = (
                    self._row_to_measurements(ts, row)
                )

        if not self._measurements_by_date:
            raise SensorPermanentError(
                f"CSV {self._csv_path} non contiene righe di dati.",
                provider=PROVIDER_NAME,
            )

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> list[Measurement]:
        """
        Restituisce tutte le Measurement della prima data del file
        (in ordine di data crescente).

        Per casi d'uso di test "voglio le condizioni di un giorno
        specifico" è preferibile usare `forecast()` con la data
        opportuna. `current_conditions()` qui ha un significato
        convenzionale di "il dato più antico nel file".
        """
        first_date = min(self._measurements_by_date.keys())
        return list(self._measurements_by_date[first_date])

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[Measurement]:
        """
        Restituisce una lista piatta di tutte le Measurement dei
        primi `days` giorni del file in ordine cronologico crescente.

        Per t_min, t_max, rain, et0 valorizzati la lunghezza è
        ~3-4 Measurement per giorno (3 se solo canonici, 4 se anche
        et0). Solleva `ValueError` se `days` supera il numero di
        righe disponibili nel CSV.
        """
        sorted_dates = sorted(self._measurements_by_date.keys())
        if days > len(sorted_dates):
            raise ValueError(
                f"Richiesti {days} giorni ma il CSV ne contiene "
                f"solo {len(sorted_dates)}."
            )
        out: list[Measurement] = []
        for d in sorted_dates[:days]:
            out.extend(self._measurements_by_date[d])
        return out


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
    l'attributo `measurements` che è una lista piatta di tutte le
    `Measurement` ordinate per (timestamp asc, parameter).

    Formato di ritorno (spec sensori v1)
    ------------------------------------

    Ogni riga del CSV genera 1..4 Measurement (una per parametro non
    vuoto), tutte con lo stesso `sensor_id` e `timestamp`. Mappatura
    delle colonne CSV → parametri canonici:

      - `theta_volumetric` (obbligatorio) → `soil_theta`.
      - `temperature_c` (opz.) → `soil_temperature_c`.
      - `ec_mscm` (opz.) → `soil_ec_mscm`.
      - `ph` (opz.) → `soil_ph`.

    Una riga con solo θ produce una sola Measurement; una riga
    completa di un WH52 ne produce tre (θ + T + EC, niente pH).

    Convenzioni di canale e identità
    --------------------------------

    Una fixture rappresenta un singolo canale (= un singolo vaso). Il
    parametro `channel_id` di `current_state()` è ignorato: la fixture
    restituisce sempre le sue letture indipendentemente da cosa il
    chiamante chiede. Per modellare più vasi, costruisci più fixture,
    una per file CSV. Il `sensor_id` di default è
    `csv_fixture:<filename_stem>`; l'utente può sovrascriverlo
    passando `sensor_id=...` al costruttore.

    Costruzione
    -----------

        fixture = CsvSoilFixture("/path/to/wh51_export.csv")
        fixture = CsvSoilFixture(
            "/path/to/wh51_export.csv",
            sensor_id="csv_fixture:basilico_balcone",
        )
    """

    def __init__(
        self,
        csv_path: Union[str, Path],
        sensor_id: Optional[str] = None,
    ) -> None:
        self._csv_path = Path(csv_path)
        if not self._csv_path.exists():
            raise SensorPermanentError(
                f"File CSV non trovato: {self._csv_path}",
                provider=PROVIDER_NAME,
            )
        self._sensor_id = sensor_id or (
            f"{PROVIDER_NAME}:{self._csv_path.stem}"
        )
        # Lista piatta di Measurement ordinata per (timestamp asc,
        # parameter). Esposta come attributo pubblico per consentire
        # iterazione (utile per calibrazione e replay storico).
        self.measurements: list[Measurement] = []
        # Timestamps distinti ordinati cronologicamente: serve a
        # current_state() per trovare velocemente il più recente
        # senza scandire l'intera lista.
        self._timestamps: list[datetime] = []
        self._load()

    @property
    def sensor_id(self) -> str:
        """Identificatore opaco usato in tutte le Measurement prodotte."""
        return self._sensor_id

    def _row_to_measurements(
        self, ts: datetime, theta: float, row: dict[str, str],
    ) -> list[Measurement]:
        """Converte una riga CSV in una lista di Measurement.

        θ è già stato parsato dal chiamante (è obbligatorio) e viene
        passato esplicitamente. Gli altri parametri vengono parsati
        qui e generano una Measurement solo se non vuoti.
        """
        out: list[Measurement] = [
            Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_SOIL_THETA,
                value=theta,
            ),
        ]

        temp = _parse_float_or_none(row.get("temperature_c", ""))
        if temp is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_SOIL_TEMPERATURE_C,
                value=temp,
            ))

        ec = _parse_float_or_none(row.get("ec_mscm", ""))
        if ec is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_SOIL_EC_MSCM,
                value=ec,
            ))

        ph = _parse_float_or_none(row.get("ph", ""))
        if ph is not None:
            out.append(Measurement(
                sensor_id=self._sensor_id,
                timestamp=ts,
                parameter=PARAM_SOIL_PH,
                value=ph,
            ))

        return out

    def _load(self) -> None:
        """Legge il CSV e popola la lista in memoria."""
        # Raggruppiamo le Measurement per timestamp durante il load,
        # così possiamo applicare l'ordinamento cronologico finale
        # anche se il CSV non è ordinato.
        by_ts: dict[datetime, list[Measurement]] = {}

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
                    # θ è obbligatorio: una riga senza θ è dati
                    # corrotti, non "dati mancanti opzionali".
                    raise SensorPermanentError(
                        f"Riga con timestamp {row['timestamp']} ha "
                        f"theta_volumetric vuoto. θ è obbligatorio.",
                        provider=PROVIDER_NAME,
                    )

                by_ts[ts] = self._row_to_measurements(ts, theta, row)

        if not by_ts:
            raise SensorPermanentError(
                f"CSV {self._csv_path} non contiene righe di dati.",
                provider=PROVIDER_NAME,
            )

        # Garantiamo l'ordinamento cronologico anche se il CSV non lo
        # avesse già. Per timestamp uguale (caso raro), l'ordine delle
        # Measurement è quello di `_row_to_measurements`: θ, T, EC, pH.
        self._timestamps = sorted(by_ts.keys())
        for ts in self._timestamps:
            self.measurements.extend(by_ts[ts])

    def current_state(self, channel_id: str) -> list[Measurement]:
        """
        Restituisce tutte le Measurement del timestamp più recente.

        Il parametro `channel_id` è ignorato (vedi docstring di classe):
        ogni fixture rappresenta un singolo canale, quindi il routing
        non è necessario.
        """
        latest_ts = self._timestamps[-1]
        return [m for m in self.measurements if m.timestamp == latest_ts]
