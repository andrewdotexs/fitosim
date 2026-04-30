"""
Test degli adapter EcowittEnvironmentSensor e EcowittWH51SoilSensor.

Strategia di test
-----------------

Come per Open-Meteo, gli adapter sono thin wrapper sopra il modulo
legacy `fitosim.io.ecowitt`. I test verificano:

  1. **Lettura credenziali**: la convenzione FITOSIM_ECOWITT_* ha
     priorità; il fallback ECOWITT_* legacy emette DeprecationWarning;
     credenziali mancanti producono errore aggregato leggibile.

  2. **Traduzione corretta**: EcowittObservation → EnvironmentReading
     per l'adapter ambient; EcowittObservation → SoilReading per il
     canale specifico del WH51.

  3. **Mapping eccezioni**: errori HTTP, di rete, di parsing vengono
     tradotti nelle nostre eccezioni canoniche.

  4. **Caratteristiche specifiche**: forecast() solleva
     NotImplementedError; channel_id non valido solleva
     SensorPermanentError; canale non collegato solleva errore
     diagnostico.

Per evitare richieste HTTP reali, monkey-patchiamo `fetch_real_time` del
modulo legacy così come abbiamo fatto per `fetch_daily_forecast` nei
test Open-Meteo.
"""

import os
import urllib.error
import warnings
from datetime import datetime, timezone

import pytest

from fitosim.io.ecowitt import EcowittObservation
from fitosim.io.sensors import (
    EcowittEnvironmentSensor,
    EcowittWH51SoilSensor,
    EnvironmentReading,
    EnvironmentSensor,
    SensorPermanentError,
    SensorTemporaryError,
    SoilReading,
    SoilSensor,
)


# --------------------------------------------------------------------------
#  Helper: EcowittObservation realistica per i test
# --------------------------------------------------------------------------

def _make_observation(
    *,
    temp: float = 22.5,
    humidity_pct: float = 65.0,
    wind: float = 2.1,
    rain_24h: float = 0.5,
    soil_channels: dict | None = None,
) -> EcowittObservation:
    """
    Costruisce una EcowittObservation con dati realistici per i test.

    Il timestamp è fissato in modo deterministico (1° maggio 2026
    mezzogiorno UTC) per non dipendere da datetime.now() nei test.
    """
    return EcowittObservation(
        timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        outdoor_temp_c=temp,
        outdoor_humidity_pct=humidity_pct,
        wind_speed_m_s=wind,
        rain_24h_mm=rain_24h,
        soil_moisture_pct=soil_channels or {},
    )


# --------------------------------------------------------------------------
#  Lettura delle credenziali da variabili d'ambiente
# --------------------------------------------------------------------------

class Test_credentials_from_env:
    """
    La doppia convenzione FITOSIM_ECOWITT_* (priorità) e ECOWITT_*
    (legacy con DeprecationWarning) deve funzionare correttamente.
    """

    def test_reads_new_convention_silently(self, monkeypatch):
        """Quando le variabili FITOSIM_ECOWITT_* sono settate, vengono
        usate senza warning."""
        monkeypatch.setenv("FITOSIM_ECOWITT_APPLICATION_KEY", "app_new")
        monkeypatch.setenv("FITOSIM_ECOWITT_API_KEY", "api_new")
        monkeypatch.setenv("FITOSIM_ECOWITT_MAC", "AA:BB:CC:DD:EE:FF")

        # Verifichiamo che non ci siano warning.
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # qualsiasi warning → eccezione
            sensor = EcowittEnvironmentSensor.from_env()

        assert sensor._application_key == "app_new"
        assert sensor._api_key == "api_new"
        assert sensor._mac == "AA:BB:CC:DD:EE:FF"

    def test_falls_back_to_legacy_with_warning(self, monkeypatch):
        """Quando solo ECOWITT_* sono settate (senza prefisso FITOSIM_),
        l'adapter le usa ma emette DeprecationWarning per ciascuna."""
        # Rimuoviamo le nuove (in caso fossero presenti dall'ambiente di
        # sviluppo del test) e mettiamo solo le legacy.
        monkeypatch.delenv("FITOSIM_ECOWITT_APPLICATION_KEY", raising=False)
        monkeypatch.delenv("FITOSIM_ECOWITT_API_KEY", raising=False)
        monkeypatch.delenv("FITOSIM_ECOWITT_MAC", raising=False)
        monkeypatch.setenv("ECOWITT_APPLICATION_KEY", "app_legacy")
        monkeypatch.setenv("ECOWITT_API_KEY", "api_legacy")
        monkeypatch.setenv("ECOWITT_MAC", "11:22:33:44:55:66")

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            sensor = EcowittEnvironmentSensor.from_env()

        # Devono essere emessi 3 DeprecationWarning, uno per credenziale.
        deprecation_warnings = [
            w for w in captured
            if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 3
        # Ogni warning suggerisce il nome nuovo da usare.
        for w in deprecation_warnings:
            assert "FITOSIM_ECOWITT" in str(w.message)

        # Le credenziali sono state caricate correttamente.
        assert sensor._application_key == "app_legacy"
        assert sensor._api_key == "api_legacy"
        assert sensor._mac == "11:22:33:44:55:66"

    def test_new_takes_priority_over_legacy(self, monkeypatch):
        """Se entrambe le convenzioni sono settate, vince FITOSIM_*
        e nessun warning viene emesso."""
        monkeypatch.setenv("FITOSIM_ECOWITT_APPLICATION_KEY", "app_new")
        monkeypatch.setenv("FITOSIM_ECOWITT_API_KEY", "api_new")
        monkeypatch.setenv("FITOSIM_ECOWITT_MAC", "NEW:MAC")
        monkeypatch.setenv("ECOWITT_APPLICATION_KEY", "app_legacy")
        monkeypatch.setenv("ECOWITT_API_KEY", "api_legacy")
        monkeypatch.setenv("ECOWITT_MAC", "LEGACY:MAC")

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            sensor = EcowittEnvironmentSensor.from_env()

        # Le legacy non devono produrre warning perché non sono usate.
        deprecation_warnings = [
            w for w in captured
            if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 0
        # Le nuove hanno vinto.
        assert sensor._application_key == "app_new"
        assert sensor._mac == "NEW:MAC"

    def test_missing_credentials_raises_aggregated_error(self, monkeypatch):
        """Se mancano credenziali, l'errore le elenca tutte insieme,
        non solo la prima incontrata."""
        # Pulisci tutte le variabili.
        for name in [
            "FITOSIM_ECOWITT_APPLICATION_KEY",
            "FITOSIM_ECOWITT_API_KEY",
            "FITOSIM_ECOWITT_MAC",
            "ECOWITT_APPLICATION_KEY",
            "ECOWITT_API_KEY",
            "ECOWITT_MAC",
        ]:
            monkeypatch.delenv(name, raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            EcowittEnvironmentSensor.from_env()

        # Il messaggio elenca tutte e tre le variabili mancanti.
        msg = str(exc_info.value)
        assert "FITOSIM_ECOWITT_APPLICATION_KEY" in msg
        assert "FITOSIM_ECOWITT_API_KEY" in msg
        assert "FITOSIM_ECOWITT_MAC" in msg

    def test_partial_credentials_listed_in_error(self, monkeypatch):
        """Se solo alcune mancano, l'errore elenca esattamente quelle
        non valorizzate."""
        for name in [
            "FITOSIM_ECOWITT_APPLICATION_KEY",
            "FITOSIM_ECOWITT_API_KEY",
            "FITOSIM_ECOWITT_MAC",
            "ECOWITT_APPLICATION_KEY",
            "ECOWITT_API_KEY",
            "ECOWITT_MAC",
        ]:
            monkeypatch.delenv(name, raising=False)
        # Settiamo solo application_key.
        monkeypatch.setenv("FITOSIM_ECOWITT_APPLICATION_KEY", "ok")

        with pytest.raises(RuntimeError) as exc_info:
            EcowittEnvironmentSensor.from_env()

        msg = str(exc_info.value)
        # APPLICATION_KEY è stato letto, non deve essere nell'errore.
        assert "FITOSIM_ECOWITT_APPLICATION_KEY" not in msg
        # API_KEY e MAC devono essere nell'errore.
        assert "FITOSIM_ECOWITT_API_KEY" in msg
        assert "FITOSIM_ECOWITT_MAC" in msg

    def test_constructor_rejects_empty_strings(self):
        """Il costruttore esplicito rifiuta credenziali vuote per non
        propagare errori opachi più tardi."""
        with pytest.raises(ValueError, match="non vuoti"):
            EcowittEnvironmentSensor(
                application_key="", api_key="x", mac="y",
            )


# --------------------------------------------------------------------------
#  EcowittEnvironmentSensor: traduzione e funzionamento
# --------------------------------------------------------------------------

class Test_EcowittEnvironment_translation:
    """
    Traduzione corretta da EcowittObservation a EnvironmentReading.
    """

    def test_translates_basic_fields(self, monkeypatch):
        """I campi outdoor vengono tradotti con conversioni di unità
        corrette: humidity da % a frazione, gli altri preservati."""
        obs = _make_observation(
            temp=22.5,
            humidity_pct=65.0,  # percentuale Ecowitt
            wind=2.1,
            rain_24h=0.5,
        )
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )

        sensor = EcowittEnvironmentSensor(
            application_key="x", api_key="y", mac="z",
        )
        reading = sensor.current_conditions(latitude=45.46, longitude=9.19)

        assert isinstance(reading, EnvironmentReading)
        assert reading.temperature_c == 22.5
        # Conversione da percentuale a frazione: 65 → 0.65.
        assert reading.humidity_relative == pytest.approx(0.65)
        assert reading.wind_speed_m_s == 2.1
        assert reading.rain_mm == 0.5
        # Ecowitt non dà ET₀ né radiazione MJ → entrambi None.
        assert reading.et0_mm is None
        assert reading.radiation_mj_m2 is None

    def test_timestamp_is_preserved_from_observation(self, monkeypatch):
        """Il timestamp del Reading è quello della observation
        (momento della misura), non quello della richiesta."""
        obs = _make_observation()
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        reading = sensor.current_conditions(latitude=45.46, longitude=9.19)
        assert reading.timestamp == obs.timestamp

    def test_quality_includes_staleness(self, monkeypatch):
        """staleness_seconds è valorizzato come differenza tra ora
        attuale e timestamp della observation."""
        # Costruiamo una observation di 5 minuti fa.
        from datetime import timedelta
        ts_old = datetime.now(timezone.utc) - timedelta(minutes=5)
        obs = EcowittObservation(
            timestamp=ts_old,
            outdoor_temp_c=20.0,
        )
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        reading = sensor.current_conditions(latitude=45.46, longitude=9.19)

        # Lettura di 5 minuti fa = circa 300 secondi.
        assert 280 <= reading.quality.staleness_seconds <= 320


class Test_EcowittEnvironment_forecast:
    """forecast() deve sollevare NotImplementedError esplicito."""

    def test_forecast_raises_not_implemented(self):
        """Il messaggio suggerisce esplicitamente di usare Open-Meteo."""
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        with pytest.raises(NotImplementedError, match="OpenMeteo"):
            sensor.forecast(latitude=45.46, longitude=9.19, days=7)


class Test_EcowittEnvironment_error_mapping:
    """Mapping delle eccezioni native sulle nostre canoniche."""

    def test_url_error_becomes_temporary(self, monkeypatch):
        def mock_fetch(**kwargs):
            raise urllib.error.URLError("connection timeout")
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time", mock_fetch,
        )
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        with pytest.raises(SensorTemporaryError):
            sensor.current_conditions(45.46, 9.19)

    def test_http_401_becomes_permanent_with_credentials_message(
            self, monkeypatch):
        """401 → SensorPermanentError con messaggio mirato sulle
        credenziali (è il caso più comune di errore di setup)."""
        def mock_fetch(**kwargs):
            raise urllib.error.HTTPError(
                url="https://api.ecowitt.net/...",
                code=401, msg="Unauthorized", hdrs={}, fp=None,
            )
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time", mock_fetch,
        )
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        with pytest.raises(SensorPermanentError, match="credenziali"):
            sensor.current_conditions(45.46, 9.19)

    def test_http_503_becomes_temporary(self, monkeypatch):
        def mock_fetch(**kwargs):
            raise urllib.error.HTTPError(
                url="https://api.ecowitt.net/...",
                code=503, msg="Service Unavailable", hdrs={}, fp=None,
            )
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time", mock_fetch,
        )
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        with pytest.raises(SensorTemporaryError, match="503"):
            sensor.current_conditions(45.46, 9.19)


class Test_EcowittEnvironment_protocol_conformance:
    """L'adapter soddisfa il Protocol EnvironmentSensor."""

    def test_isinstance_check(self):
        sensor = EcowittEnvironmentSensor("x", "y", "z")
        assert isinstance(sensor, EnvironmentSensor)


# --------------------------------------------------------------------------
#  EcowittWH51SoilSensor: traduzione e channel routing
# --------------------------------------------------------------------------

class Test_WH51_translation:
    """Traduzione del singolo canale del WH51 in SoilReading."""

    def test_extracts_correct_channel(self, monkeypatch):
        """Con più canali presenti, current_state restituisce esattamente
        quello richiesto."""
        obs = _make_observation(soil_channels={
            1: 35.0,  # 35% in percentuale Ecowitt
            2: 22.0,
            3: 48.0,
        })
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z")

        # Canale 2 → 22% → 0.22 in frazione canonica.
        reading = sensor.current_state(channel_id="2")
        assert isinstance(reading, SoilReading)
        assert reading.theta_volumetric == pytest.approx(0.22)

        # Canale 1 → 35% → 0.35.
        reading_1 = sensor.current_state(channel_id="1")
        assert reading_1.theta_volumetric == pytest.approx(0.35)

    def test_only_theta_is_set_other_fields_none(self, monkeypatch):
        """Il WH51 misura solo θ. T, EC, pH restano None nel Reading."""
        obs = _make_observation(soil_channels={1: 30.0})
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z")
        reading = sensor.current_state(channel_id="1")

        assert reading.theta_volumetric == pytest.approx(0.30)
        assert reading.temperature_c is None
        assert reading.ec_mscm is None
        assert reading.ph is None

    def test_channel_id_accepts_multiple_formats(self, monkeypatch):
        """channel_id accetta 'N', 'chN', 'soilmoisture_chN'."""
        obs = _make_observation(soil_channels={3: 40.0})
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z")

        # Tutte e tre le forme producono lo stesso risultato.
        for variant in ["3", "ch3", "soilmoisture_ch3"]:
            reading = sensor.current_state(channel_id=variant)
            assert reading.theta_volumetric == pytest.approx(0.40)

    def test_invalid_channel_id_raises_permanent_error(self, monkeypatch):
        """channel_id non interpretabile → SensorPermanentError con
        diagnostica esplicita dei formati validi."""
        obs = _make_observation(soil_channels={1: 30.0})
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z")

        with pytest.raises(SensorPermanentError, match="non riconosciuto"):
            sensor.current_state(channel_id="not_a_channel")

    def test_missing_channel_raises_diagnostic_error(self, monkeypatch):
        """Se il canale richiesto non è collegato alla base station,
        l'errore elenca i canali disponibili per facilitare il debug."""
        obs = _make_observation(soil_channels={1: 30.0, 2: 25.0})
        monkeypatch.setattr(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            lambda **kwargs: obs,
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z")

        with pytest.raises(SensorPermanentError) as exc_info:
            sensor.current_state(channel_id="5")

        msg = str(exc_info.value)
        # Il messaggio elenca i canali effettivamente disponibili.
        assert "1" in msg
        assert "2" in msg
        assert "5" in msg


class Test_WH51_protocol_conformance:
    """Il WH51 adapter soddisfa il Protocol SoilSensor."""

    def test_isinstance_check(self):
        sensor = EcowittWH51SoilSensor("x", "y", "z")
        assert isinstance(sensor, SoilSensor)


# =====================================================================
#  Test del supporto WH52 (sotto-tappa D fase 3 tappa 5)
#
#  Il parametro model del costruttore distingue tra WH51 (default) e
#  WH52. Il WH52 popola anche temperatura ed EC del substrato nel
#  SoilReading quando i dati sono disponibili dalla observation.
# =====================================================================


class TestWH52SupportInSoilSensor:

    def test_default_model_is_wh51(self):
        sensor = EcowittWH51SoilSensor("x", "y", "z")
        assert sensor._model == "WH51"

    def test_model_wh52_explicit(self):
        sensor = EcowittWH51SoilSensor("x", "y", "z", model="WH52")
        assert sensor._model == "WH52"

    def test_invalid_model_raises(self):
        import pytest
        with pytest.raises(ValueError) as excinfo:
            EcowittWH51SoilSensor("x", "y", "z", model="WH99")
        assert "WH99" in str(excinfo.value)

    def test_wh51_does_not_populate_temperature_or_ec(self):
        # Per il WH51 (default) i campi T ed EC del SoilReading
        # restano None anche se la observation li contiene.
        from datetime import datetime, timezone
        from unittest.mock import patch
        from fitosim.io.ecowitt import EcowittObservation

        fake_obs = EcowittObservation(
            timestamp=datetime(2026, 7, 19, 14, 30, 0, tzinfo=timezone.utc),
            soil_moisture_pct={1: 35.0},
            soil_temperature_c={1: 21.5},  # presente ma WH51 lo ignora
            soil_ec_mscm={1: 2.3},  # presente ma WH51 lo ignora
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z", model="WH51")
        with patch(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            return_value=fake_obs,
        ):
            reading = sensor.current_state(channel_id="1")
        assert reading.theta_volumetric == 0.35
        assert reading.temperature_c is None
        assert reading.ec_mscm is None

    def test_wh52_populates_temperature_and_ec(self):
        # Per il WH52 i campi T ed EC vengono propagati nel SoilReading.
        from datetime import datetime, timezone
        from unittest.mock import patch
        from fitosim.io.ecowitt import EcowittObservation

        fake_obs = EcowittObservation(
            timestamp=datetime(2026, 7, 19, 14, 30, 0, tzinfo=timezone.utc),
            soil_moisture_pct={1: 35.0},
            soil_temperature_c={1: 21.5},
            soil_ec_mscm={1: 2.3},
        )
        sensor = EcowittWH51SoilSensor("x", "y", "z", model="WH52")
        with patch(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            return_value=fake_obs,
        ):
            reading = sensor.current_state(channel_id="1")
        assert reading.theta_volumetric == 0.35
        assert reading.temperature_c == 21.5
        assert reading.ec_mscm == 2.3

    def test_canonical_alias_exists(self):
        # L'alias canonico EcowittSoilSensor punta a EcowittWH51SoilSensor.
        from fitosim.io.sensors.ecowitt import EcowittSoilSensor
        assert EcowittSoilSensor is EcowittWH51SoilSensor


# =====================================================================
#  Test del nuovo EcowittAmbientSensor (sotto-tappa D fase 3 tappa 5)
#
#  L'adapter espone i sensori WN31 e produce IndoorMicroclimate. Due
#  metodi: current_state per il dato istantaneo (kind=INSTANT),
#  daily_aggregate per il dato giornaliero aggregato (kind=DAILY).
# =====================================================================


class TestEcowittAmbientSensor:

    def test_construction_requires_credentials(self):
        import pytest
        from fitosim.io.sensors.ecowitt import EcowittAmbientSensor
        with pytest.raises(ValueError):
            EcowittAmbientSensor("", "y", "z")
        with pytest.raises(ValueError):
            EcowittAmbientSensor("x", "", "z")
        with pytest.raises(ValueError):
            EcowittAmbientSensor("x", "y", "")

    def test_current_state_returns_instant_microclimate(self):
        # current_state chiama fetch_real_time, estrae T e RH del
        # canale, e produce un IndoorMicroclimate INSTANT.
        from datetime import datetime, timezone
        from unittest.mock import patch
        from fitosim.io.ecowitt import EcowittObservation
        from fitosim.io.sensors.ecowitt import EcowittAmbientSensor
        from fitosim.domain.room import MicroclimateKind

        fake_obs = EcowittObservation(
            timestamp=datetime(2026, 7, 19, 14, 30, 0, tzinfo=timezone.utc),
            extra_temp_c={1: 22.5},
            extra_humidity_pct={1: 55.0},
        )
        sensor = EcowittAmbientSensor("x", "y", "z")
        with patch(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            return_value=fake_obs,
        ):
            m = sensor.current_state(channel_id="1")
        assert m.kind == MicroclimateKind.INSTANT
        assert m.temperature_c == 22.5
        assert m.humidity_relative == 0.55
        # Il timestamp è quello dell'observation, non None.
        assert m.timestamp is not None

    def test_current_state_missing_channel_raises(self):
        # Canale mancante nei dati della stazione → SensorPermanentError.
        from datetime import datetime, timezone
        from unittest.mock import patch
        from fitosim.io.ecowitt import EcowittObservation
        from fitosim.io.sensors.ecowitt import EcowittAmbientSensor
        from fitosim.io.sensors.errors import SensorPermanentError
        import pytest

        fake_obs = EcowittObservation(
            timestamp=datetime(2026, 7, 19, 14, 30, 0, tzinfo=timezone.utc),
            extra_temp_c={2: 22.5},  # solo canale 2 disponibile
            extra_humidity_pct={2: 55.0},
        )
        sensor = EcowittAmbientSensor("x", "y", "z")
        with patch(
            "fitosim.io.sensors.ecowitt.fetch_real_time",
            return_value=fake_obs,
        ):
            with pytest.raises(SensorPermanentError):
                sensor.current_state(channel_id="1")

    def test_daily_aggregate_returns_daily_microclimate(self):
        # daily_aggregate chiama fetch_history_aggregation e produce
        # un IndoorMicroclimate DAILY con t_min, t_max, RH media.
        from datetime import date
        from unittest.mock import patch
        from fitosim.io.sensors.ecowitt import EcowittAmbientSensor
        from fitosim.domain.room import MicroclimateKind

        fake_data = {
            "t_min": 19.5,
            "t_max": 22.5,
            "humidity_relative": 0.55,
        }
        sensor = EcowittAmbientSensor("x", "y", "z")
        with patch(
            "fitosim.io.sensors.ecowitt.fetch_history_aggregation",
            return_value=fake_data,
        ):
            m = sensor.daily_aggregate(
                channel_id="1", target_date=date(2026, 7, 19),
            )
        assert m.kind == MicroclimateKind.DAILY
        assert m.t_min == 19.5
        assert m.t_max == 22.5
        # La temperature_c del DAILY è la media (t_min + t_max) / 2.
        assert m.temperature_c == 21.0
        assert m.humidity_relative == 0.55

    def test_daily_aggregate_temporary_error_on_unreachable(self):
        # Errore di rete propagato come SensorTemporaryError.
        from datetime import date
        from unittest.mock import patch
        from fitosim.io.sensors.ecowitt import EcowittAmbientSensor
        from fitosim.io.sensors.errors import SensorTemporaryError
        import pytest

        sensor = EcowittAmbientSensor("x", "y", "z")
        with patch(
            "fitosim.io.sensors.ecowitt.fetch_history_aggregation",
            side_effect=OSError("network unreachable"),
        ):
            with pytest.raises(SensorTemporaryError):
                sensor.daily_aggregate(
                    channel_id="1", target_date=date(2026, 7, 19),
                )
