"""
Client per la stazione meteo Ecowitt — letture in tempo reale.

Diversamente da Open-Meteo che fornisce dati grigliati su scala
chilometrica, Ecowitt restituisce le letture *fisiche* della stazione
installata dall'utente: temperatura, umidità, vento, radiazione solare
e — soprattutto — l'umidità del substrato dei sensori WH51 inseriti
nei singoli vasi. Queste letture sono il "ground truth" che permette
a fitosim di validare e calibrare il modello di bilancio idrico contro
la realtà fisica del balcone dell'utente.

Endpoint utilizzato
-------------------
    https://api.ecowitt.net/api/v3/device/real_time

Parametri di query (tutti obbligatori):
    application_key  — chiave applicativa, ottenuta da api.ecowitt.net
    api_key          — chiave personale dell'utente
    mac              — MAC address della stazione (es. "AA:BB:CC:DD:EE:FF")
    call_back        — sempre "all" per ricevere tutti i sensori

Sicurezza delle credenziali
---------------------------
Le tre credenziali sono dati sensibili. Il modulo offre la funzione
`credentials_from_env()` che le legge dalle variabili d'ambiente:

    ECOWITT_APPLICATION_KEY
    ECOWITT_API_KEY
    ECOWITT_MAC

Questo è il pattern raccomandato: le credenziali non finiscono mai nel
codice sorgente né nei file commitati. Per uso locale è anche possibile
salvarle in un file .env (escluso dal git) e caricarle con `python-dotenv`
o uno script di shell prima di eseguire fitosim.

Conversioni di unità
--------------------
Ecowitt restituisce ogni valore nel formato {time, unit, value}, dove
`unit` è la stringa configurata nell'account utente: alcuni hanno °F /
inches / mph (imperiale), altri °C / mm / m/s (metrico). Il modulo
legge l'unità dichiarata dall'API e converte sempre in **metrico** per
coerenza con il motore scientifico FAO-56 di fitosim. L'utente non
deve preoccuparsi di come è configurato il proprio account.

Robustezza alle assenze di sensori
----------------------------------
Diversi utenti hanno diverse combinazioni di sensori collegati al
gateway: chi ha 1 WH51, chi ne ha 5, chi nessuno; chi ha il rilevatore
piezo della pioggia, chi solo quello a basculla; eccetera. Il parser è
deliberatamente tollerante: cerca ogni sensore noto, lo include
nell'osservazione se presente, e lo lascia silenziosamente assente
altrimenti. Solo i campi del payload veramente fondamentali (la
sezione `data` e il `code` di esito) sono validati strettamente.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# -----------------------------------------------------------------------
#  Endpoint e timeouts
# -----------------------------------------------------------------------
ECOWITT_REAL_TIME_URL = "https://api.ecowitt.net/api/v3/device/real_time"
HTTP_TIMEOUT_SECONDS = 10.0


# -----------------------------------------------------------------------
#  Conversioni di unità
# -----------------------------------------------------------------------
# Il carattere "º" (U+00BA, ordinal indicator) appare in molte risposte
# Ecowitt invece del corretto "°" (U+00B0, degree sign). Lo normalizziamo
# in input per tollerare entrambe le grafie senza domandarsi quale sia.
_DEGREE_VARIANTS = ("º", "°")


def _normalize_unit(unit: str) -> str:
    """
    Pulisce una stringa di unità: elimina spazi, normalizza il simbolo
    di grado tra le due varianti che Ecowitt potrebbe inviare.
    """
    s = unit.strip()
    for variant in _DEGREE_VARIANTS:
        s = s.replace(variant, "°")
    return s


def _to_celsius(value: float, unit: str) -> float:
    """Converte una temperatura nell'unità data in gradi Celsius."""
    u = _normalize_unit(unit)
    if u in ("°C", "C"):
        return value
    if u in ("°F", "F"):
        # Formula classica: ogni 5 °C corrispondono a 9 °F, e lo zero
        # Fahrenheit è 32 unità sotto lo zero Celsius.
        return (value - 32.0) * 5.0 / 9.0
    raise ValueError(f"Unità di temperatura non riconosciuta: {unit!r}")


def _to_mm(value: float, unit: str) -> float:
    """Converte una lunghezza/precipitazione in millimetri."""
    u = _normalize_unit(unit)
    if u == "mm":
        return value
    if u == "in":
        # 1 pollice = 25.4 mm esatti per definizione internazionale.
        return value * 25.4
    raise ValueError(f"Unità di lunghezza non riconosciuta: {unit!r}")


def _to_mm_per_hour(value: float, unit: str) -> float:
    """Converte un tasso di precipitazione in mm/h."""
    u = _normalize_unit(unit)
    if u in ("mm/hr", "mm/h"):
        return value
    if u in ("in/hr", "in/h"):
        return value * 25.4
    raise ValueError(f"Unità di tasso di pioggia non riconosciuta: {unit!r}")


def _to_m_per_second(value: float, unit: str) -> float:
    """Converte una velocità in metri al secondo."""
    u = _normalize_unit(unit)
    if u == "m/s":
        return value
    if u == "mph":
        # 1 mph = 0.44704 m/s esatti.
        return value * 0.44704
    if u in ("km/h", "kph"):
        return value / 3.6
    if u in ("knots", "knot", "kt"):
        return value * 0.514444
    raise ValueError(f"Unità di velocità non riconosciuta: {unit!r}")


def _to_hpa(value: float, unit: str) -> float:
    """Converte una pressione in ettopascal (= mbar)."""
    u = _normalize_unit(unit)
    if u in ("hPa", "mbar"):
        return value
    if u == "inHg":
        # 1 inHg = 33.8638866667 hPa per definizione (a 0 °C).
        return value * 33.8638866667
    if u == "mmHg":
        return value * 1.33322387415
    raise ValueError(f"Unità di pressione non riconosciuta: {unit!r}")


# -----------------------------------------------------------------------
#  Helpers di parsing dei nodi {time, unit, value}
# -----------------------------------------------------------------------

def _parse_node_to(
    node: Optional[dict],
    converter,
) -> Optional[float]:
    """
    Parsing generico di un nodo Ecowitt. Restituisce None se il nodo è
    assente, altrimenti applica il converter alla coppia (value, unit).

    Ecowitt salva i valori come stringhe (es. "64.6"), quindi facciamo
    sempre il cast a float prima di passarli al converter.
    """
    if node is None:
        return None
    raw_value = node.get("value")
    raw_unit = node.get("unit")
    if raw_value is None or raw_unit is None:
        return None
    try:
        value = float(raw_value)
    except (ValueError, TypeError):
        return None
    return converter(value, raw_unit)


def _parse_pure_float(node: Optional[dict]) -> Optional[float]:
    """
    Parsing di un nodo che contiene un valore senza unità (es. UV index)
    o con unità adimensionale (es. "%"). Restituisce solo il float.
    """
    if node is None:
        return None
    raw_value = node.get("value")
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except (ValueError, TypeError):
        return None


# -----------------------------------------------------------------------
#  EcowittObservation — il dato consumato dal motore di fitosim
# -----------------------------------------------------------------------

@dataclass(frozen=True)
class EcowittObservation:
    """
    Snapshot in tempo reale della stazione Ecowitt, in unità metriche.

    Tutti i campi sono opzionali tranne `timestamp`: la stazione di un
    utente può avere combinazioni molto diverse di sensori, e fitosim
    deve gestire elegantemente le assenze. Un campo a None significa
    "il sensore non è installato o non ha riportato dati questa volta".

    Attributi
    ---------
    timestamp : datetime
        Istante della rilevazione, in UTC. Ricavato dal campo `time`
        di livello root della risposta.
    outdoor_temp_c, outdoor_humidity_pct, outdoor_dew_point_c : float | None
        Stazione outdoor principale (es. WS90, GW2000).
    solar_w_m2 : float | None
        Radiazione solare globale in W/m². Disponibile solo con sensore
        solare (es. WS90 ne ha uno integrato).
    uv_index : float | None
        Indice UV (0-11+), adimensionale.
    wind_speed_m_s, wind_gust_m_s, wind_direction_deg : float | None
        Vento. Velocità in m/s, direzione in gradi (0=N, 90=E, ...).
    pressure_relative_hpa, pressure_absolute_hpa : float | None
        Pressione atmosferica in hPa.
    rain_rate_mm_hr : float | None
        Tasso di pioggia attuale, mm/h.
    rain_event_mm, rain_today_mm, rain_24h_mm : float | None
        Precipitazioni accumulate nei rispettivi periodi.
    indoor_temp_c, indoor_humidity_pct : float | None
        Sensore interno della console base (sempre presente).
    extra_temp_c, extra_humidity_pct : dict[int, float]
        Sensori temp+umidità aggiuntivi (es. WN31), indicizzati per
        canale (1-8). Per le piante indoor di fitosim, il canale 1 è
        tipicamente il riferimento del microclima domestico.
    soil_moisture_pct : dict[int, float]
        Sensori di umidità substrato WH51, indicizzati per canale (1-16).
        È il dato più prezioso: misura diretta del contenuto idrico del
        substrato in cui sono installati i sensori. Usabile sia per
        validazione del bilancio idrico previsto sia per calibrazione
        dei parametri di Substrate.

    Note
    ----
    I dict per i sensori multi-canale rimangono mutabili dentro un
    dataclass `frozen=True`: questo è un compromesso pragmatico per
    mantenere l'ergonomia (`obs.soil_moisture_pct[3]`) senza richiedere
    al codice cliente di gestire mappe immutabili. Il contratto è "non
    mutarli" — non c'è ragione di farlo, le osservazioni sono snapshot.
    """

    timestamp: datetime

    outdoor_temp_c: Optional[float] = None
    outdoor_humidity_pct: Optional[float] = None
    outdoor_dew_point_c: Optional[float] = None

    solar_w_m2: Optional[float] = None
    uv_index: Optional[float] = None

    wind_speed_m_s: Optional[float] = None
    wind_gust_m_s: Optional[float] = None
    wind_direction_deg: Optional[float] = None

    pressure_relative_hpa: Optional[float] = None
    pressure_absolute_hpa: Optional[float] = None

    rain_rate_mm_hr: Optional[float] = None
    rain_event_mm: Optional[float] = None
    rain_today_mm: Optional[float] = None
    rain_24h_mm: Optional[float] = None

    indoor_temp_c: Optional[float] = None
    indoor_humidity_pct: Optional[float] = None

    extra_temp_c: dict = field(default_factory=dict)
    extra_humidity_pct: dict = field(default_factory=dict)
    soil_moisture_pct: dict = field(default_factory=dict)


# -----------------------------------------------------------------------
#  Parsing puro
# -----------------------------------------------------------------------

# Ecowitt supporta fino a 8 sensori temp/umidità extra (WN31) e fino a
# 16 sensori di umidità substrato (WH51). Iteriamo su questi range
# fissi e includiamo solo quelli effettivamente presenti nel payload.
_MAX_EXTRA_TH_CHANNELS = 8
_MAX_SOIL_CHANNELS = 16


def parse_ecowitt_response(payload: dict) -> EcowittObservation:
    """
    Trasforma una risposta JSON di Ecowitt (già deserializzata in dict)
    in un EcowittObservation, con tutte le grandezze convertite in unità
    metriche.

    Funzione completamente pura: nessuna chiamata di rete, nessun
    accesso a file. Testabile con dizionari sintetici e con il payload
    di esempio salvato in `tests/fixtures/`.

    Solleva ValueError se la struttura del payload è palesemente
    corrotta (assenza della chiave `data`, codice di errore
    riportato dal server). Ignora silenziosamente sensori assenti o
    valori malformati per singoli sensori — la robustezza è prioritaria.
    """
    # Validazione basilare del wrapper di alto livello.
    if "code" in payload and payload["code"] != 0:
        # L'API di Ecowitt risponde sempre 200 OK e mette gli errori
        # nel campo `code`/`msg`. Un codice non-zero è un errore reale
        # (chiavi sbagliate, MAC inesistente, rate limit, ecc.).
        msg = payload.get("msg", "errore sconosciuto")
        raise ValueError(
            f"Ecowitt ha risposto con codice di errore {payload['code']}: "
            f"{msg!r}. Verifica le credenziali e il MAC del dispositivo."
        )

    if "data" not in payload:
        raise ValueError(
            "Risposta Ecowitt non valida: manca la sezione 'data'."
        )
    data = payload["data"]

    # Timestamp di rilevazione: il campo `time` è in root del payload e
    # rappresenta i secondi epoch. Convertiamo in datetime UTC per
    # rendere il tipo Python idiomatico.
    timestamp_unix = payload.get("time", "0")
    try:
        timestamp = datetime.fromtimestamp(
            int(timestamp_unix), tz=timezone.utc
        )
    except (ValueError, TypeError):
        timestamp = datetime.now(timezone.utc)

    # ---------- Outdoor ----------
    outdoor = data.get("outdoor", {})
    outdoor_temp_c = _parse_node_to(
        outdoor.get("temperature"), _to_celsius
    )
    outdoor_humidity = _parse_pure_float(outdoor.get("humidity"))
    outdoor_dew = _parse_node_to(
        outdoor.get("dew_point"), _to_celsius
    )

    # ---------- Solar / UV ----------
    solar_uvi = data.get("solar_and_uvi", {})
    # La radiazione solare è già in W/m² nel formato standard Ecowitt,
    # ma usiamo comunque il converter per uniformità: se un domani
    # qualcuno avrà un'unità diversa, il converter solleverà un errore
    # esplicito invece di trasportare silenziosamente un valore sbagliato.
    solar_node = solar_uvi.get("solar")
    solar = None
    if solar_node is not None:
        # Solar è semplice: l'unità W/m² è universale.
        try:
            solar = float(solar_node.get("value"))
        except (ValueError, TypeError):
            solar = None
    uv_index = _parse_pure_float(solar_uvi.get("uvi"))

    # ---------- Vento ----------
    wind = data.get("wind", {})
    wind_speed = _parse_node_to(wind.get("wind_speed"), _to_m_per_second)
    wind_gust = _parse_node_to(wind.get("wind_gust"), _to_m_per_second)
    wind_direction = _parse_pure_float(wind.get("wind_direction"))

    # ---------- Pressione ----------
    pressure = data.get("pressure", {})
    pres_rel = _parse_node_to(pressure.get("relative"), _to_hpa)
    pres_abs = _parse_node_to(pressure.get("absolute"), _to_hpa)

    # ---------- Pioggia ----------
    # Ecowitt offre due sezioni: 'rainfall' (sensore tradizionale a
    # basculla) e 'rainfall_piezo' (sensore piezoelettrico, più recente
    # e più accurato). Preferiamo il piezo se presente; altrimenti
    # ricadiamo sul tradizionale. Le due sezioni hanno la stessa
    # struttura di campi.
    rain_section = data.get("rainfall_piezo") or data.get("rainfall", {})
    rain_rate = _parse_node_to(
        rain_section.get("rain_rate"), _to_mm_per_hour
    )
    rain_event = _parse_node_to(rain_section.get("event"), _to_mm)
    rain_today = _parse_node_to(rain_section.get("daily"), _to_mm)
    rain_24h = _parse_node_to(rain_section.get("24_hours"), _to_mm)

    # ---------- Indoor ----------
    indoor = data.get("indoor", {})
    indoor_temp_c = _parse_node_to(
        indoor.get("temperature"), _to_celsius
    )
    indoor_humidity = _parse_pure_float(indoor.get("humidity"))

    # ---------- Sensori temp+umidità aggiuntivi (WN31) ----------
    extra_temp = {}
    extra_humid = {}
    for ch in range(1, _MAX_EXTRA_TH_CHANNELS + 1):
        section = data.get(f"temp_and_humidity_ch{ch}")
        if section is None:
            continue
        t = _parse_node_to(section.get("temperature"), _to_celsius)
        h = _parse_pure_float(section.get("humidity"))
        if t is not None:
            extra_temp[ch] = t
        if h is not None:
            extra_humid[ch] = h

    # ---------- Sensori umidità substrato (WH51) ----------
    soil = {}
    for ch in range(1, _MAX_SOIL_CHANNELS + 1):
        section = data.get(f"soil_ch{ch}")
        if section is None:
            continue
        # Il valore "soilmoisture" arriva in % adimensionale: nessuna
        # conversione necessaria, leggiamo solo il float.
        moisture = _parse_pure_float(section.get("soilmoisture"))
        if moisture is not None:
            soil[ch] = moisture

    return EcowittObservation(
        timestamp=timestamp,
        outdoor_temp_c=outdoor_temp_c,
        outdoor_humidity_pct=outdoor_humidity,
        outdoor_dew_point_c=outdoor_dew,
        solar_w_m2=solar,
        uv_index=uv_index,
        wind_speed_m_s=wind_speed,
        wind_gust_m_s=wind_gust,
        wind_direction_deg=wind_direction,
        pressure_relative_hpa=pres_rel,
        pressure_absolute_hpa=pres_abs,
        rain_rate_mm_hr=rain_rate,
        rain_event_mm=rain_event,
        rain_today_mm=rain_today,
        rain_24h_mm=rain_24h,
        indoor_temp_c=indoor_temp_c,
        indoor_humidity_pct=indoor_humidity,
        extra_temp_c=extra_temp,
        extra_humidity_pct=extra_humid,
        soil_moisture_pct=soil,
    )


# -----------------------------------------------------------------------
#  Fetching HTTP
# -----------------------------------------------------------------------

def _build_real_time_url(
    application_key: str,
    api_key: str,
    mac: str,
) -> str:
    """
    Costruisce la URL completa per l'endpoint real_time, con i parametri
    correttamente URL-encoded. I MAC come 'AA:BB:CC:DD:EE:FF' contengono
    `:` che è valido nei query parameters ma alcuni proxy preferiscono
    vederlo encoded; l'encoding di urllib.parse.quote ce lo fa gratis.
    """
    params = {
        "application_key": application_key,
        "api_key": api_key,
        "mac": mac,
        "call_back": "all",
    }
    encoded = urllib.parse.urlencode(params)
    return f"{ECOWITT_REAL_TIME_URL}?{encoded}"


def _http_get_json(url: str) -> dict:
    """
    GET HTTP che restituisce il JSON parsato. User-Agent dichiarato per
    educazione verso il servizio (Ecowitt monitora i client con
    statistiche aggregate, dichiararsi aiuta loro).
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "fitosim/0.1 (+https://github.com/)"},
    )
    with urllib.request.urlopen(
        request, timeout=HTTP_TIMEOUT_SECONDS,
    ) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def fetch_real_time(
    application_key: str,
    api_key: str,
    mac: str,
    *,
    fetcher=None,
) -> EcowittObservation:
    """
    Recupera la lettura in tempo reale dalla stazione Ecowitt.

    Parametri
    ---------
    application_key, api_key, mac : str
        Credenziali della stazione. Vedi `credentials_from_env()` per
        leggerle da variabili d'ambiente in modo sicuro.
    fetcher : callable, opzionale
        Funzione che prende un URL e restituisce un dict (il JSON
        parsato). Se None, viene usato il default urllib. Iniettabile
        per i test, esattamente come in `openmeteo.fetch_daily_forecast`.

    Ritorna
    -------
    EcowittObservation
        Lo snapshot della stazione, con tutti i valori in unità metriche.

    Solleva
    -------
    OSError
        Se la stazione/server non è raggiungibile.
    ValueError
        Se la risposta è malformata o riporta un codice di errore.
    """
    if fetcher is None:
        fetcher = _http_get_json

    url = _build_real_time_url(application_key, api_key, mac)
    try:
        payload = fetcher(url)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise OSError(
            f"Impossibile contattare Ecowitt per il dispositivo {mac}. "
            f"Errore originale: {exc}"
        ) from exc

    return parse_ecowitt_response(payload)


# -----------------------------------------------------------------------
#  Helper per le credenziali
# -----------------------------------------------------------------------

ENV_APPLICATION_KEY = ""
ENV_API_KEY = ""
ENV_MAC = ""


def credentials_from_env(test=False) -> tuple[str, str, str]:
    """
    Legge le credenziali Ecowitt dalle variabili d'ambiente.

    Variabili attese:
        APPLICATION_KEY
        API_KEY
        MAC

    Ritorna una tupla `(application_key, api_key, mac)` direttamente
    passabile a `fetch_real_time()` come **kwargs.

    Solleva RuntimeError se una qualsiasi delle variabili manca,
    elencando esplicitamente quali sono assenti per facilitare il
    debugging del setup utente.
    """
    missing = []
    app_key = os.environ.get("TEST_APPLICATION_KEY" if test else "APPLICATION_KEY")
    api_key = os.environ.get("TEST_API_KEY" if test else "API_KEY")
    mac = os.environ.get("TEST_MAC" if test else "MAC")

    if not app_key:
        missing.append(ENV_APPLICATION_KEY)
    if not api_key:
        missing.append(ENV_API_KEY)
    if not mac:
        missing.append(ENV_MAC)

    if missing:
        raise RuntimeError(
            f"Variabili d'ambiente Ecowitt mancanti: {', '.join(missing)}. "
            f"Esporta le credenziali (es. in ~/.bashrc o in un file .env "
            f"caricato prima di avviare fitosim) per usare la stazione."
        )

    # mypy non capisce che a questo punto i tre valori non sono più None.
    assert app_key and api_key and mac
    return app_key, api_key, mac
