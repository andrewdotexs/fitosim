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


# =======================================================================
#  Estensione: forme, materiali, colori, esposizione, active_depth
# =======================================================================
#
# Questi test mettono in sicurezza l'estensione "vasi caratterizzati"
# (Fascia 1 della roadmap). Verificano che:
#   - i default riproducano esattamente il comportamento precedente
#     (zero regressioni rispetto ai test classici sopra);
#   - il dispatch della forma in surface_area_m2 sia corretto;
#   - il fattore Kp influenzi current_et_c nella direzione giusta;
#   - la validazione __post_init__ catturi le configurazioni invalide.

class TestPotShape(unittest.TestCase):
    """Dispatch di surface_area_m2 in funzione di pot_shape."""

    def test_default_is_cylindrical(self):
        from fitosim.domain.pot import PotShape
        pot = _make_basil_pot()
        # Il default deve essere cilindrico (compatibilità retroattiva).
        self.assertEqual(pot.pot_shape, PotShape.CYLINDRICAL)

    def test_cylindrical_uses_circular_area(self):
        # Cilindrico: area = π·(d/2)². Con d=18 cm → ~0.0254 m².
        pot = _make_basil_pot()
        expected = circular_pot_surface_area_m2(pot.pot_diameter_cm)
        self.assertAlmostEqual(pot.surface_area_m2, expected, places=10)

    def test_truncated_cone_equivalent_to_cylindrical(self):
        # Stessa apertura → stessa superficie evaporante.
        from fitosim.domain.pot import PotShape
        from dataclasses import replace
        pot_cyl = _make_basil_pot()
        pot_tc = replace(pot_cyl, pot_shape=PotShape.TRUNCATED_CONE)
        self.assertAlmostEqual(
            pot_cyl.surface_area_m2, pot_tc.surface_area_m2, places=10,
        )

    def test_rectangular_uses_length_times_width(self):
        # Cassetta rettangolare 60 × 20 cm.
        from fitosim.domain.pot import PotShape
        pot = Pot(
            label="cassetta",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=12.0,
            pot_diameter_cm=60.0,    # qui rappresenta la lunghezza
            pot_width_cm=20.0,
            pot_shape=PotShape.RECTANGULAR,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 15),
        )
        # 60 cm × 20 cm = 0.12 m².
        self.assertAlmostEqual(pot.surface_area_m2, 0.12, places=6)

    def test_oval_uses_ellipse_formula(self):
        # Vaso ovale 30 × 20 cm.
        from fitosim.domain.pot import PotShape
        import math
        pot = Pot(
            label="ovale",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=5.0,
            pot_diameter_cm=30.0,
            pot_width_cm=20.0,
            pot_shape=PotShape.OVAL,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 15),
        )
        expected = math.pi * 0.15 * 0.10  # π·a·b
        self.assertAlmostEqual(pot.surface_area_m2, expected, places=6)

    def test_rectangular_without_width_raises(self):
        # Validazione __post_init__: forma rettangolare senza
        # pot_width_cm deve essere rifiutata.
        from fitosim.domain.pot import PotShape
        with self.assertRaises(ValueError) as ctx:
            Pot(
                label="invalida",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=5.0,
                pot_diameter_cm=20.0,
                pot_shape=PotShape.RECTANGULAR,
                # pot_width_cm omesso!
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 15),
            )
        self.assertIn("pot_width_cm", str(ctx.exception))

    def test_oval_without_width_raises(self):
        from fitosim.domain.pot import PotShape
        with self.assertRaises(ValueError):
            Pot(
                label="invalida",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=5.0,
                pot_diameter_cm=20.0,
                pot_shape=PotShape.OVAL,
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 15),
            )


class TestPotKp(unittest.TestCase):
    """
    Coefficiente di vaso Kp e sua composizione. Verifica che:
      - i default producano Kp = 1.00 (compatibilità retroattiva);
      - varianti di material/color/exposure cambino Kp nella
        direzione fisicamente corretta;
      - la composizione corrisponda al prodotto dei tre fattori.
    """

    def test_default_kp_is_one(self):
        # Default = (PLASTIC, MEDIUM, FULL_SUN) → Kp = 1.00.
        # Critico per la compatibilità retroattiva del modello.
        pot = _make_basil_pot()
        self.assertAlmostEqual(pot.kp, 1.00, places=10)

    def test_kp_increases_with_terracotta(self):
        from fitosim.science.pot_physics import PotMaterial
        from dataclasses import replace
        pot_plastica = _make_basil_pot()
        pot_terracotta = replace(pot_plastica, pot_material=PotMaterial.TERRACOTTA)
        self.assertGreater(pot_terracotta.kp, pot_plastica.kp)

    def test_kp_decreases_with_shade(self):
        from fitosim.science.pot_physics import SunExposure
        from dataclasses import replace
        pot_sole = _make_basil_pot()
        pot_ombra = replace(pot_sole, sun_exposure=SunExposure.SHADE)
        self.assertLess(pot_ombra.kp, pot_sole.kp)

    def test_kp_matches_pot_correction_factor(self):
        # La property kp deve essere esattamente pot_correction_factor
        # dei tre attributi. Verifica della formula completa di
        # composizione su una configurazione non-default.
        from fitosim.science.pot_physics import (
            PotColor, PotMaterial, SunExposure, pot_correction_factor,
        )
        from dataclasses import replace
        pot = replace(
            _make_basil_pot(),
            pot_material=PotMaterial.TERRACOTTA,
            pot_color=PotColor.DARK,
            sun_exposure=SunExposure.PARTIAL_SHADE,
        )
        expected = pot_correction_factor(
            material=PotMaterial.TERRACOTTA,
            color=PotColor.DARK,
            exposure=SunExposure.PARTIAL_SHADE,
        )
        self.assertAlmostEqual(pot.kp, expected, places=10)


class TestCurrentEtcWithKp(unittest.TestCase):
    """
    Effetto di Kp sul calcolo finale di ET_c,act. È il test più
    importante perché chiude il cerchio: la modifica al modello
    deve effettivamente cambiare il numero che esce dal motore.
    """

    def test_default_pot_unchanged_from_baseline(self):
        # Vaso con tutti i default: current_et_c deve essere identico
        # a quello che era prima dell'estensione (Kp=1 → moltiplicazione
        # per 1.0 invariante).
        pot = _make_basil_pot(state_mm=28.0)  # ben sopra alert
        # Stadio mid-season: 30 giorni dopo l'impianto.
        eval_date = pot.planting_date.replace(day=15)
        et_0 = 5.0
        et_c = pot.current_et_c(et_0, eval_date)
        # Calcolo manuale con Kp=1 implicito.
        manual = actual_et_c(
            species=BASIL,
            stage=pot.current_stage(eval_date),
            et_0=et_0,
            current_theta=pot.state_theta,
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        self.assertAlmostEqual(et_c, manual, places=6)

    def test_terracotta_consumes_more_than_plastic(self):
        # Stesso vaso, due materiali diversi: terracotta deve avere
        # ET_c maggiore di plastica.
        from fitosim.science.pot_physics import PotMaterial
        from dataclasses import replace
        pot_plast = _make_basil_pot(state_mm=28.0)  # ben sopra alert
        pot_terra = replace(pot_plast, pot_material=PotMaterial.TERRACOTTA)
        eval_date = pot_plast.planting_date.replace(day=15)
        et_0 = 5.0
        self.assertGreater(
            pot_terra.current_et_c(et_0, eval_date),
            pot_plast.current_et_c(et_0, eval_date),
        )

    def test_kp_scales_et_c_proportionally(self):
        # ET_c con Kp arbitrario deve essere esattamente Kp ×
        # ET_c con Kp=1. Verifica della linearità del modello.
        from fitosim.science.pot_physics import (
            PotColor, PotMaterial, SunExposure,
        )
        from dataclasses import replace
        pot_default = _make_basil_pot(state_mm=28.0)  # ben sopra alert
        pot_modified = replace(
            pot_default,
            pot_material=PotMaterial.TERRACOTTA,
            pot_color=PotColor.DARK,
            sun_exposure=SunExposure.PARTIAL_SHADE,
        )
        eval_date = pot_default.planting_date.replace(day=15)
        et_0 = 5.0
        et_c_default = pot_default.current_et_c(et_0, eval_date)
        et_c_modified = pot_modified.current_et_c(et_0, eval_date)
        # Il rapporto tra i due deve essere il Kp del vaso modificato.
        ratio = et_c_modified / et_c_default
        self.assertAlmostEqual(ratio, pot_modified.kp, places=6)


class TestActiveDepthFraction(unittest.TestCase):
    """
    Frazione attiva del substrato (per gestire lo strato drenante in
    fondo al vaso). Se < 1.0, riduce la profondità effettiva e quindi
    la riserva idrica disponibile.
    """

    def test_default_is_one(self):
        # Default 1.0 = tutto il vaso è attivo (compatibilità retroattiva).
        pot = _make_basil_pot()
        self.assertEqual(pot.active_depth_fraction, 1.0)

    def test_reduced_fraction_lowers_fc_mm(self):
        # active_depth_fraction=0.7 → strato drenante del 30% in fondo.
        # FC in mm si riduce proporzionalmente perché meno substrato
        # = meno acqua trattenibile.
        from dataclasses import replace
        pot_full = _make_basil_pot()
        pot_drenante = replace(pot_full, active_depth_fraction=0.7)
        # FC del vaso con strato drenante è 70% di quello senza.
        ratio = pot_drenante.fc_mm / pot_full.fc_mm
        self.assertAlmostEqual(ratio, 0.7, places=6)

    def test_rejects_zero_or_negative_fraction(self):
        from dataclasses import replace
        # 0.0 e negativi non hanno senso fisico.
        pot = _make_basil_pot()
        with self.assertRaises(ValueError):
            replace(pot, active_depth_fraction=0.0)
        with self.assertRaises(ValueError):
            replace(pot, active_depth_fraction=-0.1)

    def test_rejects_fraction_above_one(self):
        # > 1.0 non ha senso (non puoi avere più substrato del volume).
        from dataclasses import replace
        pot = _make_basil_pot()
        with self.assertRaises(ValueError):
            replace(pot, active_depth_fraction=1.2)


if __name__ == "__main__":
    unittest.main()
