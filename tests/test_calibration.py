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

from fitosim.science.balance import stress_coefficient_ks
from fitosim.science.calibration import (
    CalibrationResult,
    DEFAULT_FC_PERCENTILE,
    DEFAULT_PWP_PERCENTILE,
    DEFAULT_RISE_TOLERANCE,
    KcCalibrationResult,
    _percentile,
    calibrate_kc,
    calibrate_substrate,
    estimate_kc_from_window,
    estimate_theta_fc,
    estimate_theta_pwp,
    find_drying_windows,
    find_peaks,
    find_valleys,
)
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


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


# =======================================================================
#  6. Calibrazione di Kc dalla pendenza di asciugamento
# =======================================================================
#
# Il banco di prova principale e' l'inversione: costruiamo una serie
# sintetica APPLICANDO un Kc noto alla fisica del bilancio, poi
# verifichiamo che calibrate_kc lo recuperi. Se l'inversione e'
# corretta il valore torna a meno dell'errore di arrotondamento.

DEPTH_MM = 131.5  # vaso 5 L / 22 cm, come negli esempi


def _synthesize_drying(
    kc_true: float,
    et0: float,
    n_days: int,
    theta_start: float = 0.40,
    substrate=None,
    depletion_fraction: float = 0.40,
    kp: float = 1.0,
):
    """Genera (theta_series, et0_series) applicando un Kc noto.

    Riproduce esattamente il bilancio che `estimate_kc_from_window`
    inverte: deplezione = Ks * Kp * Kc * ET0, con Ks calcolato dallo
    stato di inizio giornata.
    """
    sub = substrate if substrate is not None else UNIVERSAL_POTTING_SOIL
    theta = [theta_start]
    et0_series = [0.0]
    for _ in range(n_days):
        ks = stress_coefficient_ks(
            theta[-1], sub, depletion_fraction=depletion_fraction,
        )
        depletion_theta = ks * kp * kc_true * et0 / DEPTH_MM
        theta.append(theta[-1] - depletion_theta)
        et0_series.append(et0)
    return theta, et0_series


class TestFindDryingWindows(unittest.TestCase):
    """Individuazione dei tratti di asciugamento senza apporti."""

    def test_single_monotonic_window(self):
        # Serie che scende sempre: una sola finestra che copre tutto.
        series = [0.40, 0.37, 0.34, 0.31, 0.28]
        windows = find_drying_windows(series)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start_index, 0)
        self.assertEqual(windows[0].end_index, 4)
        self.assertEqual(windows[0].n_days, 4)
        self.assertAlmostEqual(windows[0].total_depletion_theta, 0.12)

    def test_irrigation_splits_window(self):
        # Risalita netta a meta' serie: due finestre distinte.
        series = [0.40, 0.36, 0.32, 0.28, 0.40, 0.36, 0.32, 0.28]
        windows = find_drying_windows(series)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].start_index, 0)
        self.assertEqual(windows[0].end_index, 3)
        self.assertEqual(windows[1].start_index, 4)
        self.assertEqual(windows[1].end_index, 7)

    def test_noise_wobble_does_not_split(self):
        # Micro-risalite sotto la tolleranza: la finestra resta intera.
        series = [0.40, 0.365, 0.368, 0.33, 0.332, 0.29]
        windows = find_drying_windows(series, rise_tolerance=0.01)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].n_days, 5)

    def test_too_short_window_discarded(self):
        # Solo 2 transizioni: sotto min_days=3 di default.
        series = [0.40, 0.36, 0.32]
        self.assertEqual(find_drying_windows(series), [])

    def test_too_small_depletion_discarded(self):
        # Calo complessivo 0.012, sotto min_depletion=0.03: il rumore
        # dominerebbe il segnale.
        series = [0.40, 0.396, 0.392, 0.388]
        self.assertEqual(find_drying_windows(series), [])

    def test_known_water_input_excludes_transition(self):
        # Il sensore non mostra risalita (irrigazione "invisibile") ma
        # il diario la registra al giorno 4: la finestra si spezza.
        series = [0.40, 0.37, 0.34, 0.31, 0.28, 0.25, 0.22, 0.19]
        without = find_drying_windows(series)
        self.assertEqual(len(without), 1)
        with_diary = find_drying_windows(series, known_water_input_days=[4])
        self.assertEqual(len(with_diary), 2)
        self.assertEqual(with_diary[0].end_index, 3)
        self.assertEqual(with_diary[1].start_index, 4)

    def test_short_series_returns_empty(self):
        self.assertEqual(find_drying_windows([]), [])
        self.assertEqual(find_drying_windows([0.40]), [])


class TestEstimateKcFromWindow(unittest.TestCase):
    """Inversione del bilancio su una singola finestra."""

    def test_recovers_known_kc(self):
        # Ground truth: costruiamo con Kc=0.90 e lo recuperiamo.
        theta, et0 = _synthesize_drying(kc_true=0.90, et0=5.0, n_days=5)
        window = find_drying_windows(theta)[0]
        kc = estimate_kc_from_window(
            window, theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertAlmostEqual(kc, 0.90, places=6)

    def test_recovers_kc_through_stress_zone(self):
        # Il test fisicamente piu' importante: la serie scende sotto la
        # soglia di stress, dove Ks < 1 rallenta l'asciugamento.
        # Calcolando Ks dal theta osservato l'inversione resta esatta.
        theta, et0 = _synthesize_drying(kc_true=1.10, et0=6.0, n_days=12)
        # Verifichiamo davvero di essere entrati in zona di stress.
        alert_theta = (
            UNIVERSAL_POTTING_SOIL.theta_fc
            - 0.40 * (UNIVERSAL_POTTING_SOIL.theta_fc
                      - UNIVERSAL_POTTING_SOIL.theta_pwp)
        )
        self.assertLess(theta[-1], alert_theta)
        window = find_drying_windows(theta)[0]
        kc = estimate_kc_from_window(
            window, theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertAlmostEqual(kc, 1.10, places=6)

    def test_kp_scales_the_estimate(self):
        # A parita' di curva osservata, un Kp doppio implica un Kc meta':
        # il consumo osservato e' lo stesso ma se ne attribuisce meta'
        # al vaso e meta' alla coltura.
        theta, et0 = _synthesize_drying(kc_true=0.90, et0=5.0, n_days=5)
        window = find_drying_windows(theta)[0]
        kc_kp1 = estimate_kc_from_window(
            window, theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40, kp=1.0,
        )
        kc_kp2 = estimate_kc_from_window(
            window, theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40, kp=2.0,
        )
        self.assertAlmostEqual(kc_kp2, kc_kp1 / 2.0, places=6)

    def test_implausible_kc_returns_none(self):
        # ET0 minuscola con un calo enorme: Kc risulterebbe assurdo
        # (finestra contaminata da drenaggio o irrigazione non vista).
        theta = [0.40, 0.30, 0.20, 0.10]
        et0 = [0.0, 0.01, 0.01, 0.01]
        window = find_drying_windows(theta)[0]
        kc = estimate_kc_from_window(
            window, theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertIsNone(kc)

    def test_zero_demand_returns_none(self):
        # ET0 tutta nulla: la domanda e' zero, l'inversione e' indefinita.
        theta = [0.40, 0.37, 0.34, 0.31]
        et0 = [0.0, 0.0, 0.0, 0.0]
        window = find_drying_windows(theta)[0]
        kc = estimate_kc_from_window(
            window, theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertIsNone(kc)


class TestCalibrateKc(unittest.TestCase):
    """Orchestrazione end-to-end della calibrazione del consumo."""

    def _multi_cycle_series(self, kc_true, et0, n_cycles, days_per_cycle):
        """Concatena N cicli irrigazione-asciugamento con Kc noto."""
        theta_all = []
        et0_all = []
        for _ in range(n_cycles):
            th, e = _synthesize_drying(
                kc_true=kc_true, et0=et0, n_days=days_per_cycle,
            )
            theta_all.extend(th)
            et0_all.extend(e)
        return theta_all, et0_all

    def test_recovers_kc_over_multiple_cycles(self):
        # Sei cicli: la mediana recupera il Kc vero e la confidenza
        # sale a "medium".
        theta, et0 = self._multi_cycle_series(0.95, 5.0, 6, 5)
        result = calibrate_kc(
            theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertEqual(result.n_windows, 6)
        self.assertAlmostEqual(result.kc_estimate, 0.95, places=6)
        self.assertEqual(result.confidence, "medium")

    def test_confidence_scales_with_windows(self):
        # Dieci cicli -> confidenza alta.
        theta, et0 = self._multi_cycle_series(0.80, 5.0, 10, 5)
        result = calibrate_kc(
            theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertEqual(result.confidence, "high")
        self.assertEqual(len(result.window_estimates), 10)

    def test_no_usable_windows(self):
        # Serie che non si asciuga mai abbastanza: nessuna finestra.
        theta = [0.40, 0.399, 0.398, 0.397, 0.396]
        et0 = [0.0, 1.0, 1.0, 1.0, 1.0]
        result = calibrate_kc(
            theta, et0, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertIsNone(result.kc_estimate)
        self.assertEqual(result.n_windows, 0)
        self.assertEqual(result.confidence, "insufficient")
        self.assertIn("Nessuna finestra", result.notes)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError) as ctx:
            calibrate_kc(
                [0.40, 0.37, 0.34], [0.0, 5.0],
                UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            )
        self.assertIn("stessa lunghezza", str(ctx.exception))

    def test_dispersion_is_reported(self):
        # Due gruppi di cicli con consumi molto diversi (come se meta'
        # delle finestre fosse contaminata): la nota lo segnala.
        t1, e1 = self._multi_cycle_series(0.50, 5.0, 3, 5)
        t2, e2 = self._multi_cycle_series(1.60, 5.0, 3, 5)
        result = calibrate_kc(
            t1 + t2, e1 + e2, UNIVERSAL_POTTING_SOIL, DEPTH_MM,
            depletion_fraction=0.40,
        )
        self.assertGreaterEqual(result.n_windows, 4)
        self.assertIn("Dispersione ampia", result.notes)

    def test_underestimates_when_irrigation_is_invisible(self):
        # Documenta il limite noto del metodo. Costruiamo una serie
        # FISICAMENTE COERENTE con Kc=0.90 in cui a meta' percorso
        # l'utente irriga poco (+0.030 in theta): l'ET della giornata
        # maschera la risalita, il sensore vede solo un calo piu'
        # piccolo e la finestra non si spezza.
        sub = UNIVERSAL_POTTING_SOIL
        kc_true, et0_val, irrigation = 0.90, 5.0, 0.030
        theta = [0.40]
        et0 = [0.0]

        def _dry_one_day(water_added=0.0):
            ks = stress_coefficient_ks(
                theta[-1], sub, depletion_fraction=0.40,
            )
            theta.append(
                theta[-1] - ks * kc_true * et0_val / DEPTH_MM + water_added
            )
            et0.append(et0_val)

        for _ in range(4):          # fase 1: asciugamento puro
            _dry_one_day()
        _dry_one_day(irrigation)    # giorno con apporto invisibile
        invisible_day = len(theta) - 1
        for _ in range(4):          # fase 2: asciugamento dal nuovo livello
            _dry_one_day()

        # L'apporto e' davvero invisibile al rilevatore: l'eventuale
        # risalita resta sotto la tolleranza di rumore, quindi la
        # finestra non viene spezzata.
        rise = theta[invisible_day] - theta[invisible_day - 1]
        self.assertLessEqual(rise, DEFAULT_RISE_TOLERANCE)

        naive = calibrate_kc(
            theta, et0, sub, DEPTH_MM, depletion_fraction=0.40,
        )
        corrected = calibrate_kc(
            theta, et0, sub, DEPTH_MM, depletion_fraction=0.40,
            known_water_input_days=[invisible_day],
        )

        # Senza diario: una finestra sola, l'acqua aggiunta non viene
        # contata e il consumo risulta piu' basso del reale.
        self.assertEqual(naive.n_windows, 1)
        self.assertLess(naive.kc_estimate, 0.90)
        # Col diario: due finestre pulite, entrambe recuperano il vero.
        self.assertEqual(corrected.n_windows, 2)
        self.assertAlmostEqual(corrected.kc_estimate, 0.90, places=6)


if __name__ == "__main__":
    unittest.main()
