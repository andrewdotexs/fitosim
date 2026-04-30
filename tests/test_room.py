"""
Test della dataclass Room e di IndoorMicroclimate introdotte dalla
fase D1 della sotto-tappa D tappa 5.

Le dataclass sono strutture di dato pure: i test verificano la
validazione del __post_init__ (la coerenza tra il flag kind e i
campi popolati), la mutabilità del current_microclimate della Room,
e i comportamenti di gestione degli errori.
"""

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime

from fitosim.domain.room import (
    DEFAULT_INDOOR_WIND_M_S,
    IndoorMicroclimate,
    LightExposure,
    MicroclimateKind,
    Room,
)


# =====================================================================
#  Test della dataclass IndoorMicroclimate.
#
#  Verifichiamo le tre famiglie di proprietà:
#    1. Costruzione valida nei due casi INSTANT e DAILY.
#    2. Validazione del __post_init__ per casi inconsistenti (kind vs
#       campi popolati, umidità fuori range, t_min > t_max).
#    3. Immutabilità (frozen=True).
# =====================================================================


class TestIndoorMicroclimateInstantConstruction(unittest.TestCase):
    """Costruzione e validazione del caso INSTANT."""

    def test_instant_minimal_construction(self):
        # Costruzione minima INSTANT con solo i tre campi obbligatori.
        m = IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=22.3,
            humidity_relative=0.55,
        )
        self.assertEqual(m.kind, MicroclimateKind.INSTANT)
        self.assertEqual(m.temperature_c, 22.3)
        self.assertEqual(m.humidity_relative, 0.55)
        self.assertIsNone(m.t_min)
        self.assertIsNone(m.t_max)
        self.assertIsNone(m.timestamp)

    def test_instant_with_timestamp(self):
        # INSTANT con timestamp opzionale popolato.
        ts = datetime(2026, 7, 19, 14, 30, 0)
        m = IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=22.3,
            humidity_relative=0.55,
            timestamp=ts,
        )
        self.assertEqual(m.timestamp, ts)

    def test_instant_with_t_min_raises(self):
        # INSTANT con t_min popolato deve sollevare ValueError perché
        # un istante non ha minima/massima.
        with self.assertRaises(ValueError) as ctx:
            IndoorMicroclimate(
                kind=MicroclimateKind.INSTANT,
                temperature_c=22.3, humidity_relative=0.55,
                t_min=20.0,
            )
        self.assertIn("INSTANT", str(ctx.exception))

    def test_instant_with_t_max_raises(self):
        # INSTANT con t_max popolato deve sollevare ValueError.
        with self.assertRaises(ValueError):
            IndoorMicroclimate(
                kind=MicroclimateKind.INSTANT,
                temperature_c=22.3, humidity_relative=0.55,
                t_max=25.0,
            )


class TestIndoorMicroclimateDailyConstruction(unittest.TestCase):
    """Costruzione e validazione del caso DAILY."""

    def test_daily_complete_construction(self):
        # Costruzione completa DAILY con tutti i campi popolati.
        m = IndoorMicroclimate(
            kind=MicroclimateKind.DAILY,
            temperature_c=21.0, humidity_relative=0.55,
            t_min=19.5, t_max=22.5,
        )
        self.assertEqual(m.t_min, 19.5)
        self.assertEqual(m.t_max, 22.5)

    def test_daily_without_t_min_raises(self):
        # DAILY senza t_min deve sollevare ValueError.
        with self.assertRaises(ValueError) as ctx:
            IndoorMicroclimate(
                kind=MicroclimateKind.DAILY,
                temperature_c=21.0, humidity_relative=0.55,
                t_max=22.5,
            )
        self.assertIn("DAILY", str(ctx.exception))

    def test_daily_without_t_max_raises(self):
        # DAILY senza t_max deve sollevare ValueError.
        with self.assertRaises(ValueError):
            IndoorMicroclimate(
                kind=MicroclimateKind.DAILY,
                temperature_c=21.0, humidity_relative=0.55,
                t_min=19.5,
            )

    def test_daily_with_t_min_greater_than_t_max_raises(self):
        # DAILY con t_min > t_max deve sollevare ValueError.
        with self.assertRaises(ValueError) as ctx:
            IndoorMicroclimate(
                kind=MicroclimateKind.DAILY,
                temperature_c=21.0, humidity_relative=0.55,
                t_min=25.0, t_max=20.0,
            )
        self.assertIn("t_min", str(ctx.exception))


class TestIndoorMicroclimateValidation(unittest.TestCase):
    """Validazioni universali (indipendenti dal kind)."""

    def test_humidity_above_one_raises(self):
        # Umidità > 1 (errore tipico: percentuale invece di frazione).
        with self.assertRaises(ValueError) as ctx:
            IndoorMicroclimate(
                kind=MicroclimateKind.INSTANT,
                temperature_c=22.0, humidity_relative=55.0,
            )
        self.assertIn("humidity_relative", str(ctx.exception))

    def test_humidity_negative_raises(self):
        # Umidità negativa.
        with self.assertRaises(ValueError):
            IndoorMicroclimate(
                kind=MicroclimateKind.INSTANT,
                temperature_c=22.0, humidity_relative=-0.1,
            )

    def test_is_frozen(self):
        # IndoorMicroclimate è frozen: tentare di mutare un campo
        # deve sollevare FrozenInstanceError.
        m = IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=22.0, humidity_relative=0.55,
        )
        with self.assertRaises(FrozenInstanceError):
            m.temperature_c = 30.0


# =====================================================================
#  Test della dataclass Room.
#
#  La Room è mutabile (a differenza di IndoorMicroclimate) perché il
#  current_microclimate evolve nel tempo. Verifichiamo costruzione,
#  validazione del __post_init__, e il metodo update_current_microclimate.
# =====================================================================


class TestRoomConstruction(unittest.TestCase):
    """Costruzione e validazione della Room."""

    def test_minimal_construction(self):
        # Costruzione minimale con solo room_id e name.
        room = Room(room_id="salotto", name="Salotto principale")
        self.assertEqual(room.room_id, "salotto")
        self.assertEqual(room.name, "Salotto principale")
        self.assertIsNone(room.wn31_channel_id)
        self.assertIsNone(room.current_microclimate)
        self.assertEqual(room.default_wind_m_s, DEFAULT_INDOOR_WIND_M_S)

    def test_full_construction(self):
        # Costruzione con tutti i campi popolati.
        room = Room(
            room_id="cucina", name="Cucina",
            wn31_channel_id="ch1",
            default_wind_m_s=0.8,
        )
        self.assertEqual(room.wn31_channel_id, "ch1")
        self.assertEqual(room.default_wind_m_s, 0.8)

    def test_empty_room_id_raises(self):
        # room_id vuoto deve sollevare ValueError.
        with self.assertRaises(ValueError):
            Room(room_id="", name="Stanza senza id")

    def test_negative_wind_raises(self):
        # Vento negativo deve sollevare ValueError.
        with self.assertRaises(ValueError):
            Room(
                room_id="salotto", name="Salotto",
                default_wind_m_s=-1.0,
            )


class TestRoomMicroclimateUpdate(unittest.TestCase):
    """Aggiornamento del current_microclimate."""

    def test_update_with_instant(self):
        # Aggiornamento valido con un INSTANT.
        room = Room(room_id="salotto", name="Salotto")
        m = IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=22.3, humidity_relative=0.55,
        )
        room.update_current_microclimate(m)
        self.assertEqual(room.current_microclimate, m)

    def test_update_replaces_previous(self):
        # Un secondo aggiornamento sostituisce il primo.
        room = Room(room_id="salotto", name="Salotto")
        m1 = IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=22.3, humidity_relative=0.55,
        )
        m2 = IndoorMicroclimate(
            kind=MicroclimateKind.INSTANT,
            temperature_c=23.0, humidity_relative=0.50,
        )
        room.update_current_microclimate(m1)
        room.update_current_microclimate(m2)
        self.assertEqual(room.current_microclimate, m2)

    def test_update_with_daily_raises(self):
        # Aggiornamento con DAILY deve sollevare ValueError perché
        # current_microclimate rappresenta lo stato istantaneo.
        room = Room(room_id="salotto", name="Salotto")
        m_daily = IndoorMicroclimate(
            kind=MicroclimateKind.DAILY,
            temperature_c=21.0, humidity_relative=0.55,
            t_min=19.5, t_max=22.5,
        )
        with self.assertRaises(ValueError) as ctx:
            room.update_current_microclimate(m_daily)
        self.assertIn("INSTANT", str(ctx.exception))


# =====================================================================
#  Test dell'enum LightExposure.
# =====================================================================


class TestLightExposure(unittest.TestCase):

    def test_three_levels(self):
        # Tre livelli previsti dal design.
        self.assertEqual(
            {e.name for e in LightExposure},
            {"DARK", "INDIRECT_BRIGHT", "DIRECT_SUN"},
        )


if __name__ == "__main__":
    unittest.main()
