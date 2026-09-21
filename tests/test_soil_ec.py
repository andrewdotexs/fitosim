"""
Test della sonda EC (science/soil_ec.py e Pot.update_from_ec_sensor).

  1. **Topp e la sua inversa**: la cubica torna su se stessa, e i due
     estremi si fermano ai bordi fisici.
  2. **Hilhorst**: a parità di sali un substrato più bagnato legge di più
     — quindi dalla stessa lettura apparente si deduce meno soluzione —;
     l'acqua più calda ha permittività minore; il fattore scala; un
     substrato troppo asciutto non dice niente; i numeri di riferimento
     (θ 0,35 → ε ≈ 20 → σ_p/σ_b ≈ 5).
  3. **La taratura a capacità di campo**: il fattore che fa combaciare
     Hilhorst con la soluzione nota, e che poi torna quella soluzione.
  4. **Il vaso**: una lettura sposta la massa salina all'EC della
     soluzione dedotta, i serbatoi nutritivi la seguono in proporzione e
     restano dentro i sali, il θ misurato vince su quello del vaso, e un
     vaso asciutto non si tocca.
"""

import unittest
from datetime import date

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import Species
from fitosim.science.nutrients import NutrientAmounts
from fitosim.science.soil_ec import (
    EPSILON_OFFSET,
    factor_at_field_capacity,
    permittivity_from_theta,
    pore_water_ec,
    theta_from_permittivity,
    water_permittivity,
)
from fitosim.science.substrate import Substrate

PLAN = tuple((100.0, 40.0, 80.0) for _ in range(12))


def _pot(**overrides) -> Pot:
    defaults = dict(
        species=Species(
            common_name="media", scientific_name="Planta media",
            kc_initial=0.6, kc_mid=1.0, kc_late=0.8,
            ec_optimal_min_mscm=0.8, ec_optimal_max_mscm=1.6,
            ph_optimal_min=5.8, ph_optimal_max=7.0,
            nutrient_targets_mg_per_l=PLAN,
        ),
        substrate=Substrate(
            name="universale", theta_fc=0.40, theta_pwp=0.10,
            cec_meq_per_100g=50.0, ph_typical=6.5,
        ),
        pot_volume_l=4.0,
        pot_diameter_cm=20.0,
        location=Location.OUTDOOR,
        planting_date=date(2025, 4, 1),
        salt_mass_meq=0.0,
        ph_substrate=6.5,
    )
    defaults.update(overrides)
    pot = Pot(label="vaso", **defaults)
    pot.state_mm = pot.fc_mm
    return pot


class TestTopp(unittest.TestCase):

    def test_inverse_round_trips(self):
        for eps in (3.0, 10.0, 20.0, 40.0):
            theta = theta_from_permittivity(eps)
            self.assertAlmostEqual(permittivity_from_theta(theta), eps, places=6)

    def test_reference_point_and_bounds(self):
        # Il punto di riferimento: θ ≈ 0,35 a ε ≈ 20.
        self.assertAlmostEqual(theta_from_permittivity(20.0), 0.3454, places=3)
        # lo zero di Topp sta a ε ≈ 1,9; sotto, il bordo dell'aria
        self.assertAlmostEqual(permittivity_from_theta(0.0), 1.88, places=1)
        self.assertEqual(permittivity_from_theta(1.0), 80.0)
        with self.assertRaises(ValueError):
            permittivity_from_theta(-0.1)


class TestHilhorst(unittest.TestCase):

    def test_reference_ratio_at_field_capacity(self):
        # A θ 0,35: ε_b ≈ 20, σ_p/σ_b = ε_p/(20 − 4,1) ≈ 4,9 a 25 °C.
        ratio = pore_water_ec(1.0, 0.35)
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(ratio, water_permittivity(25.0) / (20.11 - EPSILON_OFFSET), delta=0.15)
        self.assertGreater(ratio, 4.5)
        self.assertLess(ratio, 5.5)

    def test_wetter_reads_more_so_the_same_reading_means_less_solution(self):
        dry = pore_water_ec(0.3, 0.20)
        wet = pore_water_ec(0.3, 0.40)
        self.assertIsNotNone(dry)
        self.assertIsNotNone(wet)
        self.assertGreater(dry, wet)

    def test_temperature_factor_and_dryness(self):
        cold = pore_water_ec(0.3, 0.35, temperature_c=10.0)
        warm = pore_water_ec(0.3, 0.35, temperature_c=30.0)
        self.assertGreater(cold, warm)
        self.assertAlmostEqual(pore_water_ec(0.3, 0.35, factor=2.0), 2 * pore_water_ec(0.3, 0.35))
        self.assertIsNone(pore_water_ec(0.3, 0.02), "troppo asciutto: la corrente non passa")
        with self.assertRaises(ValueError):
            pore_water_ec(-0.1, 0.3)
        with self.assertRaises(ValueError):
            pore_water_ec(0.3, 0.3, factor=0.0)


class TestCalibration(unittest.TestCase):

    def test_the_factor_makes_the_known_solution_come_back(self):
        factor = factor_at_field_capacity(bulk_ec_mscm=0.3, theta=0.40, solution_ec_mscm=1.2)
        self.assertIsNotNone(factor)
        self.assertAlmostEqual(pore_water_ec(0.3, 0.40, factor=factor), 1.2)
        self.assertIsNone(factor_at_field_capacity(bulk_ec_mscm=0.3, theta=0.02, solution_ec_mscm=1.2))
        with self.assertRaises(ValueError):
            factor_at_field_capacity(bulk_ec_mscm=0.3, theta=0.4, solution_ec_mscm=0.0)


class TestPotEcUpdate(unittest.TestCase):

    def test_a_reading_moves_the_salts_and_the_pools_follow(self):
        pot = _pot(salt_mass_meq=10.0, nutrient_n_mg=70.0, nutrient_k_mg=47.0)
        # a capacità di campo la sonda legge 0,3 apparente: Hilhorst dice
        # ~1,5 di soluzione, cioè più del modello (10 meq → EC bassa)
        result = pot.update_from_ec_sensor(0.3)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.theta, pot.state_theta)
        self.assertAlmostEqual(pot.ec_substrate_mscm, result.observed_solution_ec_mscm, places=6)
        self.assertAlmostEqual(result.salt_mass_before_meq, 10.0)
        self.assertGreater(result.ratio, 1.0)
        self.assertAlmostEqual(pot.nutrient_n_mg, 70.0 * result.ratio, places=6)
        self.assertLessEqual(pot.nutrient_pools.total_meq, pot.salt_mass_meq + 1e-9)
        self.assertGreater(result.discrepancy_mscm, 0.0)

    def test_the_factor_scales_and_the_measured_theta_wins(self):
        plain = _pot(salt_mass_meq=10.0)
        doubled = _pot(salt_mass_meq=10.0, ec_sensor_factor=2.0)
        a = plain.update_from_ec_sensor(0.3)
        b = doubled.update_from_ec_sensor(0.3)
        self.assertAlmostEqual(b.observed_solution_ec_mscm, 2 * a.observed_solution_ec_mscm)
        with_theta = _pot(salt_mass_meq=10.0)
        c = with_theta.update_from_ec_sensor(0.3, theta=0.25)
        self.assertEqual(c.theta, 0.25)
        self.assertGreater(c.observed_solution_ec_mscm, a.observed_solution_ec_mscm)

    def test_a_dry_pot_or_a_dry_reading_is_not_touched(self):
        pot = _pot(salt_mass_meq=10.0)
        pot.state_mm = 0.0
        self.assertIsNone(pot.update_from_ec_sensor(0.3, theta=0.35))
        self.assertAlmostEqual(pot.salt_mass_meq, 10.0)
        wet = _pot(salt_mass_meq=10.0)
        self.assertIsNone(wet.update_from_ec_sensor(0.3, theta=0.02))
        with self.assertRaises(ValueError):
            _pot(ec_sensor_factor=0.0)

    def test_from_zero_salts_the_pools_stay_and_stay_coherent(self):
        pot = _pot(salt_mass_meq=0.0)
        result = pot.update_from_ec_sensor(0.3)
        self.assertEqual(result.ratio, 1.0)
        self.assertGreater(pot.salt_mass_meq, 0.0)
        self.assertEqual(pot.nutrient_pools, NutrientAmounts())


if __name__ == "__main__":
    unittest.main()
