"""
Adapter OpenMeteoEnvironmentSensor.

Implementa il Protocol `EnvironmentSensor` traducendo i dati del modulo
legacy `fitosim.io.openmeteo` nel formato canonico `EnvironmentReading`.
È il primo adapter concreto della tappa 1 della fascia 2, ed è anche
quello più semplice perché Open-Meteo non richiede autenticazione e
copre la maggior parte dei casi d'uso "voglio dati meteo per la mia
posizione" senza setup.

Architettura
------------

L'adapter NON duplica la logica di fetch e parsing del modulo legacy:
si limita a chiamare `fetch_daily_forecast()` e a tradurre i risultati.
Questa scelta ha tre vantaggi importanti:

  1. Ogni miglioramento del codice di parsing legacy beneficia
     automaticamente l'adapter (e viceversa via i test).
  2. Il codice dell'adapter resta corto e leggibile (~150 righe), il
     suo scopo è solo "traduzione di formato" non "parsing".
  3. Quando il modulo legacy verrà eventualmente deprecato, l'adapter
     sarà l'unico posto da cui assorbire la logica.

Convenzioni di traduzione
-------------------------

Open-Meteo lavora in giorni solari (un valore aggregato al giorno).
Il nostro `EnvironmentReading` richiede invece un `datetime` puntuale.
La convenzione adottata è di usare le **12:00 UTC del giorno solare**
come timestamp rappresentativo dell'aggregato giornaliero. Le ragioni:

  - Corrisponde al momento del massimo solare medio, semanticamente
    significativo per un dato meteo aggregato.
  - È indipendente dal fuso locale del giardino (un vaso a Milano e
    uno a Tokyo riceveranno entrambi 12:00 UTC del 1° maggio anche
    se per loro è il momento solare di mezzogiorno locale diverso).
  - Evita ambiguità di "quale ora del giorno rappresenta questo
    aggregato": tutti gli adapter di altri provider che producono
    aggregati giornalieri possono adottare la stessa convenzione.

Mapping di eccezioni
--------------------

Il modulo legacy solleva eccezioni native di `urllib` per problemi di
rete e `ValueError` per dati malformati. Questo adapter le cattura e
le ri-solleva come eccezioni della nostra gerarchia, in modo che il
chiamante non debba conoscere i dettagli di urllib:

  - `urllib.error.URLError` (timeout, DNS) → SensorTemporaryError
  - `urllib.error.HTTPError` con status 5xx → SensorTemporaryError
  - `urllib.error.HTTPError` con status 4xx → SensorPermanentError
  - `ValueError` (parsing JSON) → SensorPermanentError
  - `KeyError` (campi attesi mancanti) → SensorPermanentError
"""

from __future__ import annotations

import urllib.error
from datetime import datetime, time, timezone
from typing import Optional

from fitosim.io.openmeteo import (
    DailyWeather,
    fetch_daily_forecast,
)
from fitosim.io.sensors.errors import (
    SensorPermanentError,
    SensorTemporaryError,
)
from fitosim.io.sensors.types import (
    EnvironmentReading,
    ReadingQuality,
)


# Provider tag per i log strutturati e per il campo `provider` delle
# eccezioni. Costante di modulo per evitare typo sparsi nel codice.
PROVIDER_NAME = "openmeteo"


def _daily_weather_to_reading(dw: DailyWeather) -> EnvironmentReading:
    """
    Traduce un DailyWeather legacy in EnvironmentReading canonico.

    La traduzione preserva i dati disponibili in DailyWeather e lascia
    a None i campi che il legacy non espone (humidity_relative,
    radiation_mj_m2, wind_speed_m_s). Questi campi diventeranno
    disponibili quando estenderemo DailyWeather alla tappa 5 della
    fascia 2 con il supporto Penman-Monteith completo.

    La temperatura del Reading è la **media giornaliera** calcolata
    come (t_min + t_max) / 2. Questa è una semplificazione necessaria
    perché EnvironmentReading espone un singolo valore di temperatura,
    mentre DailyWeather ne espone due. È la convenzione standard FAO-56
    per i calcoli di ET₀ a partire da dati giornalieri.
    """
    # Convertiamo il `day: date` legacy in `timestamp: datetime` UTC
    # alle 12:00, secondo la convenzione documentata sopra.
    ts = datetime.combine(dw.day, time(12, 0), tzinfo=timezone.utc)
    # Temperatura media come compromesso ragionevole per gli aggregati
    # giornalieri. Questo è esattamente quello che farebbe internamente
    # il calcolo Hargreaves-Samani dopo aver ricevuto t_min e t_max.
    t_mean = (dw.t_min + dw.t_max) / 2.0
    return EnvironmentReading(
        timestamp=ts,
        temperature_c=t_mean,
        rain_mm=dw.precipitation_mm,
        et0_mm=dw.et0_mm,  # può essere None, ed è lecito
        # Open-Meteo non espone metadati di qualità (è un servizio cloud
        # che fa modelli numerici globali, non c'è una "batteria" da
        # monitorare). Quality resta default: anonima.
        quality=ReadingQuality(),
    )


class OpenMeteoEnvironmentSensor:
    """
    Adapter Open-Meteo che implementa il Protocol EnvironmentSensor.

    Open-Meteo (https://open-meteo.com) è un servizio gratuito che
    fornisce previsioni meteo grigliate globali a partire da modelli
    numerici (ECMWF, GFS, ICON). Non richiede autenticazione per il
    piano gratuito, ha un rate limit generoso (~10000 chiamate/giorno
    per IP), e copre tutto il pianeta con risoluzione adeguata al
    giardinaggio domestico.

    Limitazioni note:
      - I dati sono grigliati a ~1-10 km di risoluzione: differenze di
        1-3 °C dal microclima specifico del balcone sono normali.
      - Il forecast è limitato a 16 giorni dal provider.
      - Per microclimi molto specifici (cantine, serre), un sensore
        locale dedicato è preferibile.

    Per l'uso operativo "Il Mio Giardino" su balcone milanese, è una
    scelta più che adeguata. Per casi d'uso più esigenti, considera
    `EcowittEnvironmentSensor` con la tua stazione meteo personale.

    Parametri del costruttore
    -------------------------
    cache_dir : Path | None
        Directory di cache delle risposte HTTP. Default: ~/.fitosim/
        openmeteo_cache. Passare None per disabilitare la cache.
    cache_ttl_hours : float
        TTL della cache in ore. Default 6 (i modelli meteo si
        aggiornano ogni 6 ore, quindi richiedere più spesso non porta
        dati nuovi).
    use_cache : bool
        Se False, ignora la cache e va sempre alla rete. Utile nei
        test di integrazione.
    """

    def __init__(
        self,
        *,
        cache_dir=None,
        cache_ttl_hours: float = 6.0,
        use_cache: bool = True,
    ) -> None:
        self._cache_dir = cache_dir
        self._cache_ttl_hours = cache_ttl_hours
        self._use_cache = use_cache

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> EnvironmentReading:
        """
        Restituisce le condizioni meteo correnti per le coordinate.

        Implementazione: chiede un forecast di 1 giorno (oggi) e
        restituisce il primo elemento. Open-Meteo non ha un endpoint
        specifico per "ora corrente" su dati giornalieri aggregati,
        quindi questa è la traduzione più sensata.

        Per una "ora corrente" istantanea (T, RH, vento minuto-per-
        minuto), si dovrebbe usare l'endpoint `current_weather` di
        Open-Meteo, che però fornisce dati istantanei diversi dalle
        aggregazioni giornaliere FAO-56 di cui fitosim ha bisogno per
        ET₀. Manteniamo questa scelta a livello di tappa 1; l'adapter
        può essere esteso in futuro se servirà l'endpoint instantaneo.
        """
        forecast_today = self.forecast(latitude, longitude, days=1)
        return forecast_today[0]

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[EnvironmentReading]:
        """
        Restituisce la previsione meteo a `days` giorni futuri.

        Solleva ValueError se days è fuori dal range supportato
        dall'API Open-Meteo (1-16 giorni).
        """
        if not 1 <= days <= 16:
            raise ValueError(
                f"days fuori range Open-Meteo [1,16]: {days}"
            )

        try:
            daily_weathers = fetch_daily_forecast(
                latitude=latitude,
                longitude=longitude,
                days=days,
                cache_dir=self._cache_dir,
                cache_ttl_hours=self._cache_ttl_hours,
                use_cache=self._use_cache,
            )
        except urllib.error.HTTPError as e:
            # Distinguiamo tra problemi server (5xx, recuperabili) e
            # problemi client (4xx, richiedono intervento). Open-Meteo
            # restituisce 400 per parametri sbagliati, 429 per rate
            # limit (che è in realtà recuperabile aspettando), 5xx
            # per problemi temporanei del loro lato.
            if e.code >= 500 or e.code == 429:
                raise SensorTemporaryError(
                    f"Open-Meteo errore server (HTTP {e.code}): {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
            else:
                raise SensorPermanentError(
                    f"Open-Meteo errore client (HTTP {e.code}): {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
        except urllib.error.URLError as e:
            # Errore generico di rete (DNS, timeout, host non
            # raggiungibile). Tipicamente recuperabile.
            raise SensorTemporaryError(
                f"Open-Meteo non raggiungibile: {e.reason}",
                provider=PROVIDER_NAME,
            ) from e
        except (ValueError, KeyError) as e:
            # Parsing JSON fallito o campi attesi mancanti. Indica un
            # cambio di schema lato Open-Meteo o un bug nostro: non
            # è recuperabile ritentando.
            raise SensorPermanentError(
                f"Open-Meteo risposta malformata: {e}",
                provider=PROVIDER_NAME,
            ) from e

        # Traduzione DailyWeather → EnvironmentReading per ogni giorno.
        return [_daily_weather_to_reading(dw) for dw in daily_weathers]
