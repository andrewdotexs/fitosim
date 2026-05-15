"""
Test dell'adapter OpenMeteoEnvironmentSensor.

Strategia di test
-----------------

L'adapter è essenzialmente un thin wrapper sopra `fetch_daily_forecast`
del modulo legacy. I test verificano due aree distinte:

  1. **Traduzione corretta**: dato un payload Open-Meteo valido, il
     Reading restituito ha i campi giusti, le unità giuste, il
     timestamp giusto.

  2. **Mapping delle eccezioni**: dato un fallimento di rete o di
     parsing, l'adapter solleva la nostra eccezione canonica giusta
     (Temporary vs Permanent), preservando la causa originale via
     `__cause__`.

Per evitare richieste HTTP reali, iniettiamo un fetcher mock tramite
il parametro `fetcher` di `fetch_daily_forecast`. Il fetcher mock è
una funzione che prende l'URL e restituisce un dict simulato.
"""

import urllib.error
from datetime import datetime, timezone

import pytest

from fitosim.io.openmeteo import fetch_daily_forecast
from fitosim.io.sensors import (
    Measurement,
    OpenMeteoEnvironmentSensor,
    SensorPermanentError,
    SensorTemporaryError,
)
from fitosim.io.sensors.measurement import (
    CUSTOM_NAMESPACE_PREFIX,
    PARAM_AIR_TEMPERATURE_C,
    PARAM_RAINFALL_MM,
)


# --------------------------------------------------------------------------
#  Helper: payload Open-Meteo realistico per testing
# --------------------------------------------------------------------------

def _make_openmeteo_payload(num_days: int = 3) -> dict:
    """
    Costruisce un payload simil-Open-Meteo con `num_days` giorni di
    dati realistici. La struttura riflette la vera risposta dell'API
    `/v1/forecast` con i parametri daily che fitosim usa.
    """
    # Date solari come stringhe ISO che il parser legacy si aspetta.
    days = [f"2026-05-{day:02d}" for day in range(1, num_days + 1)]
    return {
        "latitude": 45.46,
        "longitude": 9.19,
        "daily_units": {
            "time": "iso8601",
            "temperature_2m_min": "°C",
            "temperature_2m_max": "°C",
            "precipitation_sum": "mm",
            "et0_fao_evapotranspiration": "mm",
        },
        "daily": {
            "time": days,
            "temperature_2m_min": [12.0, 13.5, 11.0][:num_days],
            "temperature_2m_max": [22.0, 24.5, 19.0][:num_days],
            "precipitation_sum": [0.0, 2.5, 8.0][:num_days],
            "et0_fao_evapotranspiration": [4.2, 4.8, 3.1][:num_days],
        },
    }


# --------------------------------------------------------------------------
#  Test del fetcher mock: il "fixture interno" funziona
# --------------------------------------------------------------------------

class Test_mock_fetcher_works:
    """
    Verifica preliminare che il fetcher mock produca dati coerenti col
    parser legacy. Se questo gruppo fallisce, c'è qualcosa di strano
    nell'API legacy stessa, non nel nostro adapter.
    """

    def test_legacy_parses_mock_payload(self):
        """Il parser legacy accetta il nostro payload simulato e
        produce 3 DailyWeather corretti."""
        payload = _make_openmeteo_payload(num_days=3)
        weathers = fetch_daily_forecast(
            latitude=45.46,
            longitude=9.19,
            days=3,
            use_cache=False,
            fetcher=lambda url: payload,
        )
        assert len(weathers) == 3
        assert weathers[0].t_min == 12.0
        assert weathers[0].t_max == 22.0
        assert weathers[0].et0_mm == 4.2


# --------------------------------------------------------------------------
#  Traduzione corretta: DailyWeather → EnvironmentReading
# --------------------------------------------------------------------------

class Test_OpenMeteo_translation:
    """L'adapter traduce correttamente i dati legacy nel formato canonico.

    Dopo la migrazione alla spec sensori v1, l'output è
    `list[Measurement]` flat. Ogni giorno produce 2-3 Measurement
    (`air_temperature_c`, `rainfall_mm`, e `custom:et0_mm` se
    Open-Meteo lo fornisce).
    """

    def test_translation_with_mock(self, monkeypatch):
        """
        Test centrale di traduzione: monkey-patch di fetch_daily_forecast
        per controllare cosa l'adapter riceve dal legacy.
        """
        from fitosim.io.openmeteo import DailyWeather
        from datetime import date

        # Mock che restituisce 3 DailyWeather predefiniti.
        def mock_fetch(latitude, longitude, days, **kwargs):
            return [
                DailyWeather(
                    day=date(2026, 5, d),
                    t_min=10.0 + d,
                    t_max=20.0 + d,
                    precipitation_mm=float(d),
                    et0_mm=4.0 + 0.1 * d,
                )
                for d in range(1, days + 1)
            ]

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )

        sensor = OpenMeteoEnvironmentSensor()
        measurements = sensor.forecast(
            latitude=45.46, longitude=9.19, days=3,
        )

        # 3 giorni × 3 parametri (temp + rain + et0) = 9 Measurement.
        assert len(measurements) == 9
        assert all(isinstance(m, Measurement) for m in measurements)

        # Filtro: temperatura del primo giorno.
        temp_d1 = next(
            m for m in measurements
            if m.parameter == PARAM_AIR_TEMPERATURE_C
            and m.timestamp.date().isoformat() == "2026-05-01"
        )
        assert temp_d1.value == (11.0 + 21.0) / 2
        assert temp_d1.timestamp == datetime(
            2026, 5, 1, 12, 0, tzinfo=timezone.utc,
        )

        # Filtro: temperatura del secondo giorno.
        temp_d2 = next(
            m for m in measurements
            if m.parameter == PARAM_AIR_TEMPERATURE_C
            and m.timestamp.date().isoformat() == "2026-05-02"
        )
        assert temp_d2.value == (12.0 + 22.0) / 2

        # Filtro: pioggia.
        rains = [m for m in measurements if m.parameter == PARAM_RAINFALL_MM]
        rain_values_by_date = {
            m.timestamp.date().isoformat(): m.value for m in rains
        }
        assert rain_values_by_date["2026-05-01"] == 1.0
        assert rain_values_by_date["2026-05-03"] == 3.0

        # Filtro: ET₀ (custom:et0_mm).
        et0_d1 = next(
            m for m in measurements
            if m.parameter == f"{CUSTOM_NAMESPACE_PREFIX}et0_mm"
            and m.timestamp.date().isoformat() == "2026-05-01"
        )
        assert et0_d1.value == pytest.approx(4.1)

    def test_current_conditions_returns_first_day(self, monkeypatch):
        """current_conditions() ritorna le Measurement del primo
        giorno (forecast a 1 giorno)."""
        from fitosim.io.openmeteo import DailyWeather
        from datetime import date

        def mock_fetch(latitude, longitude, days, **kwargs):
            assert days == 1, "current_conditions deve chiedere 1 giorno"
            return [DailyWeather(
                day=date(2026, 5, 1),
                t_min=15.0,
                t_max=25.0,
                precipitation_mm=0.0,
                et0_mm=4.5,
            )]

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        measurements = sensor.current_conditions(
            latitude=45.46, longitude=9.19,
        )

        # 3 Measurement (temp + rain + et0) tutte per lo stesso giorno.
        assert len(measurements) == 3
        assert all(isinstance(m, Measurement) for m in measurements)
        temp = next(
            m for m in measurements if m.parameter == PARAM_AIR_TEMPERATURE_C
        )
        assert temp.value == 20.0  # media (15+25)/2

    def test_missing_et0_omits_measurement(self, monkeypatch):
        """Se Open-Meteo non fornisce et0 per un giorno (zona o data
        non coperte), la Measurement custom:et0_mm NON viene prodotta
        (la spec sensori v1 richiede value obbligatorio float, non
        None)."""
        from fitosim.io.openmeteo import DailyWeather
        from datetime import date

        def mock_fetch(latitude, longitude, days, **kwargs):
            return [DailyWeather(
                day=date(2026, 5, 1),
                t_min=10.0,
                t_max=20.0,
                precipitation_mm=0.0,
                et0_mm=None,  # non disponibile
            )]

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        measurements = sensor.forecast(
            latitude=45.46, longitude=9.19, days=1,
        )
        # Solo 2 Measurement (temp + rain), niente et0.
        assert len(measurements) == 2
        params = {m.parameter for m in measurements}
        assert PARAM_AIR_TEMPERATURE_C in params
        assert PARAM_RAINFALL_MM in params
        assert not any(p.startswith("custom:") for p in params)

    def test_all_measurements_share_sensor_id(self, monkeypatch):
        """Tutte le Measurement di una stessa coordinata condividono
        lo stesso sensor_id."""
        from fitosim.io.openmeteo import DailyWeather
        from datetime import date

        def mock_fetch(latitude, longitude, days, **kwargs):
            return [
                DailyWeather(
                    day=date(2026, 5, d),
                    t_min=10.0 + d, t_max=20.0 + d,
                    precipitation_mm=0.0, et0_mm=4.0,
                )
                for d in range(1, days + 1)
            ]

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        measurements = sensor.forecast(
            latitude=45.46, longitude=9.19, days=3,
        )
        sensor_ids = {m.sensor_id for m in measurements}
        assert len(sensor_ids) == 1

    def test_sensor_id_follows_convention(self):
        """sensor_id segue la convenzione
        `openmeteo:lat<lat>_lon<lon>` con 4 decimali."""
        sensor = OpenMeteoEnvironmentSensor()
        assert (
            sensor.sensor_id_for(45.4642, 9.1900)
            == "openmeteo:lat45.4642_lon9.1900"
        )
        # Coordinate negative formattate correttamente.
        assert (
            sensor.sensor_id_for(-33.8688, 151.2093)
            == "openmeteo:lat-33.8688_lon151.2093"
        )


# --------------------------------------------------------------------------
#  Mapping delle eccezioni native su quelle canoniche
# --------------------------------------------------------------------------

class Test_OpenMeteo_error_mapping:
    """L'adapter traduce le eccezioni native nelle nostre."""

    def test_url_error_becomes_temporary(self, monkeypatch):
        """urllib.error.URLError (timeout, DNS) → SensorTemporaryError."""
        def mock_fetch(*args, **kwargs):
            raise urllib.error.URLError("network unreachable")

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(SensorTemporaryError) as exc_info:
            sensor.forecast(latitude=45.46, longitude=9.19, days=3)
        # La causa originale è preservata via __cause__.
        assert isinstance(exc_info.value.__cause__, urllib.error.URLError)
        # Il provider è valorizzato per il logging strutturato.
        assert exc_info.value.provider == "openmeteo"

    def test_http_5xx_becomes_temporary(self, monkeypatch):
        """HTTP 5xx (server errors) → SensorTemporaryError (recuperabile)."""
        def mock_fetch(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://api.open-meteo.com/...",
                code=503,
                msg="Service Unavailable",
                hdrs={},
                fp=None,
            )

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(SensorTemporaryError, match="503"):
            sensor.forecast(latitude=45.46, longitude=9.19, days=3)

    def test_http_429_rate_limit_becomes_temporary(self, monkeypatch):
        """HTTP 429 (rate limit) è tecnicamente 4xx ma è recuperabile
        aspettando, quindi lo trattiamo come Temporary."""
        def mock_fetch(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://api.open-meteo.com/...",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=None,
            )

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(SensorTemporaryError):
            sensor.forecast(latitude=45.46, longitude=9.19, days=3)

    def test_http_4xx_becomes_permanent(self, monkeypatch):
        """HTTP 4xx generici (eccetto 429) → SensorPermanentError."""
        def mock_fetch(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://api.open-meteo.com/...",
                code=400,
                msg="Bad Request",
                hdrs={},
                fp=None,
            )

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(SensorPermanentError, match="400"):
            sensor.forecast(latitude=45.46, longitude=9.19, days=3)

    def test_value_error_becomes_permanent(self, monkeypatch):
        """ValueError (parsing JSON fallito) → SensorPermanentError."""
        def mock_fetch(*args, **kwargs):
            raise ValueError("malformed JSON response")

        monkeypatch.setattr(
            "fitosim.io.sensors.openmeteo.fetch_daily_forecast",
            mock_fetch,
        )
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(SensorPermanentError, match="malformed"):
            sensor.forecast(latitude=45.46, longitude=9.19, days=3)


# --------------------------------------------------------------------------
#  Validazione di input
# --------------------------------------------------------------------------

class Test_OpenMeteo_input_validation:
    """L'adapter rifiuta input fuori dai range supportati dal provider."""

    def test_days_zero_raises_value_error(self):
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(ValueError, match="days"):
            sensor.forecast(latitude=45.46, longitude=9.19, days=0)

    def test_days_too_many_raises_value_error(self):
        """Open-Meteo limita a 16 giorni il forecast."""
        sensor = OpenMeteoEnvironmentSensor()
        with pytest.raises(ValueError, match="days"):
            sensor.forecast(latitude=45.46, longitude=9.19, days=20)


# --------------------------------------------------------------------------
#  Conformità al Protocol
# --------------------------------------------------------------------------

class Test_OpenMeteo_protocol_conformance:
    """L'adapter soddisfa il Protocol EnvironmentSensor."""

    def test_isinstance_environment_sensor(self):
        """isinstance check via Protocol runtime_checkable."""
        from fitosim.io.sensors import EnvironmentSensor
        sensor = OpenMeteoEnvironmentSensor()
        assert isinstance(sensor, EnvironmentSensor)
