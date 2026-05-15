"""Specifica canonica per le misurazioni di sensori esterni.

Questo modulo definisce il formato `(sensor_id, timestamp, parameter, value)`
con cui ogni sorgente di dati (Ecowitt, Open-Meteo, sensori custom
dell'utente) consegna le proprie letture al backend. La spec è agnostica al
dominio: non sa nulla di Pot, Room o Garden. Il routing verso le entità
operative è responsabilità del consumatore (backend di The Pot).

Per la spec completa di trasporto (endpoint HTTP, autenticazione,
persistenza TimescaleDB, idempotenza) vedi `docs/the_pot_sensors_spec.md` in
The Pot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final


# Versione dello schema della Measurement. Va incrementata quando la
# struttura della dataclass o le invarianti di validazione cambiano in modo
# breaking. I client che inviano misure devono dichiarare lo schema_version
# nel payload HTTP.
SCHEMA_VERSION: Final[int] = 1


# ---------------------------------------------------------------------------
# Vocabolario canonico dei parametri
# ---------------------------------------------------------------------------
# Le unità sono incorporate nel nome del parametro (approccio Prometheus):
# elimina ambiguità, rende le query SQL leggibili, evita un campo "unit"
# separato che andrebbe convalidato. I parametri custom dell'utente vanno
# in namespace `custom:<arbitrary>`.

# Ambiente
PARAM_AIR_TEMPERATURE_C: Final[str] = "air_temperature_c"
PARAM_AIR_HUMIDITY: Final[str] = "air_humidity"  # frazione 0..1, NON %
PARAM_WIND_SPEED_M_S: Final[str] = "wind_speed_m_s"
PARAM_SOLAR_RADIATION_MJ_M2: Final[str] = "solar_radiation_mj_m2"
PARAM_RAINFALL_MM: Final[str] = "rainfall_mm"
PARAM_BAROMETRIC_PRESSURE_HPA: Final[str] = "barometric_pressure_hpa"

# Substrato
PARAM_SOIL_THETA: Final[str] = "soil_theta"  # frazione volumetrica 0..1
PARAM_SOIL_TEMPERATURE_C: Final[str] = "soil_temperature_c"
PARAM_SOIL_EC_MSCM: Final[str] = "soil_ec_mscm"
PARAM_SOIL_PH: Final[str] = "soil_ph"

# Stato del sistema (metadati del dispositivo come misurazioni separate,
# non come campo annidato nella Measurement principale).
PARAM_BATTERY_LEVEL: Final[str] = "battery_level"  # 0..1
PARAM_SIGNAL_STRENGTH: Final[str] = "signal_strength"  # 0..1

# Namespace per estensioni utente
CUSTOM_NAMESPACE_PREFIX: Final[str] = "custom:"


# Set di parametri canonici noti. I client possono inviare anche parametri
# in namespace `custom:<arbitrary>` che la validazione accetta come opachi.
CANONICAL_PARAMETERS: Final[frozenset[str]] = frozenset({
    PARAM_AIR_TEMPERATURE_C,
    PARAM_AIR_HUMIDITY,
    PARAM_WIND_SPEED_M_S,
    PARAM_SOLAR_RADIATION_MJ_M2,
    PARAM_RAINFALL_MM,
    PARAM_BAROMETRIC_PRESSURE_HPA,
    PARAM_SOIL_THETA,
    PARAM_SOIL_TEMPERATURE_C,
    PARAM_SOIL_EC_MSCM,
    PARAM_SOIL_PH,
    PARAM_BATTERY_LEVEL,
    PARAM_SIGNAL_STRENGTH,
})


# Parametri con vincoli semantici di routing. Servono al backend per
# rifiutare mappature incoerenti (es. soil_theta su una Room).
# La spec di trasporto NON impone questi vincoli — sono un suggerimento per
# il livello di routing.
PARAMETERS_REQUIRING_POT: Final[frozenset[str]] = frozenset({
    PARAM_SOIL_THETA,
    PARAM_SOIL_TEMPERATURE_C,
    PARAM_SOIL_EC_MSCM,
    PARAM_SOIL_PH,
})

PARAMETERS_REQUIRING_ROOM_OR_GARDEN: Final[frozenset[str]] = frozenset({
    PARAM_AIR_TEMPERATURE_C,
    PARAM_AIR_HUMIDITY,
    PARAM_WIND_SPEED_M_S,
    PARAM_SOLAR_RADIATION_MJ_M2,
    PARAM_RAINFALL_MM,
    PARAM_BAROMETRIC_PRESSURE_HPA,
})


# ---------------------------------------------------------------------------
# Range fisici per validazione
# ---------------------------------------------------------------------------
# Limiti minimo/massimo plausibili per ciascun parametro canonico. Sono
# volutamente generosi: scartiamo solo valori chiaramente impossibili
# (es. theta > 1.05, pH < 0), non valori "strani ma plausibili". La
# validazione fine (es. allerte meteorologiche) vive a livello applicativo.

_PHYSICAL_RANGES: Final[dict[str, tuple[float, float]]] = {
    PARAM_AIR_TEMPERATURE_C: (-50.0, 70.0),
    PARAM_AIR_HUMIDITY: (0.0, 1.0),
    PARAM_WIND_SPEED_M_S: (0.0, 100.0),
    PARAM_SOLAR_RADIATION_MJ_M2: (0.0, 50.0),
    PARAM_RAINFALL_MM: (0.0, 500.0),
    PARAM_BAROMETRIC_PRESSURE_HPA: (800.0, 1100.0),
    PARAM_SOIL_THETA: (0.0, 1.05),
    PARAM_SOIL_TEMPERATURE_C: (-20.0, 60.0),
    PARAM_SOIL_EC_MSCM: (0.0, 20.0),
    PARAM_SOIL_PH: (0.0, 14.0),
    PARAM_BATTERY_LEVEL: (0.0, 1.0),
    PARAM_SIGNAL_STRENGTH: (0.0, 1.0),
}


def physical_range(parameter: str) -> tuple[float, float] | None:
    """Restituisce il range plausibile (min, max) di un parametro canonico.

    Per parametri custom o sconosciuti restituisce `None`: il consumatore
    può decidere come gestire (accettare opaco, validare con regole proprie).
    """
    return _PHYSICAL_RANGES.get(parameter)


class MeasurementValidationError(ValueError):
    """Sollevata quando una Measurement viola un'invariante della spec.

    Casi:
    - sensor_id vuoto o non stringa
    - timestamp naive (senza tzinfo)
    - parameter non riconosciuto (né canonico né custom:*)
    - value non finito o fuori range plausibile del parametro
    """


@dataclass(frozen=True)
class Measurement:
    """Misurazione canonica di un sensore.

    Una tupla immutabile `(sensor_id, timestamp, parameter, value)` che
    identifica univocamente una lettura. Il consumer persiste con
    PRIMARY KEY `(sensor_id, parameter, timestamp)` e applica UPSERT
    sui conflitti.

    Note di design:
    - `sensor_id` è opaco lato spec; la convenzione raccomandata è
      `<provider>:<device_type>:<instance>` (es. `ecowitt:wh51:ch3`).
    - `timestamp` deve essere timezone-aware. La spec di trasporto richiede
      UTC con offset esplicito; qui accettiamo qualunque tz consapevole, è
      il consumatore a normalizzare a UTC alla persistenza.
    - `parameter` deve essere uno dei canonici in `CANONICAL_PARAMETERS` o
      iniziare con `custom:` per estensioni utente.
    - `value` è sempre float. Parametri logicamente booleani usano la
      convenzione `0.0 = false`, `1.0 = true`.

    I metadati di sistema (batteria, signal strength, calibrazione) viaggiano
    come Measurement separate con i propri parametri canonici, non come
    campi annidati.
    """

    sensor_id: str
    timestamp: datetime
    parameter: str
    value: float

    def __post_init__(self) -> None:
        # sensor_id: stringa non vuota
        if not isinstance(self.sensor_id, str) or not self.sensor_id.strip():
            raise MeasurementValidationError(
                f"sensor_id deve essere stringa non vuota, "
                f"ricevuto: {self.sensor_id!r}"
            )

        # timestamp: deve essere datetime timezone-aware
        if not isinstance(self.timestamp, datetime):
            raise MeasurementValidationError(
                f"timestamp deve essere datetime, "
                f"ricevuto: {type(self.timestamp).__name__}"
            )
        if self.timestamp.tzinfo is None:
            raise MeasurementValidationError(
                "timestamp deve essere timezone-aware "
                "(es. datetime.now(timezone.utc))"
            )

        # parameter: canonico o custom:*
        if not isinstance(self.parameter, str) or not self.parameter:
            raise MeasurementValidationError(
                f"parameter deve essere stringa non vuota, "
                f"ricevuto: {self.parameter!r}"
            )
        if (
            self.parameter not in CANONICAL_PARAMETERS
            and not self.parameter.startswith(CUSTOM_NAMESPACE_PREFIX)
        ):
            raise MeasurementValidationError(
                f"parameter sconosciuto: {self.parameter!r}. "
                f"Deve essere uno dei canonici di CANONICAL_PARAMETERS o "
                f"iniziare con {CUSTOM_NAMESPACE_PREFIX!r}."
            )

        # value: float finito (rifiuta bool, NaN, infiniti)
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise MeasurementValidationError(
                f"value deve essere float, "
                f"ricevuto: {type(self.value).__name__}"
            )
        v = float(self.value)
        if v != v or v in (float("inf"), float("-inf")):
            raise MeasurementValidationError(
                f"value deve essere finito, ricevuto: {self.value}"
            )

        # value: dentro il range plausibile del parametro (solo canonici)
        rng = _PHYSICAL_RANGES.get(self.parameter)
        if rng is not None:
            lo, hi = rng
            if not (lo <= v <= hi):
                raise MeasurementValidationError(
                    f"value {v} fuori range plausibile per "
                    f"{self.parameter}: [{lo}, {hi}]"
                )

    @property
    def is_custom(self) -> bool:
        """True se il parametro è in namespace `custom:*`."""
        return self.parameter.startswith(CUSTOM_NAMESPACE_PREFIX)
