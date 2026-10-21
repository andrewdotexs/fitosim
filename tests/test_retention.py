"""
La curva di ritenzione e la capacità di contenitore (`science/retention.py`,
2026-10-21, «la colonna, solo la matematica»): la forma di van Genuchten e
la sua inversione, la curva da due punti, la curva per punti, la media
sulla colonna e lo spazio d'aria.
"""

import math
import unittest

from fitosim.science.retention import (
    CM_H2O_PER_KPA,
    TabulatedCurve,
    VanGenuchten,
    air_space,
    container_capacity,
    container_capacity_by_height,
    kpa_from_tension_cm,
    mean_tension_cm,
    tension_cm_from_kpa,
    theta_profile,
)

# Una torba con vermiculite come quelle di Milks, Fonteno & Larson (1989):
# porosa, satura allo 0,85, residua 0,10, che comincia a drenare intorno ai
# cinque centimetri.
TORBA = VanGenuchten(theta_r=0.10, theta_s=0.85, alpha_per_cm=0.2, n=1.6)


class TestUnits(unittest.TestCase):
    def test_kpa_and_cm_of_water(self):
        self.assertAlmostEqual(tension_cm_from_kpa(1.0), CM_H2O_PER_KPA)
        self.assertAlmostEqual(tension_cm_from_kpa(10.0), 101.972, places=3)
        self.assertAlmostEqual(kpa_from_tension_cm(tension_cm_from_kpa(3.3)), 3.3, places=12)
        with self.assertRaises(ValueError):
            tension_cm_from_kpa(-1.0)
        self.assertEqual(mean_tension_cm(20.0), 10.0)


class TestVanGenuchten(unittest.TestCase):
    def test_saturation_residual_and_monotony(self):
        self.assertEqual(TORBA.theta_at(0.0), 0.85)
        # La coda di van Genuchten scende come (α·ψ)^(−n·m): a un milione di
        # metri manca ancora un centomillesimo alla residua.
        self.assertAlmostEqual(TORBA.theta_at(1e9), 0.10, places=4)
        self.assertAlmostEqual(TORBA.m, 1.0 - 1.0 / 1.6)
        precedente = TORBA.theta_at(0.0)
        for t in (1.0, 5.0, 10.0, 20.0, 50.0, 100.0, 1000.0):
            self.assertLess(TORBA.theta_at(t), precedente)
            precedente = TORBA.theta_at(t)

    def test_tension_at_inverts_theta_at(self):
        for t in (0.0, 2.0, 10.197, 40.0, 101.97):
            self.assertAlmostEqual(TORBA.tension_at(TORBA.theta_at(t)), t, places=6)
        self.assertEqual(TORBA.tension_at(0.9), 0.0)
        self.assertTrue(math.isinf(TORBA.tension_at(0.05)))

    def test_validation(self):
        with self.assertRaises(ValueError):
            VanGenuchten(theta_r=0.5, theta_s=0.4, alpha_per_cm=0.1, n=1.5)
        with self.assertRaises(ValueError):
            VanGenuchten(theta_r=0.1, theta_s=0.8, alpha_per_cm=0.0, n=1.5)
        with self.assertRaises(ValueError):
            VanGenuchten(theta_r=0.1, theta_s=0.8, alpha_per_cm=0.1, n=1.0)
        with self.assertRaises(ValueError):
            TORBA.theta_at(-1.0)

    def test_from_points_recovers_the_curve(self):
        # Dai due punti del catalogo (−1 e −10 kPa) con θ_s e θ_r note si
        # torna alla stessa curva: α e n al milionesimo.
        bagnato = (tension_cm_from_kpa(1.0), TORBA.theta_at(tension_cm_from_kpa(1.0)))
        asciutto = (tension_cm_from_kpa(10.0), TORBA.theta_at(tension_cm_from_kpa(10.0)))
        ricavata = VanGenuchten.from_points(
            theta_s=0.85, theta_r=0.10, wet=bagnato, dry=asciutto
        )
        self.assertAlmostEqual(ricavata.alpha_per_cm, 0.2, places=6)
        self.assertAlmostEqual(ricavata.n, 1.6, places=6)
        for t in (0.0, 3.0, 10.197, 30.0, 101.97, 300.0):
            self.assertAlmostEqual(ricavata.theta_at(t), TORBA.theta_at(t), places=6)

    def test_from_catalog_uses_the_two_substrate_points(self):
        fc = TORBA.theta_at(tension_cm_from_kpa(1.0))
        pwp = TORBA.theta_at(tension_cm_from_kpa(10.0))
        dal_catalogo = VanGenuchten.from_catalog(fc, pwp, theta_s=0.85, theta_r=0.10)
        self.assertAlmostEqual(dal_catalogo.theta_at(tension_cm_from_kpa(1.0)), fc, places=9)
        self.assertAlmostEqual(dal_catalogo.theta_at(tension_cm_from_kpa(10.0)), pwp, places=9)
        # Senza il punto a −1500 kPa la residua prudente è zero.
        prudente = VanGenuchten.from_catalog(fc, pwp, theta_s=0.85)
        self.assertEqual(prudente.theta_r, 0.0)
        self.assertAlmostEqual(prudente.theta_at(tension_cm_from_kpa(1.0)), fc, places=9)

    def test_from_points_rejects_inconsistent_points(self):
        with self.assertRaises(ValueError):
            VanGenuchten.from_points(theta_s=0.85, theta_r=0.1, wet=(10.0, 0.5), dry=(100.0, 0.6))
        with self.assertRaises(ValueError):
            VanGenuchten.from_points(theta_s=0.85, theta_r=0.1, wet=(100.0, 0.6), dry=(10.0, 0.5))
        with self.assertRaises(ValueError):
            VanGenuchten.from_points(theta_s=0.5, theta_r=0.1, wet=(10.0, 0.6), dry=(100.0, 0.3))


class TestTabulatedCurve(unittest.TestCase):
    def test_interpolation_linear_then_logarithmic_then_flat(self):
        curva = TabulatedCurve(((0.0, 0.80), (10.0, 0.60), (100.0, 0.30)))
        self.assertEqual(curva.theta_s, 0.80)
        self.assertAlmostEqual(curva.theta_at(5.0), 0.70)
        # Fra 10 e 100 cm si va dritti nel logaritmo: a 31,6 cm si è a metà.
        self.assertAlmostEqual(curva.theta_at(math.sqrt(10.0 * 100.0)), 0.45, places=9)
        self.assertEqual(curva.theta_at(100.0), 0.30)
        self.assertEqual(curva.theta_at(1000.0), 0.30)

    def test_validation(self):
        with self.assertRaises(ValueError):
            TabulatedCurve(((0.0, 0.8),))
        with self.assertRaises(ValueError):
            TabulatedCurve(((5.0, 0.8), (10.0, 0.6)))
        with self.assertRaises(ValueError):
            TabulatedCurve(((0.0, 0.8), (10.0, 0.9)))
        with self.assertRaises(ValueError):
            TabulatedCurve(((0.0, 0.8), (10.0, 0.6), (10.0, 0.5)))


class TestContainerCapacity(unittest.TestCase):
    def test_a_flat_curve_gives_its_own_theta(self):
        piatta = TabulatedCurve(((0.0, 0.5), (1000.0, 0.5)))
        self.assertAlmostEqual(container_capacity(piatta, 20.0), 0.5, places=12)
        self.assertAlmostEqual(air_space(piatta, 20.0), 0.0, places=12)

    def test_a_linear_curve_integrates_exactly(self):
        # θ = 0,8 − 0,01·z: la media su venti centimetri è 0,8 − 0,1.
        lineare = TabulatedCurve(((0.0, 0.8), (50.0, 0.3)))
        self.assertAlmostEqual(container_capacity(lineare, 20.0), 0.7, places=12)
        self.assertAlmostEqual(container_capacity(lineare, 20.0, intervals=2), 0.7, places=12)

    def test_the_column_dries_with_height(self):
        tabella = container_capacity_by_height(TORBA, (5.0, 13.0, 20.0, 30.0))
        valori = [theta for _h, theta in tabella]
        self.assertEqual(valori, sorted(valori, reverse=True))
        # Verso zero la colonna è satura; la cassetta da 13 sta più bagnata
        # del vaso da 20, che sta più bagnato di quello da 30.
        self.assertAlmostEqual(container_capacity(TORBA, 1e-6), 0.85, places=6)
        self.assertGreater(valori[1] - valori[2], 0.01)
        self.assertGreater(valori[2] - valori[3], 0.01)
        for _h, theta in tabella:
            self.assertGreater(theta, TORBA.theta_at(_h))
            self.assertLess(theta, 0.85)

    def test_air_space_is_the_complement(self):
        for h in (10.0, 20.0, 30.0):
            self.assertAlmostEqual(
                air_space(TORBA, h) + container_capacity(TORBA, h), 0.85, places=12
            )
        self.assertLess(air_space(TORBA, 10.0), air_space(TORBA, 30.0))

    def test_the_profile_runs_from_the_saturated_bottom_to_the_top(self):
        profilo = theta_profile(TORBA, 20.0, steps=4)
        self.assertEqual(len(profilo), 5)
        self.assertEqual(profilo[0], (0.0, 0.85))
        self.assertAlmostEqual(profilo[-1][0], 20.0)
        self.assertAlmostEqual(profilo[-1][1], TORBA.theta_at(20.0))
        quote = [z for z, _ in profilo]
        self.assertEqual(quote, sorted(quote))

    def test_the_default_grid_is_fine_enough(self):
        # Il gomito della curva sta nei primi centimetri: con duecento
        # intervalli su venti centimetri l'errore è sotto il decimilionesimo.
        fine = container_capacity(TORBA, 20.0, intervals=4000)
        self.assertAlmostEqual(container_capacity(TORBA, 20.0), fine, places=6)

    def test_validation(self):
        with self.assertRaises(ValueError):
            container_capacity(TORBA, 0.0)
        with self.assertRaises(ValueError):
            container_capacity(TORBA, 20.0, intervals=3)
        with self.assertRaises(ValueError):
            theta_profile(TORBA, 20.0, steps=0)
        with self.assertRaises(ValueError):
            mean_tension_cm(-1.0)


if __name__ == "__main__":
    unittest.main()
