"""
La luce nel modello (docs/proposta_luce.md, L1 e L2; 2026-11-24).

  1. **Il modulo** `science/light`: la conversione dalla radiazione al
     DLI, il DLI al vaso, le classi di Purdue, il giudizio.
  2. **Il fattore** `nutrients.light_factor` e `daily_uptake`.
  3. **Il vaso**: senza il fabbisogno della specie o senza il DLI del
     giorno niente cambia; con tutti e due la pianta mangia in
     proporzione, quello che non mangia resta come sale, e il passo
     indoor col sole vero il DLI se lo calcola da solo.
"""

import unittest
from dataclasses import replace
from datetime import date

from fitosim.domain.blocks import BalanceBlock
from fitosim.domain.pot import Location, Pot
from fitosim.domain.room import IndoorMicroclimate, LightExposure, MicroclimateKind
from fitosim.domain.species import Species, light_requirement_of
from fitosim.science.indoor import light_fraction
from fitosim.science.light import (
    LIGHT_CLASS_DLI_RANGE,
    LUX_PER_UMOL_DAYLIGHT,
    PAR_MOL_PER_MJ,
    LightClass,
    LightRequirement,
    LightSufficiency,
    dli_at_pot,
    dli_from_illuminance,
    dli_from_shortwave,
    light_class_of,
    light_sufficiency,
    shortwave_from_illuminance,
)
from fitosim.science.nutrients import (
    UPTAKE_LIGHT_FLOOR,
    NutrientAmounts,
    daily_uptake,
    light_factor,
)
from fitosim.science.substrate import Substrate

JUNE = date(2026, 6, 15)
SEASON = (100.0, 40.0, 80.0)
PLAN = tuple(SEASON for _ in range(12))


def _species(**overrides) -> Species:
    defaults = dict(
        common_name="media", scientific_name="Planta media",
        kc_initial=0.6, kc_mid=1.0, kc_late=0.8,
        kcb_initial=0.5, kcb_mid=0.95, kcb_late=0.7,
        ec_optimal_min_mscm=0.8, ec_optimal_max_mscm=1.6,
        ph_optimal_min=5.8, ph_optimal_max=7.0,
        nutrient_targets_mg_per_l=PLAN, nutrient_feed_fraction=1.0,
    )
    defaults.update(overrides)
    return Species(**defaults)


def _pot(species: Species, **overrides) -> Pot:
    defaults = dict(
        species=species,
        substrate=Substrate(
            name="universale", theta_fc=0.40, theta_pwp=0.10,
            cec_meq_per_100g=50.0, ph_typical=6.5,
        ),
        pot_volume_l=4.0, pot_diameter_cm=20.0, location=Location.OUTDOOR,
        planting_date=date(2025, 4, 1), salt_mass_meq=0.0, ph_substrate=6.5,
    )
    defaults.update(overrides)
    pot = Pot(label="vaso", **defaults)
    pot.state_mm = pot.fc_mm
    # Un vaso appena concimato: un litro e mezzo della soluzione del piano.
    pot.apply_fertigation_step(
        volume_l=1.5, ec_mscm=1.5, ph=6.5, current_date=JUNE,
        nutrients_mg_per_l=NutrientAmounts(*SEASON),
    )
    return pot


class TestConversion(unittest.TestCase):
    """Dalla radiazione globale al DLI."""

    def test_the_factor_is_the_product_of_its_two_sources(self):
        self.assertAlmostEqual(PAR_MOL_PER_MJ, 0.45 * 4.48)
        self.assertAlmostEqual(PAR_MOL_PER_MJ, 2.016)
        # 0,007265 mol per Wh, come lo scrivono le mappe (1 MJ = 277,78 Wh):
        # i due numeri arrotondati lo ridanno alla terza cifra.
        self.assertAlmostEqual(PAR_MOL_PER_MJ / 277.778, 0.007265, places=4)

    def test_a_summer_day_and_a_winter_day_in_milan(self):
        # Giugno e dicembre 2025 a Milano: 23,7 e 3,8 MJ/m²/giorno.
        self.assertAlmostEqual(dli_from_shortwave(23.7), 47.8, places=1)
        self.assertAlmostEqual(dli_from_shortwave(3.8), 7.7, places=1)
        self.assertEqual(dli_from_shortwave(0.0), 0.0)

    def test_negative_radiation_is_refused(self):
        with self.assertRaises(ValueError):
            dli_from_shortwave(-0.1)

    def test_the_pot_receives_a_fraction(self):
        self.assertAlmostEqual(dli_at_pot(20.0, 0.15), 20.0 * PAR_MOL_PER_MJ * 0.15)
        self.assertEqual(dli_at_pot(20.0, 0.0), 0.0)
        self.assertAlmostEqual(dli_at_pot(20.0, 1.0), dli_from_shortwave(20.0))
        for wrong in (-0.1, 1.1):
            with self.assertRaises(ValueError):
                dli_at_pot(20.0, wrong)

    def test_the_indoor_fractions_are_those_of_the_radiation(self):
        self.assertEqual(light_fraction(LightExposure.DIRECT_SUN), 0.40)
        self.assertEqual(light_fraction(LightExposure.INDIRECT_BRIGHT), 0.15)
        self.assertEqual(light_fraction(LightExposure.DARK), 0.05)


class TestIlluminance(unittest.TestCase):
    """Dal lux di un sensore di luce ambiente ai fotoni e all'energia."""

    def test_the_daylight_factor_is_that_of_the_source(self):
        # Purdue HO-238-W, tabella 1: 0,20 µmol/m²/s per foot-candle di
        # luce solare, e un foot-candle sono 10,764 lux.
        self.assertAlmostEqual(LUX_PER_UMOL_DAYLIGHT, 10.764 / 0.20, places=1)

    def test_the_chain_gives_the_luminous_efficacy_of_daylight(self):
        # 1 W/m² di globale → µmol/m²/s di PAR → lux: l'efficacia luminosa
        # che ne esce sta fra i 105 e i 110 lm/W di Littlefair.
        efficacy = PAR_MOL_PER_MJ * LUX_PER_UMOL_DAYLIGHT
        self.assertAlmostEqual(efficacy, 108.5, places=1)
        self.assertTrue(105.0 <= efficacy <= 110.0)

    def test_a_thousand_lux_hours(self):
        self.assertAlmostEqual(dli_from_illuminance(1000.0), 0.0669, places=4)
        self.assertAlmostEqual(shortwave_from_illuminance(1000.0), 0.0332, places=4)
        self.assertEqual(dli_from_illuminance(0.0), 0.0)

    def test_energy_and_photons_agree(self):
        # La stessa luce, per le due strade: dal lux al DLI, o dal lux
        # all'energia e dall'energia al DLI.
        lux_hours = 42_000.0
        self.assertAlmostEqual(
            dli_from_shortwave(shortwave_from_illuminance(lux_hours)),
            dli_from_illuminance(lux_hours),
        )
        # Un megajoule di globale sono trenta kilolux·ora.
        self.assertAlmostEqual(shortwave_from_illuminance(30_133.0), 1.0, places=3)

    def test_another_source_has_its_own_factor(self):
        # Sotto lampade al sodio (0,13 µmol per foot-candle): meno fotoni per lux.
        sodium = dli_from_illuminance(1000.0, lux_per_umol=10.764 / 0.13)
        self.assertLess(sodium, dli_from_illuminance(1000.0))
        self.assertAlmostEqual(sodium / dli_from_illuminance(1000.0), 0.13 / 0.20, places=3)

    def test_wrong_numbers_are_refused(self):
        for function in (dli_from_illuminance, shortwave_from_illuminance):
            with self.assertRaises(ValueError):
                function(-1.0)
            with self.assertRaises(ValueError):
                function(1000.0, lux_per_umol=0.0)


class TestClasses(unittest.TestCase):
    """Le quattro classi di coltura di Purdue HO-238-W."""

    def test_the_ranges_are_those_of_the_source(self):
        self.assertEqual(LIGHT_CLASS_DLI_RANGE[LightClass.LOW], (3.0, 6.0))
        self.assertEqual(LIGHT_CLASS_DLI_RANGE[LightClass.MEDIUM], (6.0, 12.0))
        self.assertEqual(LIGHT_CLASS_DLI_RANGE[LightClass.HIGH], (12.0, 18.0))
        self.assertEqual(LIGHT_CLASS_DLI_RANGE[LightClass.VERY_HIGH], (18.0, None))

    def test_a_dli_falls_in_its_class(self):
        self.assertIsNone(light_class_of(0.0))
        self.assertIsNone(light_class_of(2.9))
        self.assertIs(light_class_of(3.0), LightClass.LOW)
        self.assertIs(light_class_of(5.9), LightClass.LOW)
        self.assertIs(light_class_of(6.0), LightClass.MEDIUM)
        self.assertIs(light_class_of(12.0), LightClass.HIGH)
        self.assertIs(light_class_of(18.0), LightClass.VERY_HIGH)
        self.assertIs(light_class_of(60.0), LightClass.VERY_HIGH)
        with self.assertRaises(ValueError):
            light_class_of(-1.0)


class TestRequirement(unittest.TestCase):
    """Quello che la specie vuole, e il giudizio."""

    def test_the_numbers_must_be_in_order(self):
        LightRequirement(4.0)
        LightRequirement(4.0, 2.0, 6.0)
        LightRequirement(4.0, 4.0, 4.0)
        for wrong in (
            dict(dli_good=0.0),
            dict(dli_good=-1.0),
            dict(dli_good=4.0, dli_minimum=5.0),
            dict(dli_good=4.0, dli_minimum=0.0),
            dict(dli_good=4.0, dli_high=3.0),
        ):
            with self.assertRaises(ValueError):
                LightRequirement(**wrong)

    def test_the_judgement_with_all_three_thresholds(self):
        # Lo Spathiphyllum della tabella 2: 2 / 4 / 6.
        wants = LightRequirement(4.0, 2.0, 6.0)
        self.assertIs(light_sufficiency(1.1, wants), LightSufficiency.BELOW_MINIMUM)
        self.assertIs(light_sufficiency(2.0, wants), LightSufficiency.BELOW_GOOD)
        self.assertIs(light_sufficiency(3.9, wants), LightSufficiency.BELOW_GOOD)
        self.assertIs(light_sufficiency(4.0, wants), LightSufficiency.GOOD)
        self.assertIs(light_sufficiency(6.0, wants), LightSufficiency.HIGH)
        with self.assertRaises(ValueError):
            light_sufficiency(-1.0, wants)

    def test_without_a_minimum_low_light_is_only_below_good(self):
        wants = LightRequirement(12.0)
        self.assertIs(light_sufficiency(0.2, wants), LightSufficiency.BELOW_GOOD)
        self.assertIs(light_sufficiency(40.0, wants), LightSufficiency.GOOD)

    def test_the_species_declares_it_or_not(self):
        self.assertIsNone(light_requirement_of(_species()))
        wants = light_requirement_of(
            _species(dli_good_mol_m2_day=6.0, dli_minimum_mol_m2_day=4.0)
        )
        self.assertEqual(wants, LightRequirement(6.0, 4.0))

    def test_the_species_validates_its_light(self):
        with self.assertRaises(ValueError):
            _species(dli_minimum_mol_m2_day=4.0)
        with self.assertRaises(ValueError):
            _species(dli_good_mol_m2_day=4.0, dli_minimum_mol_m2_day=6.0)
        with self.assertRaises(ValueError):
            _species(dli_good_mol_m2_day=0.0)


class TestLightFactor(unittest.TestCase):
    """Il fattore di luce sull'assorbimento."""

    def test_without_light_or_without_requirement_it_is_one(self):
        self.assertEqual(light_factor(None, 12.0), 1.0)
        self.assertEqual(light_factor(3.0, None), 1.0)
        self.assertEqual(light_factor(None, None), 1.0)

    def test_it_is_proportional_up_to_the_good_dli(self):
        self.assertAlmostEqual(light_factor(3.0, 12.0), 0.25)
        self.assertAlmostEqual(light_factor(6.0, 12.0), 0.5)
        self.assertEqual(light_factor(12.0, 12.0), 1.0)
        self.assertEqual(light_factor(45.0, 12.0), 1.0)

    def test_it_has_a_floor(self):
        self.assertEqual(light_factor(0.0, 12.0), UPTAKE_LIGHT_FLOOR)
        self.assertEqual(light_factor(0.4, 12.0), UPTAKE_LIGHT_FLOOR)
        self.assertEqual(UPTAKE_LIGHT_FLOOR, 0.1)

    def test_wrong_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            light_factor(-1.0, 12.0)
        with self.assertRaises(ValueError):
            light_factor(3.0, 0.0)

    def test_the_uptake_scales_with_it(self):
        targets = NutrientAmounts(*SEASON)
        full = daily_uptake(0.2, targets)
        half = daily_uptake(0.2, targets, light_factor=0.5)
        self.assertAlmostEqual(half.n_mg, full.n_mg * 0.5)
        self.assertAlmostEqual(half.k_mg, full.k_mg * 0.5)
        # Col freddo e la frazione di alimentazione si moltiplica.
        cold = daily_uptake(0.2, targets, feed_fraction=0.5, t_mean_c=5.0, light_factor=0.5)
        self.assertAlmostEqual(cold.n_mg, 0.2 * 100.0 * 0.5 * 0.1 * 0.5)
        for wrong in (-0.1, 1.1):
            with self.assertRaises(ValueError):
                daily_uptake(0.2, targets, light_factor=wrong)


class TestPot(unittest.TestCase):
    """La luce dentro i passi del vaso."""

    def test_without_the_species_requirement_nothing_changes(self):
        dark, plain = _pot(_species()), _pot(_species())
        dark.apply_step(et_0_mm=4.0, current_date=JUNE, dli_mol_m2_day=0.5)
        plain.apply_step(et_0_mm=4.0, current_date=JUNE)
        self.assertEqual(dark.last_nutrient_step.uptake, plain.last_nutrient_step.uptake)
        self.assertEqual(dark.salt_mass_meq, plain.salt_mass_meq)
        self.assertEqual(dark.state_mm, plain.state_mm)
        self.assertEqual(dark.last_nutrient_step.light_factor, 1.0)
        self.assertEqual(dark.last_nutrient_step.dli_mol_m2_day, 0.5)
        self.assertIsNone(plain.last_nutrient_step.dli_mol_m2_day)

    def test_without_the_day_dli_nothing_changes(self):
        wants = _pot(_species(dli_good_mol_m2_day=12.0))
        plain = _pot(_species())
        wants.apply_step(et_0_mm=4.0, current_date=JUNE)
        plain.apply_step(et_0_mm=4.0, current_date=JUNE)
        self.assertEqual(wants.last_nutrient_step.uptake, plain.last_nutrient_step.uptake)
        self.assertEqual(wants.last_nutrient_step.light_factor, 1.0)

    def test_in_low_light_the_plant_eats_in_proportion(self):
        species = _species(dli_good_mol_m2_day=12.0)
        lit, dim = _pot(species), _pot(species)
        salts_before = dim.salt_mass_meq
        lit.apply_step(et_0_mm=4.0, current_date=JUNE, dli_mol_m2_day=20.0)
        dim.apply_step(et_0_mm=4.0, current_date=JUNE, dli_mol_m2_day=3.0)
        full, quarter = lit.last_nutrient_step, dim.last_nutrient_step
        self.assertEqual(full.light_factor, 1.0)
        self.assertAlmostEqual(quarter.light_factor, 0.25)
        self.assertGreater(full.uptake.n_mg, 0.0)
        self.assertAlmostEqual(quarter.uptake.n_mg, full.uptake.n_mg * 0.25)
        # L'acqua non lo sa: la luce come energia sta nell'ET₀.
        self.assertEqual(lit.state_mm, dim.state_mm)
        self.assertEqual(full.transpiration_l, quarter.transpiration_l)
        # Quello che non ha mangiato resta nel vaso come sale.
        self.assertGreater(dim.salt_mass_meq, lit.salt_mass_meq)
        self.assertAlmostEqual(
            salts_before - dim.salt_mass_meq, quarter.uptake.total_meq,
        )

    def test_the_block_day_carries_the_light_too(self):
        species = _species(dli_good_mol_m2_day=12.0)
        day, blocks = _pot(species), _pot(species)
        day.apply_step(et_0_mm=4.0, current_date=JUNE, dli_mol_m2_day=3.0)
        blocks.apply_step_blocks(
            [BalanceBlock(start_hour=0, hours=24, et_0_mm=4.0)], JUNE, dli_mol_m2_day=3.0,
        )
        self.assertAlmostEqual(blocks.last_nutrient_step.light_factor, 0.25)
        self.assertAlmostEqual(
            blocks.last_nutrient_step.uptake.n_mg, day.last_nutrient_step.uptake.n_mg,
        )
        only_water = _pot(species)
        only_water.apply_balance_blocks(
            [BalanceBlock(start_hour=0, hours=24, et_0_mm=4.0)], JUNE, dli_mol_m2_day=3.0,
        )
        self.assertAlmostEqual(only_water.last_nutrient_step.light_factor, 0.25)

    def test_the_dli_at_the_pot(self):
        species = _species(dli_good_mol_m2_day=6.0, dli_minimum_mol_m2_day=4.0)
        indoors = _pot(
            species, location=Location.INDOOR, light_exposure=LightExposure.INDIRECT_BRIGHT,
        )
        outdoors = _pot(species)
        self.assertAlmostEqual(indoors.dli_at_pot(20.0), 20.0 * PAR_MOL_PER_MJ * 0.15)
        # All'aperto una frazione di luce per esposizione non c'è.
        self.assertIsNone(outdoors.dli_at_pot(20.0))
        # Una frazione misurata vale dovunque, e vince su quella della stanza.
        self.assertAlmostEqual(outdoors.dli_at_pot(20.0, 0.5), 20.0 * PAR_MOL_PER_MJ * 0.5)
        self.assertAlmostEqual(indoors.dli_at_pot(20.0, 0.3), 20.0 * PAR_MOL_PER_MJ * 0.3)
        self.assertIs(indoors.light_sufficiency(1.1), LightSufficiency.BELOW_MINIMUM)
        self.assertIs(indoors.light_sufficiency(7.2), LightSufficiency.GOOD)
        self.assertIsNone(_pot(_species()).light_sufficiency(7.2))

    def test_the_indoor_step_computes_it_only_with_the_real_sun(self):
        species = _species(dli_good_mol_m2_day=6.0)
        room = IndoorMicroclimate(
            kind=MicroclimateKind.DAILY, temperature_c=21.0, humidity_relative=0.5,
            t_min=19.0, t_max=23.0,
        )
        winter = _pot(
            species, location=Location.INDOOR, light_exposure=LightExposure.INDIRECT_BRIGHT,
        )
        # Dicembre a Milano: 3,8 MJ/m² fuori, 1,1 mol/m² al vaso.
        winter.apply_balance_step_from_indoor(
            room, 0.0, JUNE, outdoor_solar_radiation_mj_m2_day=3.8,
        )
        step = winter.last_nutrient_step
        self.assertAlmostEqual(step.dli_mol_m2_day, 3.8 * PAR_MOL_PER_MJ * 0.15)
        self.assertAlmostEqual(step.light_factor, 3.8 * PAR_MOL_PER_MJ * 0.15 / 6.0)
        # Senza la radiazione di fuori la stanza usa il numero fisso, e
        # il DLI non si dà: il fattore resta 1.
        fixed = _pot(
            species, location=Location.INDOOR, light_exposure=LightExposure.INDIRECT_BRIGHT,
        )
        fixed.apply_balance_step_from_indoor(room, 0.0, JUNE)
        self.assertIsNone(fixed.last_nutrient_step.dli_mol_m2_day)
        self.assertEqual(fixed.last_nutrient_step.light_factor, 1.0)

    def test_replacing_the_species_light_keeps_the_rest(self):
        plain = _species()
        wants = replace(plain, dli_good_mol_m2_day=12.0)
        self.assertEqual(wants.nutrient_targets_mg_per_l, plain.nutrient_targets_mg_per_l)
        self.assertEqual(wants.dli_good_mol_m2_day, 12.0)


if __name__ == "__main__":
    unittest.main()
