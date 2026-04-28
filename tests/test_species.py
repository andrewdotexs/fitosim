"""
Test per fitosim.domain.species e per stress_coefficient_ks.

Organizzati in quattro famiglie:
  1. Ks come funzione di θ: comportamento ai bordi, linearità, monotonia.
  2. Dataclass Species: creazione, validazione, immutabilità.
  3. kc_for_stage, potential_et_c, actual_et_c: corretta composizione.
  4. Integrità del catalogo: tutte le specie pre-definite sono valide.
"""

import unittest

from fitosim.domain.species import (
    ALL_SPECIES,
    BASIL,
    CITRUS,
    LETTUCE,
    ROSEMARY,
    TOMATO,
    PhenologicalStage,
    Species,
    actual_et_c,
    kc_for_stage,
    potential_et_c,
)
from fitosim.science.balance import stress_coefficient_ks
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


class TestStressCoefficientKs(unittest.TestCase):
    """Verifica del coefficiente di stress idrico Ks."""

    def setUp(self):
        # Substrato di lavoro: terriccio universale (θ_FC=0.40, θ_PWP=0.15).
        # Con p=0.5: RAW=0.125, soglia di allerta θ=0.275.
        self.substrate = UNIVERSAL_POTTING_SOIL
        self.p = 0.5

    def test_ks_at_field_capacity_is_one(self):
        # A θ_FC siamo pienamente nella zona di comfort.
        ks = stress_coefficient_ks(0.40, self.substrate, self.p)
        self.assertEqual(ks, 1.0)

    def test_ks_well_above_alert_is_one(self):
        # θ=0.35 è ancora sopra la soglia 0.275: Ks=1.
        ks = stress_coefficient_ks(0.35, self.substrate, self.p)
        self.assertEqual(ks, 1.0)

    def test_ks_at_alert_threshold_is_one(self):
        # Alla soglia esatta di allerta, Ks deve essere 1 (uguaglianza
        # non stretta: θ ≥ soglia → Ks=1). Test di continuità al bordo
        # superiore della zona di stress.
        ks = stress_coefficient_ks(0.275, self.substrate, self.p)
        self.assertAlmostEqual(ks, 1.0, places=6)

    def test_ks_at_pwp_is_zero(self):
        # A θ_PWP la pianta non traspira più.
        ks = stress_coefficient_ks(0.15, self.substrate, self.p)
        self.assertEqual(ks, 0.0)

    def test_ks_below_pwp_is_zero(self):
        # Valori sotto PWP restituiscono comunque 0 (limite inferiore).
        ks = stress_coefficient_ks(0.10, self.substrate, self.p)
        self.assertEqual(ks, 0.0)

    def test_ks_midway_in_stress_zone(self):
        # Nel mezzo della zona di stress (θ=0.2125, a metà tra PWP=0.15
        # e alert=0.275), Ks deve valere esattamente 0.5 per linearità.
        ks = stress_coefficient_ks(0.2125, self.substrate, self.p)
        self.assertAlmostEqual(ks, 0.5, places=6)

    def test_ks_is_monotonic_increasing(self):
        # Ks deve crescere monotonicamente con θ. Controllo su griglia
        # fine che copre tutte e tre le zone.
        thetas = [0.10, 0.15, 0.18, 0.22, 0.26, 0.28, 0.35, 0.40]
        ks_values = [
            stress_coefficient_ks(t, self.substrate, self.p) for t in thetas
        ]
        for i in range(len(ks_values) - 1):
            with self.subTest(i=i):
                self.assertLessEqual(ks_values[i], ks_values[i + 1])

    def test_ks_depends_on_depletion_fraction(self):
        # Con p=0.3 (più conservativo), la soglia di allerta è più alta
        # (θ = 0.40 − 0.075 = 0.325), quindi allo stesso θ=0.30 si è
        # già in zona di stress. Con p=0.5 (default) a 0.30 si è ancora
        # in comfort (soglia 0.275).
        ks_p30 = stress_coefficient_ks(0.30, self.substrate, 0.3)
        ks_p50 = stress_coefficient_ks(0.30, self.substrate, 0.5)
        self.assertLess(ks_p30, 1.0)
        self.assertEqual(ks_p50, 1.0)

    def test_ks_out_of_range_raises(self):
        # θ fuori [0, 1] è fisicamente impossibile.
        with self.assertRaises(ValueError):
            stress_coefficient_ks(-0.1, self.substrate, self.p)
        with self.assertRaises(ValueError):
            stress_coefficient_ks(1.1, self.substrate, self.p)


class TestSpeciesDataclass(unittest.TestCase):
    """Verifica della dataclass Species."""

    def test_valid_creation(self):
        s = Species(
            common_name="Test",
            scientific_name="Testus specimenus",
            kc_initial=0.50,
            kc_mid=1.00,
            kc_late=0.75,
            depletion_fraction=0.4,
        )
        self.assertEqual(s.common_name, "Test")
        self.assertEqual(s.kc_mid, 1.00)

    def test_negative_kc_rejected(self):
        with self.assertRaises(ValueError):
            Species(
                common_name="Bad", scientific_name="x",
                kc_initial=-0.1, kc_mid=1.0, kc_late=0.8,
                depletion_fraction=0.4,
            )

    def test_unreasonably_high_kc_rejected(self):
        # Kc > 2 indica quasi certamente un errore di trascrizione.
        with self.assertRaises(ValueError):
            Species(
                common_name="Bad", scientific_name="x",
                kc_initial=0.5, kc_mid=2.5, kc_late=0.8,
                depletion_fraction=0.4,
            )

    def test_invalid_depletion_fraction_rejected(self):
        with self.assertRaises(ValueError):
            Species(
                common_name="Bad", scientific_name="x",
                kc_initial=0.5, kc_mid=1.0, kc_late=0.8,
                depletion_fraction=1.5,
            )
        with self.assertRaises(ValueError):
            Species(
                common_name="Bad", scientific_name="x",
                kc_initial=0.5, kc_mid=1.0, kc_late=0.8,
                depletion_fraction=0.0,
            )

    def test_immutability(self):
        s = BASIL
        with self.assertRaises(Exception):
            s.kc_mid = 2.0  # type: ignore[misc]


class TestEtCalculations(unittest.TestCase):
    """Verifica delle funzioni di calcolo ET_c potenziale e reale."""

    def test_kc_for_stage_returns_right_value(self):
        self.assertEqual(
            kc_for_stage(BASIL, PhenologicalStage.INITIAL),
            BASIL.kc_initial,
        )
        self.assertEqual(
            kc_for_stage(BASIL, PhenologicalStage.MID_SEASON),
            BASIL.kc_mid,
        )
        self.assertEqual(
            kc_for_stage(BASIL, PhenologicalStage.LATE_SEASON),
            BASIL.kc_late,
        )

    def test_potential_et_c_is_simple_product(self):
        et0 = 5.0  # mm/giorno
        result = potential_et_c(BASIL, PhenologicalStage.MID_SEASON, et0)
        self.assertAlmostEqual(result, BASIL.kc_mid * et0, places=6)

    def test_actual_equals_potential_in_comfort_zone(self):
        # Nella zona di comfort (θ ≥ soglia allerta) Ks=1 e quindi
        # actual = potential.
        et0 = 5.0
        # Per basilico p=0.40: soglia allerta = 0.40 - 0.40×0.25 = 0.30.
        # θ=0.35 è sopra → zona comfort.
        pot = potential_et_c(BASIL, PhenologicalStage.MID_SEASON, et0)
        act = actual_et_c(
            BASIL, PhenologicalStage.MID_SEASON, et0,
            current_theta=0.35, substrate=UNIVERSAL_POTTING_SOIL,
        )
        self.assertAlmostEqual(pot, act, places=6)

    def test_actual_is_zero_at_pwp(self):
        # A θ_PWP Ks=0, quindi ET_c,act = 0 indipendentemente da ET_0.
        act = actual_et_c(
            BASIL, PhenologicalStage.MID_SEASON, et_0=10.0,
            current_theta=UNIVERSAL_POTTING_SOIL.theta_pwp,
            substrate=UNIVERSAL_POTTING_SOIL,
        )
        self.assertEqual(act, 0.0)

    def test_actual_is_strictly_less_than_potential_in_stress(self):
        # In zona di stress (θ tra PWP e soglia allerta) Ks<1.
        et0 = 5.0
        # Per basilico: soglia allerta 0.30. Scegliamo θ=0.20 → in stress.
        pot = potential_et_c(BASIL, PhenologicalStage.MID_SEASON, et0)
        act = actual_et_c(
            BASIL, PhenologicalStage.MID_SEASON, et0,
            current_theta=0.20, substrate=UNIVERSAL_POTTING_SOIL,
        )
        self.assertLess(act, pot)
        self.assertGreater(act, 0.0)


class TestCatalogIntegrity(unittest.TestCase):
    """Sanity check sul catalogo delle specie predefinite."""

    def test_all_species_instantiate_cleanly(self):
        # Il semplice fatto che ALL_SPECIES si importi senza eccezioni
        # significa che ogni Species ha passato la sua __post_init__.
        # Qui ricontrolliamo i vincoli esplicitamente come regression
        # guard: se un domani qualcuno modifica un valore sbagliato,
        # questo test fallisce in modo loquace.
        for s in ALL_SPECIES:
            with self.subTest(name=s.common_name):
                self.assertGreater(s.kc_initial, 0.0)
                self.assertGreater(s.kc_mid, 0.0)
                self.assertGreater(s.kc_late, 0.0)
                self.assertLess(s.kc_initial, 2.0)
                self.assertLess(s.kc_mid, 2.0)
                self.assertLess(s.kc_late, 2.0)
                self.assertGreater(s.depletion_fraction, 0.0)
                self.assertLessEqual(s.depletion_fraction, 1.0)

    def test_tomato_is_high_kc(self):
        # Il pomodoro in piena fruttificazione è notoriamente tra le
        # colture a Kc più alto (letteratura: 1.10-1.20).
        self.assertGreaterEqual(TOMATO.kc_mid, 1.10)

    def test_citrus_is_evergreen_with_stable_kc(self):
        # Gli agrumi sempreverdi hanno Kc pressoché costante: tutte e
        # tre le fasi devono stare in una finestra stretta, diciamo
        # entro 0.15 di escursione.
        kcs = (CITRUS.kc_initial, CITRUS.kc_mid, CITRUS.kc_late)
        self.assertLess(max(kcs) - min(kcs), 0.15)

    def test_lettuce_has_low_depletion_fraction(self):
        # Lattuga come specie sensibile: p ≤ 0.35.
        self.assertLessEqual(LETTUCE.depletion_fraction, 0.35)

    def test_rosemary_has_high_depletion_fraction(self):
        # Rosmarino come xerofita: p ≥ 0.55.
        self.assertGreaterEqual(ROSEMARY.depletion_fraction, 0.55)


# =======================================================================
#  Species con parametri dual-Kc (Kcb)
# =======================================================================
#
# I coefficienti basali Kcb sono opzionali: quando tutti e tre sono
# valorizzati, la specie supporta il modello dual-Kc che separa
# traspirazione (Kcb) ed evaporazione superficiale (Ke). Quando sono
# None, la specie usa il single Kc tradizionale.

class TestSpeciesDualKcParameters(unittest.TestCase):
    """Validazione dei parametri opzionali Kcb."""

    def test_species_without_kcb_does_not_support_dual_kc(self):
        # Default: tutti i Kcb sono None, supports_dual_kc è False.
        # Tutte le specie del catalogo esistente sono in questo stato.
        s = Species(
            common_name="test",
            scientific_name="Test species",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
        )
        self.assertIsNone(s.kcb_initial)
        self.assertFalse(s.supports_dual_kc)

    def test_species_with_all_kcb_supports_dual_kc(self):
        # Specie con tutti i Kcb valorizzati: supports_dual_kc è True.
        s = Species(
            common_name="test",
            scientific_name="Test species",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
            kcb_initial=0.3, kcb_mid=0.85, kcb_late=0.55,
        )
        self.assertTrue(s.supports_dual_kc)

    def test_partial_kcb_rejected(self):
        # Specificare solo alcuni Kcb senza gli altri non ha senso:
        # il modello dual-Kc richiede tutti e tre gli stadi coperti.
        with self.assertRaises(ValueError):
            Species(
                common_name="test",
                scientific_name="Test",
                kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
                kcb_initial=0.3,  # mancano kcb_mid e kcb_late
            )

    def test_kcb_above_kc_rejected(self):
        # Vincolo fisico: Kcb (sola traspirazione) deve essere ≤ Kc
        # (totale: traspirazione + evaporazione media).
        with self.assertRaises(ValueError):
            Species(
                common_name="test",
                scientific_name="Test",
                kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
                kcb_initial=0.6,  # > kc_initial!
                kcb_mid=0.85, kcb_late=0.55,
            )

    def test_kcb_out_of_range_rejected(self):
        # Anche Kcb deve essere in (0, 2).
        with self.assertRaises(ValueError):
            Species(
                common_name="test",
                scientific_name="Test",
                kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
                kcb_initial=0.0,  # zero non è valido
                kcb_mid=0.85, kcb_late=0.55,
            )

    def test_kcb_typical_values_accepted(self):
        # Valori tipici per il basilico: Kcb ~0.10 più bassi dei Kc
        # per ortive in vaso secondo FAO-56 cap. 7.
        s = Species(
            common_name="basilico",
            scientific_name="Ocimum basilicum",
            kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
            kcb_initial=0.35, kcb_mid=1.00, kcb_late=0.75,
        )
        self.assertTrue(s.supports_dual_kc)


# =======================================================================
#  Estensione tappa 3 fascia 2: modello chimico (EC e pH ottimali)
# =======================================================================

class TestSpeciesChemistryModel(unittest.TestCase):
    """
    Validazione dei quattro parametri chimici aggiunti in tappa 3 della
    fascia 2 (ec_optimal_min_mscm, ec_optimal_max_mscm, ph_optimal_min,
    ph_optimal_max). Definiscono il range ottimale di EC e pH del
    substrato per la specie e alimentano il calcolo del Kn.
    """

    def _make_basic_species(self, **overrides) -> Species:
        """Helper: specie minima senza modello chimico, per estendere."""
        defaults = dict(
            common_name="test",
            scientific_name="Test species",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
        )
        defaults.update(overrides)
        return Species(**defaults)

    def test_chemistry_default_all_none(self):
        # Senza specificare nulla, i quattro campi sono None: la specie
        # non supporta il modello chimico.
        s = self._make_basic_species()
        self.assertIsNone(s.ec_optimal_min_mscm)
        self.assertIsNone(s.ec_optimal_max_mscm)
        self.assertIsNone(s.ph_optimal_min)
        self.assertIsNone(s.ph_optimal_max)

    def test_supports_chemistry_model_false_by_default(self):
        # supports_chemistry_model deve essere False per le specie
        # legacy (analogo a supports_dual_kc).
        s = self._make_basic_species()
        self.assertFalse(s.supports_chemistry_model)

    def test_full_chemistry_model_accepted(self):
        # Tutti e quattro valorizzati: la specie supporta il modello.
        s = self._make_basic_species(
            ec_optimal_min_mscm=1.0,
            ec_optimal_max_mscm=1.6,
            ph_optimal_min=6.0,
            ph_optimal_max=7.0,
        )
        self.assertTrue(s.supports_chemistry_model)
        self.assertEqual(s.ec_optimal_min_mscm, 1.0)
        self.assertEqual(s.ph_optimal_max, 7.0)

    def test_partial_chemistry_rejected(self):
        # Tre su quattro: stato indefinito, ValueError.
        with self.assertRaises(ValueError) as ctx:
            self._make_basic_species(
                ec_optimal_min_mscm=1.0,
                ec_optimal_max_mscm=1.6,
                ph_optimal_min=6.0,
                # ph_optimal_max mancante
            )
        self.assertIn("tutti o nessuno", str(ctx.exception))

    def test_one_chemistry_param_alone_rejected(self):
        # Un solo campo valorizzato: anche peggio.
        with self.assertRaises(ValueError):
            self._make_basic_species(ec_optimal_min_mscm=1.0)

    def test_ec_range_inverted_rejected(self):
        # min >= max: range vuoto, fisicamente impossibile.
        with self.assertRaises(ValueError) as ctx:
            self._make_basic_species(
                ec_optimal_min_mscm=2.0,
                ec_optimal_max_mscm=1.5,  # invertito
                ph_optimal_min=6.0,
                ph_optimal_max=7.0,
            )
        self.assertIn("EC", str(ctx.exception))

    def test_ec_excessive_rejected(self):
        # EC > 8 mS/cm è già stress salino acuto, non può essere "ottimale".
        with self.assertRaises(ValueError):
            self._make_basic_species(
                ec_optimal_min_mscm=5.0,
                ec_optimal_max_mscm=10.0,  # troppo alto
                ph_optimal_min=6.0,
                ph_optimal_max=7.0,
            )

    def test_ph_range_inverted_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._make_basic_species(
                ec_optimal_min_mscm=1.0,
                ec_optimal_max_mscm=2.0,
                ph_optimal_min=7.5,
                ph_optimal_max=6.5,  # invertito
            )
        self.assertIn("pH", str(ctx.exception))

    def test_ph_above_14_rejected(self):
        # pH > 14 esce dalla scala chimica.
        with self.assertRaises(ValueError):
            self._make_basic_species(
                ec_optimal_min_mscm=1.0,
                ec_optimal_max_mscm=2.0,
                ph_optimal_min=6.0,
                ph_optimal_max=15.0,
            )

    def test_acidophilic_species_accepted(self):
        # Mirtillo: pH acido 4.5-5.5 è accettato (sotto neutro ma sopra 0).
        s = self._make_basic_species(
            common_name="mirtillo",
            scientific_name="Vaccinium corymbosum",
            ec_optimal_min_mscm=0.8,
            ec_optimal_max_mscm=1.4,
            ph_optimal_min=4.5,
            ph_optimal_max=5.5,
        )
        self.assertTrue(s.supports_chemistry_model)
        self.assertEqual(s.ph_optimal_min, 4.5)

    def test_chemistry_compatible_with_dual_kc(self):
        # Una specie può avere sia il dual-Kc sia il modello chimico:
        # le due estensioni sono indipendenti.
        s = self._make_basic_species(
            kcb_initial=0.35, kcb_mid=0.85, kcb_late=0.55,
            ec_optimal_min_mscm=1.0,
            ec_optimal_max_mscm=1.6,
            ph_optimal_min=6.0,
            ph_optimal_max=7.0,
        )
        self.assertTrue(s.supports_dual_kc)
        self.assertTrue(s.supports_chemistry_model)


if __name__ == "__main__":
    unittest.main()
