"""
Test del giorno fatto di blocchi (A7, 2026-09-29): i tipi di
`domain/weather.py` e `domain/blocks.py`, l'ET₀ per blocco, e i tre
metodi del Pot — con l'invariante che tiene tutto insieme: un solo
blocco di 24 ore è il passo giornaliero di sempre, numero per numero.
"""

import math
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone

from fitosim.domain.blocks import (
    BalanceBlock,
    BlockFertigation,
    et0_for_blocks,
    validate_block_tiling,
)
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL, ROSEMARY
from fitosim.domain.weather import (
    WeatherBlock,
    WeatherSample,
    validate_day_blocks,
    weather_blocks_from_samples,
    weather_day_from_blocks,
)
from fitosim.science.et0 import EtMethod, distribute_daily_et0, et0_hargreaves_samani
from fitosim.science.radiation import day_of_year, extraterrestrial_radiation_interval
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

LAT, LON, TZ, Z = 45.47, 9.19, 1.0, 160.0   # Milano, ora solare CET, 160 m
DAY = date(2026, 9, 14)


def _synthetic_hourly_blocks(
    day: date = DAY, *, humidity: bool = True, wind: bool = True, solar: bool = True,
) -> list[WeatherBlock]:
    """
    Una giornata serena di settembre: T fra 17 (alle 3) e 27 (alle 15),
    umidità in controfase (0.90 → 0.54), vento 1 m/s, sole dalle 6 alle
    18 con 18 MJ/m² in tutto.
    """
    blocks = []
    for h in range(24):
        phase = 2 * math.pi * (h + 0.5 - 15) / 24
        sun = math.sin(math.pi * (h + 0.5 - 6) / 12) if 6 <= h < 18 else 0.0
        blocks.append(WeatherBlock(
            date_=day, start_hour=h, hours=1,
            t_c=22.0 + 5.0 * math.cos(phase),
            humidity_relative=(0.72 - 0.18 * math.cos(phase)) if humidity else None,
            wind_speed_m_s=1.0 if wind else None,
            solar_radiation_mj_m2=(2.4 * max(sun, 0.0)) if solar else None,
        ))
    return blocks


def _basil_pot(**overrides) -> Pot:
    kwargs = {
        "label": "basilico", "species": BASIL, "substrate": UNIVERSAL_POTTING_SOIL,
        "pot_volume_l": 5.0, "pot_diameter_cm": 20.0, "location": Location.OUTDOOR,
        "planting_date": date(2026, 7, 20), "latitude_deg": LAT, "elevation_m": Z,
    }
    kwargs.update(overrides)
    return Pot(**kwargs)


def _sun_profile_blocks(et_0_day_mm: float) -> list[BalanceBlock]:
    """L'ET₀ del giorno su 24 blocchi orari, col profilo del sole (zero di notte)."""
    j = day_of_year(DAY)
    weights = [
        extraterrestrial_radiation_interval(LAT, LON, j, h, h + 1, TZ) for h in range(24)
    ]
    return [
        BalanceBlock(start_hour=h, hours=1, et_0_mm=part)
        for h, part in enumerate(distribute_daily_et0(et_0_day_mm, weights))
    ]


class TestWeatherBlock(unittest.TestCase):
    """Il meteo di un blocco: campi, proprietà, validazione."""

    def test_properties(self):
        b = WeatherBlock(DAY, 6, 3, 18.0, humidity_relative=0.8, wind_speed_m_s=1.2,
                         solar_radiation_mj_m2=1.5)
        self.assertEqual(b.end_hour, 9)
        self.assertTrue(b.has_full_weather)
        self.assertFalse(WeatherBlock(DAY, 6, 3, 18.0, humidity_relative=0.8).has_full_weather)

    def test_validation(self):
        with self.assertRaises(ValueError):
            WeatherBlock(DAY, 0, 0, 18.0)
        with self.assertRaises(ValueError):
            WeatherBlock(DAY, 24, 1, 18.0)
        with self.assertRaises(ValueError):
            WeatherBlock(DAY, 20, 6, 18.0)
        with self.assertRaises(ValueError):
            WeatherBlock(DAY, 0, 1, 18.0, humidity_relative=65.0)
        with self.assertRaises(ValueError):
            WeatherBlock(DAY, 0, 1, 18.0, wind_speed_m_s=-0.1)


class TestDayBlocks(unittest.TestCase):
    """La copertura del giorno e il WeatherDay che ne esce."""

    def test_tiling_accepts_hourly_and_six_hourly(self):
        validate_day_blocks(_synthetic_hourly_blocks())
        validate_day_blocks([WeatherBlock(DAY, h, 6, 20.0) for h in (0, 6, 12, 18)])

    def test_tiling_rejects_gaps_short_days_and_mixed_dates(self):
        with self.assertRaises(ValueError):
            validate_day_blocks([WeatherBlock(DAY, 0, 6, 20.0), WeatherBlock(DAY, 12, 12, 20.0)])
        with self.assertRaises(ValueError):
            validate_day_blocks([WeatherBlock(DAY, 0, 12, 20.0)])
        with self.assertRaises(ValueError):
            validate_day_blocks([
                WeatherBlock(DAY, 0, 12, 20.0), WeatherBlock(date(2026, 9, 15), 12, 12, 20.0),
            ])
        with self.assertRaises(ValueError):
            validate_day_blocks([])

    def test_weather_day_from_blocks_aggregates(self):
        blocks = _synthetic_hourly_blocks()
        day = weather_day_from_blocks(blocks)
        self.assertEqual(day.date_, DAY)
        self.assertAlmostEqual(day.t_min, min(b.t_c for b in blocks))
        self.assertAlmostEqual(day.t_max, max(b.t_c for b in blocks))
        self.assertAlmostEqual(day.humidity_relative, 0.72, places=6)
        self.assertAlmostEqual(day.wind_speed_m_s, 1.0)
        self.assertAlmostEqual(
            day.solar_radiation_mj_m2_day, sum(b.solar_radiation_mj_m2 for b in blocks),
        )
        self.assertTrue(day.has_full_weather)

    def test_a_missing_field_in_one_block_is_missing_in_the_day(self):
        blocks = _synthetic_hourly_blocks()
        blocks[10] = replace(blocks[10], humidity_relative=None)
        day = weather_day_from_blocks(blocks)
        self.assertIsNone(day.humidity_relative)
        self.assertIsNotNone(day.wind_speed_m_s)


class TestWeatherSamples(unittest.TestCase):
    """Dai campioni della stazione ai blocchi, in ora civile standard."""

    def test_groups_by_standard_time(self):
        # 22:30 e 23:30 UTC del 13 sono 23:30 del 13 e 00:30 del 14 in CET.
        samples = [
            WeatherSample(datetime(2026, 9, 13, 22, 30, tzinfo=timezone.utc), t_c=20.0),
            WeatherSample(datetime(2026, 9, 13, 23, 30, tzinfo=timezone.utc), t_c=19.0),
        ]
        blocks = weather_blocks_from_samples(samples, hours=1, utc_offset_hours=TZ)
        self.assertEqual([(b.date_, b.start_hour) for b in blocks],
                         [(date(2026, 9, 13), 23), (date(2026, 9, 14), 0)])
        self.assertEqual(blocks[0].t_c, 20.0)

    def test_solar_is_the_mean_flux_over_the_block(self):
        samples = [
            WeatherSample(datetime(2026, 9, 14, 11, 5, tzinfo=timezone.utc), t_c=24.0, solar_w_m2=400.0),
            WeatherSample(datetime(2026, 9, 14, 11, 35, tzinfo=timezone.utc), t_c=25.0, solar_w_m2=600.0),
        ]
        (block,) = weather_blocks_from_samples(samples, hours=1, utc_offset_hours=TZ)
        self.assertEqual(block.start_hour, 12)              # 11 UTC → 12 CET
        self.assertAlmostEqual(block.t_c, 24.5)
        self.assertAlmostEqual(block.solar_radiation_mj_m2, 500.0 * 3600.0 / 1e6)   # 1.8 MJ
        self.assertIsNone(block.humidity_relative)

    def test_block_without_temperature_is_skipped(self):
        samples = [WeatherSample(datetime(2026, 9, 14, 11, 5, tzinfo=timezone.utc), solar_w_m2=400.0)]
        self.assertEqual(weather_blocks_from_samples(samples, 1, TZ), [])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            WeatherSample(datetime(2026, 9, 14, 11, 5), t_c=20.0)  # noqa: DTZ001 — naive, voluto
        with self.assertRaises(ValueError):
            weather_blocks_from_samples([], hours=5, utc_offset_hours=TZ)


class TestBalanceBlockTypes(unittest.TestCase):
    """I tipi dell'ingresso al secchio."""

    def test_negative_et0_is_refused(self):
        with self.assertRaises(ValueError):
            BalanceBlock(0, 1, -0.01)

    def test_tiling(self):
        validate_block_tiling([BalanceBlock(0, 24, 3.0)])
        validate_block_tiling(_sun_profile_blocks(3.0))
        with self.assertRaises(ValueError):
            validate_block_tiling([BalanceBlock(0, 12, 1.0), BalanceBlock(13, 11, 1.0)])
        with self.assertRaises(ValueError):
            validate_block_tiling([BalanceBlock(1, 23, 1.0)])

    def test_fertigation_validation(self):
        with self.assertRaises(ValueError):
            BlockFertigation(start_hour=24, volume_l=1.0)
        with self.assertRaises(ValueError):
            BlockFertigation(start_hour=8, volume_l=0.0)


class TestEt0ForBlocks(unittest.TestCase):
    """L'ET₀ per blocco: Penman-Monteith a ore, o il giorno ripartito."""

    def test_standard_when_the_species_has_no_parameters(self):
        blocks = _synthetic_hourly_blocks()
        et_blocks, method, pre_sunset = et0_for_blocks(
            blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
        )
        self.assertEqual(method, EtMethod.PENMAN_MONTEITH_STANDARD)
        self.assertEqual(len(et_blocks), 24)
        self.assertTrue(all(e.et_mm >= 0.0 for e in et_blocks))
        # Di notte la formula va sotto zero e il blocco vale zero (D7).
        night = et_blocks[2]
        self.assertFalse(night.daytime)
        self.assertLess(night.et_raw_mm, 0.0)
        self.assertEqual(night.et_mm, 0.0)
        self.assertTrue(et_blocks[12].daytime)
        self.assertGreater(et_blocks[12].et_mm, 0.2)
        # Una giornata serena di settembre a Milano: fra 2 e 4.5 mm.
        total = sum(e.et_mm for e in et_blocks)
        self.assertGreater(total, 2.0)
        self.assertLess(total, 4.5)
        self.assertIsNotNone(pre_sunset)
        self.assertGreaterEqual(pre_sunset, 0.3)
        self.assertLessEqual(pre_sunset, 1.0)

    def test_physical_when_both_parameters_are_given(self):
        blocks = _synthetic_hourly_blocks()
        standard, _, _ = et0_for_blocks(
            blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
        )
        physical, method, _ = et0_for_blocks(
            blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
            stomatal_resistance_s_m=ROSEMARY.stomatal_resistance_s_m,
            crop_height_m=ROSEMARY.crop_height_m,
        )
        self.assertEqual(method, EtMethod.PENMAN_MONTEITH_PHYSICAL)
        # Il rosmarino (r_s 200 s/m) traspira meno del prato di riferimento.
        self.assertLess(sum(e.et_mm for e in physical), sum(e.et_mm for e in standard))

    def test_missing_humidity_falls_back_to_the_day_distributed(self):
        blocks = _synthetic_hourly_blocks(humidity=False)
        et_blocks, method, pre_sunset = et0_for_blocks(
            blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
        )
        self.assertEqual(method, EtMethod.HARGREAVES_SAMANI)
        self.assertIsNone(pre_sunset)
        day = weather_day_from_blocks(blocks)
        expected = et0_hargreaves_samani(day.t_min, day.t_max, LAT, day_of_year(DAY))
        self.assertAlmostEqual(sum(e.et_mm for e in et_blocks), expected, places=9)
        self.assertEqual(et_blocks[2].et_mm, 0.0)          # notte: R_a = 0
        self.assertIsNone(et_blocks[12].rn_mj)

    def test_blocks_longer_than_twelve_hours_are_refused(self):
        blocks = [WeatherBlock(DAY, 0, 24, 20.0, 0.7, 1.0, 18.0)]
        with self.assertRaises(ValueError):
            et0_for_blocks(
                blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
            )

    def test_the_previous_night_ratio_covers_the_hours_before_sunset(self):
        blocks = _synthetic_hourly_blocks()
        own, _, pre_sunset = et0_for_blocks(
            blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
        )
        chained, _, _ = et0_for_blocks(
            blocks, latitude_deg=LAT, longitude_deg=LON, utc_offset_hours=TZ, elevation_m=Z,
            rs_rso_night_previous=0.3,
        )
        # Prima dell'alba vale il rapporto di ieri; dopo il pre-tramonto quello di oggi.
        self.assertEqual(chained[2].rs_rso, 0.3)
        self.assertEqual(own[2].rs_rso, pre_sunset)
        self.assertEqual(chained[22].rs_rso, pre_sunset)
        self.assertEqual(own[22].rs_rso, pre_sunset)


class TestPotBalanceBlocks(unittest.TestCase):
    """`Pot.apply_balance_blocks`: l'invariante e gli effetti dei blocchi."""

    def test_a_single_24h_block_is_the_daily_step(self):
        daily = _basil_pot(saucer_capacity_mm=10.0, saucer_state_mm=10.0, state_mm=50.0)
        blocks = _basil_pot(saucer_capacity_mm=10.0, saucer_state_mm=10.0, state_mm=50.0)
        d = daily.apply_balance_step(3.0, 0.0, DAY, t_mean_c=22.0)
        b = blocks.apply_balance_blocks([BalanceBlock(0, 24, 3.0)], DAY, t_mean_c=22.0)
        self.assertEqual(blocks.state_mm, daily.state_mm)
        self.assertEqual(blocks.saucer_state_mm, daily.saucer_state_mm)
        self.assertEqual(b.balance_result.new_state, d.new_state)
        self.assertEqual(b.balance_result.drainage, d.drainage)
        self.assertEqual(b.balance_result.under_alert, d.under_alert)
        self.assertEqual(b.nutrient_result, daily.last_nutrient_step)
        self.assertEqual(len(b.blocks), 1)
        self.assertIsNone(b.alert_hour)

    def test_hourly_blocks_above_the_threshold_match_the_daily_total(self):
        # Sopra la soglia Ks = 1 in tutti e due: stesso Kc, stessa ET₀
        # totale, stesso stato a fine giornata.
        daily = _basil_pot()
        blocks = _basil_pot()
        daily.apply_balance_step(3.0, 0.0, DAY)
        result = blocks.apply_balance_blocks(_sun_profile_blocks(3.0), DAY)
        self.assertAlmostEqual(blocks.state_mm, daily.state_mm, places=9)
        self.assertEqual(len(result.blocks), 24)
        self.assertAlmostEqual(result.et_c_mm, daily.fc_mm - daily.state_mm, places=9)

    def test_below_the_threshold_blocks_lose_less_and_time_the_alert(self):
        start = _basil_pot().alert_mm + 0.5
        daily = _basil_pot(state_mm=start)
        blocks = _basil_pot(state_mm=start)
        d = daily.apply_balance_step(3.0, 0.0, DAY)
        b = blocks.apply_balance_blocks(_sun_profile_blocks(3.0), DAY)
        self.assertTrue(d.under_alert)
        self.assertTrue(b.balance_result.under_alert)
        self.assertIsNotNone(b.alert_hour)
        self.assertTrue(1 <= b.alert_hour <= 24)
        # Ks scende ora per ora: i blocchi consumano meno del passo che
        # valuta Ks sullo stato di inizio giornata (D2).
        self.assertGreater(blocks.state_mm, daily.state_mm)
        self.assertLess(blocks.state_mm - daily.state_mm, 0.5)

    def test_a_day_that_starts_under_the_threshold_has_alert_hour_zero(self):
        pot = _basil_pot(state_mm=_basil_pot().alert_mm - 1.0)
        result = pot.apply_balance_blocks(_sun_profile_blocks(3.0), DAY)
        self.assertEqual(result.alert_hour, 0)
        self.assertTrue(result.balance_result.under_alert)

    def test_the_saucer_rate_is_rescaled_on_short_blocks(self):
        start = _basil_pot().fc_mm - 15.0
        daily = _basil_pot(saucer_capacity_mm=10.0, saucer_state_mm=10.0, state_mm=start)
        hourly = _basil_pot(saucer_capacity_mm=10.0, saucer_state_mm=10.0, state_mm=start)
        daily.apply_balance_step(3.0, 0.0, DAY)
        result = hourly.apply_balance_blocks(_sun_profile_blocks(3.0), DAY)
        # Con 0.4 applicato alla prima ora il piattino passerebbe 6 mm
        # subito (ne resterebbero 4); riscalato ne passa 0.3 (D4).
        self.assertGreater(result.blocks[0].saucer_state_after_mm, 9.5)
        # A fine giornata i due cammini si somigliano: il giornaliero
        # passa 0.4 × 15 mm in un colpo, i blocchi un po' di più perché
        # il deficit resta alto mentre l'ET del giorno lo riapre.
        self.assertGreater(hourly.saucer_state_mm, 1.0)
        self.assertLess(abs(hourly.saucer_state_mm - daily.saucer_state_mm), 1.5)

    def test_dual_kc_updates_de_per_block(self):
        species = replace(BASIL, kcb_initial=0.15, kcb_mid=0.95, kcb_late=0.70)
        substrate = replace(UNIVERSAL_POTTING_SOIL, rew_mm=9.0, tew_mm=32.5)
        daily = _basil_pot(species=species, substrate=substrate)
        hourly = _basil_pot(species=species, substrate=substrate)
        self.assertTrue(daily.supports_dual_kc)
        daily.apply_balance_step(3.0, 0.0, DAY)
        result = hourly.apply_balance_blocks(_sun_profile_blocks(3.0), DAY)
        self.assertGreater(hourly.de_mm, 0.0)
        self.assertAlmostEqual(hourly.de_mm, daily.de_mm, delta=0.05)
        self.assertAlmostEqual(result.soil_evaporation_mm, daily.de_mm, delta=0.05)


class TestPotStepBlocks(unittest.TestCase):
    """`Pot.apply_step_blocks`: gli eventi alla loro ora."""

    def test_an_evening_irrigation_drains_less_than_a_morning_one(self):
        start = _basil_pot().fc_mm - 10.0
        morning = _basil_pot(state_mm=start)
        evening = _basil_pot(state_mm=start)
        m = morning.apply_step_blocks(
            _sun_profile_blocks(3.0), DAY,
            fertigations=[BlockFertigation(start_hour=8, volume_l=1.0, ec_mscm=0.5, ph=7.5)],
        )
        e = evening.apply_step_blocks(
            _sun_profile_blocks(3.0), DAY,
            fertigations=[BlockFertigation(start_hour=20, volume_l=1.0, ec_mscm=0.5, ph=7.5)],
        )
        self.assertEqual(len(m.fertigation_results), 1)
        self.assertLess(e.fertigation_results[0].water_drained_mm,
                        m.fertigation_results[0].water_drained_mm)
        self.assertGreater(evening.state_mm, morning.state_mm)

    def test_rain_enters_its_block(self):
        pot = _basil_pot(state_mm=_basil_pot().fc_mm - 10.0)
        result = pot.apply_step_blocks(
            _sun_profile_blocks(3.0), DAY, rainfall_l_by_hour={14: 0.2},
        )
        self.assertEqual(len(result.rainfall_results), 1)
        trace = result.blocks_result.blocks
        self.assertGreater(trace[14].state_after_mm, trace[13].state_after_mm)

    def test_events_outside_the_day_are_refused(self):
        pot = _basil_pot()
        with self.assertRaises(ValueError):
            pot.apply_step_blocks(_sun_profile_blocks(3.0), DAY, rainfall_l_by_hour={24: 0.1})


class TestPotBlocksFromWeather(unittest.TestCase):
    """`Pot.apply_blocks_from_weather`: dal meteo dei blocchi al vaso."""

    def test_full_weather_uses_physical_for_basil_and_accumulates_gdd(self):
        pot = _basil_pot(gdd_accumulated=0.0)
        result = pot.apply_blocks_from_weather(
            _synthetic_hourly_blocks(), DAY, longitude_deg=LON, utc_offset_hours=TZ,
        )
        self.assertEqual(result.et_method, EtMethod.PENMAN_MONTEITH_PHYSICAL)
        self.assertEqual(result.blocks_result.balance_result.et_method,
                         EtMethod.PENMAN_MONTEITH_PHYSICAL)
        self.assertGreater(pot.gdd_accumulated, 0.0)
        self.assertLess(pot.state_mm, pot.fc_mm)
        self.assertGreaterEqual(result.rs_rso_pre_sunset, 0.3)
        self.assertIsNotNone(result.nutrient_result)

    def test_a_species_without_parameters_uses_the_standard_form(self):
        species = replace(BASIL, stomatal_resistance_s_m=None, crop_height_m=None)
        pot = _basil_pot(species=species)
        result = pot.apply_blocks_from_weather(
            _synthetic_hourly_blocks(), DAY, longitude_deg=LON, utc_offset_hours=TZ,
        )
        self.assertEqual(result.et_method, EtMethod.PENMAN_MONTEITH_STANDARD)

    def test_missing_humidity_gives_the_daily_hargreaves_result(self):
        blocks = _synthetic_hourly_blocks(humidity=False)
        daily = _basil_pot()
        hourly = _basil_pot()
        daily.apply_balance_step_from_weather(weather_day_from_blocks(blocks), 0.0, DAY)
        result = hourly.apply_blocks_from_weather(
            blocks, DAY, longitude_deg=LON, utc_offset_hours=TZ,
        )
        self.assertEqual(result.et_method, EtMethod.HARGREAVES_SAMANI)
        self.assertAlmostEqual(hourly.state_mm, daily.state_mm, places=9)

    def test_blocks_of_another_day_are_refused(self):
        pot = _basil_pot()
        with self.assertRaises(ValueError):
            pot.apply_blocks_from_weather(
                _synthetic_hourly_blocks(), date(2026, 9, 15),
                longitude_deg=LON, utc_offset_hours=TZ,
            )


if __name__ == "__main__":
    unittest.main()
