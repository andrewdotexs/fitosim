"""
Test delle fixture CsvEnvironmentFixture e CsvSoilFixture.

Strategia di test
-----------------

Le fixture CSV sono i nostri strumenti di laboratorio: leggono dati
deterministici da file invece di parlare con cloud. I test devono
validare:

  1. **Caso felice**: file ben formato → letture corrette in memoria.
  2. **Validazione struttura**: header mancante, colonne obbligatorie
     mancanti, file vuoto → errori esplicativi.
  3. **Parsing timestamp**: formati ISO accettati (Z e offset
     espliciti), naive datetime rifiutati per regola architetturale.
  4. **Campi opzionali**: celle vuote diventano None nei Reading.
  5. **Conformità Protocol**: le fixture soddisfano EnvironmentSensor
     e SoilSensor rispettivamente.

Costruiamo i CSV su disco usando la fixture pytest `tmp_path`, che
crea una directory temporanea pulita per ogni test ed elimina
automaticamente il contenuto al termine.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from fitosim.io.sensors import (
    CsvEnvironmentFixture,
    CsvSoilFixture,
    EnvironmentSensor,
    Measurement,
    SensorPermanentError,
    SoilSensor,
)
from fitosim.io.sensors.measurement import (
    CUSTOM_NAMESPACE_PREFIX,
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


# --------------------------------------------------------------------------
#  Helper: scrittura di CSV minimi nei tmp_path dei test
# --------------------------------------------------------------------------

def _write_env_csv(path: Path, rows: list[str]) -> None:
    """Scrive un file CSV ambientale con le righe fornite."""
    content = "date,t_min,t_max,rain_mm,et0_mm\n" + "\n".join(rows)
    path.write_text(content, encoding="utf-8")


def _write_soil_csv(path: Path, rows: list[str]) -> None:
    """Scrive un file CSV di letture suolo con le righe fornite."""
    content = ("timestamp,theta_volumetric,temperature_c,ec_mscm,ph\n"
               + "\n".join(rows))
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------
#  CsvEnvironmentFixture: caso felice e API base
# --------------------------------------------------------------------------

class Test_CsvEnvironment_basic:
    """Caso felice di lettura CSV ambientale.

    Dopo la migrazione alla spec sensori v1, la fixture produce
    `list[Measurement]` invece di singoli `EnvironmentReading`. Ogni
    riga del CSV genera N Measurement (una per parametro non vuoto)
    con stesso `sensor_id` e `timestamp`.
    """

    def test_loads_three_days_correctly(self, tmp_path):
        """File con 3 giorni → 3 × N Measurement totali."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
            "2026-05-03,11.0,19.0,8.0,3.1",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.forecast(
            latitude=45.46, longitude=9.19, days=3,
        )
        # 3 giorni × 3 parametri (temp media + rain + et0 custom) = 9
        # Measurement totali.
        assert len(measurements) == 9

        # Filtro: temperatura del primo giorno = (12+22)/2 = 17.0.
        temp_first = [
            m for m in measurements
            if m.parameter == PARAM_AIR_TEMPERATURE_C
            and m.timestamp.date() == date(2026, 5, 1)
        ]
        assert len(temp_first) == 1
        assert temp_first[0].value == 17.0
        # Il timestamp è alle 12:00 UTC del giorno solare.
        assert temp_first[0].timestamp == datetime(
            2026, 5, 1, 12, 0, tzinfo=timezone.utc
        )

    def test_all_measurements_share_sensor_id(self, tmp_path):
        """Tutte le Measurement di una stessa fixture condividono lo
        stesso sensor_id (la fixture è una sorgente unica)."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.forecast(
            latitude=0, longitude=0, days=2,
        )
        sensor_ids = {m.sensor_id for m in measurements}
        assert sensor_ids == {fixture.sensor_id}

    def test_default_sensor_id_derives_from_filename(self, tmp_path):
        """Il sensor_id di default è `csv_fixture:<filename_stem>`."""
        csv_path = tmp_path / "weather_milan_2026.csv"
        _write_env_csv(csv_path, ["2026-05-01,12.0,22.0,0.0,4.2"])
        fixture = CsvEnvironmentFixture(csv_path)
        assert fixture.sensor_id == "csv_fixture:weather_milan_2026"

    def test_explicit_sensor_id_overrides_default(self, tmp_path):
        """L'utente può sovrascrivere il sensor_id dal costruttore."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, ["2026-05-01,12.0,22.0,0.0,4.2"])
        fixture = CsvEnvironmentFixture(
            csv_path, sensor_id="custom:fixture:vintage_2020",
        )
        assert fixture.sensor_id == "custom:fixture:vintage_2020"
        # E le Measurement prodotte usano l'override.
        ms = fixture.current_conditions(latitude=0, longitude=0)
        assert all(m.sensor_id == "custom:fixture:vintage_2020" for m in ms)

    def test_current_conditions_returns_first_day_measurements(
        self, tmp_path,
    ):
        """current_conditions ritorna tutte le Measurement della data
        più antica del file."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-03,11.0,19.0,8.0,3.1",  # ordine non cronologico
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.current_conditions(
            latitude=45.46, longitude=9.19,
        )
        # Tutte le Measurement hanno timestamp 2026-05-01 12:00 UTC.
        expected_ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        assert all(m.timestamp == expected_ts for m in measurements)
        # Per t_min=12, t_max=22, rain=0, et0=4.2: 3 Measurement.
        assert len(measurements) == 3

    def test_forecast_respects_chronological_order(self, tmp_path):
        """forecast restituisce Measurement in ordine cronologico
        crescente anche se il CSV è disordinato."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-03,11.0,19.0,8.0,3.1",
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.forecast(
            latitude=45.46, longitude=9.19, days=3,
        )
        # Estrai la sequenza di date uniche dai timestamp.
        unique_dates = []
        for m in measurements:
            d = m.timestamp.date().isoformat()
            if d not in unique_dates:
                unique_dates.append(d)
        assert unique_dates == ["2026-05-01", "2026-05-02", "2026-05-03"]

    def test_empty_et0_cell_omits_measurement(self, tmp_path):
        """Cella vuota per et0_mm → la Measurement custom:et0_mm NON
        viene prodotta (la spec sensori richiede value obbligatorio
        float, non None)."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-01,12.0,22.0,0.0,",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.forecast(latitude=0, longitude=0, days=1)
        # Per t_min+t_max+rain ma senza et0: 2 Measurement (temp+rain).
        assert len(measurements) == 2
        params = {m.parameter for m in measurements}
        assert PARAM_AIR_TEMPERATURE_C in params
        assert PARAM_RAINFALL_MM in params
        # Nessuna Measurement custom:et0_mm.
        assert all(
            not m.parameter.startswith(CUSTOM_NAMESPACE_PREFIX)
            for m in measurements
        )
        # Il rain è valorizzato a zero.
        rain = [m for m in measurements if m.parameter == PARAM_RAINFALL_MM]
        assert len(rain) == 1
        assert rain[0].value == 0.0

    def test_optional_columns_humidity_wind_radiation(self, tmp_path):
        """Se il CSV ha colonne extra (humidity, wind, radiation),
        producono le corrispondenti Measurement canoniche."""
        csv_path = tmp_path / "weather.csv"
        # Header esteso con tutte le colonne opzionali.
        content = (
            "date,t_min,t_max,rain_mm,et0_mm,humidity,wind,radiation\n"
            "2026-05-01,12.0,22.0,0.0,4.2,0.65,2.5,18.0\n"
        )
        csv_path.write_text(content, encoding="utf-8")
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.current_conditions(latitude=0, longitude=0)
        params = {m.parameter: m.value for m in measurements}
        assert params[PARAM_AIR_TEMPERATURE_C] == 17.0
        assert params[PARAM_RAINFALL_MM] == 0.0
        assert params[f"{CUSTOM_NAMESPACE_PREFIX}et0_mm"] == 4.2
        assert params[PARAM_AIR_HUMIDITY] == 0.65
        assert params[PARAM_WIND_SPEED_M_S] == 2.5
        assert params[PARAM_SOLAR_RADIATION_MJ_M2] == 18.0

    def test_measurements_are_typed_correctly(self, tmp_path):
        """Sanity check: l'output è davvero `list[Measurement]`."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, ["2026-05-01,12.0,22.0,0.0,4.2"])
        fixture = CsvEnvironmentFixture(csv_path)
        measurements = fixture.forecast(latitude=0, longitude=0, days=1)
        assert all(isinstance(m, Measurement) for m in measurements)


class Test_CsvEnvironment_validation:
    """Errori di struttura del CSV."""

    def test_missing_file_raises(self, tmp_path):
        """File inesistente → SensorPermanentError esplicito."""
        with pytest.raises(SensorPermanentError, match="non trovato"):
            CsvEnvironmentFixture(tmp_path / "nonexistent.csv")

    def test_empty_file_raises(self, tmp_path):
        """File vuoto (no header, no righe) → errore."""
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("", encoding="utf-8")
        with pytest.raises(SensorPermanentError, match="vuoto"):
            CsvEnvironmentFixture(csv_path)

    def test_missing_required_column_raises(self, tmp_path):
        """Colonna obbligatoria mancante → errore che la elenca."""
        csv_path = tmp_path / "weather.csv"
        # Manca rain_mm: il fixture deve segnalarlo per nome.
        csv_path.write_text(
            "date,t_min,t_max\n2026-05-01,12.0,22.0\n",
            encoding="utf-8",
        )
        with pytest.raises(SensorPermanentError, match="rain_mm"):
            CsvEnvironmentFixture(csv_path)

    def test_no_data_rows_raises(self, tmp_path):
        """File con header ma senza righe dati → errore esplicito."""
        csv_path = tmp_path / "weather.csv"
        csv_path.write_text(
            "date,t_min,t_max,rain_mm\n",  # solo header
            encoding="utf-8",
        )
        with pytest.raises(SensorPermanentError, match="non contiene righe"):
            CsvEnvironmentFixture(csv_path)

    def test_invalid_date_raises(self, tmp_path):
        """Data malformata → errore con suggerimento sul formato."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, ["not-a-date,12.0,22.0,0.0,4.2"])
        with pytest.raises(SensorPermanentError, match="non parsabile"):
            CsvEnvironmentFixture(csv_path)

    def test_forecast_too_many_days_raises(self, tmp_path):
        """Richiedere più giorni di quanti il CSV ne contiene → ValueError."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, ["2026-05-01,12.0,22.0,0.0,4.2"])
        fixture = CsvEnvironmentFixture(csv_path)
        with pytest.raises(ValueError, match="solo 1"):
            fixture.forecast(latitude=0, longitude=0, days=7)


class Test_CsvEnvironment_protocol:
    """La fixture soddisfa il Protocol EnvironmentSensor."""

    def test_isinstance_check(self, tmp_path):
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, ["2026-05-01,12.0,22.0,0.0,4.2"])
        fixture = CsvEnvironmentFixture(csv_path)
        assert isinstance(fixture, EnvironmentSensor)


# --------------------------------------------------------------------------
#  CsvSoilFixture: caso felice e API base
# --------------------------------------------------------------------------

class Test_CsvSoil_basic:
    """Caso felice di lettura CSV del suolo.

    Dopo la migrazione alla spec sensori v1, la fixture produce
    `list[Measurement]` invece di singoli `SoilReading`. Ogni riga
    del CSV genera 1..4 Measurement (una per parametro non vuoto)
    con stesso `sensor_id` e `timestamp`.
    """

    def test_loads_full_wh52_row_correctly(self, tmp_path):
        """File con 3 letture complete (WH52: θ, T, EC, pH) → 3×4=12
        Measurement in self.measurements."""
        csv_path = tmp_path / "wh52.csv"
        _write_soil_csv(csv_path, [
            "2026-05-01T08:00:00Z,0.42,18.5,1.5,6.5",
            "2026-05-01T09:00:00Z,0.41,18.7,1.5,6.5",
            "2026-05-01T10:00:00Z,0.40,19.0,1.5,6.5",
        ])
        fixture = CsvSoilFixture(csv_path)
        assert len(fixture.measurements) == 12

        # Filtro: tutte le Measurement del primo timestamp.
        ts0 = datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
        first = [m for m in fixture.measurements if m.timestamp == ts0]
        assert len(first) == 4
        # Indicizziamo per parametro per asserire i valori.
        by_param = {m.parameter: m.value for m in first}
        assert by_param[PARAM_SOIL_THETA] == pytest.approx(0.42)
        assert by_param[PARAM_SOIL_TEMPERATURE_C] == 18.5
        assert by_param[PARAM_SOIL_EC_MSCM] == 1.5
        assert by_param[PARAM_SOIL_PH] == 6.5

    def test_current_state_returns_latest_measurements(self, tmp_path):
        """current_state ritorna tutte le Measurement del timestamp
        più recente, anche se il CSV è disordinato."""
        csv_path = tmp_path / "wh51.csv"
        # Ordine inverso nel CSV: deve venire ordinato cronologicamente.
        _write_soil_csv(csv_path, [
            "2026-05-01T10:00:00Z,0.40,,,",
            "2026-05-01T08:00:00Z,0.42,,,",
            "2026-05-01T09:00:00Z,0.41,,,",
        ])
        fixture = CsvSoilFixture(csv_path)
        measurements = fixture.current_state(channel_id="ignored")
        # L'ultima cronologicamente è 10:00; il WH51 ha solo θ.
        assert len(measurements) == 1
        assert measurements[0].parameter == PARAM_SOIL_THETA
        assert measurements[0].value == pytest.approx(0.40)
        assert measurements[0].timestamp == datetime(
            2026, 5, 1, 10, 0, tzinfo=timezone.utc,
        )

    def test_wh51_only_theta_produces_one_measurement_per_row(
        self, tmp_path,
    ):
        """Sensore tipo WH51 (solo θ): cella vuota per T/EC/pH produce
        UNA Measurement per riga (anziché un SoilReading con campi
        None come prima)."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, [
            "2026-05-01T08:00:00Z,0.42,,,",
        ])
        fixture = CsvSoilFixture(csv_path)
        # Una sola Measurement: soil_theta.
        assert len(fixture.measurements) == 1
        m = fixture.measurements[0]
        assert m.parameter == PARAM_SOIL_THETA
        assert m.value == pytest.approx(0.42)

    def test_all_measurements_share_sensor_id(self, tmp_path):
        """Tutte le Measurement di una stessa fixture condividono lo
        stesso sensor_id."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, [
            "2026-05-01T08:00:00Z,0.42,18.0,1.5,6.5",
            "2026-05-01T09:00:00Z,0.41,18.1,1.5,6.5",
        ])
        fixture = CsvSoilFixture(csv_path)
        sensor_ids = {m.sensor_id for m in fixture.measurements}
        assert sensor_ids == {fixture.sensor_id}

    def test_default_sensor_id_derives_from_filename(self, tmp_path):
        """Il sensor_id di default è `csv_fixture:<filename_stem>`."""
        csv_path = tmp_path / "basilico_balcone_ch3.csv"
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        assert fixture.sensor_id == "csv_fixture:basilico_balcone_ch3"

    def test_explicit_sensor_id_overrides_default(self, tmp_path):
        """L'utente può sovrascrivere il sensor_id dal costruttore."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,0.42,,,"])
        fixture = CsvSoilFixture(
            csv_path, sensor_id="ecowitt:wh51:ch3",
        )
        assert fixture.sensor_id == "ecowitt:wh51:ch3"
        ms = fixture.current_state(channel_id="ignored")
        assert all(m.sensor_id == "ecowitt:wh51:ch3" for m in ms)

    def test_measurements_are_typed_correctly(self, tmp_path):
        """Sanity check: l'output è davvero `list[Measurement]`."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        ms = fixture.current_state(channel_id="ignored")
        assert all(isinstance(m, Measurement) for m in ms)
        assert all(isinstance(m, Measurement) for m in fixture.measurements)


class Test_CsvSoil_timestamp_parsing:
    """Parsing dei timestamp: formati supportati e regola UTC aware."""

    def test_z_suffix_parsed_as_utc(self, tmp_path):
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        m = fixture.measurements[0]
        assert m.timestamp.tzinfo is not None
        assert m.timestamp == datetime(
            2026, 5, 1, 8, 0, tzinfo=timezone.utc,
        )

    def test_explicit_offset_parsed_correctly(self, tmp_path):
        """Offset +02:00 (CEST) viene preservato nel timestamp."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T10:00:00+02:00,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        m = fixture.measurements[0]
        assert m.timestamp.tzinfo is not None
        # Convertito in UTC, +02:00 alle 10 corrisponde alle 8 UTC.
        assert m.timestamp.astimezone(timezone.utc) == datetime(
            2026, 5, 1, 8, 0, tzinfo=timezone.utc,
        )

    def test_naive_timestamp_rejected(self, tmp_path):
        """Regola architetturale: timestamp senza timezone → errore."""
        csv_path = tmp_path / "wh51.csv"
        # Niente Z, niente offset: naive datetime.
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00,0.42,,,"])
        with pytest.raises(SensorPermanentError, match="senza timezone"):
            CsvSoilFixture(csv_path)

    def test_malformed_timestamp_rejected(self, tmp_path):
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["non-un-timestamp,0.42,,,"])
        with pytest.raises(SensorPermanentError, match="non parsabile"):
            CsvSoilFixture(csv_path)


class Test_CsvSoil_validation:
    """Validazione struttura del CSV del suolo."""

    def test_missing_theta_in_row_rejected(self, tmp_path):
        """θ è obbligatorio: una riga senza θ è dato corrotto, non
        opzionale."""
        csv_path = tmp_path / "wh51.csv"
        # Cella θ vuota.
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,,18.5,,"])
        with pytest.raises(SensorPermanentError, match="theta_volumetric vuoto"):
            CsvSoilFixture(csv_path)

    def test_missing_required_column_rejected(self, tmp_path):
        """Header senza la colonna theta_volumetric → errore."""
        csv_path = tmp_path / "wh51.csv"
        csv_path.write_text(
            "timestamp,temperature_c\n"
            "2026-05-01T08:00:00Z,18.5\n",
            encoding="utf-8",
        )
        with pytest.raises(SensorPermanentError, match="theta_volumetric"):
            CsvSoilFixture(csv_path)


class Test_CsvSoil_protocol:
    """La fixture soddisfa il Protocol SoilSensor."""

    def test_isinstance_check(self, tmp_path):
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        assert isinstance(fixture, SoilSensor)
