"""
Test per fitosim.science.balance.

Organizzati in quattro famiglie:
  1. Validazione e comportamento della funzione core (unit-agnostic).
  2. Wrapper in frazione volumetrica θ.
  3. Wrapper in colonna d'acqua mm.
  4. Coerenza cross-unit: lo stesso scenario fisico simulato in θ e in
     mm deve produrre risultati convertibili uno nell'altro esattamente.

L'ultima famiglia è la più interessante dal punto di vista epistemico:
confermare che i due wrapper sono "viste" consistenti dello stesso
fenomeno fisico è la prova che l'astrazione unit-agnostic sottostante è
ben progettata.
"""

import unittest

from fitosim.science.balance import (
    BalanceStepResult,
    water_balance_step,
    water_balance_step_mm,
    water_balance_step_theta,
)
from fitosim.science.substrate import (
    UNIVERSAL_POTTING_SOIL,
    mm_to_theta,
    pot_substrate_depth_mm,
    theta_to_mm,
)


class TestCoreBalance(unittest.TestCase):
    """Verifica del comportamento della funzione core."""

    def _simple_args(self, **overrides):
        # Default di lavoro per uno scenario "terriccio universale":
        # θ_FC=0.40, θ_PWP=0.15, RAW=0.125 (p=0.5), alert=0.275.
        args = dict(
            current_state=0.40,       # partiamo da capacità di campo
            water_input=0.0,
            et_c=0.0,
            upper_bound=0.40,
            lower_bound=0.15,
            alert_threshold=0.275,
        )
        args.update(overrides)
        return args

    def test_no_input_no_et_preserves_state(self):
        # Se nulla entra e nulla esce, lo stato è invariato.
        result = water_balance_step(**self._simple_args())
        self.assertAlmostEqual(result.new_state, 0.40, places=6)
        self.assertEqual(result.drainage, 0.0)
        self.assertFalse(result.under_alert)
        self.assertEqual(result.deficit, 0.0)

    def test_et_only_decreases_state(self):
        # ET_c senza pioggia: lo stato scende della quantità di ET.
        result = water_balance_step(**self._simple_args(et_c=0.05))
        self.assertAlmostEqual(result.new_state, 0.35, places=6)
        self.assertEqual(result.drainage, 0.0)

    def test_input_only_increases_state_up_to_capacity(self):
        # Input puro che porta esattamente a capacità di campo.
        args = self._simple_args(current_state=0.30, water_input=0.10)
        result = water_balance_step(**args)
        self.assertAlmostEqual(result.new_state, 0.40, places=6)
        self.assertEqual(result.drainage, 0.0)

    def test_overflow_drains_excess(self):
        # Irrigazione eccessiva: eccesso oltre capacità di campo si
        # disperde come drenaggio.
        args = self._simple_args(current_state=0.35, water_input=0.20)
        # Stato grezzo: 0.35 + 0.20 = 0.55 → clippato a 0.40, drainage 0.15.
        result = water_balance_step(**args)
        self.assertAlmostEqual(result.new_state, 0.40, places=6)
        self.assertAlmostEqual(result.drainage, 0.15, places=6)

    def test_underflow_clips_to_lower_bound(self):
        # ET_c superiore alla riserva: lo stato si ferma al punto di
        # appassimento (non scende sotto).
        args = self._simple_args(current_state=0.20, et_c=0.30)
        # Stato grezzo: 0.20 − 0.30 = −0.10 → clippato a 0.15 (PWP).
        result = water_balance_step(**args)
        self.assertAlmostEqual(result.new_state, 0.15, places=6)

    def test_alert_triggers_below_threshold(self):
        # Stato che cade esattamente sotto la soglia di allerta deve
        # settare under_alert e riportare il deficit giusto.
        args = self._simple_args(current_state=0.30, et_c=0.05)
        # Nuovo stato: 0.25, soglia 0.275 → sotto soglia, deficit 0.025.
        result = water_balance_step(**args)
        self.assertTrue(result.under_alert)
        self.assertAlmostEqual(result.deficit, 0.025, places=6)

    def test_alert_does_not_trigger_above_threshold(self):
        # Strettamente sopra la soglia: nessuna allerta.
        # Scegliamo un margine ampio (0.005) rispetto alla soglia 0.275
        # per essere ben lontani dal rumore di virgola mobile. Testare
        # "esattamente alla soglia" sarebbe problematico perché i
        # valori 0.30 e 0.025 non si rappresentano esattamente in
        # IEEE 754 e la loro differenza può cadere leggermente sopra
        # o sotto 0.275 a seconda dell'implementazione.
        args = self._simple_args(current_state=0.30, et_c=0.02)
        # Nuovo stato: 0.28 > 0.275 → under_alert = False.
        result = water_balance_step(**args)
        self.assertAlmostEqual(result.new_state, 0.28, places=6)
        self.assertFalse(result.under_alert)
        self.assertEqual(result.deficit, 0.0)

    def test_negative_input_raises(self):
        with self.assertRaises(ValueError):
            water_balance_step(**self._simple_args(water_input=-0.01))

    def test_negative_et_raises(self):
        with self.assertRaises(ValueError):
            water_balance_step(**self._simple_args(et_c=-0.01))

    def test_inconsistent_thresholds_raise(self):
        # alert fuori dall'intervallo [lower, upper] è invalido.
        with self.assertRaises(ValueError):
            water_balance_step(**self._simple_args(alert_threshold=0.50))
        with self.assertRaises(ValueError):
            water_balance_step(**self._simple_args(alert_threshold=0.10))


class TestThetaWrapper(unittest.TestCase):
    """Verifica del wrapper in frazione volumetrica θ."""

    def test_default_depletion_gives_expected_alert(self):
        # Terriccio universale (θ_FC=0.40, θ_PWP=0.15) → TAW=0.25 →
        # RAW=0.125 (con p=0.5) → soglia di allerta = 0.40 − 0.125 = 0.275.
        # Partendo da θ=0.30 e sottraendo ET=0.05, arriviamo a 0.25,
        # sotto la soglia: allerta attiva.
        result = water_balance_step_theta(
            current_theta=0.30,
            water_input_theta=0.0,
            et_c_theta=0.05,
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        self.assertAlmostEqual(result.new_state, 0.25, places=6)
        self.assertTrue(result.under_alert)

    def test_overflow_drains_excess_theta(self):
        # Input che saturebbe oltre capacità → drenaggio.
        result = water_balance_step_theta(
            current_theta=0.35,
            water_input_theta=0.10,
            et_c_theta=0.0,
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        self.assertAlmostEqual(result.new_state, 0.40, places=6)
        self.assertAlmostEqual(result.drainage, 0.05, places=6)

    def test_conservative_depletion_triggers_earlier(self):
        # Con p=0.3, RAW è minore (0.075), quindi la soglia di allerta
        # è più alta (0.325). Una configurazione che con p=0.5 non
        # triggererebbe, con p=0.3 sì.
        args = dict(
            current_theta=0.35,
            water_input_theta=0.0,
            et_c_theta=0.03,
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        result_p50 = water_balance_step_theta(**args, depletion_fraction=0.5)
        result_p30 = water_balance_step_theta(**args, depletion_fraction=0.3)
        # Nuovo stato: 0.32 in entrambi i casi.
        self.assertAlmostEqual(result_p50.new_state, 0.32, places=6)
        self.assertAlmostEqual(result_p30.new_state, 0.32, places=6)
        # Ma la soglia di allerta differisce.
        self.assertFalse(result_p50.under_alert)  # soglia 0.275 < 0.32
        self.assertTrue(result_p30.under_alert)   # soglia 0.325 > 0.32


class TestMmWrapper(unittest.TestCase):
    """Verifica del wrapper in colonna d'acqua mm."""

    def test_basic_balance_in_mm(self):
        # Vaso da 5L con diametro 20cm → area ≈ 0.0314 m² →
        # depth ≈ 159 mm. Su un terriccio universale, θ_FC=0.40 →
        # upper_mm ≈ 63.7 mm; θ_PWP=0.15 → lower_mm ≈ 23.9 mm.
        # Partiamo a FC (63.7 mm), sottraiamo 5 mm di ET: arriviamo a
        # 58.7 mm, ancora sopra la soglia di allerta di 43.8 mm.
        depth = pot_substrate_depth_mm(pot_volume_l=5.0, surface_area_m2=0.0314)
        start_mm = UNIVERSAL_POTTING_SOIL.theta_fc * depth
        result = water_balance_step_mm(
            current_mm=start_mm,
            water_input_mm=0.0,
            et_c_mm=5.0,
            substrate=UNIVERSAL_POTTING_SOIL,
            substrate_depth_mm=depth,
        )
        self.assertAlmostEqual(result.new_state, start_mm - 5.0, places=4)
        self.assertFalse(result.under_alert)

    def test_negative_depth_raises(self):
        with self.assertRaises(ValueError):
            water_balance_step_mm(
                current_mm=50.0,
                water_input_mm=0.0,
                et_c_mm=1.0,
                substrate=UNIVERSAL_POTTING_SOIL,
                substrate_depth_mm=-100.0,
            )


class TestCrossUnitConsistency(unittest.TestCase):
    """
    Test cruciale: lo stesso scenario fisico simulato nelle due unità
    deve dare risultati perfettamente traducibili l'uno nell'altro.

    Scenario di riferimento: vaso da 5L diametro 20cm, terriccio
    universale, stato iniziale θ=0.35, ET_c di 3 mm, zero input.
    Calcoliamo il bilancio sia in θ che in mm, poi convertiamo e
    confrontiamo.
    """

    def setUp(self):
        self.substrate = UNIVERSAL_POTTING_SOIL
        self.pot_volume_l = 5.0
        self.surface_area_m2 = 0.0314  # diametro 20cm circa
        self.depth_mm = pot_substrate_depth_mm(
            self.pot_volume_l, self.surface_area_m2
        )

    def test_theta_and_mm_give_equivalent_state(self):
        # Stato iniziale: θ = 0.35
        start_theta = 0.35
        start_mm = theta_to_mm(start_theta, self.depth_mm)

        # Input in θ: 3 mm / depth_mm. Calcolo in anticipo per passaggio
        # coerente ai due wrapper.
        et_mm = 3.0
        et_theta = mm_to_theta(et_mm, self.depth_mm)

        result_theta = water_balance_step_theta(
            current_theta=start_theta,
            water_input_theta=0.0,
            et_c_theta=et_theta,
            substrate=self.substrate,
        )

        result_mm = water_balance_step_mm(
            current_mm=start_mm,
            water_input_mm=0.0,
            et_c_mm=et_mm,
            substrate=self.substrate,
            substrate_depth_mm=self.depth_mm,
        )

        # Conversione dello stato risultante θ in mm e confronto.
        converted_mm = theta_to_mm(result_theta.new_state, self.depth_mm)
        self.assertAlmostEqual(converted_mm, result_mm.new_state, places=4)

        # I due calcoli devono concordare anche su drenaggio e allerta.
        self.assertAlmostEqual(
            theta_to_mm(result_theta.drainage, self.depth_mm),
            result_mm.drainage,
            places=4,
        )
        self.assertEqual(result_theta.under_alert, result_mm.under_alert)

    def test_overflow_drainage_matches_across_units(self):
        # Scenario con overflow: partiamo a θ=0.38, input grande (20 mm),
        # ET piccola (1 mm). Deve drenare in entrambe le unità.
        start_theta = 0.38
        start_mm = theta_to_mm(start_theta, self.depth_mm)
        input_mm = 20.0
        et_mm = 1.0

        result_theta = water_balance_step_theta(
            current_theta=start_theta,
            water_input_theta=mm_to_theta(input_mm, self.depth_mm),
            et_c_theta=mm_to_theta(et_mm, self.depth_mm),
            substrate=self.substrate,
        )
        result_mm = water_balance_step_mm(
            current_mm=start_mm,
            water_input_mm=input_mm,
            et_c_mm=et_mm,
            substrate=self.substrate,
            substrate_depth_mm=self.depth_mm,
        )

        # Entrambi devono finire a capacità di campo.
        self.assertAlmostEqual(
            theta_to_mm(result_theta.new_state, self.depth_mm),
            result_mm.new_state,
            places=4,
        )
        # Entrambi devono riportare lo stesso drenaggio (convertito).
        self.assertAlmostEqual(
            theta_to_mm(result_theta.drainage, self.depth_mm),
            result_mm.drainage,
            places=4,
        )
        self.assertGreater(result_mm.drainage, 0.0)


if __name__ == "__main__":
    unittest.main()
