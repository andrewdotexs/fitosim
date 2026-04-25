"""
Test per fitosim.domain.pot.

Cinque famiglie di test:
  1. Creazione e validazione del Pot.
  2. Proprietà geometriche derivate (area, profondità, soglie).
  3. Logica fenologica basata sulla data di impianto.
  4. Aggiornamento dello stato via apply_balance_step.
  5. Equivalenza dei risultati rispetto al flusso "manuale" diretto.
"""

import unittest
from datetime import date

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import (
    BASIL,
    CITRUS,
    LETTUCE,
    PhenologicalStage,
    actual_et_c,
)
from fitosim.science.balance import water_balance_step_mm
from fitosim.science.substrate import (
    UNIVERSAL_POTTING_SOIL,
    circular_pot_surface_area_m2,
    pot_substrate_depth_mm,
)


def _make_basil_pot(state_mm: float = -1.0) -> Pot:
    """Helper: crea un vaso di basilico standard per i test."""
    return Pot(
        label="basil-test",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0,
        pot_diameter_cm=20.0,
        location=Location.OUTDOOR,
        planting_date=date(2025, 5, 1),
        state_mm=state_mm,
    )


class TestPotCreation(unittest.TestCase):
    """Verifica creazione e validazione del Pot."""

    def test_default_state_initialized_to_fc(self):
        # Senza state_mm esplicito, il vaso parte a capacità di campo.
        p = _make_basil_pot()
        self.assertAlmostEqual(p.state_mm, p.fc_mm, places=6)

    def test_explicit_state_is_respected(self):
        p = _make_basil_pot(state_mm=30.0)
        self.assertEqual(p.state_mm, 30.0)

    def test_zero_state_is_respected(self):
        # Lo zero è un valore valido (vaso completamente asciutto):
        # solo i negativi devono essere intercettati come sentinella.
        p = _make_basil_pot(state_mm=0.0)
        self.assertEqual(p.state_mm, 0.0)

    def test_zero_volume_rejected(self):
        with self.assertRaises(ValueError):
            Pot(
                label="bad", species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=0.0, pot_diameter_cm=20.0,
                location=Location.OUTDOOR,
                planting_date=date(2025, 1, 1),
            )

    def test_zero_diameter_rejected(self):
        with self.assertRaises(ValueError):
            Pot(
                label="bad", species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=5.0, pot_diameter_cm=0.0,
                location=Location.OUTDOOR,
                planting_date=date(2025, 1, 1),
            )


class TestDerivedGeometry(unittest.TestCase):
    """Le proprietà geometriche devono coincidere con il calcolo diretto."""

    def setUp(self):
        self.p = _make_basil_pot()

    def test_surface_area_matches_direct_calculation(self):
        expected = circular_pot_surface_area_m2(20.0)
        self.assertAlmostEqual(self.p.surface_area_m2, expected, places=6)

    def test_substrate_depth_matches_direct_calculation(self):
        expected = pot_substrate_depth_mm(5.0, self.p.surface_area_m2)
        self.assertAlmostEqual(self.p.substrate_depth_mm, expected, places=6)

    def test_fc_pwp_alert_ordering(self):
        # Le tre soglie devono rispettare PWP < alert < FC.
        self.assertLess(self.p.pwp_mm, self.p.alert_mm)
        self.assertLess(self.p.alert_mm, self.p.fc_mm)

    def test_state_theta_inverse_of_state_mm(self):
        # Conversione θ ↔ mm tramite la profondità del vaso.
        self.p.state_mm = 40.0
        recomputed_mm = self.p.state_theta * self.p.substrate_depth_mm
        self.assertAlmostEqual(recomputed_mm, 40.0, places=6)

    def test_alert_threshold_uses_species_p(self):
        # Il vaso di basilico (p=0.40) ha soglia diversa da quello di
        # lattuga (p=0.30) anche se hanno stesso volume e substrato.
        basil_pot = _make_basil_pot()
        lettuce_pot = Pot(
            label="lettuce", species=LETTUCE,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=5.0, pot_diameter_cm=20.0,
            location=Location.OUTDOOR,
            planting_date=date(2025, 5, 1),
        )
        # La lattuga (p più basso) ha soglia di allerta più ALTA: tollera
        # meno deplezione, scatta prima.
        self.assertGreater(lettuce_pot.alert_mm, basil_pot.alert_mm)


class TestPhenologyFromDate(unittest.TestCase):
    """Lo stadio deve evolvere correttamente nel tempo."""

    def test_stage_at_planting_day(self):
        p = _make_basil_pot()
        # BASIL ha initial_stage_days=20. Al giorno 0 → INITIAL.
        self.assertEqual(
            p.current_stage(p.planting_date), PhenologicalStage.INITIAL
        )

    def test_stage_after_initial_period(self):
        p = _make_basil_pot()
        # Day 25: oltre i 20 giorni di INITIAL ma sotto i 70 (20+50 di MID).
        from datetime import timedelta
        d = p.planting_date + timedelta(days=25)
        self.assertEqual(p.current_stage(d), PhenologicalStage.MID_SEASON)

    def test_stage_after_mid_period(self):
        p = _make_basil_pot()
        from datetime import timedelta
        # Day 80: oltre 70 (20+50) → LATE_SEASON.
        d = p.planting_date + timedelta(days=80)
        self.assertEqual(p.current_stage(d), PhenologicalStage.LATE_SEASON)

    def test_negative_days_clamped_to_initial(self):
        # Data precedente all'impianto: trattata come INITIAL (sentinella
        # delicata, non solleva eccezione).
        p = _make_basil_pot()
        from datetime import timedelta
        d = p.planting_date - timedelta(days=5)
        self.assertEqual(p.current_stage(d), PhenologicalStage.INITIAL)

    def test_days_since_planting_arithmetic(self):
        p = _make_basil_pot()
        from datetime import timedelta
        d = p.planting_date + timedelta(days=42)
        self.assertEqual(p.days_since_planting(d), 42)


class TestBalanceStepApplication(unittest.TestCase):
    """Verifica che apply_balance_step aggiorni lo stato e restituisca i risultati."""

    def test_state_decreases_under_dry_step(self):
        p = _make_basil_pot()
        initial_state = p.state_mm
        result = p.apply_balance_step(
            et_0_mm=5.0, water_input_mm=0.0,
            current_date=date(2025, 7, 15),
        )
        # In assenza di pioggia, lo stato deve essere sceso.
        self.assertLess(p.state_mm, initial_state)
        # E lo stato del vaso deve coincidere con result.new_state.
        self.assertAlmostEqual(p.state_mm, result.new_state, places=6)

    def test_state_increases_under_irrigation(self):
        p = _make_basil_pot(state_mm=30.0)
        p.apply_balance_step(
            et_0_mm=4.0, water_input_mm=20.0,
            current_date=date(2025, 7, 15),
        )
        # Input 20 mm − ET di pochi mm → stato sale visibilmente.
        self.assertGreater(p.state_mm, 30.0)

    def test_water_to_fc_decreases_after_irrigation(self):
        p = _make_basil_pot(state_mm=30.0)
        deficit_before = p.water_to_field_capacity()
        p.apply_balance_step(
            et_0_mm=2.0, water_input_mm=10.0,
            current_date=date(2025, 7, 15),
        )
        deficit_after = p.water_to_field_capacity()
        self.assertLess(deficit_after, deficit_before)

    def test_alert_flag_in_result(self):
        # Lo stato di partenza è in zona di stress (sotto alert_mm) →
        # apply_balance_step deve riportare under_alert=True.
        p = _make_basil_pot(state_mm=30.0)
        # alert_mm per basilico (p=0.4) in vaso 5L è 47.7 mm.
        self.assertLess(p.state_mm, p.alert_mm)
        result = p.apply_balance_step(
            et_0_mm=3.0, water_input_mm=0.0,
            current_date=date(2025, 7, 15),
        )
        self.assertTrue(result.under_alert)


class TestEquivalenceWithManualFlow(unittest.TestCase):
    """
    Test cruciale: usare il Pot deve produrre risultati identici a
    chiamare manualmente le funzioni a basso livello con gli stessi
    parametri. È la garanzia che `Pot` è un'astrazione "pura" senza
    semantica nascosta.
    """

    def test_single_step_equivalence(self):
        # Setup identico in due rami: oggetto Pot vs chiamate manuali.
        sim_date = date(2025, 7, 15)
        et0_mm = 5.5
        input_mm = 0.0
        initial_state = 35.0

        # Ramo 1 — via Pot.
        pot = _make_basil_pot(state_mm=initial_state)
        pot_result = pot.apply_balance_step(
            et_0_mm=et0_mm, water_input_mm=input_mm,
            current_date=sim_date,
        )

        # Ramo 2 — via chiamate manuali.
        depth = pot_substrate_depth_mm(
            5.0, circular_pot_surface_area_m2(20.0)
        )
        from fitosim.science.substrate import mm_to_theta
        # Lo stadio nel giorno della simulazione: 5/1 → 7/15 = 75 giorni.
        # Per BASIL (initial=20, mid=50): 75 > 70 → LATE_SEASON.
        stage = PhenologicalStage.LATE_SEASON
        et_c = actual_et_c(
            species=BASIL, stage=stage, et_0=et0_mm,
            current_theta=mm_to_theta(initial_state, depth),
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        manual_result = water_balance_step_mm(
            current_mm=initial_state,
            water_input_mm=input_mm,
            et_c_mm=et_c,
            substrate=UNIVERSAL_POTTING_SOIL,
            substrate_depth_mm=depth,
            depletion_fraction=BASIL.depletion_fraction,
        )

        # I due risultati devono coincidere fino all'errore numerico.
        self.assertAlmostEqual(
            pot_result.new_state, manual_result.new_state, places=6
        )
        self.assertAlmostEqual(
            pot_result.drainage, manual_result.drainage, places=6
        )
        self.assertEqual(pot_result.under_alert, manual_result.under_alert)


if __name__ == "__main__":
    unittest.main()
