"""
Adapter HttpJsonSoilSensor per gateway hardware-to-HTTP.

Questo è il primo adapter "ricco" della tappa 2 della fascia 2: il
primo SoilSensor di fitosim che espone i campi EC, pH e temperatura
del substrato oltre a θ. È pensato per parlare con un gateway HTTP
locale (tipicamente un microcontrollore ESP32 con WiFi che a sua volta
legge sensori industriali via Modbus RTU su bus RS485) attraverso uno
schema JSON fisso e ben documentato.

Architettura: chi fa cosa
-------------------------

L'adapter divide deliberatamente le responsabilità in due livelli
distinti che risolvono problemi diversi:

  1. **Il gateway hardware** (NON parte di fitosim): un dispositivo
     fisico — tipicamente un ESP32 — che parla con i sensori reali nei
     loro protocolli nativi (Modbus, BLE, I2C, analogico) e li espone
     come endpoint HTTP REST. È responsabile dei dettagli "sporchi"
     dell'hardware: timing dei bus seriali, gestione errori dei
     sensori, alimentazione, calibrazione fisica.

  2. **L'adapter HttpJsonSoilSensor** (parte di fitosim): un client
     HTTP puro che fa GET su URL parametrizzati per channel, parsa il
     JSON secondo lo schema fisso, e produce SoilReading canonici.
     Non sa nulla di Modbus, di RS485, di Bluetooth: vede solo HTTP
     e JSON.

Questa separazione ha tre conseguenze importanti per il design del
sistema. Primo, fitosim non acquisisce mai dipendenze esterne come
pyserial o pymodbus o bleak: lo stack core resta puro standard library.
Secondo, qualsiasi sensore esistente o futuro può essere integrato in
fitosim semplicemente scrivendo un piccolo gateway dedicato che esponga
lo schema JSON V1; il codice di fitosim non cambia mai. Terzo, i test
sono semplicissimi: basta mockare le risposte HTTP, niente simulatori
hardware.

Schema JSON V1
--------------

L'adapter si aspetta che il gateway risponda con JSON conforme alla
struttura dichiarata in `HttpJsonSchemaV1`. È uno schema fisso
deliberatamente semplice, mappato uno-a-uno sui campi canonici di
SoilReading di fitosim. La docstring di HttpJsonSchemaV1 contiene un
esempio completo che il firmware del gateway deve riprodurre.

Per evolvere lo schema in futuro (es. aggiungere campi per sensori UV
o di flusso linfatico), faremo HttpJsonSchemaV2 mantenendo V1 come
legacy supportato. Il chiamante sceglierà quale versione usare al
momento della costruzione dell'adapter.

Convenzione di autenticazione
-----------------------------

Il bearer token è opzionale: senza autenticazione l'adapter funziona,
adatto a uso in LAN domestica affidabile. Per setup più rigorosi
(esposizione via Tailscale, condivisione con utenti diversi) si può
passare un token esplicito al costruttore, oppure usare il pattern
`from_env()` che legge `FITOSIM_HTTP_GATEWAY_TOKEN` dall'ambiente.

Quando il token è presente, l'adapter lo aggiunge automaticamente
all'header `Authorization: Bearer <token>` di ogni richiesta.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fitosim.io.sensors.errors import (
    SensorDataQualityError,
    SensorPermanentError,
    SensorTemporaryError,
)
from fitosim.io.sensors.types import (
    ReadingQuality,
    SoilReading,
)


PROVIDER_NAME = "http_json"

# Variabile d'ambiente per il bearer token, secondo la convenzione
# fitosim FITOSIM_<PROVIDER>_<CREDENTIAL>.
ENV_FITOSIM_GATEWAY_TOKEN = "FITOSIM_HTTP_GATEWAY_TOKEN"

# Timeout di default per le richieste HTTP. Più aggressivo di
# Open-Meteo (10s) perché ci aspettiamo che il gateway sia in LAN
# locale: 5 secondi sono ampiamente sufficienti, oltre quel tempo
# qualcosa non sta funzionando.
DEFAULT_HTTP_TIMEOUT_SECONDS = 5.0


# ==========================================================================
#  Schema JSON V1
# ==========================================================================

@dataclass(frozen=True)
class HttpJsonSchemaV1:
    """
    Schema JSON versione 1 atteso dall'HttpJsonSoilSensor.

    Questa dataclass è documentazione vivente: definisce esattamente
    cosa il gateway deve emettere sull'endpoint HTTP perché fitosim
    possa consumare i dati. Non viene mai istanziata direttamente
    dal codice utente; è un riferimento per chi scrive il firmware
    del gateway.

    Esempio di JSON che il gateway deve restituire
    ----------------------------------------------

    Risposta a `GET /api/soil/<channel_id>` (200 OK)::

        {
          "schema_version": "v1",
          "timestamp": "2026-04-27T19:55:00Z",
          "channel_id": "1",
          "theta_volumetric": 0.342,
          "temperature_c": 18.5,
          "ec_mscm": 1.85,
          "ph": 6.4,
          "provider_specific": {
            "npk_n_estimate_mg_kg": 42,
            "npk_p_estimate_mg_kg": 12,
            "npk_k_estimate_mg_kg": 55,
            "ec_raw_uncompensated_mscm": 1.92,
            "modbus_address": 1
          },
          "quality": {
            "battery_level": 0.78,
            "last_calibration": "2026-03-15",
            "staleness_seconds": 23
          }
        }

    Campi obbligatori
    -----------------

    Solo tre campi sono strettamente richiesti:
      - `schema_version`: stringa "v1" (per identificare la versione
         dello schema; il gateway può evolverlo in futuro).
      - `timestamp`: ISO8601 con timezone (es. "Z" per UTC). Il
         momento della lettura effettiva del sensore, NON il momento
         della risposta HTTP.
      - `theta_volumetric`: numero in [0, 1.05]. Il dato minimo che
         ogni SoilSensor deve fornire.

    Campi opzionali (omettibili o passabili come null)
    --------------------------------------------------

    Tutti gli altri campi sono opzionali e diventano `None` nel
    SoilReading se assenti dal JSON:
      - `temperature_c`, `ec_mscm`, `ph`: misure aggiuntive del
         sensore se disponibili.
      - `channel_id`: utile per il logging diagnostico, ignorato
         dall'adapter (che già conosce il channel da come ha costruito
         l'URL).
      - `provider_specific`: dict di qualsiasi forma per dati
         "di secondo livello" come gli NPK derivati. fitosim li
         conserva opachi e li espone nel SoilReading per la
         presentazione, ma non li usa nel modello fisico.
      - `quality`: sotto-oggetto con metadati di qualità della
         lettura (batteria, ultima calibrazione, staleness).
    """

    # Questa classe è documentale: non ha campi né logica.
    # La sua unica funzione è ospitare la docstring sopra come
    # riferimento autorevole per chi scrive un gateway compatibile.


# ==========================================================================
#  Funzioni di parsing
# ==========================================================================

def _parse_iso_timestamp(value: str) -> datetime:
    """
    Parsa un timestamp ISO8601 in datetime aware UTC.

    Stessa logica di _parse_iso_timestamp in fixtures.py ma duplicata
    qui per evitare un'importazione cross-modulo che alzerebbe
    l'accoppiamento tra moduli che non hanno altri legami.
    """
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(cleaned)
    except (ValueError, AttributeError) as e:
        raise SensorPermanentError(
            f"Timestamp non parsabile dal gateway: '{value}'. "
            f"Formato atteso ISO8601 con timezone (es. "
            f"'2026-04-27T19:55:00Z').",
            provider=PROVIDER_NAME,
        ) from e

    if ts.tzinfo is None:
        raise SensorPermanentError(
            f"Timestamp '{value}' senza timezone. "
            f"Il gateway deve emettere timestamp UTC con suffisso 'Z' "
            f"(consigliato) o offset esplicito.",
            provider=PROVIDER_NAME,
        )

    return ts


def _parse_json_to_reading(payload: dict) -> SoilReading:
    """
    Traduce un payload JSON conforme allo schema V1 in SoilReading
    canonico.

    Solleva:
      - SensorPermanentError per JSON malformato o campi obbligatori
        mancanti (problema strutturale del gateway).
      - SensorDataQualityError per valori fuori range fisici (problema
        del sensore; il gateway funziona ma i dati non sono affidabili).
        Questa eccezione viene sollevata implicitamente dai
        __post_init__ di SoilReading e ReadingQuality.
    """
    # Verifica della versione schema: se manca o non è "v1", rifiutiamo
    # esplicitamente per evitare bug subdoli da disallineamento del
    # gateway. Una eventuale evoluzione futura cambierà la versione e
    # il gateway dovrà essere aggiornato consapevolmente.
    schema_version = payload.get("schema_version")
    if schema_version != "v1":
        raise SensorPermanentError(
            f"Schema version non riconosciuta: "
            f"'{schema_version}'. Atteso 'v1'. "
            f"Verifica che il firmware del gateway sia aggiornato e "
            f"che emetta il campo schema_version corretto.",
            provider=PROVIDER_NAME,
        )

    # Campi obbligatori. Mancarne uno è un problema strutturale del
    # gateway, non un errore di qualità del dato.
    timestamp_str = payload.get("timestamp")
    if not timestamp_str:
        raise SensorPermanentError(
            "Campo obbligatorio 'timestamp' mancante o vuoto nella "
            "risposta del gateway.",
            provider=PROVIDER_NAME,
        )
    timestamp = _parse_iso_timestamp(timestamp_str)

    theta = payload.get("theta_volumetric")
    if theta is None:
        raise SensorPermanentError(
            "Campo obbligatorio 'theta_volumetric' mancante o null "
            "nella risposta del gateway.",
            provider=PROVIDER_NAME,
        )

    # Sotto-oggetto quality: opzionale, costruito solo se presente.
    # Estraiamo i campi singolarmente per validare ognuno.
    quality_data = payload.get("quality", {})
    last_calibration = None
    if "last_calibration" in quality_data and quality_data["last_calibration"]:
        try:
            from datetime import date
            last_calibration = date.fromisoformat(
                quality_data["last_calibration"]
            )
        except (ValueError, TypeError) as e:
            raise SensorPermanentError(
                f"Campo quality.last_calibration non parsabile: "
                f"'{quality_data['last_calibration']}'. "
                f"Atteso formato ISO 'YYYY-MM-DD'.",
                provider=PROVIDER_NAME,
            ) from e

    # ReadingQuality.__post_init__ valida battery_level e
    # staleness_seconds; se fuori range solleverà
    # SensorDataQualityError che propaghiamo come è.
    quality = ReadingQuality(
        battery_level=quality_data.get("battery_level"),
        last_calibration=last_calibration,
        staleness_seconds=int(quality_data.get("staleness_seconds", 0)),
    )

    # provider_specific: opzionale, accettiamo qualsiasi dict.
    provider_specific = payload.get("provider_specific", {})
    if not isinstance(provider_specific, dict):
        raise SensorPermanentError(
            f"Campo 'provider_specific' deve essere un oggetto JSON "
            f"(dict). Ricevuto: {type(provider_specific).__name__}.",
            provider=PROVIDER_NAME,
        )

    # Costruzione del SoilReading: il __post_init__ valida i range
    # fisici (theta in [0,1.05], EC in [0,20], pH in [0,14], ecc.)
    # e solleva SensorDataQualityError se i valori sono spurii.
    return SoilReading(
        timestamp=timestamp,
        theta_volumetric=float(theta),
        temperature_c=payload.get("temperature_c"),
        ec_mscm=payload.get("ec_mscm"),
        ph=payload.get("ph"),
        quality=quality,
        provider_specific=provider_specific,
    )


# ==========================================================================
#  Adapter principale
# ==========================================================================

class HttpJsonSoilSensor:
    """
    Adapter SoilSensor per gateway HTTP-JSON (tappa 2 fascia 2).

    Parla con qualsiasi endpoint HTTP che restituisca JSON conforme
    allo schema V1 documentato in `HttpJsonSchemaV1`. Il caso d'uso
    paradigmatico è un microcontrollore ESP32 con WiFi e MAX485 che
    legge sensori ATO 7-in-1 via Modbus RTU sul bus RS485 e li espone
    come endpoint REST al resto della rete locale.

    Esempio d'uso
    -------------

    ::

        from fitosim.io.sensors import HttpJsonSoilSensor

        # Gateway ESP32 in LAN, niente autenticazione (uso domestico)
        sensor = HttpJsonSoilSensor(
            base_url="http://192.168.1.42",
            endpoint_pattern="/api/soil/{channel_id}",
        )
        reading = sensor.current_state(channel_id="1")
        print(f"θ vaso 1: {reading.theta_volumetric:.3f}")
        print(f"EC: {reading.ec_mscm:.2f} mS/cm, pH: {reading.ph}")

        # Gateway con bearer token (uso più rigoroso)
        sensor = HttpJsonSoilSensor(
            base_url="http://192.168.1.42",
            endpoint_pattern="/api/soil/{channel_id}",
            bearer_token="il-mio-token-segreto",
        )

        # Oppure leggendo il token dall'ambiente
        sensor = HttpJsonSoilSensor.from_env(
            base_url="http://192.168.1.42",
        )
        # legge FITOSIM_HTTP_GATEWAY_TOKEN se presente

    Parametri del costruttore
    -------------------------
    base_url : str
        URL base del gateway, senza path finale. Esempi:
        "http://192.168.1.42", "http://esp32-balcone.local",
        "https://my-gateway.example.com:8080".
    endpoint_pattern : str
        Pattern del path che include `{channel_id}` come placeholder.
        Default: "/api/soil/{channel_id}". Il chiamante può
        personalizzarlo se il gateway usa un altro schema di URL.
    bearer_token : str | None
        Token di autenticazione Bearer da inviare nell'header
        Authorization. None = niente autenticazione (default,
        adatto a LAN affidabile).
    timeout_seconds : float
        Timeout per la richiesta HTTP, default 5 secondi.
    """

    def __init__(
        self,
        base_url: str,
        *,
        endpoint_pattern: str = "/api/soil/{channel_id}",
        bearer_token: Optional[str] = None,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        if not base_url:
            raise ValueError(
                "HttpJsonSoilSensor richiede un base_url non vuoto "
                "(es. 'http://192.168.1.42')."
            )
        if "{channel_id}" not in endpoint_pattern:
            raise ValueError(
                f"endpoint_pattern deve contenere '{{channel_id}}' "
                f"come placeholder. Ricevuto: '{endpoint_pattern}'."
            )
        # Normalizziamo il base_url togliendo eventuali / finali per
        # evitare doppie slash quando concateniamo l'endpoint.
        self._base_url = base_url.rstrip("/")
        self._endpoint_pattern = endpoint_pattern
        self._bearer_token = bearer_token
        self._timeout = timeout_seconds

    @classmethod
    def from_env(
        cls,
        base_url: str,
        *,
        endpoint_pattern: str = "/api/soil/{channel_id}",
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> "HttpJsonSoilSensor":
        """
        Costruisce l'adapter leggendo il bearer token dall'ambiente.

        La variabile letta è `FITOSIM_HTTP_GATEWAY_TOKEN`. Se è
        valorizzata, viene usata come bearer; se non è valorizzata o
        è vuota, l'adapter è costruito senza autenticazione (caso
        normale per uso LAN domestico).

        A differenza di EcowittEnvironmentSensor.from_env() che
        solleva RuntimeError se le credenziali mancano, qui l'assenza
        del token è uno stato accettato e silenzioso: l'autenticazione
        è opzionale per design.
        """
        token = os.environ.get(ENV_FITOSIM_GATEWAY_TOKEN)
        # Trattiamo stringa vuota come "non valorizzato" per essere
        # robusti a `.env` con righe tipo `FITOSIM_HTTP_GATEWAY_TOKEN=`
        # (variabile dichiarata ma vuota).
        if token is not None and token.strip() == "":
            token = None
        return cls(
            base_url=base_url,
            endpoint_pattern=endpoint_pattern,
            bearer_token=token,
            timeout_seconds=timeout_seconds,
        )

    def _build_url(self, channel_id: str) -> str:
        """Costruisce l'URL completo per un channel_id specifico."""
        path = self._endpoint_pattern.format(channel_id=channel_id)
        return f"{self._base_url}{path}"

    def _build_request(self, url: str) -> urllib.request.Request:
        """
        Costruisce la Request HTTP includendo l'header Authorization
        se il bearer token è valorizzato.
        """
        request = urllib.request.Request(url, method="GET")
        request.add_header("Accept", "application/json")
        if self._bearer_token:
            request.add_header(
                "Authorization", f"Bearer {self._bearer_token}",
            )
        # User-Agent identificativo: utile nei log del gateway per
        # capire chi sta facendo le richieste.
        request.add_header("User-Agent", "fitosim/2.0 HttpJsonSoilSensor")
        return request

    def current_state(self, channel_id: str) -> SoilReading:
        """
        Restituisce lo stato corrente del substrato per il canale.

        Solleva:
          - SensorTemporaryError per timeout di rete, errori 5xx,
            429 rate limiting (recuperabili).
          - SensorPermanentError per credenziali sbagliate (401, 403),
            URL inesistenti (404), JSON malformato, schema non
            conforme.
          - SensorDataQualityError per valori fuori range fisici (θ
            negativo, pH > 14, ecc.) — sollevata indirettamente dal
            __post_init__ di SoilReading.
        """
        if not channel_id or not str(channel_id).strip():
            raise SensorPermanentError(
                "channel_id non può essere vuoto.",
                provider=PROVIDER_NAME,
            )

        url = self._build_url(str(channel_id))
        request = self._build_request(url)

        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout,
            ) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise SensorTemporaryError(
                    f"Gateway HTTP errore server (HTTP {e.code}) "
                    f"su {url}: {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
            elif e.code in (401, 403):
                raise SensorPermanentError(
                    f"Gateway HTTP autenticazione rifiutata "
                    f"(HTTP {e.code}). Verifica il bearer token "
                    f"(variabile {ENV_FITOSIM_GATEWAY_TOKEN}).",
                    provider=PROVIDER_NAME,
                ) from e
            elif e.code == 404:
                raise SensorPermanentError(
                    f"Channel '{channel_id}' non trovato sul gateway "
                    f"(HTTP 404 su {url}). Verifica che il sensore sia "
                    f"collegato e configurato.",
                    provider=PROVIDER_NAME,
                ) from e
            else:
                raise SensorPermanentError(
                    f"Gateway HTTP errore client (HTTP {e.code}) "
                    f"su {url}: {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
        except urllib.error.URLError as e:
            # DNS, timeout, host unreachable: tutto recuperabile.
            raise SensorTemporaryError(
                f"Gateway HTTP non raggiungibile su {url}: {e.reason}",
                provider=PROVIDER_NAME,
            ) from e
        except TimeoutError as e:
            # Timeout esplicito (Python 3.10+ può sollevare questo
            # invece di URLError dipendendo dalla situazione).
            raise SensorTemporaryError(
                f"Timeout dopo {self._timeout}s su {url}.",
                provider=PROVIDER_NAME,
            ) from e

        # Parsing del JSON. Errore qui = gateway che restituisce
        # qualcosa di non-JSON, problema permanente di configurazione.
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise SensorPermanentError(
                f"Gateway ha risposto con qualcosa che non è JSON "
                f"valido: {e}",
                provider=PROVIDER_NAME,
            ) from e

        if not isinstance(payload, dict):
            raise SensorPermanentError(
                f"Gateway ha risposto con un JSON che non è un oggetto "
                f"(atteso dict, ricevuto {type(payload).__name__}).",
                provider=PROVIDER_NAME,
            )

        # Conversione finale dal payload allo schema canonico. Le
        # eccezioni di parsing del payload e di validazione fisica
        # sono già propagate correttamente da _parse_json_to_reading.
        return _parse_json_to_reading(payload)
