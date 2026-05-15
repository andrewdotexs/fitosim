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
from fitosim.io.sensors.measurement import (
    CUSTOM_NAMESPACE_PREFIX,
    Measurement,
    PARAM_AIR_TEMPERATURE_C,
    PARAM_RAINFALL_MM,
)


# Provider tag per i log strutturati e per il campo `provider` delle
# eccezioni. Costante di modulo per evitare typo sparsi nel codice.
PROVIDER_NAME = "openmeteo"

# Parametro custom per ET₀ pre-calcolato. Open-Meteo lo offre già
# (campo `et0_fao_evapotranspiration`); ET₀ non è una misura diretta
# di sensore quindi non c'è un canonico nella spec v1, vive in
# namespace `custom:*` come per `CsvEnvironmentFixture`.
_PARAM_ET0_MM = f"{CUSTOM_NAMESPACE_PREFIX}et0_mm"


def _sensor_id_for(latitude: float, longitude: float) -> str:
    """Costruisce il sensor_id canonico per una coordinata Open-Meteo.

    Formato: `openmeteo:lat<lat>_lon<lon>`. Le coordinate sono
    formattate con 4 decimali, sufficiente a discriminare grigliati
    di ~10 m, ben oltre la risoluzione effettiva del modello (~1-10 km).
    """
    return f"{PROVIDER_NAME}:lat{latitude:.4f}_lon{longitude:.4f}"


def _daily_weather_to_measurements(
    dw: DailyWeather, sensor_id: str,
) -> list[Measurement]:
    """
    Traduce un DailyWeather legacy in una lista di `Measurement`
    canoniche secondo la spec sensori v1.

    Tutte le Measurement prodotte condividono `sensor_id` e
    `timestamp` (= 12:00 UTC del giorno solare). Mappatura:

      - `t_min` + `t_max` → `air_temperature_c` (media, convenzione
        FAO-56 standard per calcoli ET₀ a partire da dati giornalieri).
      - `precipitation_mm` → `rainfall_mm`.
      - `et0_mm` → `custom:et0_mm` (opzionale: presente solo se
        Open-Meteo lo ha fornito per quella zona/data).

    Open-Meteo non espone humidity_relative, wind_speed_m_s,
    radiation_mj_m2 nel modulo legacy attuale: questi parametri
    saranno aggiunti quando il legacy verrà esteso al supporto
    Penman-Monteith completo (tappa 5 fascia 2).
    """
    # Convertiamo il `day: date` legacy in `timestamp: datetime` UTC
    # alle 12:00, secondo la convenzione documentata sopra.
    ts = datetime.combine(dw.day, time(12, 0), tzinfo=timezone.utc)
    t_mean = (dw.t_min + dw.t_max) / 2.0

    out: list[Measurement] = [
        Measurement(
            sensor_id=sensor_id,
            timestamp=ts,
            parameter=PARAM_AIR_TEMPERATURE_C,
            value=t_mean,
        ),
        Measurement(
            sensor_id=sensor_id,
            timestamp=ts,
            parameter=PARAM_RAINFALL_MM,
            value=dw.precipitation_mm,
        ),
    ]
    if dw.et0_mm is not None:
        out.append(Measurement(
            sensor_id=sensor_id,
            timestamp=ts,
            parameter=_PARAM_ET0_MM,
            value=dw.et0_mm,
        ))
    return out


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

    def sensor_id_for(
        self, latitude: float, longitude: float,
    ) -> str:
        """Restituisce il sensor_id canonico per una coordinata.

        Formato: `openmeteo:lat<lat>_lon<lon>` con 4 decimali. Le
        Measurement prodotte da `current_conditions()` e `forecast()`
        per quella coordinata avranno questo come `sensor_id`.
        """
        return _sensor_id_for(latitude, longitude)

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> list[Measurement]:
        """
        Restituisce le condizioni meteo correnti per le coordinate
        come lista piatta di `Measurement` canoniche (spec sensori v1).

        Implementazione: chiede un forecast di 1 giorno (oggi) e
        restituisce le Measurement di quel giorno. Open-Meteo non ha
        un endpoint specifico per "ora corrente" su dati giornalieri
        aggregati, quindi questa è la traduzione più sensata.

        Per una "ora corrente" istantanea (T, RH, vento minuto-per-
        minuto), si dovrebbe usare l'endpoint `current_weather` di
        Open-Meteo, che però fornisce dati istantanei diversi dalle
        aggregazioni giornaliere FAO-56 di cui fitosim ha bisogno per
        ET₀. Manteniamo questa scelta a livello di tappa 1; l'adapter
        può essere esteso in futuro se servirà l'endpoint instantaneo.
        """
        return self.forecast(latitude, longitude, days=1)

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[Measurement]:
        """
        Restituisce la previsione meteo a `days` giorni futuri come
        lista piatta di `Measurement` (spec sensori v1).

        Per ogni giorno la lista contiene 2-3 Measurement:
        `air_temperature_c` (media), `rainfall_mm`, e
        `custom:et0_mm` se Open-Meteo lo fornisce per quella zona.
        Ordine: per timestamp crescente; all'interno di uno stesso
        timestamp segue l'ordine `temp → rain → et0`.

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

        # Traduzione DailyWeather → list[Measurement] per ogni giorno,
        # poi flat concatenation. Tutte le Measurement portano lo
        # stesso sensor_id derivato dalla coordinata.
        sensor_id = _sensor_id_for(latitude, longitude)
        out: list[Measurement] = []
        for dw in daily_weathers:
            out.extend(_daily_weather_to_measurements(dw, sensor_id))
        return out
