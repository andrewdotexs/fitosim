"""
Test per fitosim.science.behavioral_calibration.

Il segnale qui non è una misura ma un comportamento: lo scostamento
sistematico tra quando il modello suggerisce di irrigare e quando il
giardiniere irriga davvero. I test coprono:

  1. IrrigationDeviation: intervalli, scarto, rapporto, validazione.
  2. La matematica della correzione: direzione e ampiezza.
  3. I guardrail: numerosità, coerenza, banda di trascurabilità,
     scarto delle osservazioni implausibili, limiti del fattore.
  4. apply_kc_correction: scalatura, limiti di validità, località
     dell'override.
"""

import unittest
from datetime import date, timedelta

from fitosim.domain.species import BASIL, Species
from fitosim.science.behavioral_calibration import (
    CORRECTION_MAX,
    CORRECTION_MIN,
    BehavioralCalibrationResult,
    IrrigationDeviation,
    MIN_OBS_FOR_LOW_CONFIDENCE,
    apply_kc_correction,
    calibrate_kc_from_behavior,
)


def _deviations(
    predicted: int,
    actual: int,
    count: int,
    start: date = date(2026, 5, 1),
) -> list:
    """Genera `count` osservazioni identiche, ben distanziate nel tempo."""
    out = []
    for i in range(count):
        previous = start + timedelta(days=i * 40)
        out.append(IrrigationDeviation(
            previous_irrigation=previous,
            suggested_date=previous + timedelta(days=predicted),
            actual_date=previous + timedelta(days=actual),
        ))
    return out


# =======================================================================
#  1. IrrigationDeviation
# =======================================================================

class TestIrrigationDeviation(unittest.TestCase):

    def test_intervals_and_shift(self):
        dev = IrrigationDeviation(
            previous_irrigation=date(2026, 5, 1),
            suggested_date=date(2026, 5, 5),
            actual_date=date(2026, 5, 7),
        )
        self.assertEqual(dev.predicted_interval_days, 4)
        self.assertEqual(dev.actual_interval_days, 6)
        self.assertEqual(dev.shift_days, 2)
        self.assertAlmostEqual(dev.ratio, 1.5)

    def test_negative_shift_when_anticipating(self):
        dev = IrrigationDeviation(
            previous_irrigation=date(2026, 5, 1),
            suggested_date=date(2026, 5, 5),
            actual_date=date(2026, 5, 3),
        )
        self.assertEqual(dev.shift_days, -2)
        self.assertAlmostEqual(dev.ratio, 0.5)

    def test_suggestion_before_previous_raises(self):
        with self.assertRaises(ValueError) as ctx:
            IrrigationDeviation(
                previous_irrigation=date(2026, 5, 5),
                suggested_date=date(2026, 5, 1),
                actual_date=date(2026, 5, 7),
            )
        self.assertIn("suggested_date", str(ctx.exception))

    def test_actual_before_previous_raises(self):
        with self.assertRaises(ValueError) as ctx:
            IrrigationDeviation(
                previous_irrigation=date(2026, 5, 5),
                suggested_date=date(2026, 5, 9),
                actual_date=date(2026, 5, 2),
            )
        self.assertIn("actual_date", str(ctx.exception))


# =======================================================================
#  2. La matematica della correzione
# =======================================================================

class TestCorrectionMath(unittest.TestCase):

    def test_postponing_lowers_the_kc(self):
        # Modello 4 giorni, utente 6: il vaso si asciuga piu' lentamente
        # del previsto, quindi il consumo stimato va abbassato.
        result = calibrate_kc_from_behavior(_deviations(4, 6, 12))
        self.assertIsNotNone(result.kc_correction_factor)
        self.assertAlmostEqual(result.kc_correction_factor, 4 / 6, places=6)
        self.assertLess(result.kc_correction_factor, 1.0)

    def test_anticipating_raises_the_kc(self):
        # Modello 6 giorni, utente 4: il vaso si asciuga piu' in fretta.
        result = calibrate_kc_from_behavior(_deviations(6, 4, 12))
        self.assertAlmostEqual(result.kc_correction_factor, 6 / 4, places=6)
        self.assertGreater(result.kc_correction_factor, 1.0)

    def test_ratio_matters_not_absolute_shift(self):
        # Due giorni di ritardo su 4 previsti sono un errore grosso;
        # due giorni su 20 sono rumore. E' il motivo per cui la
        # correzione si calcola sul rapporto tra intervalli.
        short = calibrate_kc_from_behavior(_deviations(4, 6, 12))
        long = calibrate_kc_from_behavior(_deviations(20, 22, 12))
        self.assertEqual(short.median_shift_days, long.median_shift_days)
        self.assertIsNotNone(short.kc_correction_factor)
        self.assertIsNone(long.kc_correction_factor)

    def test_median_is_robust_to_one_outlier(self):
        # Una vacanza in mezzo a un comportamento regolare non deve
        # spostare la stima.
        observations = _deviations(4, 6, 11)
        observations.append(IrrigationDeviation(
            previous_irrigation=date(2028, 5, 1),
            suggested_date=date(2028, 5, 5),
            actual_date=date(2028, 5, 15),   # rapporto 3.5
        ))
        result = calibrate_kc_from_behavior(observations)
        self.assertAlmostEqual(result.kc_correction_factor, 4 / 6, places=6)


# =======================================================================
#  3. I guardrail
# =======================================================================

class TestGuardrails(unittest.TestCase):

    def test_too_few_observations_proposes_nothing(self):
        result = calibrate_kc_from_behavior(_deviations(4, 6, 3))
        self.assertIsNone(result.kc_correction_factor)
        self.assertFalse(result.suggests_correction)
        self.assertEqual(result.confidence, "insufficient")
        self.assertIn("almeno", result.notes)

    def test_confidence_grows_with_observations(self):
        self.assertEqual(
            calibrate_kc_from_behavior(_deviations(4, 6, 6)).confidence,
            "low",
        )
        self.assertEqual(
            calibrate_kc_from_behavior(_deviations(4, 6, 12)).confidence,
            "medium",
        )
        self.assertEqual(
            calibrate_kc_from_behavior(_deviations(4, 6, 20)).confidence,
            "high",
        )

    def test_erratic_user_proposes_nothing(self):
        # Meta' delle volte anticipa, meta' posticipa: non sta dicendo
        # che il modello sbaglia, sta dicendo che la sua vita e'
        # irregolare. La mediana cade su 1.0 e la coerenza crolla.
        mixed = (
            _deviations(4, 6, 6)
            + _deviations(4, 2, 6, start=date(2028, 5, 1))
        )
        result = calibrate_kc_from_behavior(mixed)
        self.assertIsNone(result.kc_correction_factor)
        self.assertAlmostEqual(result.consistency, 0.5)
        self.assertIn("non sistematico", result.notes)

    def test_punctual_user_is_fully_consistent(self):
        # Caso limite opposto: chi segue sempre il suggerimento ha
        # mediana 1.0 come l'utente bimodale, ma coerenza piena.
        result = calibrate_kc_from_behavior(_deviations(4, 4, 12))
        self.assertIsNone(result.kc_correction_factor)
        self.assertAlmostEqual(result.consistency, 1.0)
        self.assertIn("allineato", result.notes)

    def test_small_deviation_is_negligible(self):
        # 4 -> 4.x non vale la pena disturbare l'utente. Con intervalli
        # interi usiamo 20 -> 21 (5%).
        result = calibrate_kc_from_behavior(_deviations(20, 21, 12))
        self.assertIsNone(result.kc_correction_factor)
        self.assertIn("allineato", result.notes)

    def test_implausible_observations_are_discarded(self):
        # Un'irrigazione dimenticata per due settimane non parla del
        # vaso: parla del giardiniere.
        observations = _deviations(4, 6, 12)
        observations.append(IrrigationDeviation(
            previous_irrigation=date(2029, 5, 1),
            suggested_date=date(2029, 5, 5),
            actual_date=date(2029, 6, 5),   # rapporto 8.75
        ))
        result = calibrate_kc_from_behavior(observations)
        self.assertEqual(result.n_discarded, 1)
        self.assertEqual(result.n_observations, 12)

    def test_factor_is_bounded(self):
        # Un comportamento estremo ma coerente non deve produrre una
        # correzione arbitrariamente grande.
        result = calibrate_kc_from_behavior(_deviations(12, 4, 12))
        self.assertIsNotNone(result.kc_correction_factor)
        self.assertLessEqual(result.kc_correction_factor, CORRECTION_MAX)
        self.assertGreaterEqual(result.kc_correction_factor, CORRECTION_MIN)

    def test_no_observations(self):
        result = calibrate_kc_from_behavior([])
        self.assertIsNone(result.kc_correction_factor)
        self.assertEqual(result.n_observations, 0)
        self.assertIn("Nessuna osservazione", result.notes)

    def test_notes_explain_the_proposal(self):
        # Le note sono pensate per essere mostrate all'utente cosi'
        # come sono: devono contenere direzione, entita' e coerenza.
        result = calibrate_kc_from_behavior(_deviations(4, 6, 12))
        self.assertIn("Posticipa", result.notes)
        self.assertIn("2.0 giorni", result.notes)
        self.assertIn("100%", result.notes)


# =======================================================================
#  4. Applicazione della correzione
# =======================================================================

class TestApplyCorrection(unittest.TestCase):

    def test_scales_all_kc_values(self):
        corrected = apply_kc_correction(BASIL, 0.5)
        self.assertAlmostEqual(corrected.kc_initial, BASIL.kc_initial * 0.5)
        self.assertAlmostEqual(corrected.kc_mid, BASIL.kc_mid * 0.5)
        self.assertAlmostEqual(corrected.kc_late, BASIL.kc_late * 0.5)

    def test_scales_kcb_when_present(self):
        dual = Species(
            common_name="test dual", scientific_name="Testus dualis",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.8,
            kcb_initial=0.35, kcb_mid=0.90, kcb_late=0.70,
        )
        corrected = apply_kc_correction(dual, 0.5)
        self.assertAlmostEqual(corrected.kcb_mid, 0.45)
        # La relazione Kcb <= Kc resta valida.
        self.assertLessEqual(corrected.kcb_mid, corrected.kc_mid)

    def test_result_stays_within_validity_range(self):
        # Il pomodoro ha kc_mid=1.15: raddoppiarlo sforerebbe il limite
        # di validita' di Species (Kc < 2). Il valore viene limitato.
        from fitosim.domain.species import TOMATO
        corrected = apply_kc_correction(TOMATO, 2.0)
        self.assertLess(corrected.kc_mid, 2.0)

    def test_original_species_is_untouched(self):
        # L'override e' locale per costruzione: il catalogo globale non
        # viene modificato.
        original_kc = BASIL.kc_mid
        apply_kc_correction(BASIL, 0.5)
        self.assertEqual(BASIL.kc_mid, original_kc)

    def test_name_marks_the_species_as_calibrated(self):
        corrected = apply_kc_correction(BASIL, 0.8)
        self.assertNotEqual(corrected.common_name, BASIL.common_name)
        self.assertIn("calibrato", corrected.common_name)

    def test_phenology_config_is_preserved(self):
        # La correzione tocca solo i coefficienti di consumo: tutto il
        # resto della specie deve sopravvivere.
        from fitosim.domain.species import CITRUS
        corrected = apply_kc_correction(CITRUS, 0.8)
        self.assertEqual(
            corrected.phenology_anchor, CITRUS.phenology_anchor,
        )
        self.assertEqual(
            corrected.phenology_calendar, CITRUS.phenology_calendar,
        )
        self.assertEqual(
            corrected.depletion_fraction, CITRUS.depletion_fraction,
        )

    def test_negative_factor_raises(self):
        with self.assertRaises(ValueError):
            apply_kc_correction(BASIL, -1.0)

    def test_end_to_end_lowers_predicted_consumption(self):
        # Il ciclo completo: un utente che posticipa produce una specie
        # calibrata che consuma meno, quindi suggerimenti piu' radi.
        from fitosim.domain.pot import Location, Pot
        from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

        result = calibrate_kc_from_behavior(_deviations(4, 6, 12))
        calibrated = apply_kc_correction(BASIL, result.kc_correction_factor)

        def consumption(species):
            pot = Pot(
                label="vaso", species=species,
                substrate=UNIVERSAL_POTTING_SOIL,
                pot_volume_l=2.0, pot_diameter_cm=18.0,
                location=Location.OUTDOOR,
                planting_date=date(2026, 5, 1),
            )
            return pot.current_et_c(
                et_0_mm=5.0, current_date=date(2026, 6, 15),
            )

        self.assertLess(consumption(calibrated), consumption(BASIL))


if __name__ == "__main__":
    unittest.main()
