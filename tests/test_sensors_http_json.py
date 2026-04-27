"""
Test dell'adapter HttpJsonSoilSensor (tappa 2 fascia 2).

Strategia di test
-----------------

L'adapter parla HTTP con un gateway esterno e parsa JSON. I test
coprono quattro aree distinte:

  1. **Traduzione corretta**: payload V1 ben formato → SoilReading
     canonico con campi mappati correttamente, unità preservate,
     timestamp UTC aware, provider_specific opaco.

  2. **Validazione schema V1**: schema_version sbagliata o assente,
     campi obbligatori mancanti, tipi non conformi → SensorPermanentError
     con messaggi diagnostici utili al debugging del firmware del
     gateway.

  3. **Mapping errori HTTP**: 401/403 → Permanent (autenticazione),
     404 → Permanent (channel inesistente), 5xx/429 → Temporary
     (problemi server recuperabili), URLError/timeout → Temporary
     (rete inaccessibile), JSON malformato → Permanent (gateway
     che produce qualcosa di non-JSON).

  4. **Autenticazione**: bearer token assente (uso LAN affidabile),
     bearer esplicito al costruttore (uso production), bearer letto
     da FITOSIM_HTTP_GATEWAY_TOKEN via from_env() (pattern fitosim).

Per evitare chiamate HTTP reali, mockiamo `urllib.request.urlopen`
intercettando le chiamate e restituendo risposte controllate. Questo
ci permette di testare tutto il path dell'adapter — dalla costruzione
dell'URL al parsing del JSON al sollevamento delle eccezioni — senza
dipendere da un vero gateway hardware.
"""

import io
import json
import urllib.error
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from fitosim.io.sensors import (
    HttpJsonSchemaV1,
    HttpJsonSoilSensor,
    SensorPermanentError,
    SensorTemporaryError,
    SoilReading,
    SoilSensor,
)
from fitosim.io.sensors.http_json import (
    ENV_FITOSIM_GATEWAY_TOKEN,
    _parse_iso_timestamp,
    _parse_json_to_reading,
)


# --------------------------------------------------------------------------
#  Helper: payload JSON V1 realistico per i test
# --------------------------------------------------------------------------

def _make_payload_v1(
    *,
    timestamp: str = "2026-04-27T19:55:00Z",
    theta: float = 0.342,
    temperature: float = 18.5,
    ec: float = 1.85,
    ph: float = 6.4,
    quality: dict = None,
    provider_specific: dict = None,
    channel_id: str = "1",
) -> dict:
    """
    Costruisce un payload JSON V1 realistico per un sensore ATO 7-in-1
    visto attraverso un gateway ESP32. I default rappresentano una
    lettura plausibile di un vaso di basilico ben curato a metà
    giornata.
    """
    return {
        "schema_version": "v1",
        "timestamp": timestamp,
        "channel_id": channel_id,
        "theta_volumetric": theta,
        "temperature_c": temperature,
        "ec_mscm": ec,
        "ph": ph,
        "provider_specific": provider_specific or {
            "npk_n_estimate_mg_kg": 42,
            "npk_p_estimate_mg_kg": 12,
            "npk_k_estimate_mg_kg": 55,
            "modbus_address": 1,
        },
        "quality": quality or {
            "battery_level": 0.78,
            "last_calibration": "2026-03-15",
            "staleness_seconds": 23,
        },
    }


def _mock_http_response(payload: dict):
    """
    Costruisce un MagicMock che simula la risposta di urllib.urlopen()
    quando usata con `with urllib.request.urlopen(...) as response`.
    Il payload viene serializzato in JSON e restituito come bytes da
    `response.read()`.
    """
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    # `with ... as response` chiama __enter__/__exit__: il contesto
    # ritorna `response` stesso quando usato come gestore.
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


# --------------------------------------------------------------------------
#  Famiglia 1: Traduzione corretta del payload V1
# --------------------------------------------------------------------------

class Test_HttpJson_translation:
    """
    Dato un payload V1 ben formato, l'adapter produce un SoilReading
    canonico con tutti i campi mappati correttamente.
    """

    def test_translates_full_payload(self):
        """Caso completo: payload con tutti i campi → Reading completo."""
        payload = _make_payload_v1()
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            reading = sensor.current_state(channel_id="1")

        assert isinstance(reading, SoilReading)
        assert reading.theta_volumetric == 0.342
        assert reading.temperature_c == 18.5
        assert reading.ec_mscm == 1.85
        assert reading.ph == 6.4
        # Timestamp è UTC aware
        assert reading.timestamp == datetime(
            2026, 4, 27, 19, 55, 0, tzinfo=timezone.utc,
        )

    def test_provider_specific_preserved_opaque(self):
        """
        Il dict provider_specific viene conservato verbatim, fitosim
        non lo interpreta. È il punto di estensibilità per dati di
        secondo livello come gli NPK derivati.
        """
        custom = {
            "npk_n_estimate_mg_kg": 42,
            "ec_raw_uncompensated_mscm": 1.92,
            "modbus_address": 1,
            "firmware_version": "ato-fw-2.3.1",
            "totally_custom_key": [1, 2, 3],
        }
        payload = _make_payload_v1(provider_specific=custom)
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            reading = sensor.current_state(channel_id="1")

        # Il dict è preservato verbatim, anche con chiavi/valori
        # arbitrari che fitosim non comprende.
        assert reading.provider_specific == custom

    def test_quality_metadata_preserved(self):
        """Il sotto-oggetto quality viene popolato correttamente."""
        payload = _make_payload_v1(quality={
            "battery_level": 0.42,
            "last_calibration": "2025-10-01",
            "staleness_seconds": 120,
        })
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            reading = sensor.current_state(channel_id="1")

        assert reading.quality.battery_level == 0.42
        assert reading.quality.last_calibration == date(2025, 10, 1)
        assert reading.quality.staleness_seconds == 120

    def test_optional_fields_become_none(self):
        """
        Campi opzionali assenti dal payload diventano None nel Reading.
        Caso d'uso: sensore WH51 esposto via HttpJson che fornisce solo
        θ.
        """
        # Payload minimo: solo i campi obbligatori.
        minimal = {
            "schema_version": "v1",
            "timestamp": "2026-04-27T19:55:00Z",
            "theta_volumetric": 0.32,
        }
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(minimal),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            reading = sensor.current_state(channel_id="1")

        assert reading.theta_volumetric == 0.32
        assert reading.temperature_c is None
        assert reading.ec_mscm is None
        assert reading.ph is None
        assert reading.provider_specific == {}
        # quality default: tutti i campi None/0
        assert reading.quality.battery_level is None
        assert reading.quality.staleness_seconds == 0

    def test_url_construction_with_trailing_slash(self):
        """base_url con / finale viene normalizzato (no doppio slash)."""
        payload = _make_payload_v1()
        captured_url = []

        def capture_urlopen(request, **kwargs):
            captured_url.append(request.full_url)
            return _mock_http_response(payload)

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=capture_urlopen,
        ):
            sensor = HttpJsonSoilSensor(
                base_url="http://test.local/",  # / finale
            )
            sensor.current_state(channel_id="1")

        # L'URL costruito ha un solo /, non // dopo "test.local".
        assert captured_url[0] == "http://test.local/api/soil/1"

    def test_custom_endpoint_pattern_works(self):
        """
        endpoint_pattern personalizzato funziona se contiene
        {channel_id}.
        """
        payload = _make_payload_v1()
        captured_url = []

        def capture_urlopen(request, **kwargs):
            captured_url.append(request.full_url)
            return _mock_http_response(payload)

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=capture_urlopen,
        ):
            sensor = HttpJsonSoilSensor(
                base_url="http://test.local",
                endpoint_pattern="/sensors/v2/pot-{channel_id}/state",
            )
            sensor.current_state(channel_id="basilico_1")

        assert captured_url[0] == (
            "http://test.local/sensors/v2/pot-basilico_1/state"
        )


# --------------------------------------------------------------------------
#  Famiglia 2: Validazione dello schema V1
# --------------------------------------------------------------------------

class Test_HttpJson_schema_validation:
    """Payload non conformi → SensorPermanentError con diagnostica."""

    def test_missing_schema_version_raises(self):
        """schema_version mancante → errore con suggerimento."""
        payload = {
            "timestamp": "2026-04-27T19:55:00Z",
            "theta_volumetric": 0.32,
            # niente schema_version
        }
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="schema"):
                sensor.current_state(channel_id="1")

    def test_wrong_schema_version_raises(self):
        """schema_version diversa da 'v1' → errore esplicito."""
        payload = _make_payload_v1()
        payload["schema_version"] = "v99"
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="v99"):
                sensor.current_state(channel_id="1")

    def test_missing_timestamp_raises(self):
        """timestamp obbligatorio assente → errore strutturale."""
        payload = _make_payload_v1()
        del payload["timestamp"]
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="timestamp"):
                sensor.current_state(channel_id="1")

    def test_missing_theta_raises(self):
        """theta_volumetric obbligatorio assente → errore strutturale."""
        payload = _make_payload_v1()
        del payload["theta_volumetric"]
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="theta_volumetric"):
                sensor.current_state(channel_id="1")

    def test_naive_timestamp_raises(self):
        """
        Timestamp senza timezone → errore: la regola architetturale
        richiede UTC aware sempre.
        """
        payload = _make_payload_v1(timestamp="2026-04-27T19:55:00")
        # niente Z, niente offset → naive
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="timezone"):
                sensor.current_state(channel_id="1")

    def test_provider_specific_not_a_dict_raises(self):
        """
        provider_specific deve essere un oggetto JSON, non un array
        o uno scalare.
        """
        payload = _make_payload_v1()
        payload["provider_specific"] = ["not", "a", "dict"]
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="provider_specific"):
                sensor.current_state(channel_id="1")

    def test_payload_not_json_object_raises(self):
        """
        Risposta che è un JSON ma non un dict (es. un array di top
        level) → errore.
        """
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response([1, 2, 3]),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="oggetto"):
                sensor.current_state(channel_id="1")


# --------------------------------------------------------------------------
#  Famiglia 3: Mapping degli errori HTTP/rete
# --------------------------------------------------------------------------

class Test_HttpJson_error_mapping:
    """Errori HTTP e di rete vengono mappati sulla gerarchia canonica."""

    def test_http_500_becomes_temporary(self):
        def raise_http_error(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="http://test.local/api/soil/1",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=None,
            )

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=raise_http_error,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorTemporaryError, match="500"):
                sensor.current_state(channel_id="1")

    def test_http_429_rate_limit_becomes_temporary(self):
        """429 è 4xx ma è recuperabile aspettando → Temporary."""
        def raise_http_error(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="http://test.local/api/soil/1",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=None,
            )

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=raise_http_error,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorTemporaryError):
                sensor.current_state(channel_id="1")

    def test_http_401_becomes_permanent_with_token_message(self):
        """401 → Permanent con suggerimento sulla variabile d'ambiente."""
        def raise_http_error(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="http://test.local/api/soil/1",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=None,
            )

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=raise_http_error,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(
                SensorPermanentError, match="FITOSIM_HTTP_GATEWAY_TOKEN",
            ):
                sensor.current_state(channel_id="1")

    def test_http_404_becomes_permanent_with_channel_message(self):
        """404 → Permanent con suggerimento sul channel."""
        def raise_http_error(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="http://test.local/api/soil/99",
                code=404,
                msg="Not Found",
                hdrs={},
                fp=None,
            )

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=raise_http_error,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="99"):
                sensor.current_state(channel_id="99")

    def test_url_error_becomes_temporary(self):
        """DNS, host unreachable → Temporary."""
        def raise_url_error(*args, **kwargs):
            raise urllib.error.URLError("DNS failure")

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=raise_url_error,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://nonexistent.local")
            with pytest.raises(SensorTemporaryError, match="DNS"):
                sensor.current_state(channel_id="1")

    def test_malformed_json_becomes_permanent(self):
        """Body non-JSON → Permanent (gateway misconfigurato)."""
        bad_response = MagicMock()
        bad_response.read.return_value = b"<html>Error 500</html>"
        bad_response.__enter__ = MagicMock(return_value=bad_response)
        bad_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=bad_response,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            with pytest.raises(SensorPermanentError, match="JSON"):
                sensor.current_state(channel_id="1")

    def test_data_quality_error_propagated(self):
        """
        θ fuori range nel payload → SensorDataQualityError sollevato
        dal __post_init__ di SoilReading e propagato dall'adapter.
        """
        payload = _make_payload_v1(theta=2.5)  # fuori range
        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            return_value=_mock_http_response(payload),
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            from fitosim.io.sensors import SensorDataQualityError
            with pytest.raises(SensorDataQualityError, match="theta"):
                sensor.current_state(channel_id="1")


# --------------------------------------------------------------------------
#  Famiglia 4: Autenticazione (bearer token)
# --------------------------------------------------------------------------

class Test_HttpJson_authentication:
    """
    Tre modalità di autenticazione: nessuna, token esplicito,
    token via from_env().
    """

    def test_no_auth_by_default(self):
        """Senza token, nessun header Authorization è inviato."""
        payload = _make_payload_v1()
        captured_headers = []

        def capture_urlopen(request, **kwargs):
            captured_headers.append(dict(request.headers))
            return _mock_http_response(payload)

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=capture_urlopen,
        ):
            sensor = HttpJsonSoilSensor(base_url="http://test.local")
            sensor.current_state(channel_id="1")

        # urllib normalizza i nomi degli header in title-case.
        # Authorization NON deve essere presente.
        assert "Authorization" not in captured_headers[0]

    def test_explicit_token_in_constructor(self):
        """Token esplicito → header Authorization Bearer."""
        payload = _make_payload_v1()
        captured_headers = []

        def capture_urlopen(request, **kwargs):
            captured_headers.append(dict(request.headers))
            return _mock_http_response(payload)

        with patch(
            "fitosim.io.sensors.http_json.urllib.request.urlopen",
            side_effect=capture_urlopen,
        ):
            sensor = HttpJsonSoilSensor(
                base_url="http://test.local",
                bearer_token="my-secret-token",
            )
            sensor.current_state(channel_id="1")

        assert captured_headers[0]["Authorization"] == "Bearer my-secret-token"

    def test_from_env_reads_token(self, monkeypatch):
        """from_env() legge FITOSIM_HTTP_GATEWAY_TOKEN se presente."""
        monkeypatch.setenv(ENV_FITOSIM_GATEWAY_TOKEN, "env-token-123")
        sensor = HttpJsonSoilSensor.from_env(base_url="http://test.local")
        assert sensor._bearer_token == "env-token-123"

    def test_from_env_silent_when_token_absent(self, monkeypatch):
        """
        from_env() senza token settato non solleva: l'auth è opzionale.
        """
        monkeypatch.delenv(ENV_FITOSIM_GATEWAY_TOKEN, raising=False)
        sensor = HttpJsonSoilSensor.from_env(base_url="http://test.local")
        assert sensor._bearer_token is None

    def test_from_env_treats_empty_string_as_absent(self, monkeypatch):
        """
        Variabile dichiarata ma vuota (es. `FITOSIM_HTTP_GATEWAY_TOKEN=`
        nel .env) viene trattata come assente.
        """
        monkeypatch.setenv(ENV_FITOSIM_GATEWAY_TOKEN, "")
        sensor = HttpJsonSoilSensor.from_env(base_url="http://test.local")
        assert sensor._bearer_token is None


# --------------------------------------------------------------------------
#  Famiglia 5: Validazione dei parametri di costruzione
# --------------------------------------------------------------------------

class Test_HttpJson_constructor_validation:
    """Il costruttore rifiuta input invalidi con messaggi chiari."""

    def test_empty_base_url_raises(self):
        with pytest.raises(ValueError, match="base_url"):
            HttpJsonSoilSensor(base_url="")

    def test_endpoint_without_placeholder_raises(self):
        """
        endpoint_pattern senza {channel_id} è inutile: tutte le
        richieste andrebbero allo stesso URL.
        """
        with pytest.raises(ValueError, match="channel_id"):
            HttpJsonSoilSensor(
                base_url="http://test.local",
                endpoint_pattern="/api/soil/static",  # niente {channel_id}
            )

    def test_empty_channel_id_in_current_state_raises(self):
        """channel_id vuoto al runtime → SensorPermanentError."""
        sensor = HttpJsonSoilSensor(base_url="http://test.local")
        with pytest.raises(SensorPermanentError, match="channel_id"):
            sensor.current_state(channel_id="")


# --------------------------------------------------------------------------
#  Famiglia 6: Conformità al Protocol SoilSensor
# --------------------------------------------------------------------------

class Test_HttpJson_protocol_conformance:
    """L'adapter soddisfa il Protocol SoilSensor via runtime_checkable."""

    def test_isinstance_check(self):
        sensor = HttpJsonSoilSensor(base_url="http://test.local")
        assert isinstance(sensor, SoilSensor)


# --------------------------------------------------------------------------
#  Famiglia 7: HttpJsonSchemaV1 come dataclass documentale
# --------------------------------------------------------------------------

class Test_HttpJsonSchemaV1:
    """
    HttpJsonSchemaV1 è una dataclass documentale: la sua docstring è
    il contratto, non i suoi campi (non ne ha).
    """

    def test_has_documentation(self):
        """La docstring contiene un esempio JSON completo."""
        assert HttpJsonSchemaV1.__doc__ is not None
        assert "schema_version" in HttpJsonSchemaV1.__doc__
        assert "v1" in HttpJsonSchemaV1.__doc__

    def test_can_be_instantiated_for_introspection(self):
        """Si può istanziare senza errori per ispezionarla."""
        # Niente campi obbligatori, costruzione default.
        schema = HttpJsonSchemaV1()
        assert schema is not None
