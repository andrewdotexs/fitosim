"""
Test della dataclass WeatherDay introdotta dalla sotto-tappa C tappa 5.

WeatherDay è una struttura di dato pura: i test verificano le sue
proprietà strutturali (campi, immutabilità) e il comportamento della
property has_full_weather che determina se il dato è "completo per
Penman-Monteith" o no.
"""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from fitosim.domain.weather import WeatherDay


class TestWeatherDayStructure(unittest.TestCase):
    """
    Verifica delle proprietà strutturali della dataclass: i campi
    obbligatori, i default dei campi opzionali, l'immutabilità.
    """

    def test_minimal_construction_with_only_temperatures(self):
        # Con solo data e temperature deve costruirsi correttamente.
        # Gli altri tre campi prendono il default None.
        w = WeatherDay(date_=date(2026, 7, 19), t_min=20.0, t_max=32.0)
        self.assertEqual(w.t_min, 20.0)
        self.assertEqual(w.t_max, 32.0)
        self.assertIsNone(w.humidity_relative)
        self.assertIsNone(w.wind_speed_m_s)
        self.assertIsNone(w.solar_radiation_mj_m2_day)

    def test_full_construction_with_all_fields(self):
        # Costruzione con tutti i campi popolati: i valori passati
        # devono essere conservati esattamente.
        w = WeatherDay(
            date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            solar_radiation_mj_m2_day=24.0,
        )
        self.assertEqual(w.humidity_relative, 0.60)
        self.assertEqual(w.wind_speed_m_s, 1.5)
        self.assertEqual(w.solar_radiation_mj_m2_day, 24.0)

    def test_is_frozen(self):
        # WeatherDay è frozen: tentare di mutare un campo deve sollevare
        # FrozenInstanceError. Questo assicura che i dati meteo di un
        # giorno non siano modificabili una volta registrati.
        w = WeatherDay(date_=date(2026, 7, 19), t_min=20.0, t_max=32.0)
        with self.assertRaises(FrozenInstanceError):
            w.t_min = 100.0


class TestWeatherDayHasFullWeather(unittest.TestCase):
    """
    Verifica della property has_full_weather, che determina se i tre
    dati meteo aggiuntivi (umidità, vento, radiazione) sono tutti
    presenti. È utile come sanity check rapido senza dover ispezionare
    i tre campi individualmente.
    """

    def test_all_three_present(self):
        # Tutti i tre dati popolati: has_full_weather deve essere True.
        w = WeatherDay(
            date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            solar_radiation_mj_m2_day=24.0,
        )
        self.assertTrue(w.has_full_weather)

    def test_only_temperatures(self):
        # Solo temperature, niente altri dati meteo: deve essere False.
        w = WeatherDay(date_=date(2026, 7, 19), t_min=20.0, t_max=32.0)
        self.assertFalse(w.has_full_weather)

    def test_partial_two_of_three(self):
        # Due dei tre presenti (manca solo radiazione): comunque False.
        # La property è "tutto o niente" sui tre dati aggiuntivi,
        # coerentemente con la logica del selettore.
        w = WeatherDay(
            date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            # solar_radiation_mj_m2_day mancante
        )
        self.assertFalse(w.has_full_weather)

    def test_partial_only_humidity(self):
        # Solo umidità presente: False.
        w = WeatherDay(
            date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
            humidity_relative=0.60,
        )
        self.assertFalse(w.has_full_weather)


if __name__ == "__main__":
    unittest.main()
