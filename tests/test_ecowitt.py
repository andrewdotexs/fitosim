"""
Test per fitosim.io.ecowitt.

Cinque famiglie:
  1. Conversioni di unità (imperial → metric).
  2. Parsing del payload reale fornito dall'utente — è il test "ground
     truth" che valida il modulo contro dati veri della stazione.
  3. Robustezza del parsing: sensori mancanti, valori malformati, gestione
     dei codici di errore dell'API.
  4. URL builder: contiene tutti i parametri richiesti.
  5. fetch_real_time end-to-end con fetcher iniettato.
"""

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fitosim.io.ecowitt import (
    EcowittObservation,
    _build_real_time_url,
    _to_celsius,
    _to_hpa,
    _to_m_per_second,
    _to_mm,
    _to_mm_per_hour,
    credentials_from_env,
    fetch_real_time,
    parse_ecowitt_response,
)


# Path della fixture: il payload reale catturato dalla stazione
# dell'utente. Lo carichiamo una volta all'avvio dei test.
FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "ecowitt_real_sample.json"
)


def _load_real_payload() -> dict:
    """Carica il payload reale della stazione utente come dict."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# =======================================================================
#  1. Conversioni di unità
# =======================================================================

class TestUnitConversions(unittest.TestCase):
    """
    Le conversioni sono punti critici: un errore di formula propaga
    silenziosamente errori di calcolo per tutta fitosim. Test stretti
    contro valori canonici noti.
    """

    def test_celsius_passthrough(self):
        # Identità: °C non viene toccato.
        self.assertAlmostEqual(_to_celsius(20.0, "°C"), 20.0, places=6)
        # Variante con "º" (ordinal indicator): stesso comportamento.
        self.assertAlmostEqual(_to_celsius(20.0, "ºC"), 20.0, places=6)

    def test_fahrenheit_to_celsius_canonical_points(self):
        # 32 °F = 0 °C (punto di congelamento dell'acqua).
        self.assertAlmostEqual(_to_celsius(32.0, "°F"), 0.0, places=6)
        # 212 °F = 100 °C (punto di ebollizione a 1 atm).
        self.assertAlmostEqual(_to_celsius(212.0, "°F"), 100.0, places=6)
        # Variante "º" — la stessa che usa effettivamente Ecowitt.
        self.assertAlmostEqual(_to_celsius(64.6, "ºF"), 18.111, places=2)

    def test_celsius_unit_unrecognized_raises(self):
        with self.assertRaises(ValueError):
            _to_celsius(20.0, "K")

    def test_inches_to_mm_canonical(self):
        # 1 in = 25.4 mm esatti per definizione internazionale.
        self.assertAlmostEqual(_to_mm(1.0, "in"), 25.4, places=6)
        # mm passthrough.
        self.assertAlmostEqual(_to_mm(10.0, "mm"), 10.0, places=6)

    def test_inches_per_hour_to_mm_per_hour(self):
        # Stesso fattore di 25.4 ma per il rate.
        self.assertAlmostEqual(_to_mm_per_hour(1.0, "in/hr"), 25.4, places=6)
        self.assertAlmostEqual(_to_mm_per_hour(2.5, "mm/hr"), 2.5, places=6)

    def test_mph_to_ms(self):
        # 1 mph = 0.44704 m/s esatti.
        self.assertAlmostEqual(
            _to_m_per_second(1.0, "mph"), 0.44704, places=5,
        )
        self.assertAlmostEqual(_to_m_per_second(5.0, "m/s"), 5.0, places=6)

    def test_kmh_to_ms(self):
        # 36 km/h = 10 m/s.
        self.assertAlmostEqual(
            _to_m_per_second(36.0, "km/h"), 10.0, places=6,
        )

    def test_inhg_to_hpa(self):
        # 29.92 inHg ≈ 1013.25 hPa (pressione standard al livello del mare).
        self.assertAlmostEqual(_to_hpa(29.92, "inHg"), 1013.21, places=1)
        # hPa passthrough.
        self.assertAlmostEqual(_to_hpa(1013.25, "hPa"), 1013.25, places=6)


# =======================================================================
#  2. Parsing del payload reale (validazione "ground truth")
# =======================================================================

class TestRealPayloadParsing(unittest.TestCase):
    """
    Verifica del parser contro il payload reale della stazione.
    Sono i numeri esatti che il modulo deve riprodurre dopo le
    conversioni — è il test più importante del file.
    """

    def setUp(self):
        self.payload = _load_real_payload()
        self.obs = parse_ecowitt_response(self.payload)

    def test_returns_ecowitt_observation(self):
        self.assertIsInstance(self.obs, EcowittObservation)

    def test_timestamp_decoded_correctly(self):
        # Il payload ha "time": "1777147849". Decodifica → 26 aprile 2026.
        self.assertEqual(self.obs.timestamp.year, 2026)
        self.assertEqual(self.obs.timestamp.tzinfo, timezone.utc)

    def test_outdoor_temperature_converted_to_celsius(self):
        # 64.6 °F → 18.111 °C circa.
        self.assertAlmostEqual(self.obs.outdoor_temp_c, 18.11, places=1)

    def test_outdoor_humidity_passthrough(self):
        # L'umidità è già adimensionale (%) — niente conversione.
        self.assertAlmostEqual(self.obs.outdoor_humidity_pct, 59.0, places=1)

    def test_indoor_temperature_converted(self):
        # 71.2 °F → 21.78 °C.
        self.assertAlmostEqual(self.obs.indoor_temp_c, 21.78, places=1)

    def test_solar_zero_at_night(self):
        # Solar = 0 W/m²: tipico di notte. Deve passare come 0.0.
        self.assertEqual(self.obs.solar_w_m2, 0.0)

    def test_uv_index_zero(self):
        self.assertEqual(self.obs.uv_index, 0.0)

    def test_wind_speed_converted_to_ms(self):
        # 1.8 mph → 0.805 m/s.
        self.assertAlmostEqual(self.obs.wind_speed_m_s, 0.805, places=2)

    def test_wind_gust_converted_to_ms(self):
        # 4.2 mph → 1.878 m/s.
        self.assertAlmostEqual(self.obs.wind_gust_m_s, 1.878, places=2)

    def test_wind_direction_passthrough(self):
        # I gradi sono adimensionali, niente conversione.
        self.assertAlmostEqual(self.obs.wind_direction_deg, 185.0, places=1)

    def test_pressure_converted_to_hpa(self):
        # 29.95 inHg → 1014.21 hPa.
        self.assertAlmostEqual(
            self.obs.pressure_relative_hpa, 1014.2, places=0,
        )
        # 29.17 inHg (assoluta) → 987.8 hPa.
        self.assertAlmostEqual(
            self.obs.pressure_absolute_hpa, 987.8, places=0,
        )

    def test_rain_today_converted_to_mm(self):
        # 0.00 in resta 0 in mm.
        self.assertEqual(self.obs.rain_today_mm, 0.0)

    def test_wn31_channel_1_present(self):
        # Il payload include temp_and_humidity_ch1: deve apparire
        # nel dict extra_temp_c con chiave 1.
        self.assertIn(1, self.obs.extra_temp_c)
        # 72.3 °F → 22.39 °C.
        self.assertAlmostEqual(self.obs.extra_temp_c[1], 22.39, places=1)
        # Umidità del WN31 CH1: 42%.
        self.assertEqual(self.obs.extra_humidity_pct[1], 42.0)

    def test_wn31_other_channels_absent(self):
        # Solo CH1 è installato; CH2-CH8 non devono apparire.
        for ch in range(2, 9):
            self.assertNotIn(ch, self.obs.extra_temp_c)
            self.assertNotIn(ch, self.obs.extra_humidity_pct)

    def test_five_soil_channels_parsed(self):
        # La stazione ha 5 sensori WH51 attivi (ch1..ch5).
        self.assertEqual(set(self.obs.soil_moisture_pct.keys()),
                         {1, 2, 3, 4, 5})

    def test_soil_moisture_values_match_payload(self):
        # Verifica puntuale di ogni canale.
        expected = {1: 44.0, 2: 15.0, 3: 48.0, 4: 34.0, 5: 50.0}
        for ch, val in expected.items():
            with self.subTest(channel=ch):
                self.assertAlmostEqual(
                    self.obs.soil_moisture_pct[ch], val, places=1,
                )

    def test_soil_channels_above_5_absent(self):
        # I canali 6-16 non sono installati: niente entry.
        for ch in range(6, 17):
            self.assertNotIn(ch, self.obs.soil_moisture_pct)


# =======================================================================
#  3. Robustezza del parsing
# =======================================================================

class TestParsingRobustness(unittest.TestCase):
    """
    Comportamento del parser su payload incompleti, malformati, errori
    dell'API. Vogliamo essere tolleranti dove ha senso (sensori
    mancanti) e severi dove conta (struttura corrotta).
    """

    def test_error_code_raises(self):
        # API risponde con code != 0 → ValueError esplicita.
        bad_payload = {
            "code": 40010, "msg": "Invalid api_key",
            "time": "1777147849", "data": {},
        }
        with self.assertRaises(ValueError) as ctx:
            parse_ecowitt_response(bad_payload)
        # Il messaggio d'errore deve includere il codice e la causa
        # leggibile, per aiutare il debug.
        self.assertIn("40010", str(ctx.exception))
        self.assertIn("api_key", str(ctx.exception))

    def test_missing_data_section_raises(self):
        with self.assertRaises(ValueError):
            parse_ecowitt_response({"code": 0, "time": "1777147849"})

    def test_minimal_payload_with_only_outdoor(self):
        # Payload con solo l'outdoor (caso di stazione minima): niente
        # eccezioni, gli altri campi restano None / dict vuoti.
        minimal = {
            "code": 0,
            "time": "1777147849",
            "data": {
                "outdoor": {
                    "temperature": {"unit": "°C", "value": "20.0"},
                    "humidity": {"unit": "%", "value": "55"},
                },
            },
        }
        obs = parse_ecowitt_response(minimal)
        self.assertAlmostEqual(obs.outdoor_temp_c, 20.0)
        self.assertEqual(obs.outdoor_humidity_pct, 55.0)
        self.assertIsNone(obs.indoor_temp_c)
        self.assertIsNone(obs.wind_speed_m_s)
        self.assertEqual(obs.soil_moisture_pct, {})
        self.assertEqual(obs.extra_temp_c, {})

    def test_malformed_value_yields_none(self):
        # Un singolo valore non parsabile non deve far crashare il
        # parser intero: il campo specifico va a None.
        broken = {
            "code": 0,
            "time": "1777147849",
            "data": {
                "outdoor": {
                    "temperature": {"unit": "°C", "value": "non-un-numero"},
                    "humidity": {"unit": "%", "value": "55"},
                },
            },
        }
        obs = parse_ecowitt_response(broken)
        self.assertIsNone(obs.outdoor_temp_c)
        # Altri campi parsabili devono venire correttamente.
        self.assertEqual(obs.outdoor_humidity_pct, 55.0)

    def test_piezo_rain_preferred_over_traditional(self):
        # Quando entrambi i pluviometri sono presenti, il parser deve
        # preferire il piezo (è documentato come più accurato).
        payload = {
            "code": 0,
            "time": "1777147849",
            "data": {
                "rainfall": {
                    "daily": {"unit": "mm", "value": "5.0"},
                },
                "rainfall_piezo": {
                    "daily": {"unit": "mm", "value": "4.7"},
                },
            },
        }
        obs = parse_ecowitt_response(payload)
        self.assertAlmostEqual(obs.rain_today_mm, 4.7)

    def test_traditional_rain_used_if_piezo_absent(self):
        # Senza piezo, fallback al pluviometro tradizionale.
        payload = {
            "code": 0,
            "time": "1777147849",
            "data": {
                "rainfall": {
                    "daily": {"unit": "mm", "value": "5.0"},
                },
            },
        }
        obs = parse_ecowitt_response(payload)
        self.assertAlmostEqual(obs.rain_today_mm, 5.0)


# =======================================================================
#  4. URL builder
# =======================================================================

class TestUrlBuilder(unittest.TestCase):
    def test_url_contains_all_parameters(self):
        url = _build_real_time_url(
            application_key="APP123",
            api_key="API456",
            mac="88:13:BF:CB:5A:AF",
        )
        self.assertIn("application_key=APP123", url)
        self.assertIn("api_key=API456", url)
        # Il MAC con `:` viene URL-encoded come %3A.
        self.assertIn("88%3A13%3ABF%3ACB%3A5A%3AAF", url)
        self.assertIn("call_back=all", url)
        self.assertTrue(url.startswith("https://api.ecowitt.net/"))


# =======================================================================
#  5. Fetch end-to-end con fetcher iniettato
# =======================================================================

class TestFetchRealTime(unittest.TestCase):
    """
    Test del flusso completo, intercettando il fetcher per evitare
    qualsiasi chiamata di rete reale. Stesso pattern del test di
    Open-Meteo per coerenza.
    """

    def test_fetch_with_mock_returns_observation(self):
        # Il fetcher mock restituisce il payload reale dell'utente.
        captured_urls = []

        def mock_fetcher(url):
            captured_urls.append(url)
            return _load_real_payload()

        obs = fetch_real_time(
            application_key="APP123",
            api_key="API456",
            mac="88:13:BF:CB:5A:AF",
            fetcher=mock_fetcher,
        )

        # Risposta corretta + URL chiamato una sola volta.
        self.assertIsInstance(obs, EcowittObservation)
        self.assertEqual(len(captured_urls), 1)
        # I parametri sono dentro l'URL chiamato.
        self.assertIn("application_key=APP123", captured_urls[0])

    def test_fetch_propagates_network_error_as_oserror(self):
        # Se il fetcher solleva URLError, fetch_real_time la incapsula
        # in OSError con messaggio leggibile.
        import urllib.error

        def failing_fetcher(url):
            raise urllib.error.URLError("simulated outage")

        with self.assertRaises(OSError) as ctx:
            fetch_real_time(
                application_key="APP123",
                api_key="API456",
                mac="88:13:BF:CB:5A:AF",
                fetcher=failing_fetcher,
            )
        # Il messaggio deve includere il MAC del dispositivo come
        # contesto utile per il debug.
        self.assertIn("88:13:BF:CB:5A:AF", str(ctx.exception))


# =======================================================================
#  6. Helper per credenziali da env
# =======================================================================

class TestCredentialsFromEnv(unittest.TestCase):
    def test_reads_all_three_from_env(self):
        with patch.dict(os.environ, {
            "TEST_APPLICATION_KEY": "app-x",
            "TEST_API_KEY": "api-y",
            "TEST_MAC": "AA:BB:CC:DD:EE:FF",
        }, clear=False):
            app, api, mac = credentials_from_env(test=True)
            self.assertEqual(app, "app-x")
            self.assertEqual(api, "api-y")
            self.assertEqual(mac, "AA:BB:CC:DD:EE:FF")

    def test_missing_variable_raises_with_explicit_message(self):
        # Ripuliamo le tre variabili e poi mettiamo solo due.
        env = {
            "TEST_APPLICATION_KEY": "app-x",
            "TEST_API_KEY": "api-y",
            # TEST_MAC mancante apposta
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                credentials_from_env(test=True)
            self.assertNotIn("TEST_MAC", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
