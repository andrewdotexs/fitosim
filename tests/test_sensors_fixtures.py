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

from datetime import datetime, timezone
from pathlib import Path

import pytest

from fitosim.io.sensors import (
    CsvEnvironmentFixture,
    CsvSoilFixture,
    EnvironmentSensor,
    SensorPermanentError,
    SoilSensor,
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
    """Caso felice di lettura CSV ambientale."""

    def test_loads_three_days_correctly(self, tmp_path):
        """File con 3 giorni → 3 Reading consecutivi."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
            "2026-05-03,11.0,19.0,8.0,3.1",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        readings = fixture.forecast(latitude=45.46, longitude=9.19, days=3)
        assert len(readings) == 3
        # La temperatura del primo giorno è la media (12+22)/2 = 17.0.
        assert readings[0].temperature_c == 17.0
        # Il timestamp è alle 12:00 UTC del giorno solare.
        assert readings[0].timestamp == datetime(
            2026, 5, 1, 12, 0, tzinfo=timezone.utc
        )

    def test_current_conditions_returns_first_day(self, tmp_path):
        """current_conditions ritorna il dato più antico del file."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-03,11.0,19.0,8.0,3.1",  # ordine non cronologico
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        reading = fixture.current_conditions(latitude=45.46, longitude=9.19)
        # Anche se il CSV è disordinato, current_conditions usa la
        # data più antica (2026-05-01).
        assert reading.timestamp.date().isoformat() == "2026-05-01"

    def test_forecast_respects_chronological_order(self, tmp_path):
        """forecast restituisce dati in ordine cronologico crescente
        anche se il CSV è disordinato."""
        csv_path = tmp_path / "weather.csv"
        _write_env_csv(csv_path, [
            "2026-05-03,11.0,19.0,8.0,3.1",
            "2026-05-01,12.0,22.0,0.0,4.2",
            "2026-05-02,13.5,24.5,2.5,4.8",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        readings = fixture.forecast(latitude=45.46, longitude=9.19, days=3)
        dates = [r.timestamp.date().isoformat() for r in readings]
        assert dates == ["2026-05-01", "2026-05-02", "2026-05-03"]

    def test_optional_columns_become_none(self, tmp_path):
        """Celle vuote per et0_mm diventano None nel Reading."""
        csv_path = tmp_path / "weather.csv"
        # Riga senza et0_mm (cella vuota).
        _write_env_csv(csv_path, [
            "2026-05-01,12.0,22.0,0.0,",
        ])
        fixture = CsvEnvironmentFixture(csv_path)
        readings = fixture.forecast(latitude=0, longitude=0, days=1)
        assert readings[0].et0_mm is None
        # Il rain è valorizzato.
        assert readings[0].rain_mm == 0.0


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
    """Caso felice di lettura CSV del suolo."""

    def test_loads_multiple_readings(self, tmp_path):
        """File con N letture → N elementi in self.readings."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, [
            "2026-05-01T08:00:00Z,0.42,18.5,1.5,6.5",
            "2026-05-01T09:00:00Z,0.41,18.7,1.5,6.5",
            "2026-05-01T10:00:00Z,0.40,19.0,1.5,6.5",
        ])
        fixture = CsvSoilFixture(csv_path)
        assert len(fixture.readings) == 3
        ts0, r0 = fixture.readings[0]
        assert r0.theta_volumetric == pytest.approx(0.42)
        assert r0.temperature_c == 18.5
        assert r0.ec_mscm == 1.5
        assert r0.ph == 6.5

    def test_current_state_returns_latest(self, tmp_path):
        """current_state ritorna l'ULTIMA lettura cronologicamente."""
        csv_path = tmp_path / "wh51.csv"
        # Ordine inverso nel CSV: deve venire ordinato cronologicamente.
        _write_soil_csv(csv_path, [
            "2026-05-01T10:00:00Z,0.40,,,",
            "2026-05-01T08:00:00Z,0.42,,,",
            "2026-05-01T09:00:00Z,0.41,,,",
        ])
        fixture = CsvSoilFixture(csv_path)
        # L'ultima cronologicamente è 10:00 con θ=0.40.
        reading = fixture.current_state(channel_id="ignored")
        assert reading.theta_volumetric == pytest.approx(0.40)

    def test_partial_columns_become_none(self, tmp_path):
        """Sensore tipo WH51 (solo θ): tutti gli altri campi vuoti
        nel CSV diventano None nel Reading."""
        csv_path = tmp_path / "wh51.csv"
        # Solo θ valorizzato, T/EC/pH vuoti come per il WH51 reale.
        _write_soil_csv(csv_path, [
            "2026-05-01T08:00:00Z,0.42,,,",
        ])
        fixture = CsvSoilFixture(csv_path)
        ts, r = fixture.readings[0]
        assert r.theta_volumetric == pytest.approx(0.42)
        assert r.temperature_c is None
        assert r.ec_mscm is None
        assert r.ph is None


class Test_CsvSoil_timestamp_parsing:
    """Parsing dei timestamp: formati supportati e regola UTC aware."""

    def test_z_suffix_parsed_as_utc(self, tmp_path):
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T08:00:00Z,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        ts, _ = fixture.readings[0]
        assert ts.tzinfo is not None
        assert ts == datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)

    def test_explicit_offset_parsed_correctly(self, tmp_path):
        """Offset +02:00 (CEST) viene preservato nel timestamp."""
        csv_path = tmp_path / "wh51.csv"
        _write_soil_csv(csv_path, ["2026-05-01T10:00:00+02:00,0.42,,,"])
        fixture = CsvSoilFixture(csv_path)
        ts, _ = fixture.readings[0]
        assert ts.tzinfo is not None
        # Convertito in UTC, +02:00 alle 10 corrisponde alle 8 UTC.
        assert ts.astimezone(timezone.utc) == datetime(
            2026, 5, 1, 8, 0, tzinfo=timezone.utc
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
