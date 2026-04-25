"""
Client per l'API Open-Meteo: dati meteorologici reali per fitosim.

Questo è il primo modulo del livello `io/`: il punto in cui fitosim
smette di operare con dati sintetici inventati e comincia a parlare con
una fonte meteorologica reale. Open-Meteo (https://open-meteo.com) è un
servizio gratuito, senza chiave API, con licenza Creative Commons sui
dati e copertura globale, e fornisce previsioni e dati storici a
risoluzione oraria/giornaliera per qualunque latitudine/longitudine.

Architettura
------------

Il modulo è strutturato in tre parti concettualmente separate:

  1. Un modello dati interno (`DailyWeather`) che rappresenta una
     giornata meteo nei termini che il nostro motore consuma.
     Questo è il "vocabolario interno": qualunque sorgente meteo
     futura (Ecowitt, sensori locali, file CSV) dovrà produrre questo
     formato, non il proprio formato nativo. È l'idea dell'*adapter
     pattern* applicata.

  2. La funzione di fetch (`fetch_daily_forecast`) che esegue la
     chiamata HTTP, parsa il JSON di risposta, e adatta i campi nel
     formato `DailyWeather`. Usa `urllib.request` della standard
     library Python: nessuna dipendenza esterna.

  3. Un piccolo sistema di cache su disco basato su file JSON, con
     timestamp di scadenza. Serve a due scopi: rispettare il servizio
     gratuito di Open-Meteo (non si chiama il server dieci volte al
     minuto durante lo sviluppo) e fornire un fallback offline quando
     la rete non risponde.

Limitazioni note
----------------

I dati di Open-Meteo provengono da modelli numerici globali (ECMWF,
GFS, ICON). Sono di alta qualità ma non rappresentano il microclima
specifico del tuo balcone: differenze di 1-3 °C rispetto alle misure
locali sono normali. Per applicazioni che richiedono precisione
millimetrica, il prossimo passo sarà integrare i dati della tua
stazione Ecowitt (modulo `io/ecowitt.py`, futuro), usando Open-Meteo
come fallback quando la stazione non risponde.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


# URL base dell'endpoint forecast di Open-Meteo. Lo scegliamo come
# costante di modulo per centralizzare l'eventuale modifica futura
# (es. passaggio a `historical-forecast-api` per dati passati).
OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Timeout per la chiamata HTTP, in secondi. Open-Meteo è generalmente
# molto rapida (< 1s); 10 secondi sono un compromesso che tollera
# rallentamenti senza bloccare il programma a oltranza.
HTTP_TIMEOUT_SECONDS = 10.0

# Validità di default della cache. Per dati di previsione, riusare lo
# stesso JSON entro 6 ore è ragionevole: i modelli meteo si aggiornano
# tipicamente ogni 6 ore e durante lo sviluppo questo evita richieste
# ripetute per la stessa zona.
DEFAULT_CACHE_TTL_HOURS = 6.0

# Directory di default per la cache. Sotto la home dell'utente per
# essere portabile tra Linux, macOS, Termux. Viene creata se manca.
DEFAULT_CACHE_DIR = Path.home() / ".fitosim" / "openmeteo_cache"


@dataclass(frozen=True)
class DailyWeather:
    """
    Dati meteorologici di un singolo giorno, nel formato consumato dal
    motore di fitosim.

    Attributi
    ---------
    day : date
        Giorno calendario a cui i dati si riferiscono.
    t_min : float
        Temperatura minima giornaliera in °C.
    t_max : float
        Temperatura massima giornaliera in °C.
    precipitation_mm : float
        Precipitazione totale in mm. Include pioggia e neve liquida.
    et0_mm : float | None, opzionale
        ET di riferimento giornaliera secondo FAO-56 Penman-Monteith,
        in mm/giorno, già calcolata da Open-Meteo a partire dai loro
        dati grigliati di T, RH, vento e radiazione netta. Può essere
        None per giornate o zone in cui i dati di input non sono
        disponibili. È preziosissima come benchmark indipendente per
        validare il nostro Hargreaves-Samani: confrontare i due valori
        ci dice quanto la nostra approssimazione è in accordo con la
        formula completa "gold standard" della letteratura agronomica.

    Note
    ----
    Questo è volutamente un sottoinsieme minimo dei dati Open-Meteo:
    il motore Hargreaves-Samani v0.2 di fitosim consuma solo (t_min,
    t_max). La precipitazione viene caricata perché serve al bilancio
    idrico come `water_input_mm` per i vasi outdoor. Quando in futuro
    estenderemo il motore a Penman-Monteith FAO-56 (versione 0.3),
    aggiungeremo qui campi per umidità relativa, vento, radiazione
    solare misurata.
    """

    day: date
    t_min: float
    t_max: float
    precipitation_mm: float
    et0_mm: Optional[float] = None

    def __post_init__(self) -> None:
        if self.t_max < self.t_min:
            raise ValueError(
                f"DailyWeather per {self.day}: t_max ({self.t_max}) "
                f"non può essere minore di t_min ({self.t_min})."
            )
        if self.precipitation_mm < 0:
            raise ValueError(
                f"DailyWeather per {self.day}: precipitation_mm "
                f"({self.precipitation_mm}) non può essere negativa."
            )


# =======================================================================
#  Cache su disco
# =======================================================================

def _cache_filename(latitude: float, longitude: float, days: int) -> str:
    """
    Costruisce il nome del file di cache per una specifica
    coppia (lat, lon, n_days). Le coordinate sono arrotondate a tre
    decimali (precisione ~100 m) per riusare la cache di vasi vicini.
    """
    return f"forecast_{latitude:.3f}_{longitude:.3f}_{days}d.json"


def _read_cache(
    cache_path: Path,
    ttl_hours: float,
) -> Optional[dict]:
    """
    Tenta di leggere la cache. Restituisce il payload se il file esiste
    ed è ancora valido (entro ttl_hours dalla scrittura), altrimenti None.
    Errori di lettura/parsing sono trattati come "cache assente" senza
    propagare eccezioni: un cache corrotto non deve bloccare il flusso.
    """
    if not cache_path.exists():
        return None
    try:
        with cache_path.open("r", encoding="utf-8") as fh:
            cached = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None

    written_at_str = cached.get("_fitosim_cached_at")
    if written_at_str is None:
        return None
    try:
        written_at = datetime.fromisoformat(written_at_str)
    except ValueError:
        return None

    age = datetime.now() - written_at
    # Caso speciale: TTL infinito significa "accetta qualunque cache",
    # usato come fallback quando la rete è giù. Senza questo branch,
    # `timedelta(hours=inf)` solleverebbe OverflowError.
    if ttl_hours == float("inf"):
        return cached.get("payload")
    if age > timedelta(hours=ttl_hours):
        return None
    return cached.get("payload")


def _write_cache(cache_path: Path, payload: dict) -> None:
    """
    Scrive la cache, racchiudendo il payload con un timestamp di
    scrittura. Se la directory non esiste, viene creata. Errori di
    scrittura (permessi, disco pieno) sono loggati silenziosamente
    perché non devono interrompere il flusso principale.
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper = {
        "_fitosim_cached_at": datetime.now().isoformat(),
        "payload": payload,
    }
    try:
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump(wrapper, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass  # cache è un'ottimizzazione, non un requisito


# =======================================================================
#  Chiamata HTTP e parsing
# =======================================================================

def _build_request_url(
    latitude: float,
    longitude: float,
    days: int,
) -> str:
    """
    Costruisce la URL completa con i query parameters per Open-Meteo.

    I parametri richiesti corrispondono al sottoinsieme minimo per
    fitosim v0.2: temperature minime/massime giornaliere e precipitazione.
    Open-Meteo accetta `forecast_days` da 1 a 16 sulle previsioni e
    risponde sempre dal giorno corrente (UTC) in avanti.
    """
    if not (1 <= days <= 16):
        raise ValueError(
            f"days deve essere in [1, 16] (ricevuto {days}). "
            f"Open-Meteo limita le previsioni a 16 giorni."
        )
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(
            f"latitude deve essere in [-90, 90] (ricevuto {latitude})."
        )
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(
            f"longitude deve essere in [-180, 180] "
            f"(ricevuto {longitude})."
        )

    # I parametri sono assemblati a mano per evitare la dipendenza da
    # `urllib.parse.urlencode` -- è una funzione standard ma vogliamo
    # che il codice sia leggibile a colpo d'occhio. Le virgole nei
    # parametri-lista sono valide e non richiedono encoding.
    params = (
        f"latitude={latitude:.4f}"
        f"&longitude={longitude:.4f}"
        f"&daily=temperature_2m_max,temperature_2m_min,"
        f"precipitation_sum,et0_fao_evapotranspiration"
        f"&timezone=auto"
        f"&forecast_days={days}"
    )
    return f"{OPENMETEO_BASE_URL}?{params}"


def _http_get_json(url: str) -> dict:
    """
    Esegue una GET HTTP e restituisce il JSON parsato come dict.

    Solleva URLError se la rete non è raggiungibile, HTTPError se il
    server risponde con codice di errore, json.JSONDecodeError se la
    risposta non è JSON valido. Tutti questi errori sono lasciati
    propagare al chiamante: la decisione su come gestirli (fallback a
    cache, retry, errore visibile) appartiene al livello superiore.
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


def _parse_openmeteo_response(payload: dict) -> list[DailyWeather]:
    """
    Adatta la struttura JSON di Open-Meteo nella nostra lista di
    DailyWeather. Se il formato non è quello atteso, solleva un
    ValueError con messaggio descrittivo.

    Open-Meteo restituisce una struttura del tipo:
        {
          "daily": {
            "time":              ["2025-04-25", "2025-04-26", ...],
            "temperature_2m_max":[18.4, 19.1, ...],
            "temperature_2m_min":[ 8.7,  9.0, ...],
            "precipitation_sum": [ 0.0,  2.4, ...],
            "et0_fao_evapotranspiration": [3.2, 3.8, ...],
          },
          ...
        }
    Tutte le quattro liste obbligatorie (time, t_max, t_min, rain)
    devono avere la stessa lunghezza. La lista et0 è opzionale: se
    presente deve avere anch'essa la stessa lunghezza, ma può
    contenere `None` per singoli giorni.
    """
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ValueError(
            "Risposta Open-Meteo malformata: campo 'daily' assente o "
            "non oggetto."
        )

    times = daily.get("time")
    t_max = daily.get("temperature_2m_max")
    t_min = daily.get("temperature_2m_min")
    rain = daily.get("precipitation_sum")
    # ET₀ FAO è opzionale: se manca, lavoriamo come prima (et0_mm=None
    # in tutti i DailyWeather risultanti).
    et0 = daily.get("et0_fao_evapotranspiration")

    if not all(isinstance(x, list) for x in (times, t_max, t_min, rain)):
        raise ValueError(
            "Risposta Open-Meteo malformata: uno dei campi attesi "
            "(time, temperature_2m_max, temperature_2m_min, "
            "precipitation_sum) non è una lista."
        )
    if not (len(times) == len(t_max) == len(t_min) == len(rain)):
        raise ValueError(
            "Risposta Open-Meteo malformata: le liste daily hanno "
            "lunghezze diverse, atteso lo stesso numero di elementi."
        )
    # Se et0 è presente come lista, deve essere coerente con le altre.
    # Ammettiamo invece il caso in cui sia totalmente assente.
    if et0 is not None and (
        not isinstance(et0, list) or len(et0) != len(times)
    ):
        raise ValueError(
            "Risposta Open-Meteo malformata: et0_fao_evapotranspiration "
            "presente ma con struttura non coerente con le altre serie."
        )

    result = []
    for i, day_str in enumerate(times):
        # Per et0: il valore può essere None per singoli giorni anche
        # quando la lista nel suo complesso è valida — preserviamo il
        # None invece di forzare 0.0, perché distingue "non c'è dato"
        # da "ET pari a zero" (concettualmente diversi).
        et0_value: Optional[float] = None
        if et0 is not None and et0[i] is not None:
            et0_value = float(et0[i])

        result.append(
            DailyWeather(
                day=date.fromisoformat(day_str),
                t_min=float(t_min[i]),
                t_max=float(t_max[i]),
                precipitation_mm=float(rain[i]),
                et0_mm=et0_value,
            )
        )
    return result


# =======================================================================
#  Funzione principale di alto livello
# =======================================================================

def fetch_daily_forecast(
    latitude: float,
    longitude: float,
    days: int = 7,
    *,
    cache_dir: Optional[Path] = None,
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    use_cache: bool = True,
    fetcher: Optional[callable] = None,
) -> list[DailyWeather]:
    """
    Recupera la previsione meteo giornaliera per una località.

    Il flusso è:
      1. Se `use_cache` è True e c'è una cache fresca, la usa.
      2. Altrimenti chiama Open-Meteo. Se la chiamata riesce, salva
         la cache e restituisce i dati.
      3. Se la chiamata fallisce e c'è una cache (anche scaduta), la
         usa come fallback con un avviso.
      4. Se nessuna delle due strade funziona, propaga l'eccezione di
         rete originale al chiamante.

    Parametri
    ---------
    latitude : float
        Latitudine in gradi decimali, positiva a nord.
    longitude : float
        Longitudine in gradi decimali, positiva a est.
    days : int, default 7
        Numero di giorni di previsione (1-16).
    cache_dir : Path, opzionale
        Directory per i file di cache. Default: ~/.fitosim/openmeteo_cache.
    cache_ttl_hours : float, default 6
        Validità della cache in ore.
    use_cache : bool, default True
        Se False, salta la lettura della cache e forza una chiamata
        HTTP nuova. Utile in test o per invalidare manualmente.
    fetcher : callable, opzionale
        Funzione che prende un URL e restituisce un dict (il payload
        JSON parsato). Se None, viene usato il fetcher HTTP di default
        basato su urllib. Consente ai test di iniettare un mock per
        verificare il flusso end-to-end senza fare chiamate di rete.

    Ritorna
    -------
    list[DailyWeather]
        Lista ordinata cronologicamente, lunghezza pari a `days`.
    """
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR
    cache_path = cache_dir / _cache_filename(latitude, longitude, days)
    if fetcher is None:
        fetcher = _http_get_json

    # Step 1: cache fresca disponibile?
    if use_cache:
        cached = _read_cache(cache_path, cache_ttl_hours)
        if cached is not None:
            return _parse_openmeteo_response(cached)

    # Step 2-3: tentativo HTTP.
    url = _build_request_url(latitude, longitude, days)
    try:
        payload = fetcher(url)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        # Step 3 fallback: usa cache anche se scaduta.
        if use_cache:
            stale = _read_cache(cache_path, ttl_hours=float("inf"))
            if stale is not None:
                return _parse_openmeteo_response(stale)
        # Nessun fallback disponibile: propagare l'errore originale,
        # incapsulato per renderlo leggibile.
        raise OSError(
            f"Impossibile contattare Open-Meteo e nessuna cache "
            f"disponibile per ({latitude}, {longitude}). "
            f"Errore originale: {exc}"
        ) from exc

    # Step 2 (continuo): scrittura cache e parsing.
    if use_cache:
        _write_cache(cache_path, payload)
    return _parse_openmeteo_response(payload)


# =======================================================================
#  Archivio storico
# =======================================================================
# Open-Meteo offre un endpoint separato (`archive-api.open-meteo.com`)
# per i dati passati. La firma è simile alla previsione, ma richiede
# date di inizio e fine esplicite invece del numero di giorni.
# L'archivio copre dal 1940 fino a ~5 giorni prima di oggi.

OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _build_archive_url(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
) -> str:
    """
    Costruisce la URL completa per la richiesta archivio.

    L'archivio Open-Meteo accetta start_date e end_date in formato
    ISO (YYYY-MM-DD) e restituisce una serie giornaliera continua tra
    i due estremi (inclusi).
    """
    if start_date > end_date:
        raise ValueError(
            f"start_date ({start_date}) non può essere successiva a "
            f"end_date ({end_date})."
        )
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(
            f"latitude deve essere in [-90, 90] (ricevuto {latitude})."
        )
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(
            f"longitude deve essere in [-180, 180] "
            f"(ricevuto {longitude})."
        )
    params = (
        f"latitude={latitude:.4f}"
        f"&longitude={longitude:.4f}"
        f"&start_date={start_date.isoformat()}"
        f"&end_date={end_date.isoformat()}"
        f"&daily=temperature_2m_max,temperature_2m_min,"
        f"precipitation_sum,et0_fao_evapotranspiration"
        f"&timezone=auto"
    )
    return f"{OPENMETEO_ARCHIVE_URL}?{params}"


def fetch_daily_archive(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    *,
    fetcher: Optional[callable] = None,
) -> list[DailyWeather]:
    """
    Recupera dati meteorologici storici tra start_date ed end_date
    (inclusi) per la posizione specificata.

    L'archivio non utilizza cache su disco perché tipicamente i dati
    storici si interrogano una sola volta per uno specifico back-test
    (le serie passate non cambiano). Se in futuro emergerà la necessità
    di cache (es. simulazioni ripetute sullo stesso periodo), si potrà
    aggiungere riusando l'infrastruttura della previsione.

    Parametri
    ---------
    latitude, longitude : float
        Coordinate del sito.
    start_date, end_date : date
        Estremi inclusi del periodo richiesto. start_date <= end_date.
    fetcher : callable, opzionale
        Iniezione del fetcher per testabilità, come in fetch_daily_forecast.

    Ritorna
    -------
    list[DailyWeather]
        Una entry per ogni giorno tra start_date ed end_date inclusi,
        in ordine cronologico.
    """
    if fetcher is None:
        fetcher = _http_get_json

    url = _build_archive_url(latitude, longitude, start_date, end_date)
    try:
        payload = fetcher(url)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise OSError(
            f"Impossibile contattare l'archivio Open-Meteo per "
            f"({latitude}, {longitude}) tra {start_date} e {end_date}. "
            f"Errore originale: {exc}"
        ) from exc

    return _parse_openmeteo_response(payload)


# Alias pubblico della funzione di parsing, esposto perché utile nei
# test e per casi d'uso che leggono JSON cached da file (es. risposte
# salvate per back-test riproducibili).
parse_openmeteo_response = _parse_openmeteo_response
