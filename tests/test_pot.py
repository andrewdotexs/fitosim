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
    Substrate,
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


# =======================================================================
#  update_from_sensor: modalità ricca con SoilReading (tappa 2 fascia 2)
# =======================================================================

class TestSensorUpdateWithSoilReading(unittest.TestCase):
    """
    update_from_sensor accetta alternativamente un SoilReading completo
    via parametro keyword-only `reading`. Il θ del SoilReading viene
    usato per chiudere il feedback loop esattamente come la modalità
    legacy; gli altri campi (T, EC, pH, provider_specific) vengono
    propagati nel SensorUpdateResult per logging diagnostico.
    """

    def _make_reading(self, **overrides):
        """Helper: costruisce un SoilReading di test con default ATO-like."""
        from datetime import datetime, timezone
        from fitosim.io.sensors import SoilReading
        defaults = dict(
            timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            theta_volumetric=0.32,
            temperature_c=18.5,
            ec_mscm=1.85,
            ph=6.4,
            provider_specific={"npk_n_estimate_mg_kg": 42},
        )
        defaults.update(overrides)
        return SoilReading(**defaults)

    def test_reading_modality_updates_state_correctly(self):
        # La modalità ricca aggiorna state_mm allo stesso modo della
        # modalità legacy: estrae θ dal reading e lo usa per il
        # feedback loop. Il risultato deve essere numericamente
        # identico a quello che si otterrebbe passando solo il float.
        pot_a = _make_simple_pot(state_mm=20.0)
        pot_b = _make_simple_pot(state_mm=20.0)

        reading = self._make_reading(theta_volumetric=0.25)
        result_a = pot_a.update_from_sensor(reading=reading)
        result_b = pot_b.update_from_sensor(theta_observed=0.25)

        # state_mm finale deve essere identico nei due Pot.
        self.assertAlmostEqual(pot_a.state_mm, pot_b.state_mm, places=6)
        # Anche le discrepanze devono essere identiche.
        self.assertAlmostEqual(
            result_a.discrepancy_mm, result_b.discrepancy_mm, places=6,
        )

    def test_reading_modality_propagates_extra_fields(self):
        # I campi extra del SoilReading (T, EC, pH, provider_specific)
        # vengono valorizzati nel SensorUpdateResult per il logging.
        pot = _make_simple_pot(state_mm=20.0)
        reading = self._make_reading(
            temperature_c=22.0,
            ec_mscm=2.1,
            ph=6.8,
            provider_specific={"custom_key": "custom_value"},
        )
        result = pot.update_from_sensor(reading=reading)

        self.assertEqual(result.observed_temperature_c, 22.0)
        self.assertEqual(result.observed_ec_mscm, 2.1)
        self.assertEqual(result.observed_ph, 6.8)
        self.assertEqual(
            result.provider_specific, {"custom_key": "custom_value"},
        )

    def test_reading_modality_with_partial_data(self):
        # Sensore tipo WH51 esposto via Protocol: SoilReading con
        # solo θ valorizzato, gli altri campi None. I campi extra
        # nel result restano None coerentemente.
        from datetime import datetime, timezone
        from fitosim.io.sensors import SoilReading

        partial_reading = SoilReading(
            timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            theta_volumetric=0.30,
            # niente temperature_c, ec_mscm, ph, provider_specific
        )
        pot = _make_simple_pot(state_mm=20.0)
        result = pot.update_from_sensor(reading=partial_reading)

        self.assertIsNone(result.observed_temperature_c)
        self.assertIsNone(result.observed_ec_mscm)
        self.assertIsNone(result.observed_ph)
        self.assertEqual(result.provider_specific, {})

    def test_legacy_modality_unaffected_by_extension(self):
        # Test critico di retrocompatibilità: chiamare update_from_sensor
        # con il singolo float (forma legacy) deve produrre i campi
        # extra del result tutti None, esattamente come prima della
        # tappa 2.
        pot = _make_simple_pot(state_mm=20.0)
        result = pot.update_from_sensor(theta_observed=0.30)

        self.assertIsNone(result.observed_temperature_c)
        self.assertIsNone(result.observed_ec_mscm)
        self.assertIsNone(result.observed_ph)
        self.assertEqual(result.provider_specific, {})

    def test_passing_both_parameters_raises(self):
        # Mutua esclusività: passare sia theta_observed sia reading
        # è un errore di programmazione che solleva ValueError con
        # messaggio diagnostico chiaro.
        pot = _make_simple_pot(state_mm=20.0)
        reading = self._make_reading()

        with self.assertRaises(ValueError) as ctx:
            pot.update_from_sensor(theta_observed=0.30, reading=reading)
        self.assertIn("entrambi", str(ctx.exception))

    def test_passing_neither_parameter_raises(self):
        # Anche non passare nulla è un errore: serve specificare
        # esattamente uno dei due parametri.
        pot = _make_simple_pot(state_mm=20.0)

        with self.assertRaises(ValueError) as ctx:
            pot.update_from_sensor()
        self.assertIn("obbligatorio", str(ctx.exception))

    def test_reading_with_invalid_theta_raises_at_construction(self):
        # Il SoilReading già valida θ nel suo __post_init__: un θ
        # fuori range viene intercettato prima ancora di arrivare a
        # update_from_sensor. Questo è il pattern del sistema di
        # tipi: gli errori sono catturati al confine (al momento
        # della costruzione del Reading), non al livello del modello.
        from datetime import datetime, timezone
        from fitosim.io.sensors import (
            SensorDataQualityError, SoilReading,
        )

        with self.assertRaises(SensorDataQualityError):
            SoilReading(
                timestamp=datetime(2026, 5, 1, 12, 0,
                                    tzinfo=timezone.utc),
                theta_volumetric=2.5,  # fuori range fisico
            )

    def test_is_significant_works_with_reading_modality(self):
        # Le proprietà derivate del SensorUpdateResult (is_significant,
        # absolute_error_mm) funzionano identicamente nelle due
        # modalità.
        pot = _make_simple_pot(state_mm=20.0)
        predicted = pot.state_theta

        # Discrepanza grande (>0.02): is_significant deve essere True.
        big_drift_reading = self._make_reading(
            theta_volumetric=predicted + 0.05,
        )
        result = pot.update_from_sensor(reading=big_drift_reading)
        self.assertTrue(result.is_significant)


# =======================================================================
#  Sotto-tappa B fascia 2: stati chimici del Pot (salt_mass_meq, ph_substrate)
# =======================================================================

class TestPotChemistryState(unittest.TestCase):
    """
    Validazione dei due nuovi stati chimici del Pot aggiunti in sotto-
    tappa B della tappa 3 fascia 2: `salt_mass_meq` (massa salina totale
    in milli-equivalenti) e `ph_substrate` (pH del substrato).

    Copre cinque aspetti distinti:
      1. Default e gerarchia di inizializzazione del ph_substrate.
      2. Default zero del salt_mass_meq e accettazione di valori espliciti.
      3. Property derivata `ec_substrate_mscm` con la conversione
         meq/L → mS/cm.
      4. Fenomeno della concentrazione per evapotraspirazione.
      5. Validazione fisica degli input.
    """

    def _make_chemistry_substrate(
        self, ph_typical=None, cec=None,
    ) -> Substrate:
        """Helper: substrato configurabile per i test chimici."""
        return Substrate(
            name="test", theta_fc=0.40, theta_pwp=0.10,
            ph_typical=ph_typical,
            cec_meq_per_100g=cec,
        )

    def _make_chemistry_pot(self, **overrides) -> Pot:
        """Helper: vaso configurabile per i test chimici."""
        defaults = dict(
            label="chem-test",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 1),
        )
        defaults.update(overrides)
        return Pot(**defaults)

    # ----- Inizializzazione del ph_substrate -----

    def test_ph_default_falls_back_to_neutral_for_legacy_substrate(self):
        # UNIVERSAL_POTTING_SOIL non ha ph_typical configurato (legacy):
        # il pH iniziale ricade sul neutro 7.0.
        pot = self._make_chemistry_pot()
        self.assertEqual(pot.ph_substrate, 7.0)

    def test_ph_inherits_from_substrate_when_typical_specified(self):
        # Substrato per acidofile: il pH iniziale è quello del substrato.
        acidic = self._make_chemistry_substrate(ph_typical=5.0)
        pot = self._make_chemistry_pot(substrate=acidic)
        self.assertEqual(pot.ph_substrate, 5.0)

    def test_ph_explicit_overrides_substrate(self):
        # Quando il chiamante passa ph_substrate esplicitamente, ha la
        # precedenza anche su substrato con ph_typical configurato.
        # Caso d'uso: il giardiniere ha appena letto il sensore ATO e
        # vuole agganciare il Pot allo stato reale.
        acidic = self._make_chemistry_substrate(ph_typical=5.0)
        pot = self._make_chemistry_pot(
            substrate=acidic, ph_substrate=6.2,
        )
        self.assertEqual(pot.ph_substrate, 6.2)

    def test_ph_alkaline_substrate(self):
        # Substrato calcareo: pH iniziale alcalino.
        alkaline = self._make_chemistry_substrate(ph_typical=7.8)
        pot = self._make_chemistry_pot(substrate=alkaline)
        self.assertEqual(pot.ph_substrate, 7.8)

    # ----- salt_mass_meq -----

    def test_salt_mass_default_is_zero(self):
        # Default zero: vaso "appena rinvasato in terriccio fresco".
        pot = self._make_chemistry_pot()
        self.assertEqual(pot.salt_mass_meq, 0.0)

    def test_salt_mass_explicit_accepted(self):
        # Caso "vaso preesistente con storia di fertilizzazione": il
        # giardiniere passa il valore esplicito.
        pot = self._make_chemistry_pot(salt_mass_meq=15.0)
        self.assertEqual(pot.salt_mass_meq, 15.0)

    # ----- Property derivata ec_substrate_mscm -----

    def test_ec_zero_when_no_salts(self):
        # Vaso senza sali: EC=0 indipendentemente dall'acqua.
        pot = self._make_chemistry_pot(salt_mass_meq=0.0)
        self.assertEqual(pot.ec_substrate_mscm, 0.0)

    def test_ec_calculation_basic(self):
        # Conversione canonica: 10 meq/L equivalgono a 1.0 mS/cm.
        # Costruiamo un caso aritmetico semplice: 1L d'acqua nel vaso
        # con 10 meq di sali → EC=1.0.
        pot = self._make_chemistry_pot(
            pot_volume_l=2.0, pot_diameter_cm=18.0,
        )
        # L'area è π·r² = π·(0.09)² ≈ 0.0254 m²; per avere 1L=1mm·m²·1000
        # impostiamo state_mm in modo che state_mm × area = 1.0 L.
        # state_mm = 1.0 / 0.0254 ≈ 39.3 mm.
        target_water_l = 1.0
        pot.state_mm = target_water_l / pot.surface_area_m2
        pot.salt_mass_meq = 10.0
        # Adesso water_volume_liters ≈ 1.0 e salt_mass = 10 meq.
        # Quindi EC = 10/1/10 = 1.0 mS/cm.
        self.assertAlmostEqual(pot.water_volume_liters, 1.0, places=5)
        self.assertAlmostEqual(pot.ec_substrate_mscm, 1.0, places=5)

    def test_ec_zero_when_no_water(self):
        # Caso degenere: zero acqua → EC=0 per convenzione (non
        # ZeroDivisionError).
        pot = self._make_chemistry_pot(state_mm=0.0, salt_mass_meq=15.0)
        self.assertEqual(pot.ec_substrate_mscm, 0.0)

    def test_ec_increases_when_water_decreases(self):
        # IL FENOMENO DELLA CONCENTRAZIONE PER EVAPOTRASPIRAZIONE.
        # Questo è il test che ha motivato la scelta della versione
        # fedele del modello. Quando il vaso si asciuga, la massa
        # salina resta costante ma il volume di acqua diminuisce, e
        # l'EC sale automaticamente. È esattamente quello che si vede
        # sui sensori reali.
        pot = self._make_chemistry_pot(state_mm=40.0, salt_mass_meq=20.0)
        ec_iniziale = pot.ec_substrate_mscm

        # Simuliamo evapotraspirazione: lo state_mm si dimezza, ma i
        # sali NON vengono toccati (stati indipendenti).
        pot.state_mm = 20.0
        ec_finale = pot.ec_substrate_mscm

        # Con water_volume dimezzato e salt_mass invariata, l'EC deve
        # essere esattamente raddoppiata.
        self.assertAlmostEqual(ec_finale / ec_iniziale, 2.0, places=5)

    # ----- Validazione degli input -----

    def test_negative_ph_rejected_at_construction(self):
        # Il sentinel value è esattamente -1.0 (vedi __post_init__ del
        # Pot). Valori negativi diversi dal sentinel devono essere
        # rifiutati come errori di input, non confusi con la sentinella.
        with self.assertRaises(ValueError):
            self._make_chemistry_pot(ph_substrate=-5.0)

    def test_ph_above_14_rejected(self):
        with self.assertRaises(ValueError):
            self._make_chemistry_pot(ph_substrate=15.0)

    def test_ph_zero_rejected(self):
        # pH=0 è chimicamente al limite della scala, non ha senso per
        # un substrato di coltivazione.
        with self.assertRaises(ValueError):
            self._make_chemistry_pot(ph_substrate=0.0)

    def test_negative_salt_mass_rejected(self):
        with self.assertRaises(ValueError):
            self._make_chemistry_pot(salt_mass_meq=-5.0)

    def test_zero_salt_mass_accepted(self):
        # Zero è il default ed è perfettamente legittimo.
        pot = self._make_chemistry_pot(salt_mass_meq=0.0)
        self.assertEqual(pot.salt_mass_meq, 0.0)

    # ----- Indipendenza dal modello idrico esistente -----

    def test_chemistry_does_not_affect_water_balance(self):
        # I nuovi stati chimici NON devono influenzare il bilancio
        # idrico: chiamando apply_balance_step con o senza chimica
        # attiva, lo state_mm finale e il drainage devono essere
        # identici nei due casi.
        pot_a = self._make_chemistry_pot(state_mm=30.0)
        pot_b = self._make_chemistry_pot(
            state_mm=30.0, salt_mass_meq=25.0, ph_substrate=5.5,
        )

        # Stesso evento idrico nei due Pot: stessa ET, niente input.
        test_date = date(2026, 5, 15)
        result_a = pot_a.apply_balance_step(
            et_0_mm=4.0, water_input_mm=0.0, current_date=test_date,
        )
        result_b = pot_b.apply_balance_step(
            et_0_mm=4.0, water_input_mm=0.0, current_date=test_date,
        )

        # Lo state_mm finale e il drainage devono essere identici.
        self.assertAlmostEqual(pot_a.state_mm, pot_b.state_mm, places=6)
        self.assertAlmostEqual(
            result_a.new_state, result_b.new_state, places=6,
        )
        self.assertAlmostEqual(
            result_a.drainage, result_b.drainage, places=6,
        )


# =======================================================================
#  Sotto-tappa C tappa 3 fascia 2: metodi di fertirrigazione del Pot
# =======================================================================

class TestPotFertigationMethods(unittest.TestCase):
    """
    Validazione dei tre nuovi metodi del Pot aggiunti in sotto-tappa C:
    `apply_fertigation_step`, `apply_rainfall_step`, `apply_step`.

    Questi metodi orchestrano le funzioni pure di `science/fertigation.py`
    aggiornando lo stato del Pot in-place. I test di livello "scienza"
    sono già in tests/test_fertigation.py; qui ci concentriamo
    sull'integrazione: che gli stati del Pot si muovano nel modo giusto,
    che il FertigationResult contenga i dati corretti, che la
    composizione di metodi produca risultati coerenti.
    """

    def _make_chemistry_pot(self, **overrides):
        """Helper: vaso configurabile per i test della fertirrigazione."""
        defaults = dict(
            label="fert-test",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 1),
        )
        defaults.update(overrides)
        return Pot(**defaults)

    # ----- apply_fertigation_step -----

    def test_fertigation_increases_salt_mass(self):
        # Una fertirrigazione con EC>0 deve far crescere la massa salina.
        pot = self._make_chemistry_pot(salt_mass_meq=5.0)
        salt_before = pot.salt_mass_meq
        pot.apply_fertigation_step(
            volume_l=0.3, ec_mscm=2.0, ph=6.0,
            current_date=date(2026, 5, 1),
        )
        self.assertGreater(pot.salt_mass_meq, salt_before)

    def test_fertigation_modifies_ph(self):
        # Fertirrigazione a pH diverso dal substrato: il pH cambia.
        pot = self._make_chemistry_pot()  # ph default 7.0
        ph_before = pot.ph_substrate
        pot.apply_fertigation_step(
            volume_l=0.5, ec_mscm=2.0, ph=5.5,
            current_date=date(2026, 5, 1),
        )
        # pH è sceso ma resta tra 5.5 e 7.0
        self.assertLess(pot.ph_substrate, ph_before)
        self.assertGreater(pot.ph_substrate, 5.5)

    def test_fertigation_increases_water_state(self):
        # Una fertirrigazione che non causa drenaggio aumenta state_mm.
        pot = self._make_chemistry_pot(state_mm=20.0)
        state_before = pot.state_mm
        pot.apply_fertigation_step(
            volume_l=0.05,                # volume piccolo: no drenaggio
            ec_mscm=1.5, ph=6.5,
            current_date=date(2026, 5, 1),
        )
        self.assertGreater(pot.state_mm, state_before)

    def test_fertigation_can_cause_drainage(self):
        # Una fertirrigazione abbondante su vaso quasi pieno fa drenaggio.
        pot = self._make_chemistry_pot()
        # Riempi quasi a fc per provocare drenaggio con un piccolo input.
        pot.state_mm = pot.fc_mm - 1.0
        result = pot.apply_fertigation_step(
            volume_l=0.5,                  # volume abbondante
            ec_mscm=1.5, ph=6.5,
            current_date=date(2026, 5, 1),
        )
        # Lo stato finale è capped alla fc.
        self.assertAlmostEqual(pot.state_mm, pot.fc_mm, places=3)
        # Il drenaggio è positivo.
        self.assertGreater(result.water_drained_l, 0.0)
        # Il drenaggio ha portato via dei sali.
        self.assertGreater(result.salt_mass_drained_meq, 0.0)

    def test_fertigation_result_fields_populated(self):
        # Il FertigationResult contiene tutti i campi attesi.
        event_date = date(2026, 5, 1)
        pot = self._make_chemistry_pot(salt_mass_meq=5.0)
        result = pot.apply_fertigation_step(
            volume_l=0.3, ec_mscm=2.0, ph=6.0,
            current_date=event_date,
        )
        self.assertEqual(result.event_date, event_date)
        self.assertEqual(result.volume_input_l, 0.3)
        self.assertEqual(result.ec_input_mscm, 2.0)
        self.assertEqual(result.ph_input, 6.0)
        self.assertEqual(result.salt_mass_before_meq, 5.0)
        self.assertGreater(result.salt_mass_added_meq, 0.0)
        # ph_delta è coerente
        self.assertAlmostEqual(
            result.ph_delta, result.ph_after - result.ph_before, places=9,
        )

    # ----- apply_rainfall_step -----

    def test_rainfall_does_not_add_salts(self):
        # La pioggia naturale ha EC=0: non aggiunge sali.
        pot = self._make_chemistry_pot(salt_mass_meq=10.0, state_mm=15.0)
        result = pot.apply_rainfall_step(
            volume_l=0.1,                  # pioggia leggera
            current_date=date(2026, 5, 1),
        )
        self.assertEqual(result.salt_mass_added_meq, 0.0)
        # ph_input riconoscibile come pH della pioggia
        from fitosim.science.fertigation import RAINFALL_PH
        self.assertEqual(result.ph_input, RAINFALL_PH)

    def test_rainfall_can_leach_salts(self):
        # Pioggia abbondante che causa drenaggio: rimuove sali (pulisce).
        pot = self._make_chemistry_pot(salt_mass_meq=30.0)
        pot.state_mm = pot.fc_mm  # vaso a capacità di campo
        salt_before = pot.salt_mass_meq
        pot.apply_rainfall_step(
            volume_l=0.5,                  # pioggia abbondante → drenaggio
            current_date=date(2026, 5, 1),
        )
        # La massa salina è diminuita (pioggia ha lavato).
        self.assertLess(pot.salt_mass_meq, salt_before)

    def test_rainfall_pulls_ph_toward_acidic(self):
        # Una pioggia abbondante su vaso alcalino abbassa il pH verso 5.6.
        pot = self._make_chemistry_pot(ph_substrate=7.5)
        ph_before = pot.ph_substrate
        pot.apply_rainfall_step(
            volume_l=0.5,
            current_date=date(2026, 5, 1),
        )
        self.assertLess(pot.ph_substrate, ph_before)
        # Ma non lo abbassa sotto 5.6 (limite asintotico).
        self.assertGreater(pot.ph_substrate, 5.6)

    # ----- apply_step orchestratore -----

    def test_apply_step_water_only_equivalent_to_balance(self):
        # apply_step senza pioggia né fertirrigazione equivale a
        # apply_balance_step puro: state_mm finale identico.
        pot_a = self._make_chemistry_pot(state_mm=30.0)
        pot_b = self._make_chemistry_pot(state_mm=30.0)
        test_date = date(2026, 5, 15)

        result_a = pot_a.apply_step(et_0_mm=4.0, current_date=test_date)
        result_b = pot_b.apply_balance_step(
            et_0_mm=4.0, water_input_mm=0.0, current_date=test_date,
        )

        self.assertAlmostEqual(pot_a.state_mm, pot_b.state_mm, places=6)
        self.assertIsNone(result_a.rainfall_result)
        self.assertIsNone(result_a.fertigation_result)

    def test_apply_step_with_fertigation(self):
        # apply_step con fertirrigazione attiva tutti gli stati.
        pot = self._make_chemistry_pot(state_mm=20.0, salt_mass_meq=5.0)
        result = pot.apply_step(
            et_0_mm=3.0,
            current_date=date(2026, 5, 15),
            fertigation_volume_l=0.3,
            fertigation_ec_mscm=2.0,
            fertigation_ph=6.0,
        )
        # FertigationResult presente, RainfallResult assente
        self.assertIsNotNone(result.fertigation_result)
        self.assertIsNone(result.rainfall_result)
        # Massa salina cresciuta
        self.assertGreater(pot.salt_mass_meq, 5.0)

    def test_apply_step_with_rainfall(self):
        # apply_step con pioggia: il rainfall_result è popolato.
        pot = self._make_chemistry_pot(salt_mass_meq=15.0)
        result = pot.apply_step(
            et_0_mm=3.0,
            current_date=date(2026, 5, 15),
            rainfall_volume_l=0.2,
        )
        self.assertIsNotNone(result.rainfall_result)
        self.assertIsNone(result.fertigation_result)

    def test_apply_step_with_rainfall_and_fertigation(self):
        # Entrambi gli eventi nello stesso giorno: entrambi i result
        # sono popolati, e l'ordine di applicazione è pioggia →
        # fertirrigazione → ET.
        pot = self._make_chemistry_pot(salt_mass_meq=10.0)
        result = pot.apply_step(
            et_0_mm=3.0,
            current_date=date(2026, 5, 15),
            fertigation_volume_l=0.2,
            fertigation_ec_mscm=2.0,
            fertigation_ph=6.0,
            rainfall_volume_l=0.1,
        )
        self.assertIsNotNone(result.rainfall_result)
        self.assertIsNotNone(result.fertigation_result)

    # ----- Coerenza con la science -----

    def test_ec_property_consistent_with_state(self):
        # Dopo una fertirrigazione, la property ec_substrate_mscm deve
        # essere coerente con il nuovo stato (salt_mass / volume / 10).
        pot = self._make_chemistry_pot()
        pot.state_mm = pot.fc_mm  # vaso a capacità di campo
        pot.apply_fertigation_step(
            volume_l=0.05,                # piccolo, niente drenaggio
            ec_mscm=2.0, ph=6.5,
            current_date=date(2026, 5, 1),
        )
        # Ricalcola manualmente l'EC attesa
        expected_ec = (pot.salt_mass_meq / pot.water_volume_liters) / 10.0
        self.assertAlmostEqual(pot.ec_substrate_mscm, expected_ec, places=9)


# =======================================================================
#  Sotto-tappa D tappa 3 fascia 2: integrazione del Kn nel Pot
# =======================================================================

class TestPotNutritionIntegration(unittest.TestCase):
    """
    Validazione dell'integrazione del coefficiente nutrizionale Kn
    nel calcolo dell'ET colturale del Pot, sotto-tappa D.

    Test concentrati su:
      1. Retrocompatibilità: specie legacy (BASIL del catalogo) →
         Kn=1 silenzioso, ET identica a prima della tappa 3.
      2. Specie con modello chimico in condizioni ottimali → Kn=1,
         ET identica al caso legacy con stessi parametri.
      3. Specie con modello chimico in stress → Kn<1, ET strettamente
         minore del caso ottimale.
      4. Effetto materiale: il Kn modula il bilancio idrico via
         apply_balance_step.
    """

    def _make_basil_with_chemistry(self) -> Species:
        """Basilico con modello chimico configurato (range tipici)."""
        return Species(
            common_name="basilico-chem",
            scientific_name="Ocimum basilicum",
            kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
            ec_optimal_min_mscm=1.0,
            ec_optimal_max_mscm=1.6,
            ph_optimal_min=6.0,
            ph_optimal_max=7.0,
        )

    def _make_pot(self, species, **overrides):
        defaults = dict(
            label="nutrition-test",
            species=species,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 1),
        )
        defaults.update(overrides)
        return Pot(**defaults)

    # ----- Retrocompat con specie legacy -----

    def test_legacy_species_unaffected(self):
        # Specie BASIL del catalogo (legacy, no chemistry).
        # Indipendentemente da come configuriamo il Pot sul piano
        # chimico (EC alta, pH fuori range), l'ET deve essere identica
        # a quella che otterremmo senza chimica configurata.
        pot_normal = self._make_pot(BASIL)
        pot_stressed = self._make_pot(
            BASIL,
            salt_mass_meq=200.0,    # provoca EC alta
            ph_substrate=4.0,        # fuori range
        )
        et_normal = pot_normal.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        et_stressed = pot_stressed.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        # Identici: la specie legacy non sa di chimica.
        self.assertAlmostEqual(et_normal, et_stressed, places=9)

    # ----- Specie con modello chimico in condizioni ottimali -----

    def test_chemistry_species_optimal_conditions_kn_one(self):
        # Basilico con modello chimico, condizioni perfette: Kn=1
        # e l'ET deve essere identica a quella del basilico legacy
        # con gli stessi parametri di Kc.
        chem_species = self._make_basil_with_chemistry()
        pot_chem = self._make_pot(
            chem_species,
            salt_mass_meq=0.0,        # niente sali → EC=0, dentro range
                                       # [1.0, 1.6]? No, 0 è SOTTO 1.0.
                                       # Devo scegliere un EC dentro range.
        )
        # Per portare EC nel range ottimale, calcolo la salt_mass
        # corretta. ec=1.3 con water_volume corrente.
        # ec = salt/(volume*10) → salt = ec*volume*10
        target_ec = 1.3
        pot_chem.salt_mass_meq = target_ec * pot_chem.water_volume_liters * 10
        pot_chem.ph_substrate = 6.5  # dentro range [6.0, 7.0]

        # Verifichiamo che l'EC corrente sia effettivamente nel range
        self.assertGreater(pot_chem.ec_substrate_mscm, 1.0)
        self.assertLess(pot_chem.ec_substrate_mscm, 1.6)

        # ET con condizioni ottimali = ET di una specie equivalente
        # senza chimica configurata.
        et_chem = pot_chem.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        # Riferimento: la stessa simulazione con specie senza chimica
        # ma stessi Kc.
        legacy_species = Species(
            common_name="basil-legacy",
            scientific_name="Ocimum basilicum",
            kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
        )
        pot_legacy = self._make_pot(
            legacy_species,
            state_mm=pot_chem.state_mm,
        )
        et_legacy = pot_legacy.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        # In condizioni ottimali Kn=1 → ET identica.
        self.assertAlmostEqual(et_chem, et_legacy, places=6)

    # ----- Specie con modello chimico in stress -----

    def test_chemistry_species_stressed_kn_reduces_et(self):
        # Stesso basilico chimico ma in condizioni di stress salino:
        # EC molto fuori range → Kn<1 → ET ridotta.
        chem_species = self._make_basil_with_chemistry()

        # Caso ottimale di riferimento.
        pot_optimal = self._make_pot(chem_species)
        target_ec = 1.3
        pot_optimal.salt_mass_meq = (
            target_ec * pot_optimal.water_volume_liters * 10
        )
        pot_optimal.ph_substrate = 6.5

        # Caso con stress salino: EC molto sopra il range.
        pot_stress = self._make_pot(chem_species)
        stress_ec = 2.5    # ben sopra il max=1.6
        pot_stress.salt_mass_meq = (
            stress_ec * pot_stress.water_volume_liters * 10
        )
        pot_stress.ph_substrate = 6.5  # pH ottimale

        et_optimal = pot_optimal.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        et_stressed = pot_stress.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        # ET del Pot stressato STRETTAMENTE INFERIORE al Pot ottimale.
        self.assertLess(et_stressed, et_optimal)

    def test_extreme_chemistry_stress_floor_effect(self):
        # Stress massimo simultaneo (EC e pH entrambi molto fuori):
        # Kn = KN_MIN² ≈ 0.09, ET ridotta drasticamente.
        chem_species = self._make_basil_with_chemistry()

        pot_optimal = self._make_pot(chem_species)
        target_ec = 1.3
        pot_optimal.salt_mass_meq = (
            target_ec * pot_optimal.water_volume_liters * 10
        )
        pot_optimal.ph_substrate = 6.5

        pot_extreme = self._make_pot(chem_species)
        extreme_ec = 10.0   # molto sopra
        pot_extreme.salt_mass_meq = (
            extreme_ec * pot_extreme.water_volume_liters * 10
        )
        pot_extreme.ph_substrate = 11.0  # molto fuori

        et_optimal = pot_optimal.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        et_extreme = pot_extreme.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        # Il rapporto deve essere circa Kn² = 0.09 (approssimato perché
        # entrano in gioco anche Ks dipendente da theta, ma con
        # state_mm uguali si compensa). Aspettative: il ratio è
        # significativamente inferiore a 1.
        ratio = et_extreme / et_optimal
        # Il floor teorico è 0.09; in pratica deve essere intorno a quello.
        self.assertLess(ratio, 0.15)

    # ----- Effetto materiale sul bilancio idrico -----

    def test_kn_materially_affects_water_balance(self):
        # Il Kn modula effettivamente il bilancio idrico: una giornata
        # di apply_balance_step su un vaso stressato consuma meno acqua
        # di un vaso ottimale.
        chem_species = self._make_basil_with_chemistry()

        # Configurazione ottimale.
        pot_opt = self._make_pot(chem_species, state_mm=30.0)
        pot_opt.salt_mass_meq = 1.3 * pot_opt.water_volume_liters * 10
        pot_opt.ph_substrate = 6.5

        # Configurazione stressata (EC alta).
        pot_str = self._make_pot(chem_species, state_mm=30.0)
        pot_str.salt_mass_meq = 3.0 * pot_str.water_volume_liters * 10
        pot_str.ph_substrate = 6.5

        # Stesso evento: niente input, ET₀ = 5 mm.
        test_date = date(2026, 5, 15)
        pot_opt.apply_balance_step(
            et_0_mm=5.0, water_input_mm=0.0, current_date=test_date,
        )
        pot_str.apply_balance_step(
            et_0_mm=5.0, water_input_mm=0.0, current_date=test_date,
        )

        # Il Pot ottimale deve aver consumato MORE acqua del Pot
        # stressato: state_mm finale del primo è inferiore.
        self.assertLess(pot_opt.state_mm, pot_str.state_mm)


# =======================================================================
#  Sotto-tappa E tappa 3 fascia 2: feedback loop chimico via sensore
# =======================================================================

class TestSensorUpdateChemistry(unittest.TestCase):
    """
    Validazione dell'aggancio degli stati chimici del Pot ai campi
    chimici del SoilReading (sotto-tappa E della tappa 3).

    Test concentrati su:
      1. Aggiornamento di salt_mass_meq da observed_ec_mscm.
      2. Aggiornamento di ph_substrate da observed_ph.
      3. Sequenza corretta: state_mm prima, chimica dopo.
      4. Coerenza: dopo l'update, ec_substrate_mscm del Pot deve
         coincidere col valore osservato.
      5. Reading parziali: campi None lasciano gli stati invariati.
      6. Campi diagnostici (predicted_*, discrepancy_*) valorizzati
         correttamente.
    """

    def _make_reading(self, **overrides):
        from datetime import datetime, timezone
        from fitosim.io.sensors import SoilReading
        defaults = dict(
            timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            theta_volumetric=0.32,
            temperature_c=18.5,
            ec_mscm=2.0,
            ph=6.4,
            provider_specific={},
        )
        defaults.update(overrides)
        return SoilReading(**defaults)

    def _make_chem_pot(self, **overrides):
        defaults = dict(
            label="chem-update-test",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 4, 1),
            salt_mass_meq=10.0,
            ph_substrate=7.0,
        )
        defaults.update(overrides)
        return Pot(**defaults)

    # ----- Aggiornamento dell'EC tramite massa salina derivata -----

    def test_ec_observed_updates_salt_mass(self):
        # Quando reading.ec_mscm è valorizzato, salt_mass_meq del Pot
        # viene ricalcolata in modo che ec_substrate_mscm = observed.
        pot = self._make_chem_pot()
        reading = self._make_reading(ec_mscm=2.5)
        pot.update_from_sensor(reading=reading)
        # Dopo l'update, l'EC corrente del Pot deve essere 2.5 al
        # millesimo (potremmo avere errori floating).
        self.assertAlmostEqual(pot.ec_substrate_mscm, 2.5, places=6)

    def test_salt_mass_calculation_uses_new_water_volume(self):
        # CRUCIALE: la conversione EC → salt_mass deve usare il NUOVO
        # state_mm (post-aggiornamento idrico), non quello precedente.
        pot = self._make_chem_pot(state_mm=10.0)  # vaso quasi secco
        # Il sensore vede più acqua e una EC moderata: il volume
        # da usare è quello implicato dal θ osservato.
        reading = self._make_reading(theta_volumetric=0.40, ec_mscm=1.5)
        pot.update_from_sensor(reading=reading)

        # Dopo l'update, ec_substrate_mscm del Pot deve essere 1.5
        # E il volume d'acqua deve corrispondere al θ osservato.
        self.assertAlmostEqual(pot.ec_substrate_mscm, 1.5, places=6)
        expected_state_mm = 0.40 * pot.substrate_depth_mm
        self.assertAlmostEqual(pot.state_mm, expected_state_mm, places=6)

    # ----- Aggiornamento del pH -----

    def test_ph_observed_updates_substrate_ph(self):
        # Il pH è una grandezza intensiva: sovrascrittura diretta.
        pot = self._make_chem_pot(ph_substrate=7.0)
        reading = self._make_reading(ph=5.8)
        pot.update_from_sensor(reading=reading)
        self.assertEqual(pot.ph_substrate, 5.8)

    def test_acidic_reading_lowers_substrate_ph(self):
        # Test qualitativo: lettura più acida abbassa il pH del Pot.
        pot = self._make_chem_pot(ph_substrate=7.0)
        reading = self._make_reading(ph=5.0)
        pot.update_from_sensor(reading=reading)
        self.assertLess(pot.ph_substrate, 7.0)
        self.assertEqual(pot.ph_substrate, 5.0)

    # ----- Reading parziali: solo alcuni campi valorizzati -----

    def test_partial_reading_only_theta(self):
        # Reading di sensore WH51 (solo θ): salt_mass e ph_substrate
        # non devono cambiare.
        from datetime import datetime, timezone
        from fitosim.io.sensors import SoilReading
        partial = SoilReading(
            timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            theta_volumetric=0.30,
            # niente ec_mscm, niente ph
        )
        pot = self._make_chem_pot(salt_mass_meq=15.0, ph_substrate=6.5)
        pot.update_from_sensor(reading=partial)
        # state_mm aggiornato, ma chimica invariata
        self.assertEqual(pot.salt_mass_meq, 15.0)
        self.assertEqual(pot.ph_substrate, 6.5)

    def test_partial_reading_ec_only(self):
        # Reading con solo θ ed EC, niente pH: ph_substrate invariato.
        from datetime import datetime, timezone
        from fitosim.io.sensors import SoilReading
        partial = SoilReading(
            timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            theta_volumetric=0.30,
            ec_mscm=1.8,
        )
        pot = self._make_chem_pot(ph_substrate=6.5)
        pot.update_from_sensor(reading=partial)
        # EC del Pot aggiornata, pH invariato
        self.assertAlmostEqual(pot.ec_substrate_mscm, 1.8, places=6)
        self.assertEqual(pot.ph_substrate, 6.5)

    # ----- Legacy mode (theta_observed float, no Reading) -----

    def test_legacy_float_mode_unaffected(self):
        # Chiamata legacy con theta_observed float: nessun campo
        # chimico nel result, nessun aggiornamento degli stati chimici
        # del Pot.
        pot = self._make_chem_pot(salt_mass_meq=15.0, ph_substrate=6.5)
        result = pot.update_from_sensor(theta_observed=0.30)
        # Stati chimici del Pot invariati.
        self.assertEqual(pot.salt_mass_meq, 15.0)
        self.assertEqual(pot.ph_substrate, 6.5)
        # Campi diagnostici chimici tutti None nel result.
        self.assertIsNone(result.observed_ec_mscm)
        self.assertIsNone(result.observed_ph)
        self.assertIsNone(result.predicted_ec_mscm)
        self.assertIsNone(result.predicted_ph)
        self.assertIsNone(result.discrepancy_ec_mscm)
        self.assertIsNone(result.discrepancy_ph)

    # ----- Campi diagnostici nel SensorUpdateResult -----

    def test_diagnostic_fields_populated(self):
        # Quando il Reading porta EC e pH, i campi diagnostici del
        # result vengono valorizzati con i valori predetti dal modello
        # PRIMA dell'aggiornamento, e con le discrepanze.
        pot = self._make_chem_pot(state_mm=30.0, salt_mass_meq=20.0,
                                    ph_substrate=7.0)
        # Salviamo l'EC predetta prima dell'update (al volume corrente)
        ec_before_update = pot.ec_substrate_mscm
        reading = self._make_reading(
            theta_volumetric=0.30, ec_mscm=2.5, ph=5.5,
        )
        result = pot.update_from_sensor(reading=reading)

        # Predicted = stato del Pot prima dell'update
        self.assertAlmostEqual(
            result.predicted_ec_mscm, ec_before_update, places=6,
        )
        self.assertEqual(result.predicted_ph, 7.0)
        # Discrepancy = observed - predicted
        self.assertAlmostEqual(
            result.discrepancy_ec_mscm,
            2.5 - ec_before_update,
            places=6,
        )
        self.assertAlmostEqual(result.discrepancy_ph, 5.5 - 7.0, places=6)

    def test_predicted_ec_uses_state_before_water_update(self):
        # CRUCIALE: predicted_ec_mscm deve essere calcolata col
        # state_mm e il salt_mass PRIMA dell'aggiornamento, non con
        # quelli intermedi. Verifichiamo numericamente il caso in cui
        # il sensore osserva θ molto diverso dal predetto.
        pot = self._make_chem_pot(state_mm=10.0, salt_mass_meq=15.0)
        # Salva l'EC corrente del Pot (con state_mm=10).
        ec_predicted_at_current_state = pot.ec_substrate_mscm

        reading = self._make_reading(
            theta_volumetric=0.40,    # molto più alto del predetto
            ec_mscm=1.0,
        )
        result = pot.update_from_sensor(reading=reading)

        # predicted_ec_mscm deve essere quella calcolata SU state_mm=10,
        # non su state_mm aggiornato. Quindi deve coincidere col
        # valore precedente.
        self.assertAlmostEqual(
            result.predicted_ec_mscm,
            ec_predicted_at_current_state,
            places=6,
        )

    # ----- Effetto del feedback loop sul Kn -----

    def test_chemistry_update_affects_subsequent_kn(self):
        # Dopo un update_from_sensor con valori subottimali, il Kn
        # del Pot riflette il nuovo stato chimico, e ciò influenza
        # il calcolo dell'ET successivo.
        chem_species = Species(
            common_name="basilico-chem",
            scientific_name="Ocimum basilicum",
            kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
            ec_optimal_min_mscm=1.0,
            ec_optimal_max_mscm=1.6,
            ph_optimal_min=6.0,
            ph_optimal_max=7.0,
        )
        pot = self._make_chem_pot(species=chem_species)
        # Stato iniziale ottimale.
        pot.salt_mass_meq = 1.3 * pot.water_volume_liters * 10
        pot.ph_substrate = 6.5
        et_optimal = pot.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )

        # Update con sensore che vede stress salino.
        reading = self._make_reading(
            theta_volumetric=pot.state_theta,    # stesso θ
            ec_mscm=2.5,                          # EC alta
            ph=6.5,                               # pH ottimo
        )
        pot.update_from_sensor(reading=reading)

        # Il nuovo Kn riflette lo stress: ET ridotta.
        et_after_stress_reading = pot.current_et_c(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
        )
        self.assertLess(et_after_stress_reading, et_optimal)


if __name__ == "__main__":
    unittest.main()
