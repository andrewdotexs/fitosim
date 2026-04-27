"""
Adapter EcowittEnvironmentSensor.

Implementa il Protocol `EnvironmentSensor` traducendo `EcowittObservation`
del modulo legacy `fitosim.io.ecowitt` nel formato canonico
`EnvironmentReading`. È l'adapter da usare quando hai una stazione
meteo Ecowitt personale (es. WS90, GW2000) e vuoi alimentare fitosim
con i dati reali del tuo microclima specifico, anziché con i dati
grigliati di Open-Meteo che possono differire di 1-3 °C.

Limitazione importante: forecast non è supportato
-------------------------------------------------

A differenza di Open-Meteo, Ecowitt è un servizio di **misurazione**,
non di **forecasting**. La stazione ti dice cosa sta succedendo *ora*
nel tuo balcone, e ricordi cosa è successo nel passato (storico), ma
non può prevedere il futuro. Per questo `forecast()` solleva
`NotImplementedError` con un messaggio esplicito che suggerisce di
combinare Ecowitt (per le condizioni reali) con Open-Meteo (per il
forecast). La tappa 4 della fascia 2 (Garden orchestrator) saprà
combinare automaticamente sensori diversi per ruoli diversi.

Convenzione delle variabili d'ambiente
--------------------------------------

Il pattern `from_env()` legge le credenziali secondo la convenzione
fissata: prefisso `FITOSIM_ECOWITT_` per la nuova nomenclatura,
fallback su `ECOWITT_` (senza prefisso) come compatibilità con il
modulo legacy. Quando il fallback viene attivato, viene emesso un
DeprecationWarning per avvisare l'utente che il nome è cambiato.

Variabili nuove (priorità):
  - FITOSIM_ECOWITT_APPLICATION_KEY
  - FITOSIM_ECOWITT_API_KEY
  - FITOSIM_ECOWITT_MAC

Variabili legacy (fallback con warning):
  - ECOWITT_APPLICATION_KEY
  - ECOWITT_API_KEY
  - ECOWITT_MAC

Mapping di unità
----------------

EcowittObservation espone l'umidità in percentuale (0-100) e il vento
in m/s. Il Reading canonico vuole l'umidità come frazione (0-1) e il
vento sempre in m/s. La conversione di umidità avviene in questo
adapter, mantenendo coerente l'interfaccia esterna.
"""

from __future__ import annotations

import os
import urllib.error
import warnings
from typing import Optional

from fitosim.io.ecowitt import (
    EcowittObservation,
    fetch_real_time,
)
from fitosim.io.sensors.errors import (
    SensorPermanentError,
    SensorTemporaryError,
)
from fitosim.io.sensors.types import (
    EnvironmentReading,
    ReadingQuality,
    SoilReading,
)


PROVIDER_NAME = "ecowitt"

# Convenzione nuova (priorità): prefisso FITOSIM_ECOWITT_*
ENV_FITOSIM_APPLICATION_KEY = "FITOSIM_ECOWITT_APPLICATION_KEY"
ENV_FITOSIM_API_KEY = "FITOSIM_ECOWITT_API_KEY"
ENV_FITOSIM_MAC = "FITOSIM_ECOWITT_MAC"

# Convenzione legacy (fallback con DeprecationWarning): senza prefisso.
# Mantenute per compatibilità con utenti esistenti del modulo legacy
# `fitosim.io.ecowitt.credentials_from_env()` che usavano questi nomi.
ENV_LEGACY_APPLICATION_KEY = "ECOWITT_APPLICATION_KEY"
ENV_LEGACY_API_KEY = "ECOWITT_API_KEY"
ENV_LEGACY_MAC = "ECOWITT_MAC"


def _read_credential(
    new_name: str, legacy_name: str,
) -> Optional[str]:
    """
    Legge una credenziale dalle variabili d'ambiente con doppia
    convenzione.

    Logica di lookup:
      1. Cerca prima `new_name` (FITOSIM_*). Se trovata, la usa
         silenziosamente — è la convenzione corretta.
      2. Altrimenti cerca `legacy_name` (senza prefisso). Se trovata,
         emette DeprecationWarning con istruzioni di migrazione.
      3. Se nessuna delle due è valorizzata, ritorna None. Il chiamante
         decide cosa fare (tipicamente sollevare un errore aggregato
         che elenca tutte le variabili mancanti).
    """
    new_value = os.environ.get(new_name)
    if new_value:
        return new_value

    legacy_value = os.environ.get(legacy_name)
    if legacy_value:
        warnings.warn(
            f"La variabile d'ambiente '{legacy_name}' è deprecata. "
            f"Usa '{new_name}' come da convenzione fitosim. "
            f"Il fallback continuerà a funzionare in tutte le versioni "
            f"della fascia 2, ma sarà rimosso in futuro.",
            DeprecationWarning,
            stacklevel=3,  # stacklevel=3 per puntare al chiamante esterno
        )
        return legacy_value

    return None


def _observation_to_reading(obs: EcowittObservation) -> EnvironmentReading:
    """
    Traduce un EcowittObservation legacy in EnvironmentReading canonico.

    Estrae solo i campi ambientali (outdoor_*, solar, wind, rain,
    pressure). I campi del suolo (`soil_moisture_pct`) sono ignorati
    da questo adapter: vengono gestiti separatamente da
    `EcowittWH51SoilSensor` che produce `SoilReading` per ogni canale.

    Conversione di unità:
      - outdoor_humidity_pct (0-100) → humidity_relative (0-1)
      - solar_w_m2 (W/m² istantaneo) NON viene convertito in MJ/m²/g
        perché serve un'aggregazione su 24 ore che richiede dati
        storici. Resta come campo non valorizzato per ora; l'estensione
        Penman-Monteith della tappa 5 fornirà la conversione corretta.
      - rain: usiamo `rain_24h_mm` come "pioggia delle ultime 24 ore"
        che è la convenzione del nostro Reading.
    """
    # Conversione umidità da percentuale a frazione, se presente.
    humidity_relative = None
    if obs.outdoor_humidity_pct is not None:
        humidity_relative = obs.outdoor_humidity_pct / 100.0

    # Calcolo della staleness della lettura: se il timestamp del provider
    # è significativamente nel passato rispetto a "ora", la lettura è
    # vecchia (sensore offline da un po'). La calcoliamo qui per esporla
    # nei metadati di qualità.
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    # Il timestamp di Ecowitt è già in UTC (come da docstring legacy).
    age_seconds = max(0, int((now_utc - obs.timestamp).total_seconds()))

    return EnvironmentReading(
        timestamp=obs.timestamp,
        temperature_c=obs.outdoor_temp_c,
        humidity_relative=humidity_relative,
        # solar_w_m2 e radiation_mj_m2 sono unità diverse: non convertiamo.
        # Sarà gestito propriamente in tappa 5 (Penman-Monteith).
        radiation_mj_m2=None,
        wind_speed_m_s=obs.wind_speed_m_s,
        rain_mm=obs.rain_24h_mm,
        # Ecowitt non calcola ET₀: fitosim la calcolerà internamente
        # da temperatura+radiazione quando serve.
        et0_mm=None,
        quality=ReadingQuality(
            staleness_seconds=age_seconds,
            # battery_level: il livello batteria dei sensori Ecowitt
            # è esposto in EcowittObservation come campi separati per
            # ogni sensore (battery_*). Per la stazione principale
            # potremmo aggregarli, ma per ora lasciamo None: l'estensione
            # è semplice se servirà.
            battery_level=None,
        ),
    )


class EcowittEnvironmentSensor:
    """
    Adapter Ecowitt che implementa il Protocol EnvironmentSensor.

    Legge i dati ambientali (temperatura, umidità, vento, pioggia)
    dalla stazione meteo Ecowitt personale dell'utente via Ecowitt
    Cloud. Richiede credenziali API (application_key, api_key) e
    l'identificativo MAC della stazione.

    Vantaggi rispetto a OpenMeteoEnvironmentSensor:
      - Dati misurati realmente nel tuo balcone, non grigliati su 1-10 km.
      - Aggiornamento ogni ~5 minuti (Open-Meteo aggiorna i modelli ogni
        6 ore).
      - Include la lettura dei sensori del suolo via canali WH51 (gestiti
        dall'adapter SoilSensor parallelo).

    Limitazioni:
      - Richiede setup (creazione account Ecowitt, generazione chiavi
        API, registrazione del MAC della stazione).
      - Solo "current conditions": il forecast non è supportato dal
        provider e va combinato con un altro EnvironmentSensor che lo
        supporti (tipicamente Open-Meteo).
      - Dipendenza dalla connettività Internet del datalogger e dalla
        disponibilità del cloud Ecowitt.

    Costruzione
    -----------

    Il costruttore canonico accetta le credenziali esplicitamente::

        sensor = EcowittEnvironmentSensor(
            application_key="abc123...",
            api_key="def456...",
            mac="AA:BB:CC:DD:EE:FF",
        )

    Per casi d'uso comuni, il metodo factory `from_env()` legge le
    credenziali dalle variabili d'ambiente seguendo la convenzione
    fitosim::

        sensor = EcowittEnvironmentSensor.from_env()
    """

    def __init__(
        self,
        application_key: str,
        api_key: str,
        mac: str,
    ) -> None:
        # Validazione minima: rifiutiamo stringhe vuote subito per
        # evitare di tentare chiamate API che falliranno comunque ma
        # con messaggi meno chiari.
        if not application_key or not api_key or not mac:
            raise ValueError(
                "EcowittEnvironmentSensor richiede application_key, "
                "api_key e mac non vuoti. Usa from_env() se vuoi "
                "leggerli automaticamente dalle variabili d'ambiente."
            )
        self._application_key = application_key
        self._api_key = api_key
        self._mac = mac

    @classmethod
    def from_env(cls) -> "EcowittEnvironmentSensor":
        """
        Costruisce l'adapter leggendo le credenziali dalle variabili
        d'ambiente.

        Cerca prima le variabili con prefisso `FITOSIM_ECOWITT_*`
        (convenzione corrente). Se non trovate, ripiega su `ECOWITT_*`
        (convenzione legacy del modulo `fitosim.io.ecowitt`),
        emettendo un DeprecationWarning per ciascuna variabile letta
        dal nome legacy.

        Solleva `RuntimeError` se una qualsiasi credenziale manca da
        entrambe le convenzioni, elencando esplicitamente quali
        variabili nuove sarebbero attese.
        """
        application_key = _read_credential(
            ENV_FITOSIM_APPLICATION_KEY, ENV_LEGACY_APPLICATION_KEY,
        )
        api_key = _read_credential(
            ENV_FITOSIM_API_KEY, ENV_LEGACY_API_KEY,
        )
        mac = _read_credential(
            ENV_FITOSIM_MAC, ENV_LEGACY_MAC,
        )

        # Aggreghiamo gli errori in un unico messaggio che elenca tutto
        # quello che manca, anziché fallire alla prima variabile assente.
        # È più ergonomico per chi configura il sistema per la prima volta.
        missing = []
        if not application_key:
            missing.append(ENV_FITOSIM_APPLICATION_KEY)
        if not api_key:
            missing.append(ENV_FITOSIM_API_KEY)
        if not mac:
            missing.append(ENV_FITOSIM_MAC)

        if missing:
            raise RuntimeError(
                f"Variabili d'ambiente Ecowitt mancanti: "
                f"{', '.join(missing)}. "
                f"Imposta le tre credenziali nel tuo ambiente (o nel "
                f"file .env del progetto) e riprova."
            )

        return cls(
            application_key=application_key,
            api_key=api_key,
            mac=mac,
        )

    def current_conditions(
        self, latitude: float, longitude: float,
    ) -> EnvironmentReading:
        """
        Restituisce le condizioni meteo correnti misurate dalla stazione.

        I parametri `latitude` e `longitude` sono accettati per
        conformità al Protocol EnvironmentSensor ma sono ignorati:
        Ecowitt restituisce sempre i dati della stazione associata
        al `mac` con cui l'adapter è configurato. È la firma dell'API
        del provider, non una scelta di fitosim.
        """
        try:
            obs = fetch_real_time(
                application_key=self._application_key,
                api_key=self._api_key,
                mac=self._mac,
            )
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise SensorTemporaryError(
                    f"Ecowitt errore server (HTTP {e.code}): {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
            elif e.code in (401, 403):
                # Credenziali sbagliate: caso permanente paradigmatico,
                # con messaggio mirato che suggerisce la causa.
                raise SensorPermanentError(
                    f"Ecowitt credenziali rifiutate (HTTP {e.code}): "
                    f"verifica application_key, api_key e mac.",
                    provider=PROVIDER_NAME,
                ) from e
            else:
                raise SensorPermanentError(
                    f"Ecowitt errore client (HTTP {e.code}): {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
        except urllib.error.URLError as e:
            raise SensorTemporaryError(
                f"Ecowitt cloud non raggiungibile: {e.reason}",
                provider=PROVIDER_NAME,
            ) from e
        except (ValueError, KeyError) as e:
            raise SensorPermanentError(
                f"Ecowitt risposta malformata: {e}",
                provider=PROVIDER_NAME,
            ) from e

        return _observation_to_reading(obs)

    def forecast(
        self, latitude: float, longitude: float, days: int,
    ) -> list[EnvironmentReading]:
        """
        Forecast NON supportato dalla stazione Ecowitt.

        La stazione misura il presente e il passato, ma non genera
        previsioni meteo. Per ottenere il forecast del tuo balcone,
        combina questo adapter (per le misure attuali) con un altro
        EnvironmentSensor che supporti il forecasting, tipicamente
        OpenMeteoEnvironmentSensor.

        La tappa 4 della fascia 2 (Garden orchestrator) automatizzerà
        questa combinazione. Per ora il chiamante deve farla a mano.
        """
        raise NotImplementedError(
            "EcowittEnvironmentSensor non supporta forecast: la "
            "stazione misura ma non prevede. Usa "
            "OpenMeteoEnvironmentSensor.forecast() in combinazione "
            "con questo adapter per ottenere previsioni."
        )


# ==========================================================================
#  EcowittWH51SoilSensor: sensori del suolo via Ecowitt Cloud
# ==========================================================================

def _channel_id_to_int(channel_id: str) -> int:
    """
    Traduce un channel_id stringa nel numero di canale intero usato da
    EcowittObservation.soil_moisture_pct.

    Convenzioni accettate per channel_id:
      - "1", "2", ..., "8": numero di canale puro come stringa.
      - "ch1", "ch2", ..., "ch8": prefisso "ch" che alcuni utenti
        scrivono naturalmente.
      - "soilmoisture_ch1", ...: nome completo del campo Ecowitt come
        appare nel JSON dell'API.

    Tutte e tre le forme vengono normalizzate al numero intero
    corrispondente. Per channel_id non riconosciuti solleva
    SensorPermanentError con diagnostica esplicita.
    """
    cleaned = channel_id.strip().lower()
    # Rimuove i prefissi conosciuti.
    for prefix in ("soilmoisture_ch", "ch"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    try:
        return int(cleaned)
    except ValueError as e:
        raise SensorPermanentError(
            f"channel_id non riconosciuto: '{channel_id}'. "
            f"Formati accettati: '1'..'8', 'ch1'..'ch8', "
            f"'soilmoisture_ch1'..'soilmoisture_ch8'.",
            provider=PROVIDER_NAME,
        ) from e


class EcowittWH51SoilSensor:
    """
    Adapter per i sensori di umidità del suolo WH51 via Ecowitt Cloud.

    Il WH51 è un sensore wireless di umidità del substrato che si
    abbina alla base station Ecowitt (GW1100, GW2000, etc.). Una
    singola base station riceve fino a 8 canali WH51, ognuno associato
    a un vaso diverso. Questo adapter espone un singolo canale come
    SoilSensor: per gestire più vasi servono più istanze, una per
    canale.

    Il WH51 misura **solo θ** (contenuto idrico volumetrico).
    Temperatura, EC e pH non sono disponibili e vengono restituiti
    come None nel SoilReading. Per sensori più ricchi (T, EC, pH) si
    usa l'adapter ATO 7-in-1 (tappa 2 della fascia 2).

    Convenzione di unità
    --------------------

    Il WH51 espone θ come percentuale 0-100 nel JSON Ecowitt. L'adapter
    converte automaticamente in frazione 0-1 secondo la convenzione
    canonica di SoilReading.

    Costruzione
    -----------

    Come EcowittEnvironmentSensor, accetta credenziali esplicite o le
    legge da variabili d'ambiente con `from_env()`. Le credenziali sono
    le stesse: una sola stazione Ecowitt serve sia i dati ambientali
    sia i WH51 collegati.

    Esempio d'uso::

        sensor = EcowittWH51SoilSensor.from_env()
        reading = sensor.current_state(channel_id="1")  # o "ch1"
        print(f"θ del vaso 1: {reading.theta_volumetric:.3f}")
    """

    def __init__(
        self,
        application_key: str,
        api_key: str,
        mac: str,
    ) -> None:
        if not application_key or not api_key or not mac:
            raise ValueError(
                "EcowittWH51SoilSensor richiede application_key, "
                "api_key e mac non vuoti. Usa from_env() per leggerli "
                "automaticamente dalle variabili d'ambiente."
            )
        self._application_key = application_key
        self._api_key = api_key
        self._mac = mac

    @classmethod
    def from_env(cls) -> "EcowittWH51SoilSensor":
        """
        Costruisce l'adapter leggendo le credenziali dalle variabili
        d'ambiente, con la stessa logica di EcowittEnvironmentSensor
        (convenzione FITOSIM_ECOWITT_* con fallback ECOWITT_* legacy).
        """
        application_key = _read_credential(
            ENV_FITOSIM_APPLICATION_KEY, ENV_LEGACY_APPLICATION_KEY,
        )
        api_key = _read_credential(
            ENV_FITOSIM_API_KEY, ENV_LEGACY_API_KEY,
        )
        mac = _read_credential(
            ENV_FITOSIM_MAC, ENV_LEGACY_MAC,
        )
        missing = []
        if not application_key:
            missing.append(ENV_FITOSIM_APPLICATION_KEY)
        if not api_key:
            missing.append(ENV_FITOSIM_API_KEY)
        if not mac:
            missing.append(ENV_FITOSIM_MAC)
        if missing:
            raise RuntimeError(
                f"Variabili d'ambiente Ecowitt mancanti: "
                f"{', '.join(missing)}."
            )
        return cls(
            application_key=application_key,
            api_key=api_key,
            mac=mac,
        )

    def current_state(self, channel_id: str) -> SoilReading:
        """
        Restituisce lo stato corrente del substrato per il canale WH51.

        Solleva:
          - SensorPermanentError se il channel_id non è valido o non è
            collegato alla base station.
          - SensorTemporaryError per errori di rete o server.
        """
        channel_int = _channel_id_to_int(channel_id)

        # Fetch della observation completa: la stessa che usa
        # EcowittEnvironmentSensor. La logica di gestione errori è
        # identica, e per evitare duplicazione la incapsuliamo qui.
        try:
            obs = fetch_real_time(
                application_key=self._application_key,
                api_key=self._api_key,
                mac=self._mac,
            )
        except urllib.error.HTTPError as e:
            if e.code >= 500 or e.code == 429:
                raise SensorTemporaryError(
                    f"Ecowitt errore server (HTTP {e.code}): {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
            elif e.code in (401, 403):
                raise SensorPermanentError(
                    f"Ecowitt credenziali rifiutate (HTTP {e.code}).",
                    provider=PROVIDER_NAME,
                ) from e
            else:
                raise SensorPermanentError(
                    f"Ecowitt errore client (HTTP {e.code}): {e.reason}",
                    provider=PROVIDER_NAME,
                ) from e
        except urllib.error.URLError as e:
            raise SensorTemporaryError(
                f"Ecowitt cloud non raggiungibile: {e.reason}",
                provider=PROVIDER_NAME,
            ) from e
        except (ValueError, KeyError) as e:
            raise SensorPermanentError(
                f"Ecowitt risposta malformata: {e}",
                provider=PROVIDER_NAME,
            ) from e

        # Estrazione del canale specifico dal dict soil_moisture_pct.
        # Se il canale non è presente nella observation, significa che
        # quel WH51 non è collegato/registrato sulla base station: caso
        # permanente che richiede intervento (non è recuperabile
        # ritentando).
        if channel_int not in obs.soil_moisture_pct:
            available = sorted(obs.soil_moisture_pct.keys())
            raise SensorPermanentError(
                f"Canale {channel_int} non presente nei dati della "
                f"stazione. Canali disponibili: {available}. Verifica "
                f"che il WH51 sia accoppiato e funzionante.",
                provider=PROVIDER_NAME,
            )

        moisture_pct = obs.soil_moisture_pct[channel_int]
        # Conversione percentuale → frazione canonica.
        theta = moisture_pct / 100.0

        # Calcolo staleness come per EcowittEnvironmentSensor.
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        age_seconds = max(0, int((now_utc - obs.timestamp).total_seconds()))

        return SoilReading(
            timestamp=obs.timestamp,
            theta_volumetric=theta,
            # WH51 misura solo θ. T, EC, pH restano None.
            temperature_c=None,
            ec_mscm=None,
            ph=None,
            quality=ReadingQuality(
                staleness_seconds=age_seconds,
                # Anche qui battery_level potrebbe essere estratto in
                # futuro dai campi battery_* di EcowittObservation.
                battery_level=None,
            ),
        )
