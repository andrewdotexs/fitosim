"""Test della dataclass canonica `Measurement`.

Questo file copre i comportamenti garantiti dal modulo
`fitosim.io.sensors.measurement`: costruzione corretta nei casi normali,
validazione del sensor_id, del timestamp (UTC obbligatorio), del parameter
(canonico o custom:*) e del value (float finito dentro il range fisico
plausibile del parametro).

Famiglie di test
----------------

  - `Test_Measurement_construction`: casi felici di costruzione.
  - `Test_Measurement_sensor_id_validation`: stringa non vuota richiesta.
  - `Test_Measurement_timestamp_validation`: deve essere tz-aware.
  - `Test_Measurement_parameter_validation`: canonico o custom:*.
  - `Test_Measurement_value_validation`: float finito, bool rifiutato.
  - `Test_Measurement_physical_ranges`: range fisicamente plausibili
    per ciascun parametro canonico (bordi inferiori e superiori).
  - `Test_Measurement_is_custom`: discriminazione canonico vs custom.
  - `Test_Measurement_frozen`: immutabilità dopo costruzione.
  - `Test_physical_range_helper`: funzione di lookup pubblico.
  - `Test_canonical_constants`: invarianti delle costanti esportate.
  - `Test_schema_version`: stabilità della versione dello schema.
"""

from datetime import datetime, timedelta, timezone
from math import inf, nan

import pytest

from fitosim.io.sensors.measurement import (
    CANONICAL_PARAMETERS,
    CUSTOM_NAMESPACE_PREFIX,
    Measurement,
    MeasurementValidationError,
    PARAM_AIR_HUMIDITY,
    PARAM_AIR_TEMPERATURE_C,
    PARAM_BAROMETRIC_PRESSURE_HPA,
    PARAM_BATTERY_LEVEL,
    PARAM_RAINFALL_MM,
    PARAM_SIGNAL_STRENGTH,
    PARAM_SOIL_EC_MSCM,
    PARAM_SOIL_PH,
    PARAM_SOIL_TEMPERATURE_C,
    PARAM_SOIL_THETA,
    PARAM_SOLAR_RADIATION_MJ_M2,
    PARAM_WIND_SPEED_M_S,
    PARAMETERS_REQUIRING_POT,
    PARAMETERS_REQUIRING_ROOM_OR_GARDEN,
    SCHEMA_VERSION,
    physical_range,
)


# Helper: un timestamp UTC valido riusato in tanti test.
def _ts() -> datetime:
    return datetime(2026, 5, 15, 14, 30, 0, tzinfo=timezone.utc)


# Valori sicuri (a metà del range plausibile) per ciascun parametro canonico:
# si usano nei test che vogliono iterare su CANONICAL_PARAMETERS senza
# preoccuparsi del range specifico.
_MIDPOINTS: dict[str, float] = {
    PARAM_AIR_TEMPERATURE_C: 20.0,
    PARAM_AIR_HUMIDITY: 0.5,
    PARAM_WIND_SPEED_M_S: 3.0,
    PARAM_SOLAR_RADIATION_MJ_M2: 15.0,
    PARAM_RAINFALL_MM: 5.0,
    PARAM_BAROMETRIC_PRESSURE_HPA: 1013.0,
    PARAM_SOIL_THETA: 0.3,
    PARAM_SOIL_TEMPERATURE_C: 18.0,
    PARAM_SOIL_EC_MSCM: 1.2,
    PARAM_SOIL_PH: 6.5,
    PARAM_BATTERY_LEVEL: 0.75,
    PARAM_SIGNAL_STRENGTH: 0.8,
}


# --------------------------------------------------------------------------
#  Costruzione: casi felici
# --------------------------------------------------------------------------


class Test_Measurement_construction:
    """Costruzione di Measurement nei casi felici."""

    def test_minimal_canonical_construction(self):
        """Costruzione tipica con un parametro canonico: tutti e quattro
        i campi popolati, nessuna eccezione."""
        m = Measurement(
            sensor_id="ecowitt:wh51:ch3",
            timestamp=_ts(),
            parameter=PARAM_SOIL_THETA,
            value=0.27,
        )
        assert m.sensor_id == "ecowitt:wh51:ch3"
        assert m.timestamp == _ts()
        assert m.parameter == PARAM_SOIL_THETA
        assert m.value == 0.27

    def test_custom_namespace_construction(self):
        """Parametri custom:* sono accettati senza validazione di range
        (la spec li tratta come opachi)."""
        m = Measurement(
            sensor_id="custom:user42:diy",
            timestamp=_ts(),
            parameter="custom:co2_ppm",
            value=412.5,
        )
        assert m.parameter == "custom:co2_ppm"
        assert m.value == 412.5

    def test_custom_namespace_accepts_extreme_values(self):
        """Per i parametri custom non c'è range plausibile: anche valori
        improbabili (es. 1_000_000) passano la validazione."""
        m = Measurement(
            sensor_id="custom:user42:strange",
            timestamp=_ts(),
            parameter="custom:weird",
            value=1_000_000.0,
        )
        assert m.value == 1_000_000.0

    def test_integer_value_accepted_as_float(self):
        """int viene accettato e trattato come float (è il comportamento
        naturale di Python: 22 == 22.0). Solo bool è esplicitamente
        rifiutato perché in Python bool è sottoclasse di int."""
        m = Measurement(
            sensor_id="custom:test:1",
            timestamp=_ts(),
            parameter=PARAM_AIR_TEMPERATURE_C,
            value=22,
        )
        assert m.value == 22

    def test_timezone_other_than_utc_is_accepted(self):
        """La dataclass richiede tz-aware ma non impone UTC: la
        normalizzazione a UTC è responsabilità del consumatore al
        momento della persistenza."""
        rome = timezone(timedelta(hours=2))
        ts = datetime(2026, 5, 15, 16, 30, 0, tzinfo=rome)
        m = Measurement(
            sensor_id="ecowitt:weather_station:001",
            timestamp=ts,
            parameter=PARAM_RAINFALL_MM,
            value=2.5,
        )
        assert m.timestamp.tzinfo is not None

    def test_all_canonical_parameters_constructible(self):
        """Tutti e 12 i parametri canonici sono costruibili con un valore
        a metà del loro range plausibile."""
        for param in CANONICAL_PARAMETERS:
            m = Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=param,
                value=_MIDPOINTS[param],
            )
            assert m.parameter == param


# --------------------------------------------------------------------------
#  sensor_id: validazione
# --------------------------------------------------------------------------


class Test_Measurement_sensor_id_validation:
    """Validazione del campo sensor_id."""

    def test_empty_string_raises(self):
        """sensor_id vuoto è semanticamente privo di significato: ogni
        misura DEVE essere attribuibile a una sorgente."""
        with pytest.raises(MeasurementValidationError, match="sensor_id"):
            Measurement(
                sensor_id="",
                timestamp=_ts(),
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_whitespace_only_raises(self):
        """sensor_id di soli spazi/tab è equivalente a vuoto (errore di
        configurazione del device)."""
        with pytest.raises(MeasurementValidationError, match="sensor_id"):
            Measurement(
                sensor_id="   ",
                timestamp=_ts(),
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_non_string_raises(self):
        """sensor_id deve essere stringa: int o altri tipi → errore."""
        with pytest.raises(MeasurementValidationError, match="sensor_id"):
            Measurement(
                sensor_id=42,
                timestamp=_ts(),
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_none_raises(self):
        """sensor_id None → errore (caso più comune di bug applicativo)."""
        with pytest.raises(MeasurementValidationError, match="sensor_id"):
            Measurement(
                sensor_id=None,
                timestamp=_ts(),
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_unicode_and_special_chars_accepted(self):
        """sensor_id è opaco: caratteri unicode, colon, slash, hyphen
        sono tutti validi (es. `custom:user42:diy-temp-è1`)."""
        m = Measurement(
            sensor_id="custom:user42:diy-temp-è1/v2",
            timestamp=_ts(),
            parameter=PARAM_AIR_TEMPERATURE_C,
            value=22.0,
        )
        assert m.sensor_id == "custom:user42:diy-temp-è1/v2"


# --------------------------------------------------------------------------
#  timestamp: tz-aware obbligatorio
# --------------------------------------------------------------------------


class Test_Measurement_timestamp_validation:
    """Validazione del campo timestamp."""

    def test_naive_datetime_raises(self):
        """datetime senza tzinfo → errore: i timestamp naive sono
        ambigui (UTC? locale? quale offset?) e nascondono bug subdoli
        in serie storiche cross-fuso."""
        naive = datetime(2026, 5, 15, 14, 30, 0)  # nessun tzinfo
        with pytest.raises(MeasurementValidationError, match="timezone-aware"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=naive,
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_non_datetime_raises(self):
        """Stringa ISO o int unix non sono datetime: l'adapter HTTP
        deve fare il parsing prima della costruzione."""
        with pytest.raises(MeasurementValidationError, match="datetime"):
            Measurement(
                sensor_id="test:device:1",
                timestamp="2026-05-15T14:30:00Z",
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_none_timestamp_raises(self):
        """timestamp None → errore."""
        with pytest.raises(MeasurementValidationError, match="datetime"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=None,
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )

    def test_utc_timestamp_accepted(self):
        """timestamp UTC esplicito è il caso felice principale."""
        m = Measurement(
            sensor_id="test:device:1",
            timestamp=datetime.now(timezone.utc),
            parameter=PARAM_SOIL_THETA,
            value=0.3,
        )
        assert m.timestamp.tzinfo is not None

    def test_other_timezones_accepted(self):
        """Qualsiasi tzinfo è valido: la spec di trasporto richiederà
        UTC ma la dataclass è permissiva e lascia al consumer la
        normalizzazione."""
        for offset_hours in (-12, -5, 0, 1, 5, 12):
            tz = timezone(timedelta(hours=offset_hours))
            ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=tz)
            m = Measurement(
                sensor_id="test:device:1",
                timestamp=ts,
                parameter=PARAM_SOIL_THETA,
                value=0.3,
            )
            assert m.timestamp.utcoffset() == timedelta(hours=offset_hours)


# --------------------------------------------------------------------------
#  parameter: canonico o custom:*
# --------------------------------------------------------------------------


class Test_Measurement_parameter_validation:
    """Validazione del campo parameter."""

    def test_empty_parameter_raises(self):
        """parameter vuoto → errore."""
        with pytest.raises(MeasurementValidationError, match="parameter"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter="",
                value=0.3,
            )

    def test_non_string_parameter_raises(self):
        """parameter non stringa → errore."""
        with pytest.raises(MeasurementValidationError, match="parameter"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=42,
                value=0.3,
            )

    def test_unknown_canonical_parameter_raises(self):
        """parameter non in vocabolario canonico e senza prefisso custom:
        → errore con messaggio diagnostico (es. typo "air_temp" anziché
        "air_temperature_c")."""
        with pytest.raises(MeasurementValidationError, match="sconosciuto"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter="air_temp",  # typo plausibile
                value=22.0,
            )

    def test_custom_prefix_with_arbitrary_suffix_accepted(self):
        """Qualunque stringa dopo `custom:` è accettata come opaca."""
        for suffix in ("co2_ppm", "par_umol_m2_s", "anything-here", "x"):
            m = Measurement(
                sensor_id="custom:user:1",
                timestamp=_ts(),
                parameter=f"{CUSTOM_NAMESPACE_PREFIX}{suffix}",
                value=1.0,
            )
            assert m.parameter == f"custom:{suffix}"

    def test_uppercase_canonical_not_accepted(self):
        """Il vocabolario è case-sensitive: AIR_TEMPERATURE_C non è
        riconosciuto come variante di air_temperature_c."""
        with pytest.raises(MeasurementValidationError, match="sconosciuto"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter="AIR_TEMPERATURE_C",
                value=22.0,
            )


# --------------------------------------------------------------------------
#  value: float finito, bool rifiutato
# --------------------------------------------------------------------------


class Test_Measurement_value_validation:
    """Validazione del campo value."""

    def test_bool_true_rejected(self):
        """bool è sottoclasse di int in Python, ma la spec richiede float
        esplicito: i booleani devono passare via convenzione 0.0/1.0."""
        with pytest.raises(MeasurementValidationError, match="float"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_BATTERY_LEVEL,
                value=True,
            )

    def test_bool_false_rejected(self):
        """Stesso discorso per False (anche se False == 0)."""
        with pytest.raises(MeasurementValidationError, match="float"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_BATTERY_LEVEL,
                value=False,
            )

    def test_string_value_rejected(self):
        """Stringa non è float: l'adapter deve fare il parsing prima."""
        with pytest.raises(MeasurementValidationError, match="float"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_SOIL_THETA,
                value="0.3",
            )

    def test_none_value_rejected(self):
        """value None → errore (Measurement è una misura, non un'assenza
        di misura: omettere la riga, non passare None)."""
        with pytest.raises(MeasurementValidationError, match="float"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_SOIL_THETA,
                value=None,
            )

    def test_nan_rejected(self):
        """NaN è il segno tipico di una divisione per zero o di un
        sensore con dati corrotti."""
        with pytest.raises(MeasurementValidationError, match="finito"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_AIR_TEMPERATURE_C,
                value=nan,
            )

    def test_positive_infinity_rejected(self):
        """+inf non è una misura plausibile."""
        with pytest.raises(MeasurementValidationError, match="finito"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_AIR_TEMPERATURE_C,
                value=inf,
            )

    def test_negative_infinity_rejected(self):
        """-inf non è una misura plausibile."""
        with pytest.raises(MeasurementValidationError, match="finito"):
            Measurement(
                sensor_id="test:device:1",
                timestamp=_ts(),
                parameter=PARAM_AIR_TEMPERATURE_C,
                value=-inf,
            )

    def test_zero_value_accepted(self):
        """Zero è un valore valido (pioggia nulla, vento fermo, ecc.)."""
        m = Measurement(
            sensor_id="test:device:1",
            timestamp=_ts(),
            parameter=PARAM_RAINFALL_MM,
            value=0.0,
        )
        assert m.value == 0.0


# --------------------------------------------------------------------------
#  Range fisici per parametro canonico (bordi del range)
# --------------------------------------------------------------------------


# (parameter, valid_low, valid_high, invalid_below, invalid_above)
_RANGE_CASES = [
    (PARAM_AIR_TEMPERATURE_C, -50.0, 70.0, -51.0, 71.0),
    (PARAM_AIR_HUMIDITY, 0.0, 1.0, -0.01, 1.01),
    (PARAM_WIND_SPEED_M_S, 0.0, 100.0, -0.1, 100.1),
    (PARAM_SOLAR_RADIATION_MJ_M2, 0.0, 50.0, -0.1, 50.1),
    (PARAM_RAINFALL_MM, 0.0, 500.0, -0.1, 500.1),
    (PARAM_BAROMETRIC_PRESSURE_HPA, 800.0, 1100.0, 799.9, 1100.1),
    (PARAM_SOIL_THETA, 0.0, 1.05, -0.01, 1.06),
    (PARAM_SOIL_TEMPERATURE_C, -20.0, 60.0, -20.1, 60.1),
    (PARAM_SOIL_EC_MSCM, 0.0, 20.0, -0.1, 20.1),
    (PARAM_SOIL_PH, 0.0, 14.0, -0.1, 14.1),
    (PARAM_BATTERY_LEVEL, 0.0, 1.0, -0.01, 1.01),
    (PARAM_SIGNAL_STRENGTH, 0.0, 1.0, -0.01, 1.01),
]


class Test_Measurement_physical_ranges:
    """Validazione dei range fisici per ciascun parametro canonico."""

    @pytest.mark.parametrize(
        "parameter,low,high,below,above", _RANGE_CASES
    )
    def test_lower_bound_inclusive(
        self, parameter, low, high, below, above
    ):
        """Il bordo inferiore del range è inclusivo (es. 0.0 OK per
        air_humidity)."""
        m = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=parameter, value=low,
        )
        assert m.value == low

    @pytest.mark.parametrize(
        "parameter,low,high,below,above", _RANGE_CASES
    )
    def test_upper_bound_inclusive(
        self, parameter, low, high, below, above
    ):
        """Il bordo superiore del range è inclusivo."""
        m = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=parameter, value=high,
        )
        assert m.value == high

    @pytest.mark.parametrize(
        "parameter,low,high,below,above", _RANGE_CASES
    )
    def test_below_lower_bound_rejected(
        self, parameter, low, high, below, above
    ):
        """Valore sotto il bordo inferiore → errore (segnala sensore
        guasto o conversione di unità sbagliata)."""
        with pytest.raises(MeasurementValidationError, match="fuori range"):
            Measurement(
                sensor_id="t:d:1", timestamp=_ts(),
                parameter=parameter, value=below,
            )

    @pytest.mark.parametrize(
        "parameter,low,high,below,above", _RANGE_CASES
    )
    def test_above_upper_bound_rejected(
        self, parameter, low, high, below, above
    ):
        """Valore sopra il bordo superiore → errore (es. umidità in %
        invece di frazione 0-1)."""
        with pytest.raises(MeasurementValidationError, match="fuori range"):
            Measurement(
                sensor_id="t:d:1", timestamp=_ts(),
                parameter=parameter, value=above,
            )


# --------------------------------------------------------------------------
#  is_custom property
# --------------------------------------------------------------------------


class Test_Measurement_is_custom:
    """Discriminazione tra parametri canonici e custom."""

    def test_canonical_parameters_are_not_custom(self):
        """Tutti i parametri canonici hanno is_custom=False."""
        for param in CANONICAL_PARAMETERS:
            m = Measurement(
                sensor_id="t:d:1", timestamp=_ts(),
                parameter=param,
                value=_MIDPOINTS[param],
            )
            assert m.is_custom is False, (
                f"Il parametro canonico {param!r} non dovrebbe essere custom"
            )

    def test_custom_namespace_is_custom(self):
        """Qualunque parametro con prefisso `custom:` ha is_custom=True."""
        for suffix in ("co2", "lux", "ph_strip", "anything"):
            m = Measurement(
                sensor_id="t:d:1", timestamp=_ts(),
                parameter=f"{CUSTOM_NAMESPACE_PREFIX}{suffix}",
                value=1.0,
            )
            assert m.is_custom is True


# --------------------------------------------------------------------------
#  Frozen dataclass: immutabilità
# --------------------------------------------------------------------------


class Test_Measurement_frozen:
    """Measurement è una frozen dataclass."""

    def test_cannot_modify_sensor_id(self):
        """Tentare di modificare sensor_id dopo la costruzione → errore."""
        m = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        with pytest.raises((AttributeError, TypeError)):
            m.sensor_id = "other"

    def test_cannot_modify_value(self):
        """Tentare di modificare value dopo la costruzione → errore."""
        m = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        with pytest.raises((AttributeError, TypeError)):
            m.value = 0.5

    def test_hashable(self):
        """frozen dataclass è hashable per default: due Measurement
        identiche hanno lo stesso hash, possono stare in set/dict."""
        m1 = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        m2 = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        assert hash(m1) == hash(m2)
        assert {m1, m2} == {m1}

    def test_equality(self):
        """Due Measurement con stessi campi sono uguali."""
        m1 = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        m2 = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        assert m1 == m2

    def test_inequality_on_value(self):
        """Due Measurement con value diverso non sono uguali."""
        m1 = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.3,
        )
        m2 = Measurement(
            sensor_id="t:d:1", timestamp=_ts(),
            parameter=PARAM_SOIL_THETA, value=0.4,
        )
        assert m1 != m2


# --------------------------------------------------------------------------
#  physical_range helper
# --------------------------------------------------------------------------


class Test_physical_range_helper:
    """La funzione di lookup pubblica del range plausibile."""

    @pytest.mark.parametrize(
        "parameter,low,high,below,above", _RANGE_CASES
    )
    def test_returns_tuple_for_canonical(
        self, parameter, low, high, below, above
    ):
        """Per ogni canonico ritorna la tupla (low, high) corretta."""
        assert physical_range(parameter) == (low, high)

    def test_returns_none_for_custom(self):
        """Per parametri custom ritorna None: il consumer decide come
        gestire (accettare opaco, validare con regole proprie)."""
        assert physical_range("custom:anything") is None

    def test_returns_none_for_unknown(self):
        """Anche per parametri sconosciuti (typo) ritorna None — non
        solleva."""
        assert physical_range("not_a_real_param") is None


# --------------------------------------------------------------------------
#  Costanti esportate
# --------------------------------------------------------------------------


class Test_canonical_constants:
    """Invarianti delle costanti esportate dal modulo."""

    def test_canonical_set_has_expected_size(self):
        """12 parametri canonici: 6 ambiente + 4 substrato + 2 sistema."""
        assert len(CANONICAL_PARAMETERS) == 12

    def test_all_environment_params_in_canonical(self):
        """I 6 parametri ambiente sono in CANONICAL_PARAMETERS."""
        for p in (
            PARAM_AIR_TEMPERATURE_C, PARAM_AIR_HUMIDITY,
            PARAM_WIND_SPEED_M_S, PARAM_SOLAR_RADIATION_MJ_M2,
            PARAM_RAINFALL_MM, PARAM_BAROMETRIC_PRESSURE_HPA,
        ):
            assert p in CANONICAL_PARAMETERS

    def test_all_soil_params_in_canonical(self):
        """I 4 parametri substrato sono in CANONICAL_PARAMETERS."""
        for p in (
            PARAM_SOIL_THETA, PARAM_SOIL_TEMPERATURE_C,
            PARAM_SOIL_EC_MSCM, PARAM_SOIL_PH,
        ):
            assert p in CANONICAL_PARAMETERS

    def test_system_params_in_canonical(self):
        """I 2 parametri di sistema sono in CANONICAL_PARAMETERS."""
        assert PARAM_BATTERY_LEVEL in CANONICAL_PARAMETERS
        assert PARAM_SIGNAL_STRENGTH in CANONICAL_PARAMETERS

    def test_requiring_pot_contains_only_soil_params(self):
        """PARAMETERS_REQUIRING_POT contiene esattamente i 4 soil_*."""
        assert PARAMETERS_REQUIRING_POT == frozenset({
            PARAM_SOIL_THETA, PARAM_SOIL_TEMPERATURE_C,
            PARAM_SOIL_EC_MSCM, PARAM_SOIL_PH,
        })

    def test_requiring_room_or_garden_contains_environment_params(self):
        """PARAMETERS_REQUIRING_ROOM_OR_GARDEN contiene esattamente i 6
        parametri ambiente (no soil_*, no battery/signal)."""
        assert PARAMETERS_REQUIRING_ROOM_OR_GARDEN == frozenset({
            PARAM_AIR_TEMPERATURE_C, PARAM_AIR_HUMIDITY,
            PARAM_WIND_SPEED_M_S, PARAM_SOLAR_RADIATION_MJ_M2,
            PARAM_RAINFALL_MM, PARAM_BAROMETRIC_PRESSURE_HPA,
        })

    def test_pot_and_room_garden_sets_are_disjoint(self):
        """Un parametro non può essere sia su Pot che su Room/Garden:
        i due set non si intersecano (invariante semantica)."""
        intersection = (
            PARAMETERS_REQUIRING_POT & PARAMETERS_REQUIRING_ROOM_OR_GARDEN
        )
        assert intersection == frozenset()

    def test_canonical_namespace_prefix_value(self):
        """Il prefisso custom è la stringa letterale `custom:`."""
        assert CUSTOM_NAMESPACE_PREFIX == "custom:"

    def test_canonical_parameters_have_no_custom_prefix(self):
        """Nessun parametro canonico inizia per accidente con `custom:`
        (sarebbe ambiguità: spec rotta)."""
        for p in CANONICAL_PARAMETERS:
            assert not p.startswith(CUSTOM_NAMESPACE_PREFIX)


# --------------------------------------------------------------------------
#  SCHEMA_VERSION
# --------------------------------------------------------------------------


class Test_schema_version:
    """Stabilità della versione dello schema."""

    def test_schema_version_is_one(self):
        """La v1 è la versione corrente. Quando si farà una v2 questo
        test sarà rotto di proposito (è un canary): la decisione di
        bumping va affrontata esplicitamente."""
        assert SCHEMA_VERSION == 1

    def test_schema_version_is_int(self):
        """schema_version è un intero per facilitare confronti
        applicativi (es. `if payload['schema_version'] != SCHEMA_VERSION`)."""
        assert isinstance(SCHEMA_VERSION, int)
