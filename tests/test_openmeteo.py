"""
Test per fitosim.io.openmeteo.

Strutturati in cinque famiglie:
  1. Validazione DailyWeather.
  2. Costruzione URL.
  3. Parsing della risposta Open-Meteo (sintetica, senza rete).
  4. Cache su disco: scrittura, lettura, scadenza.
  5. Fetch end-to-end con mocking di urllib.request.urlopen.

I test della famiglia 5 usano `unittest.mock.patch` per intercettare
le chiamate HTTP. Questa è la pratica standard per testare codice di
rete senza dipendere dalla disponibilità di un server reale: i test
girano in CI offline e in pochi millisecondi.
"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fitosim.io.openmeteo import (
    DailyWeather,
    _build_request_url,
    _cache_filename,
    _parse_openmeteo_response,
    _read_cache,
    _write_cache,
    fetch_daily_forecast,
)


def _sample_payload() -> dict:
    """
    Fixture: una risposta sintetica di Open-Meteo che imita la struttura
    reale, con tre giorni di dati. È la base di confronto usata in più
    test del file.
    """
    return {
        "latitude": 45.47,
        "longitude": 9.19,
        "daily": {
            "time": ["2025-04-25", "2025-04-26", "2025-04-27"],
            "temperature_2m_max": [18.4, 19.1, 21.7],
            "temperature_2m_min": [8.7, 9.0, 11.2],
            "precipitation_sum": [0.0, 2.4, 0.6],
        },
    }


class TestDailyWeather(unittest.TestCase):
    """Validazione della dataclass DailyWeather."""

    def test_valid_creation(self):
        w = DailyWeather(
            day=date(2025, 7, 15),
            t_min=18.0, t_max=30.0,
            precipitation_mm=0.0,
        )
        self.assertEqual(w.t_min, 18.0)

    def test_inverted_temperatures_rejected(self):
        with self.assertRaises(ValueError):
            DailyWeather(
                day=date(2025, 7, 15),
                t_min=30.0, t_max=18.0, precipitation_mm=0.0,
            )

    def test_negative_precipitation_rejected(self):
        with self.assertRaises(ValueError):
            DailyWeather(
                day=date(2025, 7, 15),
                t_min=18.0, t_max=30.0, precipitation_mm=-1.0,
            )

    def test_immutability(self):
        w = DailyWeather(
            day=date(2025, 7, 15),
            t_min=18.0, t_max=30.0, precipitation_mm=0.0,
        )
        with self.assertRaises(Exception):
            w.t_min = 10.0  # type: ignore[misc]


class TestUrlBuilding(unittest.TestCase):
    """Costruzione della URL di richiesta."""

    def test_url_contains_required_params(self):
        url = _build_request_url(45.47, 9.19, days=7)
        self.assertIn("latitude=45.4700", url)
        self.assertIn("longitude=9.1900", url)
        self.assertIn("forecast_days=7", url)
        self.assertIn("temperature_2m_max", url)
        self.assertIn("precipitation_sum", url)

    def test_invalid_days_rejected(self):
        with self.assertRaises(ValueError):
            _build_request_url(0.0, 0.0, days=0)
        with self.assertRaises(ValueError):
            _build_request_url(0.0, 0.0, days=20)

    def test_invalid_latitude_rejected(self):
        with self.assertRaises(ValueError):
            _build_request_url(91.0, 0.0, days=7)

    def test_invalid_longitude_rejected(self):
        with self.assertRaises(ValueError):
            _build_request_url(0.0, 181.0, days=7)


class TestResponseParsing(unittest.TestCase):
    """Parsing della risposta JSON di Open-Meteo, senza rete."""

    def test_parses_three_days(self):
        result = _parse_openmeteo_response(_sample_payload())
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].day, date(2025, 4, 25))
        self.assertEqual(result[0].t_min, 8.7)
        self.assertEqual(result[0].t_max, 18.4)
        self.assertEqual(result[0].precipitation_mm, 0.0)
        self.assertEqual(result[1].precipitation_mm, 2.4)

    def test_missing_daily_field_raises(self):
        with self.assertRaises(ValueError):
            _parse_openmeteo_response({"latitude": 0, "longitude": 0})

    def test_mismatched_list_lengths_raise(self):
        bad = {
            "daily": {
                "time": ["2025-04-25", "2025-04-26"],
                "temperature_2m_max": [18.4],  # ← una sola voce
                "temperature_2m_min": [8.7, 9.0],
                "precipitation_sum": [0.0, 2.4],
            },
        }
        with self.assertRaises(ValueError):
            _parse_openmeteo_response(bad)

    def test_non_list_field_raises(self):
        bad = {"daily": {"time": "not a list"}}
        with self.assertRaises(ValueError):
            _parse_openmeteo_response(bad)


class TestCache(unittest.TestCase):
    """Scrittura, lettura e scadenza della cache su disco."""

    def setUp(self):
        # Directory temporanea isolata per ogni test, eliminata in tearDown.
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)
        self.cache_path = self.cache_dir / "test_cache.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read_roundtrip(self):
        payload = _sample_payload()
        _write_cache(self.cache_path, payload)
        # Cache appena scritta: deve essere fresca.
        recovered = _read_cache(self.cache_path, ttl_hours=24.0)
        self.assertEqual(recovered, payload)

    def test_read_missing_returns_none(self):
        result = _read_cache(self.cache_path, ttl_hours=24.0)
        self.assertIsNone(result)

    def test_read_corrupted_returns_none(self):
        # File esiste ma non è JSON valido: deve essere trattato come
        # cache assente (no exception).
        self.cache_path.write_text("{ this is not json", encoding="utf-8")
        self.assertIsNone(_read_cache(self.cache_path, ttl_hours=24.0))

    def test_expired_cache_returns_none(self):
        # Scriviamo una cache con timestamp molto vecchio.
        old_payload = {
            "_fitosim_cached_at":
                (datetime.now() - timedelta(hours=48)).isoformat(),
            "payload": _sample_payload(),
        }
        self.cache_path.write_text(
            json.dumps(old_payload), encoding="utf-8",
        )
        # TTL di 6 ore → cache vecchia di 48h è scaduta.
        result = _read_cache(self.cache_path, ttl_hours=6.0)
        self.assertIsNone(result)

    def test_infinite_ttl_returns_even_old_cache(self):
        # Scenario fallback: server irraggiungibile, leggiamo anche
        # cache scaduta passando ttl=infinity.
        old_payload = {
            "_fitosim_cached_at":
                (datetime.now() - timedelta(days=30)).isoformat(),
            "payload": _sample_payload(),
        }
        self.cache_path.write_text(
            json.dumps(old_payload), encoding="utf-8",
        )
        result = _read_cache(self.cache_path, ttl_hours=float("inf"))
        self.assertEqual(result, _sample_payload())

    def test_cache_filename_uses_coordinates(self):
        name = _cache_filename(45.47, 9.19, 7)
        self.assertIn("45.470", name)
        self.assertIn("9.190", name)
        self.assertIn("7", name)


class TestFetchEndToEnd(unittest.TestCase):
    """
    Test del flusso completo `fetch_daily_forecast`, con mocking di
    urllib.request.urlopen per simulare risposte HTTP.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_mock_response(self, payload: dict):
        """
        Costruisce un context manager che imita il return value di
        urllib.request.urlopen: un oggetto con metodo .read() che
        restituisce bytes.
        """
        class FakeResponse:
            def __init__(self, body: bytes):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        body = json.dumps(payload).encode("utf-8")
        return FakeResponse(body)

    def test_successful_fetch(self):
        with patch(
            "fitosim.io.openmeteo.urllib.request.urlopen",
            return_value=self._make_mock_response(_sample_payload()),
        ):
            result = fetch_daily_forecast(
                latitude=45.47, longitude=9.19, days=3,
                cache_dir=self.cache_dir,
            )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].day, date(2025, 4, 25))

    def test_cache_is_used_on_second_call(self):
        # Prima chiamata: HTTP reale (mock).
        call_count = {"n": 0}
        original = self._make_mock_response

        def counting_urlopen(*args, **kwargs):
            call_count["n"] += 1
            return original(_sample_payload())

        with patch(
            "fitosim.io.openmeteo.urllib.request.urlopen",
            side_effect=counting_urlopen,
        ):
            fetch_daily_forecast(
                latitude=45.47, longitude=9.19, days=3,
                cache_dir=self.cache_dir,
            )
            # Seconda chiamata identica: deve usare la cache, NON HTTP.
            fetch_daily_forecast(
                latitude=45.47, longitude=9.19, days=3,
                cache_dir=self.cache_dir,
            )
        self.assertEqual(call_count["n"], 1)

    def test_use_cache_false_forces_http(self):
        call_count = {"n": 0}

        def counting_urlopen(*args, **kwargs):
            call_count["n"] += 1
            return self._make_mock_response(_sample_payload())

        with patch(
            "fitosim.io.openmeteo.urllib.request.urlopen",
            side_effect=counting_urlopen,
        ):
            fetch_daily_forecast(
                latitude=45.47, longitude=9.19, days=3,
                cache_dir=self.cache_dir,
            )
            # Seconda chiamata con use_cache=False: HTTP comunque.
            fetch_daily_forecast(
                latitude=45.47, longitude=9.19, days=3,
                cache_dir=self.cache_dir, use_cache=False,
            )
        self.assertEqual(call_count["n"], 2)

    def test_network_failure_falls_back_to_stale_cache(self):
        # Step 1: salviamo una cache scaduta artificialmente.
        cache_filename = _cache_filename(45.47, 9.19, 3)
        cache_path = self.cache_dir / cache_filename
        old_payload = {
            "_fitosim_cached_at":
                (datetime.now() - timedelta(days=10)).isoformat(),
            "payload": _sample_payload(),
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(old_payload), encoding="utf-8")

        # Step 2: la chiamata HTTP fallisce, ma il fallback su cache
        # scaduta deve consegnare comunque dati validi.
        import urllib.error

        def failing_urlopen(*args, **kwargs):
            raise urllib.error.URLError("simulated network failure")

        with patch(
            "fitosim.io.openmeteo.urllib.request.urlopen",
            side_effect=failing_urlopen,
        ):
            result = fetch_daily_forecast(
                latitude=45.47, longitude=9.19, days=3,
                cache_dir=self.cache_dir,
                cache_ttl_hours=1.0,  # cache "fresca" sarebbe scaduta
            )
        self.assertEqual(len(result), 3)

    def test_network_failure_without_cache_raises(self):
        # Senza cache disponibile e senza rete, ci aspettiamo OSError.
        import urllib.error

        def failing_urlopen(*args, **kwargs):
            raise urllib.error.URLError("simulated failure")

        with patch(
            "fitosim.io.openmeteo.urllib.request.urlopen",
            side_effect=failing_urlopen,
        ):
            with self.assertRaises(OSError):
                fetch_daily_forecast(
                    latitude=45.47, longitude=9.19, days=3,
                    cache_dir=self.cache_dir,
                )


class TestEt0Parsing(unittest.TestCase):
    """
    Verifica del parsing del nuovo campo et0_fao_evapotranspiration,
    aggiunto per usare Open-Meteo come benchmark indipendente del
    nostro Hargreaves-Samani.
    """

    def test_et0_extracted_when_present(self):
        # Payload con et0 presente: il campo deve arrivare nei DailyWeather.
        payload = _sample_payload()
        payload["daily"]["et0_fao_evapotranspiration"] = [3.5, 3.8, 4.1]
        result = _parse_openmeteo_response(payload)
        self.assertAlmostEqual(result[0].et0_mm, 3.5, places=4)
        self.assertAlmostEqual(result[1].et0_mm, 3.8, places=4)
        self.assertAlmostEqual(result[2].et0_mm, 4.1, places=4)

    def test_et0_none_when_absent(self):
        # Senza et0 nella risposta, et0_mm deve essere None per ogni
        # giorno (compatibilità con server o zone in cui il dato manca).
        payload = _sample_payload()
        # Assicuriamoci che il campo non ci sia.
        payload["daily"].pop("et0_fao_evapotranspiration", None)
        result = _parse_openmeteo_response(payload)
        for w in result:
            self.assertIsNone(w.et0_mm)

    def test_et0_none_for_specific_day(self):
        # Un singolo giorno con None nella lista et0 deve diventare
        # et0_mm=None per quel DailyWeather, senza propagare errori
        # agli altri giorni.
        payload = _sample_payload()
        payload["daily"]["et0_fao_evapotranspiration"] = [3.5, None, 4.1]
        result = _parse_openmeteo_response(payload)
        self.assertAlmostEqual(result[0].et0_mm, 3.5, places=4)
        self.assertIsNone(result[1].et0_mm)
        self.assertAlmostEqual(result[2].et0_mm, 4.1, places=4)

    def test_et0_inconsistent_length_rejected(self):
        # Se et0 è presente ma con lunghezza diversa dalle altre serie,
        # è un payload corrotto: rigettiamo con ValueError.
        payload = _sample_payload()
        payload["daily"]["et0_fao_evapotranspiration"] = [3.5, 3.8]
        with self.assertRaises(ValueError):
            _parse_openmeteo_response(payload)


class TestForecastWithFetcherInjection(unittest.TestCase):
    """
    L'iniezione del fetcher è il pattern che ci permette di testare
    fetch_daily_forecast end-to-end senza alcuna chiamata di rete e
    senza monkey-patching di urlopen — molto più pulito.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_fetcher_injection_short_circuits_http(self):
        # Il fetcher mock viene chiamato al posto della rete e i suoi
        # dati passano per il parser come se fossero arrivati da HTTP.
        sample = _sample_payload()
        # Aggiungiamo et0 al payload per rendere il test più ricco.
        sample["daily"]["et0_fao_evapotranspiration"] = [3.0, 3.2, 3.4]

        captured_urls = []

        def mock_fetcher(url):
            captured_urls.append(url)
            return sample

        result = fetch_daily_forecast(
            latitude=45.47, longitude=9.19, days=3,
            cache_dir=self.cache_dir,
            use_cache=False,  # forziamo HTTP per testare il fetcher
            fetcher=mock_fetcher,
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(len(captured_urls), 1)
        # L'URL deve contenere i parametri attesi.
        self.assertIn("latitude=45.4700", captured_urls[0])
        self.assertIn("et0_fao_evapotranspiration", captured_urls[0])
        # Il dato et0 viene effettivamente trasportato fino al risultato.
        self.assertAlmostEqual(result[0].et0_mm, 3.0, places=4)


class TestArchiveEndpoint(unittest.TestCase):
    """Test della nuova funzione fetch_daily_archive."""

    def test_build_archive_url_includes_dates(self):
        from fitosim.io.openmeteo import _build_archive_url
        url = _build_archive_url(
            latitude=45.47, longitude=9.19,
            start_date=date(2025, 7, 1),
            end_date=date(2025, 7, 7),
        )
        self.assertIn("start_date=2025-07-01", url)
        self.assertIn("end_date=2025-07-07", url)
        self.assertIn("archive-api.open-meteo.com", url)

    def test_build_archive_url_rejects_inverted_dates(self):
        from fitosim.io.openmeteo import _build_archive_url
        with self.assertRaises(ValueError):
            _build_archive_url(
                latitude=45.47, longitude=9.19,
                start_date=date(2025, 7, 7),
                end_date=date(2025, 7, 1),
            )

    def test_fetch_archive_with_mock_fetcher(self):
        from fitosim.io.openmeteo import fetch_daily_archive

        sample = _sample_payload()
        sample["daily"]["et0_fao_evapotranspiration"] = [4.5, 4.7, 5.0]

        def mock_fetcher(url):
            self.assertIn("archive-api", url)  # endpoint corretto
            return sample

        result = fetch_daily_archive(
            latitude=45.47, longitude=9.19,
            start_date=date(2025, 7, 1),
            end_date=date(2025, 7, 3),
            fetcher=mock_fetcher,
        )
        self.assertEqual(len(result), 3)
        # I dati arrivano fino in fondo, et0 incluso.
        self.assertAlmostEqual(result[0].et0_mm, 4.5, places=4)
        self.assertAlmostEqual(result[2].et0_mm, 5.0, places=4)


if __name__ == "__main__":
    unittest.main()
