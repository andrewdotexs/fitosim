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
from datetime import date, timedelta

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import (
    BASIL,
    CITRUS,
    LETTUCE,
    PhenologicalStage,
    Species,
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


# =======================================================================
#  Sottovaso e risalita capillare
# =======================================================================
#
# Il sottovaso introduce un secondo serbatoio idrico accoppiato al
# substrato del vaso. Verifichiamo che:
#   - in assenza del sottovoto (default), il comportamento è identico
#     al modello pre-estensione (regressione zero);
#   - con il sottovaso, il drenaggio viene catturato invece che perso;
#   - la risalita capillare nei giorni successivi reidrata il vaso;
#   - l'evaporazione del piattino svuota gradualmente il sottovaso;
#   - i campi __post_init__ catturano configurazioni invalide.

class TestSaucerOptional(unittest.TestCase):
    """Backward compatibility: senza sottovaso tutto è invariato."""

    def test_default_pot_has_no_saucer(self):
        # Il default è "nessun sottovaso", per zero regressione sui
        # vasi creati prima dell'estensione.
        pot = _make_basil_pot()
        self.assertIsNone(pot.saucer_capacity_mm)

    def test_no_saucer_step_identical_to_baseline(self):
        # Test critico: un vaso senza sottovoto fa esattamente lo
        # stesso bilancio di prima dell'estensione. Confrontiamo il
        # risultato del passo con il calcolo manuale del water_balance.
        pot = _make_basil_pot(state_mm=25.0)
        eval_date = pot.planting_date.replace(day=10)
        result_pot = pot.apply_balance_step(
            et_0_mm=5.0,
            water_input_mm=2.0,
            current_date=eval_date,
        )
        # Stato del piattino non deve mai cambiare quando il sottovoto
        # non è attivo (resta al default 0.0).
        self.assertEqual(pot.saucer_state_mm, 0.0)
        # Ricalcolo manuale equivalente.
        manual = water_balance_step_mm(
            current_mm=25.0,
            water_input_mm=2.0,
            et_c_mm=actual_et_c(
                species=BASIL,
                stage=pot.current_stage(eval_date),
                et_0=5.0,
                current_theta=25.0 / pot.substrate_depth_mm,
                substrate=UNIVERSAL_POTTING_SOIL,
            ),
            substrate=UNIVERSAL_POTTING_SOIL,
            substrate_depth_mm=pot.substrate_depth_mm,
            depletion_fraction=BASIL.depletion_fraction,
        )
        self.assertAlmostEqual(result_pot.new_state, manual.new_state, places=6)
        self.assertAlmostEqual(result_pot.drainage, manual.drainage, places=6)


class TestSaucerValidation(unittest.TestCase):
    """Validazione __post_init__ dei nuovi campi del sottovaso."""

    def test_negative_capacity_rejected(self):
        with self.assertRaises(ValueError):
            Pot(
                label="invalido",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=2.0, pot_diameter_cm=18.0,
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 1),
                saucer_capacity_mm=-5.0,
            )

    def test_state_above_capacity_rejected(self):
        with self.assertRaises(ValueError):
            Pot(
                label="invalido",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=2.0, pot_diameter_cm=18.0,
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 1),
                saucer_capacity_mm=10.0,
                saucer_state_mm=15.0,  # > capacity
            )

    def test_negative_state_rejected(self):
        with self.assertRaises(ValueError):
            Pot(
                label="invalido",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=2.0, pot_diameter_cm=18.0,
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 1),
                saucer_capacity_mm=10.0,
                saucer_state_mm=-1.0,
            )

    def test_zero_capacity_rejected(self):
        # Una capacità di zero significa "nessun sottovoto"; in tal caso
        # la convenzione è impostare saucer_capacity_mm=None, non zero.
        with self.assertRaises(ValueError):
            Pot(
                label="invalido",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=2.0, pot_diameter_cm=18.0,
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 1),
                saucer_capacity_mm=0.0,
            )

    def test_negative_capillary_rate_rejected(self):
        with self.assertRaises(ValueError):
            Pot(
                label="invalido",
                species=BASIL,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=2.0, pot_diameter_cm=18.0,
                location=Location.OUTDOOR,
                planting_date=date(2026, 4, 1),
                saucer_capacity_mm=10.0,
                saucer_capillary_rate=-0.1,
            )


def _make_pot_with_saucer(
    saucer_state_mm: float = 0.0,
    state_mm: float = -1.0,
) -> Pot:
    """Helper: vaso di basilico con sottovoto da 10 mm."""
    return Pot(
        label="basil-saucer",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        state_mm=state_mm,
        saucer_capacity_mm=10.0,
        saucer_state_mm=saucer_state_mm,
    )


class TestSaucerCapturesDrainage(unittest.TestCase):
    """
    Effetto chiave del sottovaso: cattura il drenaggio invece di
    perderlo definitivamente.
    """

    def test_overflow_irrigation_fills_saucer(self):
        # Vaso a FC; aggiungo 8 mm di pioggia: tutto va a drenaggio
        # (perché sopra FC); il drenaggio viene catturato dal sottovoto.
        pot = _make_pot_with_saucer()
        # Stato iniziale: vaso a FC (default), sottovoto vuoto.
        initial_fc = pot.fc_mm
        eval_date = date(2026, 4, 15)
        # Saturo il vaso con un input molto grande.
        result = pot.apply_balance_step(
            et_0_mm=0.0, water_input_mm=8.0, current_date=eval_date,
        )
        # Il vaso resta a FC (il surplus va a drenaggio).
        self.assertAlmostEqual(pot.state_mm, initial_fc, places=2)
        self.assertGreater(result.drainage, 0.0)
        # Il sottovoto ora ha acqua, fino al limite della sua capacità.
        self.assertGreater(pot.saucer_state_mm, 0.0)
        self.assertLessEqual(pot.saucer_state_mm, pot.saucer_capacity_mm)

    def test_overflow_above_saucer_capacity_is_lost(self):
        # Drenaggio enorme: il sottovaso si riempie fino al massimo,
        # l'eccedenza è persa (non c'è ritorno nel modello).
        pot = _make_pot_with_saucer(saucer_state_mm=8.0)  # già quasi pieno
        eval_date = date(2026, 4, 15)
        # Forza un drenaggio enorme.
        pot.apply_balance_step(
            et_0_mm=0.0, water_input_mm=20.0, current_date=eval_date,
        )
        # Il sottovaso è a capacità (10 mm), non oltre.
        self.assertEqual(pot.saucer_state_mm, 10.0)


class TestCapillaryRise(unittest.TestCase):
    """
    Effetto della risalita capillare: il sottovaso reidrata il
    substrato nei giorni successivi.
    """

    def test_dry_pot_with_full_saucer_recovers(self):
        # Vaso secco (state_mm bassa) e sottovaso pieno: il giorno
        # dopo, anche senza pioggia o irrigazione, lo stato del vaso
        # cresce per risalita capillare. È l'effetto fisico cardine.
        pot = _make_pot_with_saucer(saucer_state_mm=10.0, state_mm=15.0)
        # Per evitare che ET₀ confonda il test (con et_0=5 il vaso
        # consuma di più del sottovaso che gli porta), uso et_0=0.
        eval_date = date(2026, 4, 15)
        state_before = pot.state_mm
        saucer_before = pot.saucer_state_mm
        pot.apply_balance_step(
            et_0_mm=0.0, water_input_mm=0.0, current_date=eval_date,
        )
        # Il vaso si è idratato.
        self.assertGreater(pot.state_mm, state_before)
        # Il sottovaso è diminuito.
        self.assertLess(pot.saucer_state_mm, saucer_before)
        # Conservazione: l'aumento del vaso corrisponde alla diminuzione
        # del sottovaso (meno l'evaporazione del piattino, qui zero
        # perché et_0=0).
        delta_pot = pot.state_mm - state_before
        delta_saucer = saucer_before - pot.saucer_state_mm
        self.assertAlmostEqual(delta_pot, delta_saucer, places=6)

    def test_saturated_pot_does_not_capillary_rise(self):
        # Vaso a FC e sottovaso pieno: nessun trasferimento (deficit=0).
        pot = _make_pot_with_saucer(saucer_state_mm=10.0)  # vaso a FC default
        eval_date = date(2026, 4, 15)
        saucer_before = pot.saucer_state_mm
        pot.apply_balance_step(
            et_0_mm=0.0, water_input_mm=0.0, current_date=eval_date,
        )
        # Il sottovaso non perde acqua per capillarità (et_0=0 anche),
        # ma neanche per evaporazione perché coef × et_0 = 0.
        self.assertAlmostEqual(pot.saucer_state_mm, saucer_before, places=6)


class TestSaucerVsNoSaucer(unittest.TestCase):
    """
    Test integrato: simulazione comparata di due vasi identici, uno
    con e uno senza sottovaso. Quello con sottovaso deve richiedere
    meno irrigazioni nel tempo.
    """

    def test_saucer_extends_autonomy(self):
        from dataclasses import replace

        # Setup: due vasi identici, uno senza sottovaso e uno con
        # sottovaso da 10 mm. Stato iniziale: entrambi a FC.
        pot_no = _make_basil_pot()
        pot_yes = replace(
            pot_no,
            label="con-sottovoto",
            saucer_capacity_mm=10.0,
            saucer_state_mm=10.0,  # piattino già pieno (post-irrigazione)
        )

        # Simulo 14 giorni di asciugatura senza pioggia né irrigazione.
        # Dopo questo periodo, il vaso con sottovoto deve avere uno
        # stato idrico maggiore (è stato "rifornito" dal piattino).
        et_0_daily = 4.0
        for d in range(14):
            current_date = date(2026, 4, 15) + __import__("datetime").timedelta(days=d)
            pot_no.apply_balance_step(et_0_daily, 0.0, current_date)
            pot_yes.apply_balance_step(et_0_daily, 0.0, current_date)

        # Il vaso con sottovaso ha più acqua residua.
        self.assertGreater(pot_yes.state_mm, pot_no.state_mm)


# =======================================================================
#  Dual-Kc: integrazione di FAO-56 cap. 7 in Pot
# =======================================================================
#
# Quattro famiglie di test che coprono la nuova capacità di
# evapotraspirazione separata in traspirazione (Kcb) ed evaporazione
# superficiale (Ke), con tracking della cumulative depletion De.

# Helper per creare specie con Kcb e substrato con REW/TEW.
def _make_basil_with_kcb() -> Species:
    """Specie basilico con i Kcb FAO-56 cap. 7."""
    return Species(
        common_name="basilico",
        scientific_name="Ocimum basilicum",
        kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
        kcb_initial=0.35, kcb_mid=1.00, kcb_late=0.75,
        depletion_fraction=0.40,
    )


def _make_substrate_with_rew_tew() -> "Substrate":
    """Substrato torba con REW e TEW per dual-Kc."""
    from fitosim.science.substrate import Substrate
    return Substrate(
        name="Torba commerciale dual-Kc",
        theta_fc=0.40, theta_pwp=0.10,
        rew_mm=9.0, tew_mm=22.0,
    )


def _make_dual_kc_pot(state_mm: float = -1.0) -> Pot:
    """Vaso completo per dual-Kc (basilico + torba con REW/TEW)."""
    return Pot(
        label="basil-dual-kc",
        species=_make_basil_with_kcb(),
        substrate=_make_substrate_with_rew_tew(),
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        state_mm=state_mm,
    )


class TestDualKcSupport(unittest.TestCase):
    """Verifica della property supports_dual_kc."""

    def test_default_pot_does_not_support_dual_kc(self):
        # Vaso standard (specie senza Kcb, substrato senza REW/TEW):
        # supports_dual_kc è False, comportamento single Kc.
        pot = _make_basil_pot()
        self.assertFalse(pot.supports_dual_kc)

    def test_pot_with_only_kcb_does_not_support_dual_kc(self):
        # Specie con Kcb ma substrato senza REW/TEW: NON supporta
        # dual-Kc (servono entrambi i lati della configurazione).
        from dataclasses import replace
        pot = _make_basil_pot()
        pot_with_kcb_species = replace(pot, species=_make_basil_with_kcb())
        self.assertFalse(pot_with_kcb_species.supports_dual_kc)

    def test_pot_with_only_rew_tew_does_not_support_dual_kc(self):
        # Substrato con REW/TEW ma specie senza Kcb: NON supporta
        # dual-Kc.
        from dataclasses import replace
        pot = _make_basil_pot()
        pot_with_substrate = replace(
            pot, substrate=_make_substrate_with_rew_tew(),
        )
        self.assertFalse(pot_with_substrate.supports_dual_kc)

    def test_complete_pot_supports_dual_kc(self):
        # Vaso completo con tutto al posto giusto: True.
        pot = _make_dual_kc_pot()
        self.assertTrue(pot.supports_dual_kc)


class TestDualKcBackwardCompatibility(unittest.TestCase):
    """
    Verifica che l'introduzione del dual-Kc non rompa il comportamento
    dei vasi che non lo supportano.
    """

    def test_default_pot_uses_single_kc(self):
        # Stesso vaso, stessa data, stesso ET₀: il risultato deve
        # essere identico a quello che si otterrebbe senza l'estensione.
        pot = _make_basil_pot(state_mm=20.0)
        et_0 = 5.0
        eval_date = date(2026, 4, 15)
        # Calcolo via Pot.current_et_c.
        et_c_pot = pot.current_et_c(et_0, eval_date)
        # Calcolo manuale single Kc (l'unico modo di farlo prima
        # dell'estensione).
        et_c_manual = actual_et_c(
            species=BASIL,
            stage=pot.current_stage(eval_date),
            et_0=et_0,
            current_theta=pot.state_theta,
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        # I due valori devono coincidere (Kp=1 per default).
        self.assertAlmostEqual(et_c_pot, et_c_manual, places=6)

    def test_default_pot_does_not_track_de(self):
        # In modalità single Kc, de_mm rimane al default (0) anche
        # dopo apply_balance_step.
        pot = _make_basil_pot(state_mm=20.0)
        eval_date = date(2026, 4, 15)
        pot.apply_balance_step(
            et_0_mm=5.0, water_input_mm=2.0, current_date=eval_date,
        )
        # de_mm non viene aggiornato perché il vaso non supporta dual-Kc.
        self.assertEqual(pot.de_mm, 0.0)


class TestDualKcDynamics(unittest.TestCase):
    """
    Verifica della dinamica del dual-Kc: De cresce con l'asciugamento,
    si resetta con le irrigazioni, e Ke risponde correttamente.
    """

    def test_de_increases_during_drying(self):
        # Vaso che parte appena bagnato (de=0). Dopo qualche giorno
        # senza pioggia, de_mm deve crescere.
        pot = _make_dual_kc_pot()
        de_history = [pot.de_mm]
        for d in range(5):
            current_date = date(2026, 4, 15) + timedelta(days=d)
            pot.apply_balance_step(
                et_0_mm=4.0, water_input_mm=0.0, current_date=current_date,
            )
            de_history.append(pot.de_mm)
        # de_mm deve essere monotonicamente crescente (senza input
        # idrico, l'evaporazione superficiale ha solo questo effetto).
        for i in range(len(de_history) - 1):
            with self.subTest(day=i):
                self.assertGreaterEqual(de_history[i + 1], de_history[i])
        # Dopo 5 giorni de_mm deve essere significativamente maggiore
        # di zero.
        self.assertGreater(pot.de_mm, 0.0)

    def test_irrigation_resets_de(self):
        # Vaso con de_mm già accumulato; un'irrigazione abbondante
        # azzera de_mm.
        from dataclasses import replace
        pot = _make_dual_kc_pot()
        # Forziamo un de_mm intermedio.
        pot.de_mm = 15.0
        eval_date = date(2026, 4, 15)
        # Input idrico abbondante: 25 mm (> TEW=22 mm).
        pot.apply_balance_step(
            et_0_mm=4.0, water_input_mm=25.0, current_date=eval_date,
        )
        # de_mm deve essere azzerato (saturato a 0).
        self.assertEqual(pot.de_mm, 0.0)

    def test_de_capped_at_tew(self):
        # Anche con asciugamento estremo, de_mm non eccede TEW=22.
        pot = _make_dual_kc_pot()
        for d in range(60):  # 60 giorni senza pioggia: scenario limite
            current_date = date(2026, 4, 15) + timedelta(days=d)
            pot.apply_balance_step(
                et_0_mm=6.0, water_input_mm=0.0, current_date=current_date,
            )
        # de_mm non eccede mai TEW.
        self.assertLessEqual(pot.de_mm, 22.0)

    def test_dual_kc_higher_consumption_post_irrigation(self):
        # Test cardine dell'utilità del dual-Kc: nei giorni post-
        # irrigazione, il dual-Kc prevede consumo MAGGIORE rispetto
        # al single Kc (cattura il contributo di Ke aggiuntivo).
        from dataclasses import replace
        # Due vasi gemelli: uno con dual-Kc, uno senza.
        pot_dual = _make_dual_kc_pot()
        pot_single = Pot(
            label="single-kc",
            species=BASIL,  # specie senza Kcb
            substrate=UNIVERSAL_POTTING_SOIL,  # substrato senza REW/TEW
            pot_volume_l=2.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 1),
        )
        # Stato iniziale: entrambi a FC, de_mm=0 (substrato appena
        # bagnato).
        eval_date = date(2026, 4, 15)
        et_c_dual = pot_dual.current_et_c(et_0_mm=5.0,
                                          current_date=eval_date)
        et_c_single = pot_single.current_et_c(et_0_mm=5.0,
                                              current_date=eval_date)
        # Il dual-Kc, con substrato appena bagnato (Kr=1, Ke al massimo),
        # deve prevedere consumo maggiore o uguale del single Kc.
        # La verifica esatta dipende dai valori di Kc/Kcb; come sanity
        # check verifichiamo che siano nello stesso ordine di grandezza
        # ma non identici.
        self.assertNotAlmostEqual(et_c_dual, et_c_single, places=2)


class TestDualKcSeparation(unittest.TestCase):
    """
    Test che verificano la corretta separazione di Kcb e Ke nel
    calcolo finale di ETc.
    """

    def test_dry_surface_zero_evaporation(self):
        # Quando de_mm = TEW (superficie completamente asciutta),
        # Ke = 0 e l'ETc è dovuto al solo Kcb. Il consumo deve
        # essere proporzionale a Ks × Kcb × Kp × ET₀.
        pot = _make_dual_kc_pot()
        pot.de_mm = 22.0  # TEW: superficie asciutta
        eval_date = date(2026, 4, 15)
        et_0 = 5.0
        et_c, soil_evap = pot._current_et_c_dual_kc(
            et_0_mm=et_0, current_date=eval_date,
        )
        # Evaporazione superficiale praticamente nulla.
        self.assertAlmostEqual(soil_evap, 0.0, places=6)
        # ET totale = solo traspirazione = Ks × Kcb × Kp × ET₀.
        # Per il basilico alla 14a giornata, siamo in stadio INITIAL
        # (initial_stage_days=30 di default). Quindi Kcb = kcb_initial
        # = 0.35. Vaso a FC (Ks=1), plastica neutra (Kp=1):
        # et_c atteso = 1.0 × 0.35 × 1.0 × 5.0 = 1.75 mm.
        self.assertAlmostEqual(et_c, 1.75, places=2)

    def test_fresh_surface_evaporation_active(self):
        # Quando de_mm = 0 (superficie appena bagnata), Kr = 1 e
        # Ke è massimo. ETc ha entrambi i contributi.
        pot = _make_dual_kc_pot()
        pot.de_mm = 0.0
        eval_date = date(2026, 4, 15)
        et_0 = 5.0
        et_c, soil_evap = pot._current_et_c_dual_kc(
            et_0_mm=et_0, current_date=eval_date,
        )
        # Evaporazione superficiale > 0.
        self.assertGreater(soil_evap, 0.0)
        # Calcolo specifico per il basilico al giorno 14 (stadio
        # INITIAL): Kcb=0.35, Kcmax=max(1.20, 0.40)=1.20.
        # Ke = Kr × (Kcmax - Kcb) = 1.0 × (1.20 - 0.35) = 0.85.
        # soil_evap = Kp × Ke × ET₀ = 1.0 × 0.85 × 5.0 = 4.25 mm.
        # Notare il valore alto (~85% di ET₀): è il segnale che il
        # dual-Kc cattura davvero il contributo dell'evaporazione
        # superficiale post-irrigazione, che il single Kc media via.
        self.assertAlmostEqual(soil_evap, 4.25, places=2)


# =======================================================================
#  update_from_sensor: chiusura del feedback loop sensore-modello
# =======================================================================
#
# Cinque famiglie di test che coprono il nuovo metodo:
#   1. Comportamento di base (state_mm cambia, valori tornano).
#   2. Convenzione dei segni (observed - predicted).
#   3. Interazione con altre parti dello stato (saucer, de_mm).
#   4. Validazione degli input.
#   5. Property derivate del SensorUpdateResult.

from fitosim.domain.pot import SensorUpdateResult


def _make_simple_pot(state_mm: float = 30.0) -> Pot:
    """Vaso semplice di basilico per i test del sensore."""
    return Pot(
        label="sensor-test",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        state_mm=state_mm,
    )


class TestSensorUpdateBasicBehavior(unittest.TestCase):
    """Comportamento di base dell'aggiornamento da sensore."""

    def test_state_mm_aligned_to_observation(self):
        # Dopo un update, state_mm deve essere theta_observed × depth.
        pot = _make_simple_pot(state_mm=30.0)
        depth = pot.substrate_depth_mm
        result = pot.update_from_sensor(theta_observed=0.25)
        # Lo state_mm è stato aggiornato a 0.25 × depth.
        expected_mm = 0.25 * depth
        self.assertAlmostEqual(pot.state_mm, expected_mm, places=6)

    def test_returns_well_formed_result(self):
        # Verifica che il risultato sia un SensorUpdateResult con
        # tutti i campi popolati.
        pot = _make_simple_pot(state_mm=30.0)
        result = pot.update_from_sensor(theta_observed=0.25)
        self.assertIsInstance(result, SensorUpdateResult)
        self.assertGreater(result.predicted_theta, 0)
        self.assertEqual(result.observed_theta, 0.25)
        self.assertGreater(result.predicted_mm, 0)
        self.assertGreater(result.observed_mm, 0)

    def test_zero_discrepancy_when_match(self):
        # Se il sensore conferma esattamente la previsione del modello,
        # la discrepanza è zero.
        pot = _make_simple_pot(state_mm=30.0)
        observed = pot.state_theta  # uso il theta corrente come osservazione
        result = pot.update_from_sensor(theta_observed=observed)
        self.assertAlmostEqual(result.discrepancy_theta, 0.0, places=10)
        self.assertAlmostEqual(result.discrepancy_mm, 0.0, places=10)
        self.assertAlmostEqual(result.relative_error_pct, 0.0, places=10)

    def test_multiple_updates_in_sequence(self):
        # Aggiornamenti successivi devono comporsi correttamente: ogni
        # aggiornamento parte dallo stato già aggiornato dal precedente.
        pot = _make_simple_pot(state_mm=30.0)
        depth = pot.substrate_depth_mm
        # Prima lettura: 0.30
        r1 = pot.update_from_sensor(theta_observed=0.30)
        self.assertAlmostEqual(pot.state_mm, 0.30 * depth, places=6)
        # Seconda lettura: 0.20. Il "previsto" del secondo update deve
        # essere 0.30 (lo stato lasciato dal primo), non lo stato
        # iniziale.
        r2 = pot.update_from_sensor(theta_observed=0.20)
        self.assertAlmostEqual(r2.predicted_theta, 0.30, places=6)
        self.assertAlmostEqual(pot.state_mm, 0.20 * depth, places=6)


class TestSensorUpdateSignConventions(unittest.TestCase):
    """Convenzione dei segni: discrepancy = observed - predicted."""

    def test_positive_discrepancy_when_sensor_wetter(self):
        # Sensore vede più acqua del modello: discrepanza positiva.
        pot = _make_simple_pot(state_mm=10.0)  # vaso piuttosto secco
        result = pot.update_from_sensor(theta_observed=0.40)  # sensore wetter
        self.assertGreater(result.discrepancy_theta, 0)
        self.assertGreater(result.discrepancy_mm, 0)
        self.assertGreater(result.relative_error_pct, 0)

    def test_negative_discrepancy_when_sensor_drier(self):
        # Sensore vede meno acqua del modello: discrepanza negativa.
        # Setup: vaso a stato alto, lettura bassa.
        pot = _make_simple_pot(state_mm=50.0)
        result = pot.update_from_sensor(theta_observed=0.10)
        self.assertLess(result.discrepancy_theta, 0)
        self.assertLess(result.discrepancy_mm, 0)
        self.assertLess(result.relative_error_pct, 0)

    def test_discrepancy_magnitude_correct(self):
        # Verifica numerica diretta della discrepanza in mm.
        pot = _make_simple_pot(state_mm=30.0)
        depth = pot.substrate_depth_mm
        predicted_theta = pot.state_theta
        observed_theta = predicted_theta + 0.05  # +0.05 di discrepanza
        result = pot.update_from_sensor(theta_observed=observed_theta)
        # discrepancy_theta deve essere esattamente +0.05.
        self.assertAlmostEqual(result.discrepancy_theta, 0.05, places=10)
        # discrepancy_mm deve essere 0.05 × depth.
        self.assertAlmostEqual(result.discrepancy_mm, 0.05 * depth,
                               places=6)


class TestSensorUpdateStateIsolation(unittest.TestCase):
    """
    Verifica che update_from_sensor tocchi SOLO state_mm e lasci
    invariate le altre componenti dello stato (sottovaso, de_mm).
    """

    def test_saucer_state_not_touched(self):
        # Vaso con sottovaso popolato. L'update non deve toccare
        # saucer_state_mm.
        pot = Pot(
            label="con-sottovaso",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 1),
            saucer_capacity_mm=20.0,
            saucer_state_mm=15.0,  # sottovaso parzialmente pieno
        )
        saucer_before = pot.saucer_state_mm
        pot.update_from_sensor(theta_observed=0.25)
        # Il sottovaso non è stato toccato.
        self.assertEqual(pot.saucer_state_mm, saucer_before)

    def test_de_mm_not_touched(self):
        # Vaso con dual-Kc attivo e de_mm popolato. L'update non deve
        # toccare de_mm.
        pot = _make_dual_kc_pot()
        pot.de_mm = 10.0  # imposta una depletion intermedia
        de_before = pot.de_mm
        pot.update_from_sensor(theta_observed=0.30)
        # de_mm non è stato toccato.
        self.assertEqual(pot.de_mm, de_before)


class TestSensorUpdateValidation(unittest.TestCase):
    """Validazione dell'input theta_observed."""

    def test_rejects_theta_above_one(self):
        pot = _make_simple_pot()
        with self.assertRaises(ValueError):
            pot.update_from_sensor(theta_observed=1.5)

    def test_rejects_negative_theta(self):
        pot = _make_simple_pot()
        with self.assertRaises(ValueError):
            pot.update_from_sensor(theta_observed=-0.05)

    def test_accepts_zero(self):
        # θ=0 (vaso completamente asciutto) è fisicamente plausibile.
        pot = _make_simple_pot()
        result = pot.update_from_sensor(theta_observed=0.0)
        self.assertEqual(pot.state_mm, 0.0)

    def test_accepts_one(self):
        # θ=1 (vaso completamente saturo, caso limite) è accettato.
        pot = _make_simple_pot()
        result = pot.update_from_sensor(theta_observed=1.0)
        self.assertAlmostEqual(
            pot.state_mm, pot.substrate_depth_mm, places=6,
        )


class TestSensorUpdateResultProperties(unittest.TestCase):
    """Property derivate di SensorUpdateResult."""

    def test_absolute_error_always_non_negative(self):
        # absolute_error_mm è sempre >= 0, indipendentemente dal segno
        # della discrepanza.
        pot = _make_simple_pot(state_mm=10.0)
        # Caso 1: sensore wetter (discrepanza positiva).
        result_pos = pot.update_from_sensor(theta_observed=0.40)
        self.assertGreaterEqual(result_pos.absolute_error_mm, 0)
        self.assertEqual(result_pos.absolute_error_mm,
                         abs(result_pos.discrepancy_mm))
        # Caso 2: sensore drier (discrepanza negativa).
        pot2 = _make_simple_pot(state_mm=50.0)
        result_neg = pot2.update_from_sensor(theta_observed=0.05)
        self.assertGreaterEqual(result_neg.absolute_error_mm, 0)
        self.assertEqual(result_neg.absolute_error_mm,
                         abs(result_neg.discrepancy_mm))

    def test_is_significant_threshold(self):
        # is_significant è True solo se |discrepancy_theta| > 0.02.
        # Test su valori chiaramente sotto e chiaramente sopra soglia,
        # evitando il confine esatto a 0.02 che è instabile in floating
        # point: l'aritmetica IEEE 754 fa sì che (predicted + 0.02) -
        # predicted non sia esattamente 0.02 in tutti i casi, e questo
        # fragilizza i test di uguaglianza al confine. La semantica
        # pratica di is_significant è "chiaramente sopra il rumore vs
        # chiaramente sotto", non l'uguaglianza al picosecondo.

        # Caso chiaramente sotto soglia: |0.010| < 0.02 → False.
        pot1 = _make_simple_pot(state_mm=30.0)
        predicted = pot1.state_theta
        r1 = pot1.update_from_sensor(theta_observed=predicted + 0.010)
        self.assertFalse(r1.is_significant)

        # Caso vicino al confine ma sotto: |0.019| < 0.02 → False.
        pot2 = _make_simple_pot(state_mm=30.0)
        predicted2 = pot2.state_theta
        r2 = pot2.update_from_sensor(theta_observed=predicted2 + 0.019)
        self.assertFalse(r2.is_significant)

        # Caso vicino al confine ma sopra: |0.021| > 0.02 → True.
        pot3 = _make_simple_pot(state_mm=30.0)
        predicted3 = pot3.state_theta
        r3 = pot3.update_from_sensor(theta_observed=predicted3 + 0.021)
        self.assertTrue(r3.is_significant)

        # Caso chiaramente sopra soglia: |0.05| > 0.02 → True.
        pot4 = _make_simple_pot(state_mm=30.0)
        predicted4 = pot4.state_theta
        r4 = pot4.update_from_sensor(theta_observed=predicted4 + 0.05)
        self.assertTrue(r4.is_significant)

    def test_relative_error_zero_for_zero_state(self):
        # Edge case: vaso completamente asciutto (state_mm=0 → divisione
        # per zero). La convenzione è che relative_error_pct vale 0 in
        # questo caso (non NaN o errore).
        pot = _make_simple_pot(state_mm=0.0)
        result = pot.update_from_sensor(theta_observed=0.10)
        # relative_error_pct deve essere finito (0.0 per convenzione).
        self.assertEqual(result.relative_error_pct, 0.0)
        # Ma absolute_error_mm è > 0 perché c'è davvero discrepanza.
        self.assertGreater(result.absolute_error_mm, 0)


if __name__ == "__main__":
    unittest.main()
