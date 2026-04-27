"""
Test per fitosim.science.calibration.

Cinque famiglie di test che coprono il modulo:
  1. find_peaks: rilevamento di picchi con filtri di robustezza.
  2. find_valleys: rilevamento di valli (specchio dei picchi).
  3. _percentile: statistica robusta usata nelle stime.
  4. estimate_theta_fc / estimate_theta_pwp: stime parametriche.
  5. calibrate_substrate: orchestrazione end-to-end e esperimento sintetico
     che valida la pipeline su dati con ground truth nota.
"""

import unittest
from random import Random

from fitosim.science.calibration import (
    CalibrationResult,
    DEFAULT_FC_PERCENTILE,
    DEFAULT_PWP_PERCENTILE,
    _percentile,
    calibrate_substrate,
    estimate_theta_fc,
    estimate_theta_pwp,
    find_peaks,
    find_valleys,
)


# =======================================================================
#  1. find_peaks
# =======================================================================

class TestFindPeaks(unittest.TestCase):
    """Comportamento del rilevatore di picchi."""

    def test_simple_peaks(self):
        # Serie classica a denti di sega: tre picchi netti, due valli.
        series = [0.10, 0.40, 0.30, 0.15, 0.42, 0.28, 0.12, 0.45, 0.32]
        peaks = find_peaks(series, min_distance=2, min_prominence=0.0)
        self.assertEqual(peaks, [1, 4, 7])

    def test_no_peaks_for_monotonic_series(self):
        # Serie monotonica crescente: nessun picco interno (solo bordi
        # che la convenzione esclude).
        series = [0.10, 0.20, 0.30, 0.40, 0.50]
        self.assertEqual(find_peaks(series), [])

    def test_no_peaks_for_constant_series(self):
        # Serie costante: nessun massimo locale stretto.
        series = [0.30] * 10
        self.assertEqual(find_peaks(series), [])

    def test_short_series_returns_empty(self):
        # Serie con meno di 3 punti: non si può definire un picco.
        self.assertEqual(find_peaks([]), [])
        self.assertEqual(find_peaks([0.5]), [])
        self.assertEqual(find_peaks([0.5, 0.6]), [])

    def test_min_distance_filter(self):
        # Due picchi vicini: con min_distance=3 viene tenuto solo il
        # più alto.
        series = [0.10, 0.30, 0.20, 0.40, 0.10]  # picchi a 1 (0.30) e 3 (0.40)
        # min_distance=2: entrambi distanti 2 → entrambi accettati.
        self.assertEqual(
            find_peaks(series, min_distance=2, min_prominence=0.0),
            [1, 3],
        )
        # min_distance=3: troppo vicini → tieni il più alto (0.40 a idx 3).
        self.assertEqual(
            find_peaks(series, min_distance=3, min_prominence=0.0),
            [3],
        )

    def test_min_prominence_filter(self):
        # Tre picchi crescenti, ma la prominenza del primo è bassa.
        series = [0.40, 0.42, 0.40, 0.10, 0.50, 0.10, 0.20, 0.55, 0.10]
        # Senza filtro di prominenza si trovano tre picchi.
        peaks_no_filter = find_peaks(
            series, min_distance=2, min_prominence=0.0,
        )
        self.assertEqual(peaks_no_filter, [1, 4, 7])
        # Con prominenza minima 0.05 il primo picco (prominenza 0.02
        # rispetto al bordo iniziale) viene scartato.
        peaks_filtered = find_peaks(
            series, min_distance=2, min_prominence=0.05,
        )
        self.assertEqual(peaks_filtered, [4, 7])

    def test_rejects_invalid_parameters(self):
        with self.assertRaises(ValueError):
            find_peaks([0.1, 0.2, 0.1], min_distance=0)
        with self.assertRaises(ValueError):
            find_peaks([0.1, 0.2, 0.1], min_prominence=-0.1)


# =======================================================================
#  2. find_valleys
# =======================================================================

class TestFindValleys(unittest.TestCase):
    """Le valli sono lo specchio dei picchi."""

    def test_simple_valleys(self):
        # Stessa serie del test dei picchi: valli a indici 3 e 6.
        series = [0.10, 0.40, 0.30, 0.15, 0.42, 0.28, 0.12, 0.45, 0.32]
        valleys = find_valleys(series, min_distance=2, min_prominence=0.0)
        self.assertEqual(valleys, [3, 6])

    def test_valleys_are_negated_peaks(self):
        # Le valli di una serie sono i picchi della serie negata.
        series = [0.4, 0.1, 0.5, 0.2, 0.6, 0.15, 0.7]
        negated = [-v for v in series]
        valleys = find_valleys(series, min_distance=1, min_prominence=0.0)
        peaks_of_negated = find_peaks(
            negated, min_distance=1, min_prominence=0.0,
        )
        self.assertEqual(valleys, peaks_of_negated)


# =======================================================================
#  3. _percentile
# =======================================================================

class TestPercentile(unittest.TestCase):
    """Calcolo del percentile con interpolazione lineare."""

    def test_single_value(self):
        # Lista con un solo elemento: il percentile è quel valore.
        self.assertEqual(_percentile([0.5], 0), 0.5)
        self.assertEqual(_percentile([0.5], 50), 0.5)
        self.assertEqual(_percentile([0.5], 100), 0.5)

    def test_extremes(self):
        sorted_values = [0.1, 0.2, 0.3, 0.4, 0.5]
        # 0° percentile: minimo.
        self.assertEqual(_percentile(sorted_values, 0), 0.1)
        # 100° percentile: massimo.
        self.assertEqual(_percentile(sorted_values, 100), 0.5)
        # 50° percentile: mediana (3° elemento di 5).
        self.assertEqual(_percentile(sorted_values, 50), 0.3)

    def test_linear_interpolation(self):
        # 5 valori: posizione del 25° percentile è 0.25 × 4 = 1.0
        # → esattamente il 2° elemento (idx 1).
        sorted_values = [0.0, 0.1, 0.2, 0.3, 0.4]
        self.assertAlmostEqual(_percentile(sorted_values, 25), 0.1,
                               places=10)
        # 75° percentile: posizione 0.75 × 4 = 3.0 → idx 3.
        self.assertAlmostEqual(_percentile(sorted_values, 75), 0.3,
                               places=10)

    def test_interpolation_between_indices(self):
        # 4 valori: 50° percentile è a posizione 0.5 × 3 = 1.5,
        # cioè a metà tra il 2° e il 3° elemento.
        sorted_values = [0.10, 0.20, 0.30, 0.40]
        self.assertAlmostEqual(_percentile(sorted_values, 50), 0.25,
                               places=10)

    def test_rejects_empty_list(self):
        with self.assertRaises(ValueError):
            _percentile([], 50)

    def test_rejects_invalid_percentile(self):
        with self.assertRaises(ValueError):
            _percentile([0.5], -1)
        with self.assertRaises(ValueError):
            _percentile([0.5], 101)


# =======================================================================
#  4. Stime parametriche
# =======================================================================

def _generate_clean_sawtooth(
    n_cycles: int,
    fc: float,
    pwp: float,
    days_per_cycle: int = 7,
) -> list[float]:
    """
    Genera una serie sintetica a denti di sega con parametri noti.
    Ogni ciclo ha un picco a `fc` seguito da un asciugamento lineare
    fino a un livello sopra `pwp` (irrigazione anticipa il PWP).

    Le stime di calibrazione applicate a questa serie devono
    recuperare valori vicini ai parametri di input.
    """
    series = []
    valley_level = pwp + 0.05  # giardiniere prudente: irriga sopra PWP
    for _ in range(n_cycles):
        # Salita rapida (1 giorno) da valley_level a fc.
        series.append(fc)
        # Asciugamento lineare verso valley_level.
        for d in range(1, days_per_cycle):
            frac = d / (days_per_cycle - 1)
            series.append(fc - frac * (fc - valley_level))
    return series


class TestEstimateThetaFc(unittest.TestCase):
    """Stima di θ_FC dai picchi della serie."""

    def test_recovers_known_fc_on_clean_data(self):
        # Serie sintetica con FC noto: la stima deve essere vicina.
        # Usiamo 12 cicli (non 10) perché find_peaks scarta per
        # convenzione il primo punto della serie come picco, quindi
        # con N cicli generati si ottengono N-1 picchi rilevabili.
        # 12 cicli → 11 picchi, confidenza "high" (soglia: 10).
        true_fc = 0.40
        series = _generate_clean_sawtooth(
            n_cycles=12, fc=true_fc, pwp=0.10,
        )
        estimate, n_peaks, conf = estimate_theta_fc(series)
        self.assertAlmostEqual(estimate, true_fc, places=2)
        self.assertGreaterEqual(n_peaks, 10)
        self.assertEqual(conf, "high")

    def test_returns_none_on_short_data(self):
        # Serie troppo corta: non abbastanza picchi.
        series = [0.10, 0.40, 0.20]
        estimate, n_peaks, conf = estimate_theta_fc(series)
        self.assertIsNone(estimate)
        self.assertEqual(conf, "insufficient")

    def test_robust_to_outlier_peak(self):
        # Serie con un picco anomalo (pioggia eccezionale o doppia
        # irrigazione): il 75° percentile non viene perturbato come
        # sarebbe il massimo.
        true_fc = 0.40
        series = _generate_clean_sawtooth(
            n_cycles=10, fc=true_fc, pwp=0.10,
        )
        # Sostituiamo il valore al primo picco (idx 0) con un outlier.
        series[0] = 0.65  # outlier alto
        estimate, _, _ = estimate_theta_fc(series)
        # La stima resta vicina al vero FC (0.40), non scivola verso
        # l'outlier (0.65) come farebbe un max diretto.
        self.assertLess(abs(estimate - true_fc), 0.05)


class TestEstimateThetaPwp(unittest.TestCase):
    """Stima di θ_PWP (limite superiore) dalle valli."""

    def test_estimates_upper_bound_of_pwp(self):
        # Per costruzione, valley_level = PWP + 0.05 nel sintetico,
        # quindi la stima di PWP recuperata sarà vicina a PWP + 0.05,
        # NON al vero PWP. Questo è esattamente il limite superiore
        # che la docstring annuncia.
        true_pwp = 0.10
        valley_level_used = 0.15  # = pwp + 0.05
        series = _generate_clean_sawtooth(
            n_cycles=10, fc=0.40, pwp=true_pwp,
        )
        estimate, _, _ = estimate_theta_pwp(series)
        self.assertGreaterEqual(estimate, true_pwp)
        self.assertAlmostEqual(estimate, valley_level_used, places=2)

    def test_confidence_capped_at_medium(self):
        # Anche con tante valli, la confidenza per PWP non sale a "high".
        series = _generate_clean_sawtooth(
            n_cycles=20, fc=0.40, pwp=0.10,  # tante valli
        )
        _, n_valleys, conf = estimate_theta_pwp(series)
        self.assertGreaterEqual(n_valleys, 10)
        # n_valleys è alto ma la confidenza è cappata a "medium".
        self.assertIn(conf, ("low", "medium"))
        self.assertNotEqual(conf, "high")


# =======================================================================
#  5. calibrate_substrate: orchestratore + esperimento sintetico
# =======================================================================

class TestCalibrateSubstrate(unittest.TestCase):
    """Pipeline completa di calibrazione."""

    def test_returns_well_formed_result(self):
        series = _generate_clean_sawtooth(
            n_cycles=10, fc=0.40, pwp=0.10,
        )
        result = calibrate_substrate(series, name="test")
        self.assertIsInstance(result, CalibrationResult)
        self.assertEqual(result.name, "test")
        self.assertGreater(result.theta_fc_estimate, 0)
        self.assertIsNotNone(result.theta_pwp_estimate)
        self.assertGreater(result.n_peaks, 0)
        self.assertGreater(result.n_valleys, 0)
        self.assertIn(result.confidence_fc,
                      ("high", "medium", "low", "insufficient"))

    def test_rejects_too_short_series(self):
        with self.assertRaises(ValueError):
            calibrate_substrate([0.3, 0.4, 0.2], name="short")

    def test_rejects_out_of_range_values(self):
        # Valori θ devono essere in [0, 1] per essere fisici.
        bad_series = [0.3] * 9 + [1.5]  # ultimo valore fuori range
        with self.assertRaises(ValueError):
            calibrate_substrate(bad_series, name="bad")
        bad_series2 = [0.3] * 9 + [-0.1]
        with self.assertRaises(ValueError):
            calibrate_substrate(bad_series2, name="bad")

    def test_notes_explain_pwp_asymmetry(self):
        # Quando PWP è stimato con confidenza non-perfetta, la note
        # deve mettere in guardia che è un limite superiore.
        series = _generate_clean_sawtooth(
            n_cycles=10, fc=0.40, pwp=0.10,
        )
        result = calibrate_substrate(series, name="test")
        self.assertIn("limite", result.notes.lower())


class TestSyntheticExperimentEndToEnd(unittest.TestCase):
    """
    Esperimento sintetico completo: simulazione forward con parametri
    noti, aggiunta di rumore, calibrazione inversa, verifica del
    recupero. È il test che valida l'intera pipeline come funziona
    nel mondo reale.
    """

    def test_recovers_parameters_with_realistic_noise(self):
        # Ground truth: FC=0.42, PWP=0.12.
        true_fc = 0.42
        true_pwp = 0.12
        # Generiamo 20 cicli di 7 giorni = 140 giorni di dati.
        clean = _generate_clean_sawtooth(
            n_cycles=20, fc=true_fc, pwp=true_pwp,
        )
        # Aggiungiamo rumore gaussiano con sigma 0.01 (rumore tipico
        # del sensore WH51 dopo aggregazione giornaliera).
        rng = Random(42)
        noisy = [
            max(0.0, min(1.0, v + rng.gauss(0, 0.01)))
            for v in clean
        ]
        result = calibrate_substrate(noisy, name="synthetic")
        # FC recuperato a meno di 0.02 dal vero (il 75° percentile è
        # robusto al rumore di sigma=0.01).
        self.assertLess(abs(result.theta_fc_estimate - true_fc), 0.02)
        # PWP è limite superiore: ≥ true_pwp.
        self.assertGreaterEqual(result.theta_pwp_estimate, true_pwp)
        # Confidenza alta per FC (20 picchi).
        self.assertEqual(result.confidence_fc, "high")
        # Confidenza al massimo medium per PWP (asimmetria intrinseca).
        self.assertIn(result.confidence_pwp, ("low", "medium"))


if __name__ == "__main__":
    unittest.main()
