"""
Test per fitosim.science.phenology (gradi-giorno).

Tre famiglie:
  1. growing_degree_days: il calcolo giornaliero, incluso il clamp a
     T_base che distingue la media semplice "modificata" da quella
     classica, e il tetto opzionale.
  2. accumulate_gdd: la somma su una serie.
  3. Validazione degli input.
"""

import unittest

from fitosim.science.phenology import accumulate_gdd, growing_degree_days


class TestGrowingDegreeDays(unittest.TestCase):
    """Calcolo giornaliero con media semplice modificata."""

    def test_simple_case(self):
        # Media (10+20)/2 = 15, meno T_base 10 -> 5 GDD.
        self.assertAlmostEqual(
            growing_degree_days(t_min=10.0, t_max=20.0, t_base=10.0), 5.0,
        )

    def test_entirely_below_base_is_zero(self):
        # Giornata interamente sotto soglia: nessuno sviluppo, ma
        # nemmeno sviluppo negativo.
        self.assertEqual(
            growing_degree_days(t_min=0.0, t_max=8.0, t_base=10.0), 0.0,
        )

    def test_cold_night_is_clamped_not_subtracted(self):
        # E' il punto del metodo "modificato": una notte a 2 gradi non
        # manda la pianta indietro. Col clamp la minima conta come
        # T_base, quindi (20+10)/2 - 10 = 5, non (20+2)/2 - 10 = 1.
        with_clamp = growing_degree_days(
            t_min=2.0, t_max=20.0, t_base=10.0,
        )
        naive = (20.0 + 2.0) / 2.0 - 10.0
        self.assertAlmostEqual(with_clamp, 5.0)
        self.assertGreater(with_clamp, naive)

    def test_cap_truncates_high_temperatures(self):
        # Col tetto a 30, una massima di 40 conta come 30:
        # (30+20)/2 - 10 = 15 invece di (40+20)/2 - 10 = 20.
        capped = growing_degree_days(
            t_min=20.0, t_max=40.0, t_base=10.0, t_cap=30.0,
        )
        uncapped = growing_degree_days(
            t_min=20.0, t_max=40.0, t_base=10.0,
        )
        self.assertAlmostEqual(capped, 15.0)
        self.assertAlmostEqual(uncapped, 20.0)
        self.assertLess(capped, uncapped)

    def test_cap_does_not_affect_mild_days(self):
        mild = growing_degree_days(
            t_min=12.0, t_max=22.0, t_base=10.0, t_cap=30.0,
        )
        self.assertAlmostEqual(mild, 7.0)

    def test_result_is_never_negative(self):
        for t_min, t_max in ((-10.0, -5.0), (-5.0, 5.0), (0.0, 9.9)):
            with self.subTest(t_min=t_min, t_max=t_max):
                self.assertGreaterEqual(
                    growing_degree_days(t_min, t_max, t_base=10.0), 0.0,
                )

    def test_higher_temperature_gives_more_gdd(self):
        cool = growing_degree_days(12.0, 22.0, 10.0)
        warm = growing_degree_days(18.0, 30.0, 10.0)
        self.assertGreater(warm, cool)

    def test_lower_base_gives_more_gdd(self):
        # Una coltura di stagione fresca (T_base bassa) accumula piu'
        # sviluppo della stessa giornata rispetto a una estiva.
        lettuce_like = growing_degree_days(10.0, 18.0, t_base=4.0)
        basil_like = growing_degree_days(10.0, 18.0, t_base=10.0)
        self.assertGreater(lettuce_like, basil_like)


class TestAccumulateGdd(unittest.TestCase):
    """Somma su una serie giornaliera."""

    def test_sums_the_series(self):
        series = [(10.0, 20.0), (12.0, 22.0), (14.0, 24.0)]
        expected = sum(
            growing_degree_days(a, b, 10.0) for a, b in series
        )
        self.assertAlmostEqual(accumulate_gdd(series, t_base=10.0), expected)

    def test_empty_series_is_zero(self):
        self.assertEqual(accumulate_gdd([], t_base=10.0), 0.0)

    def test_cold_days_do_not_reduce_the_total(self):
        warm_only = accumulate_gdd([(15.0, 25.0)], t_base=10.0)
        with_cold = accumulate_gdd(
            [(15.0, 25.0), (-2.0, 5.0)], t_base=10.0,
        )
        self.assertEqual(warm_only, with_cold)

    def test_cap_is_propagated(self):
        series = [(20.0, 40.0), (20.0, 40.0)]
        self.assertLess(
            accumulate_gdd(series, t_base=10.0, t_cap=30.0),
            accumulate_gdd(series, t_base=10.0),
        )


class TestValidation(unittest.TestCase):
    """Input incoerenti vengono rifiutati con messaggi espliciti."""

    def test_max_below_min_raises(self):
        with self.assertRaises(ValueError) as ctx:
            growing_degree_days(t_min=20.0, t_max=10.0, t_base=10.0)
        self.assertIn("t_max", str(ctx.exception))

    def test_cap_below_base_raises(self):
        with self.assertRaises(ValueError) as ctx:
            growing_degree_days(
                t_min=10.0, t_max=20.0, t_base=10.0, t_cap=5.0,
            )
        self.assertIn("t_cap", str(ctx.exception))

    def test_equal_min_max_is_valid(self):
        # Giornata isoterma: caso degenere ma legittimo.
        self.assertAlmostEqual(
            growing_degree_days(15.0, 15.0, t_base=10.0), 5.0,
        )


if __name__ == "__main__":
    unittest.main()
