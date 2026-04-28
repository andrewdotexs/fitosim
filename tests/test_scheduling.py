"""
Test del modulo domain/scheduling.py (sotto-tappa D tappa 4 fascia 2).

Strategia di test
-----------------

Test unitari basilari sulle dataclass ScheduledEvent e
WeatherDayForecast: frozen-ness, validazione dei campi, equality
strutturale.
"""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from fitosim.domain.scheduling import ScheduledEvent, WeatherDayForecast


class TestScheduledEvent(unittest.TestCase):
    """Validazione e proprietà di ScheduledEvent."""

    def test_minimal_construction(self):
        ev = ScheduledEvent(
            event_id="e1", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
        )
        self.assertEqual(ev.event_id, "e1")
        self.assertEqual(ev.payload, {})  # default empty dict

    def test_full_construction(self):
        ev = ScheduledEvent(
            event_id="e1", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
            payload={"volume_l": 0.3, "product": "BioBizz Bio-Grow"},
        )
        self.assertEqual(ev.payload["product"], "BioBizz Bio-Grow")

    def test_frozen(self):
        ev = ScheduledEvent(
            event_id="e1", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
        )
        with self.assertRaises(FrozenInstanceError):
            ev.event_id = "e2"

    def test_empty_event_id_rejected(self):
        with self.assertRaises(ValueError):
            ScheduledEvent(
                event_id="", pot_label="x", event_type="x",
                scheduled_date=date(2026, 5, 18),
            )

    def test_empty_pot_label_rejected(self):
        with self.assertRaises(ValueError):
            ScheduledEvent(
                event_id="e1", pot_label="", event_type="x",
                scheduled_date=date(2026, 5, 18),
            )

    def test_empty_event_type_rejected(self):
        with self.assertRaises(ValueError):
            ScheduledEvent(
                event_id="e1", pot_label="x", event_type="",
                scheduled_date=date(2026, 5, 18),
            )


class TestWeatherDayForecast(unittest.TestCase):
    """Validazione e proprietà di WeatherDayForecast."""

    def test_minimal_construction(self):
        # rainfall_mm ha default 0.0
        wf = WeatherDayForecast(
            date_=date(2026, 5, 15), et_0_mm=4.5,
        )
        self.assertEqual(wf.rainfall_mm, 0.0)

    def test_full_construction(self):
        wf = WeatherDayForecast(
            date_=date(2026, 5, 15), et_0_mm=4.5, rainfall_mm=2.0,
        )
        self.assertEqual(wf.et_0_mm, 4.5)
        self.assertEqual(wf.rainfall_mm, 2.0)

    def test_frozen(self):
        wf = WeatherDayForecast(date_=date(2026, 5, 15), et_0_mm=4.5)
        with self.assertRaises(FrozenInstanceError):
            wf.et_0_mm = 5.0

    def test_negative_et_rejected(self):
        with self.assertRaises(ValueError):
            WeatherDayForecast(date_=date(2026, 5, 15), et_0_mm=-1.0)

    def test_negative_rainfall_rejected(self):
        with self.assertRaises(ValueError):
            WeatherDayForecast(
                date_=date(2026, 5, 15), et_0_mm=4.0, rainfall_mm=-1.0,
            )


if __name__ == "__main__":
    unittest.main()
