"""
Test per fitosim.science.lysimeter.

Il lisimetro è il ground truth del layer di feedback, quindi i test
hanno un carattere diverso da quelli delle altre fonti: non c'è un
modello da validare, c'è una conversione da verificare. Se la
conversione grammi → millimetri è sbagliata, tutto ciò che si appoggia
al lisimetro è sbagliato in silenzio, con l'aggravante che sembrerà
autorevole.

Copertura:

  1. LysimeterInterval: validazione e bilancio di massa.
  2. La conversione massa → mm, incluso il giro chiuso contro la
     geometria reale di un Pot.
  3. L'inversione: da ET misurata a Kc, con recupero di un valore noto.
  4. L'aggregazione: mediana, confidenza, scarti, robustezza.
"""

import unittest
from datetime import date, timedelta

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL
from fitosim.science.lysimeter import (
    KC_MAX_PLAUSIBLE,
    LysimeterInterval,
    MIN_INTERVALS_FOR_HIGH_CONFIDENCE,
    MIN_INTERVALS_FOR_LOW_CONFIDENCE,
    MIN_INTERVALS_FOR_MEDIUM_CONFIDENCE,
    calibrate_kc_from_lysimeter,
    estimate_kc_from_interval,
    mass_to_mm,
    measured_et_mm,
    measured_et_mm_per_day,
)

# Superficie di comodo: 100 cm² rende la conversione leggibile a
# occhio (1 g → 0.1 mm), così i test dicono cosa verificano senza
# nascondere l'aritmetica.
AREA = 100.0

START = date(2026, 6, 1)


def _interval(
    *,
    lost_g: float,
    et0_mm: float,
    days: int = 1,
    start: date = START,
    added_g: float = 0.0,
    drained_g: float = 0.0,
    mean_ks: float = 1.0,
) -> LysimeterInterval:
    """Costruisce un intervallo che perde esattamente `lost_g` grammi."""
    base = 5000.0
    return LysimeterInterval(
        start_date=start,
        end_date=start + timedelta(days=days),
        mass_start_g=base,
        mass_end_g=base - lost_g + added_g - drained_g,
        et0_mm=et0_mm,
        water_added_g=added_g,
        drainage_g=drained_g,
        mean_ks=mean_ks,
    )


def _interval_with_kc(
    kc: float, *, et0_mm: float = 5.0, start: date = START,
) -> LysimeterInterval:
    """
    Intervallo la cui perdita di massa corrisponde esattamente al Kc dato.

    Percorre la catena in avanti (Kc → ET → massa) così che il test
    dell'inversione parta da un valore noto e non da un numero scelto
    per far tornare il risultato.
    """
    et_mm = kc * et0_mm
    # mm → cm → volume su AREA cm² → grammi (densità 1 g/cm³).
    lost_g = et_mm / 10.0 * AREA
    return _interval(lost_g=lost_g, et0_mm=et0_mm, start=start)


# =======================================================================
#  1. LysimeterInterval
# =======================================================================

class TestLysimeterIntervalValidation(unittest.TestCase):

    def test_end_date_must_follow_start(self):
        for end in (START, START - timedelta(days=1)):
            with self.subTest(end=end):
                with self.assertRaises(ValueError):
                    LysimeterInterval(
                        start_date=START, end_date=end,
                        mass_start_g=5000.0, mass_end_g=4900.0,
                        et0_mm=5.0,
                    )

    def test_masses_must_be_positive(self):
        for start_g, end_g in ((0.0, 4900.0), (5000.0, -1.0)):
            with self.subTest(start_g=start_g, end_g=end_g):
                with self.assertRaises(ValueError):
                    LysimeterInterval(
                        start_date=START, end_date=START + timedelta(days=1),
                        mass_start_g=start_g, mass_end_g=end_g, et0_mm=5.0,
                    )

    def test_water_and_drainage_cannot_be_negative(self):
        with self.assertRaises(ValueError):
            _interval(lost_g=50.0, et0_mm=5.0, added_g=-10.0)
        with self.assertRaises(ValueError):
            _interval(lost_g=50.0, et0_mm=5.0, drained_g=-10.0)

    def test_ks_must_be_a_coefficient(self):
        for ks in (-0.1, 1.1):
            with self.subTest(ks=ks):
                with self.assertRaises(ValueError):
                    _interval(lost_g=50.0, et0_mm=5.0, mean_ks=ks)

    def test_et0_cannot_be_negative(self):
        with self.assertRaises(ValueError):
            _interval(lost_g=50.0, et0_mm=-1.0)

    def test_duration_in_days(self):
        self.assertEqual(_interval(lost_g=50.0, et0_mm=5.0).duration_days, 1)
        self.assertEqual(
            _interval(lost_g=50.0, et0_mm=5.0, days=7).duration_days, 7,
        )


class TestMassBalance(unittest.TestCase):
    """
    Il bilancio è l'unica formula del modulo che non ha modello dietro:
    tre casi a mano coprono i tre termini.
    """

    def test_pure_loss(self):
        interval = LysimeterInterval(
            start_date=START, end_date=START + timedelta(days=1),
            mass_start_g=5000.0, mass_end_g=4900.0, et0_mm=5.0,
        )
        self.assertAlmostEqual(interval.water_lost_g, 100.0)

    def test_irrigation_that_stays_in_the_pot(self):
        # Aggiungo 200 g, il vaso ne guadagna 100: 100 sono
        # evapotraspirati piu' i 100 persi dal contenuto iniziale.
        interval = LysimeterInterval(
            start_date=START, end_date=START + timedelta(days=1),
            mass_start_g=5000.0, mass_end_g=5100.0, et0_mm=5.0,
            water_added_g=200.0,
        )
        self.assertAlmostEqual(interval.water_lost_g, 100.0)

    def test_irrigation_with_drainage(self):
        # 300 g dentro, 100 g fuori dal fondo, il vaso guadagna 150:
        # restano 50 g evapotraspirati.
        interval = LysimeterInterval(
            start_date=START, end_date=START + timedelta(days=1),
            mass_start_g=5000.0, mass_end_g=5150.0, et0_mm=5.0,
            water_added_g=300.0, drainage_g=100.0,
        )
        self.assertAlmostEqual(interval.water_lost_g, 50.0)

    def test_unaccounted_rain_shows_up_as_negative_loss(self):
        # Il vaso guadagna massa senza che nessuno abbia irrigato: il
        # bilancio non si chiude, ed è giusto che il segno lo dica.
        interval = LysimeterInterval(
            start_date=START, end_date=START + timedelta(days=1),
            mass_start_g=5000.0, mass_end_g=5200.0, et0_mm=5.0,
        )
        self.assertLess(interval.water_lost_g, 0.0)


# =======================================================================
#  2. Conversione massa → millimetri
# =======================================================================

class TestMassToMm(unittest.TestCase):

    def test_known_conversion(self):
        # 100 g su 100 cm²: 100 cm³ / 100 cm² = 1 cm = 10 mm.
        self.assertAlmostEqual(mass_to_mm(100.0, 100.0), 10.0)

    def test_realistic_pot(self):
        # Vaso da 22 cm di diametro: superficie ~380 cm². Cento grammi
        # in una giornata sono un consumo estivo credibile, e devono
        # dare pochi millimetri, non decine.
        area = 3.14159265 * 11.0 ** 2
        et = mass_to_mm(100.0, area)
        self.assertAlmostEqual(et, 2.63, places=2)

    def test_narrow_pot_yields_more_millimetres(self):
        # I millimetri sono un'altezza: la stessa massa su una
        # superficie minore fa una colonna più alta.
        self.assertGreater(mass_to_mm(100.0, 200.0), mass_to_mm(100.0, 400.0))

    def test_area_must_be_positive(self):
        for area in (0.0, -10.0):
            with self.subTest(area=area):
                with self.assertRaises(ValueError):
                    mass_to_mm(100.0, area)

    def test_measured_et_and_per_day(self):
        interval = _interval(lost_g=350.0, et0_mm=25.0, days=7)
        self.assertAlmostEqual(measured_et_mm(interval, AREA), 35.0)
        self.assertAlmostEqual(measured_et_mm_per_day(interval, AREA), 5.0)


class TestClosedLoopAgainstPotGeometry(unittest.TestCase):
    """
    Il giro chiuso che conta davvero.

    Un errore di fattore 10 o 10 000 nella conversione non lo vede
    nessuno finché non si confronta la pesata con la geometria vera di
    un vaso: qui faccio consumare acqua al modello, la traduco in
    grammi come farebbe una bilancia sotto quel vaso, e verifico che il
    lisimetro restituisca esattamente i millimetri di partenza.
    """

    def _pot(self) -> Pot:
        return Pot(
            label="lisimetro", species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 5, 1),
        )

    def test_model_consumption_round_trips_through_the_scale(self):
        pot = self._pot()
        area_cm2 = pot.surface_area_m2 * 10_000.0

        day = date(2026, 6, 15)
        before_mm = pot.state_mm
        pot.apply_balance_step(
            et_0_mm=5.0, water_input_mm=0.0, current_date=day,
        )
        consumed_mm = before_mm - pot.state_mm
        self.assertGreater(consumed_mm, 0.0)

        # Quello che la bilancia leggerebbe: mm → cm → cm³ su tutta la
        # superficie → grammi.
        consumed_g = consumed_mm / 10.0 * area_cm2

        interval = LysimeterInterval(
            start_date=day, end_date=day + timedelta(days=1),
            mass_start_g=5000.0, mass_end_g=5000.0 - consumed_g,
            et0_mm=5.0,
        )
        self.assertAlmostEqual(
            measured_et_mm(interval, area_cm2), consumed_mm, places=6,
        )

    def test_a_summer_day_weighs_a_plausible_number_of_grams(self):
        # Guardia contro gli errori di scala: un vaso da 18 cm in
        # piena estate perde decine di grammi al giorno, non decimi né
        # chilogrammi.
        pot = self._pot()
        area_cm2 = pot.surface_area_m2 * 10_000.0
        before_mm = pot.state_mm
        pot.apply_balance_step(
            et_0_mm=6.0, water_input_mm=0.0, current_date=date(2026, 7, 15),
        )
        grams = (before_mm - pot.state_mm) / 10.0 * area_cm2
        self.assertGreater(grams, 5.0)
        self.assertLess(grams, 500.0)


# =======================================================================
#  3. Inversione: da ET misurata a Kc
# =======================================================================

class TestEstimateKcFromInterval(unittest.TestCase):

    def test_recovers_a_known_kc(self):
        for kc in (0.35, 0.60, 1.05, 1.40):
            with self.subTest(kc=kc):
                estimate = estimate_kc_from_interval(
                    _interval_with_kc(kc), AREA,
                )
                self.assertIsNotNone(estimate)
                self.assertAlmostEqual(estimate, kc, places=6)

    def test_pot_coefficient_raises_the_implied_kc(self):
        # A parità di consumo misurato, se il vaso frena
        # l'evaporazione (Kp < 1) la pianta deve avere un Kc più alto
        # per giustificare quella stessa perdita.
        interval = _interval_with_kc(1.00)
        neutral = estimate_kc_from_interval(interval, AREA, kp=1.0)
        braked = estimate_kc_from_interval(interval, AREA, kp=0.8)
        self.assertAlmostEqual(neutral, 1.00, places=6)
        self.assertAlmostEqual(braked, 1.25, places=6)

    def test_stress_is_divided_out(self):
        # Stessa perdita misurata, ma dichiarata sotto stress: il Kc
        # implicato è più alto perché la pianta avrebbe consumato di
        # più senza il freno idrico.
        stressed = _interval(
            lost_g=1.00 * 5.0 / 10.0 * AREA, et0_mm=5.0, mean_ks=0.5,
        )
        self.assertAlmostEqual(
            estimate_kc_from_interval(stressed, AREA), 2.00, places=6,
        )

    def test_no_atmospheric_demand_gives_no_estimate(self):
        self.assertIsNone(
            estimate_kc_from_interval(
                _interval(lost_g=50.0, et0_mm=0.0), AREA,
            )
        )

    def test_a_pot_that_gained_water_gives_no_estimate(self):
        gained = LysimeterInterval(
            start_date=START, end_date=START + timedelta(days=1),
            mass_start_g=5000.0, mass_end_g=5300.0, et0_mm=5.0,
        )
        self.assertIsNone(estimate_kc_from_interval(gained, AREA))

    def test_implausible_kc_is_rejected(self):
        # Perdita enorme rispetto alla domanda: una potatura, non ET.
        absurd = _interval(lost_g=2000.0, et0_mm=1.0)
        self.assertGreater(
            measured_et_mm(absurd, AREA) / 1.0, KC_MAX_PLAUSIBLE,
        )
        self.assertIsNone(estimate_kc_from_interval(absurd, AREA))

    def test_degenerate_coefficients_give_no_estimate(self):
        interval = _interval_with_kc(1.0)
        self.assertIsNone(estimate_kc_from_interval(interval, AREA, kp=0.0))
        self.assertIsNone(estimate_kc_from_interval(interval, AREA, kn=0.0))
        self.assertIsNone(
            estimate_kc_from_interval(
                _interval(lost_g=50.0, et0_mm=5.0, mean_ks=0.0), AREA,
            )
        )


# =======================================================================
#  4. Aggregazione
# =======================================================================

def _series(kcs, et0_mm: float = 5.0) -> list:
    """Una serie di intervalli distanziati, ciascuno con il suo Kc vero."""
    return [
        _interval_with_kc(kc, et0_mm=et0_mm, start=START + timedelta(days=i * 3))
        for i, kc in enumerate(kcs)
    ]


class TestCalibrateKcFromLysimeter(unittest.TestCase):

    def test_uniform_series_recovers_the_value(self):
        result = calibrate_kc_from_lysimeter(_series([0.90] * 6), AREA)
        self.assertAlmostEqual(result.kc_estimate, 0.90, places=6)
        self.assertEqual(result.n_intervals, 6)
        self.assertEqual(result.n_discarded, 0)

    def test_median_ignores_a_single_wild_interval(self):
        # Un intervallo contaminato ma ancora dentro i limiti di
        # plausibilità non deve spostare la stima: è per questo che si
        # aggrega con la mediana e non con la media.
        clean = calibrate_kc_from_lysimeter(_series([0.90] * 5), AREA)
        with_outlier = calibrate_kc_from_lysimeter(
            _series([0.90, 0.90, 0.90, 2.40, 0.90]), AREA,
        )
        self.assertAlmostEqual(
            with_outlier.kc_estimate, clean.kc_estimate, places=6,
        )

    def test_confidence_grows_with_the_number_of_intervals(self):
        cases = [
            (MIN_INTERVALS_FOR_LOW_CONFIDENCE - 1, "insufficient"),
            (MIN_INTERVALS_FOR_LOW_CONFIDENCE, "low"),
            (MIN_INTERVALS_FOR_MEDIUM_CONFIDENCE, "medium"),
            (MIN_INTERVALS_FOR_HIGH_CONFIDENCE, "high"),
        ]
        for n, expected in cases:
            with self.subTest(n=n):
                result = calibrate_kc_from_lysimeter(_series([0.90] * n), AREA)
                self.assertEqual(result.confidence, expected)
                self.assertEqual(result.n_intervals, n)

    def test_contaminated_intervals_are_counted_not_hidden(self):
        intervals = _series([0.90] * 4)
        intervals.append(_interval(
            lost_g=2000.0, et0_mm=1.0, start=START + timedelta(days=40),
        ))
        result = calibrate_kc_from_lysimeter(intervals, AREA)
        self.assertEqual(result.n_intervals, 4)
        self.assertEqual(result.n_discarded, 1)
        self.assertIn("scartat", result.notes)

    def test_no_usable_interval_gives_no_estimate(self):
        result = calibrate_kc_from_lysimeter(
            [_interval(lost_g=50.0, et0_mm=0.0)], AREA,
        )
        self.assertIsNone(result.kc_estimate)
        self.assertEqual(result.confidence, "insufficient")
        self.assertEqual(result.n_discarded, 1)

    def test_empty_input(self):
        result = calibrate_kc_from_lysimeter([], AREA)
        self.assertIsNone(result.kc_estimate)
        self.assertEqual(result.n_intervals, 0)
        self.assertEqual(result.measured_et_mm, ())

    def test_wide_spread_is_flagged_in_the_notes(self):
        tight = calibrate_kc_from_lysimeter(
            _series([0.88, 0.90, 0.92, 0.90, 0.89]), AREA,
        )
        wide = calibrate_kc_from_lysimeter(
            _series([0.40, 0.70, 0.90, 1.20, 1.50]), AREA,
        )
        self.assertIn("coerente", tight.notes)
        self.assertIn("Dispersione ampia", wide.notes)

    def test_raw_measurements_are_exposed(self):
        # L'ET misurata vale anche fuori dalla stima di Kc: è il dato
        # grezzo contro cui si validano le altre fonti.
        result = calibrate_kc_from_lysimeter(_series([1.00] * 3), AREA)
        self.assertEqual(len(result.measured_et_mm), 3)
        for et in result.measured_et_mm:
            self.assertAlmostEqual(et, 5.0, places=6)

    def test_insufficient_count_is_explained(self):
        result = calibrate_kc_from_lysimeter(_series([0.90] * 2), AREA)
        self.assertIsNotNone(result.kc_estimate)
        self.assertEqual(result.confidence, "insufficient")
        self.assertIn("Numerosità troppo bassa", result.notes)


if __name__ == "__main__":
    unittest.main()
