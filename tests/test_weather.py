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

from fitosim.domain.weather import WeatherBlock, WeatherDay, weather_day_from_blocks


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


class TestWeatherDayExtremes(unittest.TestCase):
    """
    A9 (2026-10-21): le umidità relative estreme del giorno, facoltative e
    a coppia, e la validazione che il giorno fa su se stesso.
    """

    def test_extremes_are_optional_and_kept(self):
        w = WeatherDay(date_=date(2026, 7, 19), t_min=20.0, t_max=32.0)
        self.assertIsNone(w.humidity_min)
        self.assertIsNone(w.humidity_max)
        w = WeatherDay(
            date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
            humidity_relative=0.60, humidity_min=0.35, humidity_max=0.90,
        )
        self.assertEqual((w.humidity_min, w.humidity_max), (0.35, 0.90))

    def test_unpaired_extremes_raise(self):
        with self.assertRaises(ValueError):
            WeatherDay(date_=date(2026, 7, 19), t_min=20.0, t_max=32.0, humidity_min=0.35)

    def test_out_of_range_or_inverted_values_raise(self):
        with self.assertRaises(ValueError):
            WeatherDay(
                date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
                humidity_min=35.0, humidity_max=90.0,
            )
        with self.assertRaises(ValueError):
            WeatherDay(
                date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
                humidity_min=0.90, humidity_max=0.35,
            )
        with self.assertRaises(ValueError):
            WeatherDay(date_=date(2026, 7, 19), t_min=20.0, t_max=32.0, humidity_relative=65.0)

    def test_t_min_above_t_max_raises(self):
        with self.assertRaises(ValueError):
            WeatherDay(date_=date(2026, 7, 19), t_min=32.0, t_max=20.0)

    def test_the_day_from_blocks_derives_the_extremes(self):
        giorno = date(2026, 7, 19)
        blocchi = [
            WeatherBlock(giorno, 0, 6, 18.0, humidity_relative=0.90),
            WeatherBlock(giorno, 6, 6, 24.0, humidity_relative=0.50),
            WeatherBlock(giorno, 12, 6, 31.0, humidity_relative=0.40),
            WeatherBlock(giorno, 18, 6, 25.0, humidity_relative=0.80),
        ]
        w = weather_day_from_blocks(blocchi)
        self.assertAlmostEqual(w.humidity_relative, 0.65)
        self.assertEqual((w.humidity_min, w.humidity_max), (0.40, 0.90))
        # Un blocco senza umidità: niente media e niente estremi.
        senza = blocchi[:3] + [WeatherBlock(giorno, 18, 6, 25.0)]
        w = weather_day_from_blocks(senza)
        self.assertIsNone(w.humidity_relative)
        self.assertIsNone(w.humidity_min)
        self.assertIsNone(w.humidity_max)


if __name__ == "__main__":
    unittest.main()
