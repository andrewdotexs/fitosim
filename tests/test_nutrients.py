"""
Test del colore dei sali (science/nutrients.py e i serbatoi del Pot).

Strategia di test
-----------------

  1. **Le funzioni pure**: le quantità e la loro scala in
     milliequivalenti, il cancello della temperatura, l'assorbimento
     (proporzionale alla traspirazione e alla frazione di
     alimentazione, mai oltre il disponibile), il dilavamento (il
     nitrato di più), la riserva (il serbatoio più vuoto fra quelli col
     bersaglio), la coerenza coi sali, i rilasci per classe.

  2. **Il vaso**: una fertirrigazione riempie i serbatoi con
     l'etichetta e il drenaggio li svuota nella proporzione dei sali;
     l'acqua e la pioggia dilavano senza portare niente; il passo
     giornaliero toglie alla traspirazione, e toglie anche dai sali; il
     freddo chiude il cancello; una specie senza piano non mangia; la
     carica iniziale; l'allerta col *quale* e i giorni.

  3. **Il bilancio annuale** (nutrizione-spec di The Pot, §4): un anno
     simulato di un vaso di profilo medio concimato secondo il suo piano
     — un liquido ogni quattordici giorni alla concentrazione del mese,
     l'acqua quando serve — finisce l'anno con la riserva dove l'ha
     iniziata: la pianta ha mangiato quasi tutto quello che le è stato
     dato (il resto l'ha portato via la pioggia), la riserva oscilla fra
     una concimazione e l'altra senza accumulare. E chi mangia meno di
     quel che riceve accumula: la direzione del modello.
"""

import math
import unittest
from datetime import date, timedelta

from fitosim.domain.alerts import (
    NUTRIENT_RESERVE_INFO_FRACTION,
    AlertCategory,
    AlertSeverity,
    check_nutrient_low,
)
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import Species
from fitosim.science.nutrients import (
    FULL_CHARGE_FRACTION,
    MG_PER_MEQ,
    NITRATE_LEACHING_BONUS,
    UPTAKE_COLD_FLOOR,
    ZERO,
    NutrientAmounts,
    ReleaseClass,
    clamp_to_salts,
    daily_release_fraction,
    daily_uptake,
    full_charge_mg,
    leached,
    reserve,
    temperature_gate,
)
from fitosim.science.substrate import Substrate

# Il piano di un profilo medio: 100/40/80 mg/L da marzo a ottobre, niente
# d'inverno. Le stesse tre cifre per tutti i mesi di stagione, così i
# test non dipendono dal giorno.
SEASON = (100.0, 40.0, 80.0)
PLAN = tuple(SEASON if 3 <= m <= 10 else (0.0, 0.0, 0.0) for m in range(1, 13))


def _species(**overrides) -> Species:
    defaults = dict(
        common_name="media",
        scientific_name="Planta media",
        kc_initial=0.6, kc_mid=1.0, kc_late=0.8,
        kcb_initial=0.5, kcb_mid=0.95, kcb_late=0.7,
        ec_optimal_min_mscm=0.8, ec_optimal_max_mscm=1.6,
        ph_optimal_min=5.8, ph_optimal_max=7.0,
        nutrient_targets_mg_per_l=PLAN,
        nutrient_feed_fraction=1.0,
    )
    defaults.update(overrides)
    return Species(**defaults)


def _substrate() -> Substrate:
    return Substrate(
        name="universale", theta_fc=0.40, theta_pwp=0.10,
        cec_meq_per_100g=50.0, ph_typical=6.5,
    )


def _pot(**overrides) -> Pot:
    defaults = dict(
        species=_species(),
        substrate=_substrate(),
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


JUNE = date(2026, 6, 15)
JANUARY = date(2026, 1, 15)


# =======================================================================
#  1. Le funzioni pure
# =======================================================================

class TestAmounts(unittest.TestCase):

    def test_scale_in_milliequivalents(self):
        # 14 mg di N, 71 di P₂O₅, 47 di K₂O: un meq ciascuno.
        amounts = NutrientAmounts(14.0, 71.0, 47.0)
        self.assertAlmostEqual(amounts.total_meq, 3.0)
        self.assertEqual(MG_PER_MEQ["n"], 14.0)

    def test_minus_never_goes_below_zero(self):
        left = NutrientAmounts(10.0, 5.0, 2.0).minus(NutrientAmounts(20.0, 5.0, 1.0))
        self.assertEqual(left.as_tuple, (0.0, 0.0, 1.0))

    def test_negative_is_refused(self):
        with self.assertRaises(ValueError):
            NutrientAmounts(-1.0, 0.0, 0.0)


class TestTemperatureGate(unittest.TestCase):

    def test_open_warm_floor_cold_ramp_between(self):
        self.assertEqual(temperature_gate(None), 1.0)
        self.assertEqual(temperature_gate(20.0), 1.0)
        self.assertEqual(temperature_gate(12.0), 1.0)
        self.assertEqual(temperature_gate(3.0), UPTAKE_COLD_FLOOR)
        middle = temperature_gate(10.0)
        self.assertGreater(middle, UPTAKE_COLD_FLOOR)
        self.assertLess(middle, 1.0)


class TestDailyUptake(unittest.TestCase):

    def test_mass_flow_at_the_target_concentration(self):
        # Mezzo litro traspirato a 100 mg/L: 50 mg di N.
        taken = daily_uptake(0.5, NutrientAmounts(100.0, 40.0, 80.0))
        self.assertAlmostEqual(taken.n_mg, 50.0)
        self.assertAlmostEqual(taken.p_mg, 20.0)
        self.assertAlmostEqual(taken.k_mg, 40.0)

    def test_feed_fraction_and_cold_scale_it(self):
        base = daily_uptake(0.5, NutrientAmounts(100.0, 40.0, 80.0))
        quarter = daily_uptake(0.5, NutrientAmounts(100.0, 40.0, 80.0), feed_fraction=0.25)
        cold = daily_uptake(0.5, NutrientAmounts(100.0, 40.0, 80.0), t_mean_c=2.0)
        self.assertAlmostEqual(quarter.n_mg, base.n_mg * 0.25)
        self.assertAlmostEqual(cold.n_mg, base.n_mg * UPTAKE_COLD_FLOOR)

    def test_never_more_than_available(self):
        taken = daily_uptake(
            0.5, NutrientAmounts(100.0, 40.0, 80.0),
            available=NutrientAmounts(10.0, 0.0, 1000.0),
        )
        self.assertEqual((taken.n_mg, taken.p_mg), (10.0, 0.0))
        self.assertAlmostEqual(taken.k_mg, 40.0)

    def test_validation(self):
        with self.assertRaises(ValueError):
            daily_uptake(-1.0, ZERO)
        with self.assertRaises(ValueError):
            daily_uptake(1.0, ZERO, feed_fraction=1.5)


class TestLeachingAndCoherence(unittest.TestCase):

    def test_nitrate_leaches_more_than_the_others(self):
        lost = leached(NutrientAmounts(100.0, 100.0, 100.0), 0.5)
        self.assertAlmostEqual(lost.n_mg, 100.0 * min(1.0, 0.5 * NITRATE_LEACHING_BONUS))
        self.assertAlmostEqual(lost.p_mg, 50.0)
        self.assertAlmostEqual(lost.k_mg, 50.0)

    def test_leaching_of_everything_is_capped(self):
        lost = leached(NutrientAmounts(100.0, 100.0, 100.0), 1.0)
        self.assertEqual(lost.as_tuple, (100.0, 100.0, 100.0))

    def test_pools_never_exceed_the_salts(self):
        pools = NutrientAmounts(140.0, 0.0, 0.0)  # 10 meq
        self.assertEqual(clamp_to_salts(pools, 20.0), pools)
        halved = clamp_to_salts(pools, 5.0)
        self.assertAlmostEqual(halved.n_mg, 70.0)
        self.assertEqual(clamp_to_salts(pools, 0.0), ZERO)


class TestReserve(unittest.TestCase):

    def test_the_emptiest_pool_with_a_target_decides(self):
        # Carica piena su 2 L: 100 mg N, 40 P, 80 K (metà dell'acqua).
        charge = full_charge_mg(NutrientAmounts(*SEASON), 2.0)
        self.assertAlmostEqual(charge.n_mg, 100.0 * 2.0 * FULL_CHARGE_FRACTION)
        found = reserve(NutrientAmounts(50.0, 30.0, 80.0), NutrientAmounts(*SEASON), 2.0)
        self.assertIsNotNone(found)
        self.assertEqual(found.limiting, "n")
        self.assertAlmostEqual(found.fraction, 0.5)
        self.assertAlmostEqual(found.per_nutrient["k"], 1.0)

    def test_a_nutrient_the_plan_does_not_want_is_not_missing(self):
        found = reserve(NutrientAmounts(0.0, 0.0, 80.0), NutrientAmounts(0.0, 0.0, 80.0), 2.0)
        self.assertEqual(found.limiting, "k")
        self.assertEqual(list(found.per_nutrient), ["k"])
        self.assertIsNone(reserve(NutrientAmounts(10.0, 10.0, 10.0), ZERO, 2.0))


class TestReleaseByClass(unittest.TestCase):

    def test_quick_is_all_at_once_and_the_others_by_the_label(self):
        self.assertEqual(daily_release_fraction(ReleaseClass.QUICK, 90), 1.0)
        for klass in (ReleaseClass.GRANULAR, ReleaseClass.CONTROLLED, ReleaseClass.ORGANIC):
            self.assertAlmostEqual(daily_release_fraction(klass, 100), 0.01, msg=klass)

    def test_coated_follows_the_temperature_only(self):
        warm = daily_release_fraction(ReleaseClass.CONTROLLED, 100, t_mean_c=31.0)
        cold = daily_release_fraction(ReleaseClass.CONTROLLED, 100, t_mean_c=11.0)
        dry = daily_release_fraction(ReleaseClass.CONTROLLED, 100, t_mean_c=21.0, theta_relative=0.0)
        self.assertAlmostEqual(warm, 0.02)
        self.assertAlmostEqual(cold, 0.005)
        self.assertAlmostEqual(dry, 0.01)

    def test_organic_stops_dry_and_granular_needs_water(self):
        self.assertEqual(daily_release_fraction(ReleaseClass.ORGANIC, 90, theta_relative=0.1), 0.0)
        self.assertEqual(daily_release_fraction(ReleaseClass.GRANULAR, 7, theta_relative=0.0), 0.0)
        wet_warm = daily_release_fraction(ReleaseClass.ORGANIC, 100, t_mean_c=30.0, theta_relative=1.0)
        self.assertAlmostEqual(wet_warm, 0.02)
        with self.assertRaises(ValueError):
            daily_release_fraction(ReleaseClass.ORGANIC, 0)


# =======================================================================
#  2. Il vaso
# =======================================================================

class TestPotPools(unittest.TestCase):

    def test_a_fertigation_fills_the_pools_with_the_label(self):
        pot = _pot()
        pot.state_mm = pot.alert_mm  # c'è posto: niente drenaggio
        pot.apply_fertigation_step(
            volume_l=0.5, ec_mscm=1.2, ph=6.5, current_date=JUNE,
            nutrients_mg_per_l=NutrientAmounts(*SEASON),
        )
        self.assertAlmostEqual(pot.nutrient_n_mg, 50.0)
        self.assertAlmostEqual(pot.nutrient_p_mg, 20.0)
        self.assertAlmostEqual(pot.nutrient_k_mg, 40.0)
        self.assertLessEqual(pot.nutrient_pools.total_meq, pot.salt_mass_meq + 1e-9)

    def test_drainage_leaches_the_pools_like_the_salts_nitrate_more(self):
        pot = _pot(salt_mass_meq=20.0, nutrient_n_mg=140.0, nutrient_k_mg=235.0)
        # A capacità di campo: un litro entra, un litro drena, e con
        # l'acqua pura non entra niente.
        result = pot.apply_fertigation_step(volume_l=1.0, ec_mscm=0.0, ph=7.0, current_date=JUNE)
        self.assertGreater(result.salt_mass_drained_meq, 0.0)
        drained = result.salt_mass_drained_meq / result.salt_mass_before_meq
        self.assertAlmostEqual(pot.nutrient_k_mg, 235.0 * (1 - drained), places=6)
        self.assertAlmostEqual(
            pot.nutrient_n_mg, 140.0 * (1 - min(1.0, drained * NITRATE_LEACHING_BONUS)), places=6,
        )
        self.assertEqual(pot.nutrient_p_mg, 0.0)

    def test_rain_leaches_without_bringing_anything(self):
        pot = _pot(salt_mass_meq=20.0, nutrient_n_mg=140.0)
        pot.apply_rainfall_step(volume_l=1.0, current_date=JUNE)
        self.assertLess(pot.nutrient_n_mg, 140.0)

    def test_the_plant_eats_with_its_transpiration_and_from_the_salts(self):
        pot = _pot(salt_mass_meq=30.0, nutrient_n_mg=140.0, nutrient_p_mg=71.0, nutrient_k_mg=94.0)
        salt_before = pot.salt_mass_meq
        result = pot.apply_step(et_0_mm=5.0, current_date=JUNE, t_mean_c=22.0)
        step = result.nutrient_result
        self.assertIsNotNone(step)
        self.assertGreater(step.transpiration_l, 0.0)
        self.assertAlmostEqual(step.uptake.n_mg, step.transpiration_l * 100.0)
        self.assertAlmostEqual(step.uptake.k_mg, step.transpiration_l * 80.0)
        self.assertAlmostEqual(pot.nutrient_n_mg, 140.0 - step.uptake.n_mg)
        self.assertAlmostEqual(pot.salt_mass_meq, salt_before - step.uptake.total_meq)
        self.assertEqual(step.temperature_gate, 1.0)
        self.assertIs(pot.last_nutrient_step, step)

    def test_more_transpiration_more_uptake_and_the_cold_closes_the_gate(self):
        def eaten(et0: float, t_mean: float) -> float:
            pot = _pot(salt_mass_meq=30.0, nutrient_n_mg=140.0, nutrient_p_mg=71.0, nutrient_k_mg=94.0)
            return pot.apply_step(et_0_mm=et0, current_date=JUNE, t_mean_c=t_mean).nutrient_result.uptake.n_mg

        self.assertGreater(eaten(6.0, 22.0), eaten(3.0, 22.0))
        self.assertAlmostEqual(eaten(6.0, 2.0), eaten(6.0, 22.0) * UPTAKE_COLD_FLOOR)

    def test_out_of_season_and_without_a_plan_nothing_is_eaten(self):
        pot = _pot(salt_mass_meq=30.0, nutrient_n_mg=140.0)
        pot.apply_step(et_0_mm=2.0, current_date=JANUARY, t_mean_c=15.0)
        self.assertAlmostEqual(pot.nutrient_n_mg, 140.0)
        self.assertIsNone(pot.nutrient_reserve(JANUARY))

        plain = _pot(species=_species(nutrient_targets_mg_per_l=None), salt_mass_meq=30.0, nutrient_n_mg=140.0)
        result = plain.apply_step(et_0_mm=5.0, current_date=JUNE, t_mean_c=22.0)
        self.assertEqual(result.nutrient_result.uptake, ZERO)
        self.assertAlmostEqual(plain.nutrient_n_mg, 140.0)
        self.assertIsNone(plain.nutrient_reserve(JUNE))

    def test_the_weather_path_passes_the_mean_temperature(self):
        from fitosim.domain.weather import WeatherDay
        pot = _pot(salt_mass_meq=30.0, nutrient_n_mg=140.0, nutrient_p_mg=71.0, nutrient_k_mg=94.0)
        pot.latitude_deg = 45.0
        pot.elevation_m = 150.0
        cold = WeatherDay(date_=JUNE, t_min=0.0, t_max=4.0)
        result = pot.apply_step_from_weather(weather=cold, current_date=JUNE)
        self.assertEqual(result.nutrient_result.temperature_gate, UPTAKE_COLD_FLOOR)

    def test_dry_release_adds_to_pools_and_salts_and_stays_coherent(self):
        pot = _pot(salt_mass_meq=2.0)
        pot.add_nutrients(NutrientAmounts(28.0, 0.0, 47.0), salt_meq=5.0)
        self.assertAlmostEqual(pot.salt_mass_meq, 7.0)
        self.assertAlmostEqual(pot.nutrient_n_mg, 28.0)
        # senza sali dichiarati entra l'equivalente
        pot.add_nutrients(NutrientAmounts(14.0, 0.0, 0.0))
        self.assertAlmostEqual(pot.salt_mass_meq, 8.0)

    def test_a_lower_salt_state_shrinks_the_pools(self):
        pot = _pot(salt_mass_meq=30.0, nutrient_n_mg=140.0)
        pot.salt_mass_meq = 5.0  # una lettura di sonda, una partenza stimata
        pot._set_nutrient_pools(pot.nutrient_pools)
        self.assertAlmostEqual(pot.nutrient_n_mg, 70.0)

    def test_starter_charge_fills_to_the_peak_and_marks_until_when(self):
        pot = _pot()
        pot.apply_starter_charge(weeks=6, current_date=date(2026, 3, 1))
        self.assertEqual(pot.starter_charge_until, date(2026, 4, 12))
        found = pot.nutrient_reserve(JUNE)
        self.assertAlmostEqual(found.fraction, 1.0)
        self.assertLessEqual(pot.nutrient_pools.total_meq, pot.salt_mass_meq + 1e-9)
        # senza piano si segna solo la data
        plain = _pot(species=_species(nutrient_targets_mg_per_l=None))
        plain.apply_starter_charge(weeks=4, current_date=JUNE)
        self.assertEqual(plain.nutrient_pools, ZERO)
        self.assertIsNotNone(plain.starter_charge_until)

    def test_micronutrients_are_flags_with_a_date(self):
        pot = _pot()
        pot.record_micronutrients(("Fe", "Mg"), JUNE)
        self.assertEqual(pot.micronutrients_given, {"Fe": JUNE, "Mg": JUNE})


class TestNutrientAlert(unittest.TestCase):

    def _charged(self, fraction: float) -> Pot:
        pot = _pot(salt_mass_meq=100.0)
        charge = full_charge_mg(NutrientAmounts(*SEASON), pot.fc_water_volume_l)
        pot._set_nutrient_pools(charge.scaled(fraction))
        return pot

    def test_no_alert_when_the_reserve_is_fine_or_there_is_no_plan(self):
        self.assertIsNone(check_nutrient_low(self._charged(0.6), JUNE))
        self.assertIsNone(check_nutrient_low(self._charged(0.0), JANUARY), "riposo: niente")
        plain = _pot(species=_species(nutrient_targets_mg_per_l=None))
        self.assertIsNone(check_nutrient_low(plain, JUNE))

    def test_info_then_warning_and_the_message_says_which(self):
        pot = self._charged(0.2)
        # il potassio più vuoto di tutti
        pot._set_nutrient_pools(NutrientAmounts(pot.nutrient_n_mg, pot.nutrient_p_mg, pot.nutrient_k_mg * 0.5))
        info = check_nutrient_low(pot, JUNE)
        self.assertIsNotNone(info)
        self.assertIs(info.category, AlertCategory.NUTRIENT_LOW)
        self.assertIs(info.severity, AlertSeverity.INFO)
        self.assertIn("potassio", info.message)
        self.assertLess(NUTRIENT_RESERVE_INFO_FRACTION, 0.5)
        warning = check_nutrient_low(self._charged(0.05), JUNE)
        self.assertIs(warning.severity, AlertSeverity.WARNING)

    def test_the_days_left_come_from_the_last_step(self):
        pot = self._charged(0.2)
        pot.apply_step(et_0_mm=4.0, current_date=JUNE, t_mean_c=22.0)
        days = pot.nutrient_days_left(JUNE)
        self.assertIsNotNone(days)
        self.assertGreater(days, 0.0)
        alert = check_nutrient_low(pot, JUNE)
        self.assertIn("si svuota fra", alert.message)

    def test_silent_during_the_starter_charge(self):
        pot = self._charged(0.05)
        pot.starter_charge_until = JUNE + timedelta(days=10)
        self.assertIsNone(check_nutrient_low(pot, JUNE))
        self.assertIsNotNone(check_nutrient_low(pot, JUNE + timedelta(days=11)))


# =======================================================================
#  3. Il bilancio annuale
# =======================================================================

def _year(feed_fraction: float, cadence_days: int = 14) -> dict:
    """
    Un anno di vaso: meteo sinusoidale (ET₀ fra 0,6 e 5 mm, temperatura
    media fra 3 e 23 °C, 6 mm di pioggia ogni nove giorni), l'acqua
    quando il vaso arriva alla soglia di allerta, e ogni `cadence_days`
    in stagione quell'acqua è la soluzione del piano. Torna i totali.
    """
    pot = _pot(species=_species(nutrient_feed_fraction=feed_fraction))
    given = ZERO
    eaten = ZERO
    reserves: list[float] = []
    irrigations = 0
    season_days = 0
    last_feed = None
    start = date(2026, 1, 1)
    for i in range(365):
        today = start + timedelta(days=i)
        phase = math.sin((i - 80) / 365 * 2 * math.pi)
        et0 = max(0.6, 2.8 + 2.2 * phase)
        t_mean = 13.0 + 10.0 * phase
        rain_mm = 6.0 if i % 9 == 0 else 0.0
        targets = pot.nutrient_targets(today)
        in_season = targets is not None and targets.total_mg > 0
        season_days += in_season
        dose_l = 0.0
        ec = 0.0
        solution = None
        if pot.state_mm <= pot.alert_mm:
            irrigations += in_season
            dose_l = (pot.fc_mm - pot.state_mm) * pot.surface_area_m2 * 1.1
            ec = 0.5
            if in_season and (last_feed is None or (today - last_feed).days >= cadence_days):
                solution = targets
                ec = 0.5 + targets.total_meq / 10.0
                last_feed = today
                given = given.plus(targets.scaled(dose_l))
        result = pot.apply_step(
            et_0_mm=et0, current_date=today,
            fertigation_volume_l=dose_l, fertigation_ec_mscm=ec, fertigation_ph=7.0,
            rainfall_volume_l=rain_mm * pot.surface_area_m2,
            fertigation_nutrients_mg_per_l=solution, t_mean_c=t_mean,
        )
        eaten = eaten.plus(result.nutrient_result.uptake)
        found = pot.nutrient_reserve(today)
        if found is not None:
            reserves.append(found.fraction)
    return {
        "pot": pot,
        "given": given,
        "eaten": eaten,
        "reserves": reserves,
        "interval_days": season_days / max(1, irrigations),
    }


class TestAnnualBalance(unittest.TestCase):

    def test_fed_by_the_plan_the_year_closes_in_balance(self):
        # La frazione di alimentazione è l'intervallo fra le annaffiature
        # sulla cadenza delle concimazioni: si misura sull'anno stesso.
        dry_run = _year(feed_fraction=1.0)
        feed_fraction = min(1.0, dry_run["interval_days"] / 14)
        self.assertGreater(feed_fraction, 0.4)
        self.assertLess(feed_fraction, 1.0)

        year = _year(feed_fraction=feed_fraction)
        given, eaten = year["given"], year["eaten"]
        self.assertGreater(given.n_mg, 0.0)
        # Ha mangiato quasi tutto quello che ha ricevuto: quel che manca
        # l'ha portato via la pioggia dal foro.
        for x in ("n", "p", "k"):
            ratio = eaten.get(x) / given.get(x)
            self.assertGreater(ratio, 0.6, x)
            self.assertLessEqual(ratio, 1.0, x)
        # Niente accumulo: a fine anno resta meno di una carica piena.
        charge = full_charge_mg(NutrientAmounts(*SEASON), year["pot"].fc_water_volume_l)
        self.assertLess(year["pot"].nutrient_n_mg, charge.n_mg)
        # E niente fame: la riserva oscilla fra una concimazione e
        # l'altra — una concimazione rimpiazza l'acqua bevuta, quindi
        # arriva vicino alla carica piena, e scende fino alla successiva.
        reserves = year["reserves"]
        mean = sum(reserves) / len(reserves)
        self.assertGreater(mean, 0.2)
        self.assertLess(mean, 0.8)
        self.assertGreater(max(reserves), 0.7)
        self.assertLess(min(reserves), 0.1)

    def test_eating_less_than_it_gets_accumulates(self):
        year = _year(feed_fraction=0.15)
        self.assertLess(year["eaten"].n_mg, year["given"].n_mg * 0.5)
        self.assertGreater(max(year["reserves"]), 1.5)


if __name__ == "__main__":
    unittest.main()
