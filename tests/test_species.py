"""
Test per fitosim.domain.species e per stress_coefficient_ks.

Organizzati in quattro famiglie:
  1. Ks come funzione di θ: comportamento ai bordi, linearità, monotonia.
  2. Dataclass Species: creazione, validazione, immutabilità.
  3. kc_for_stage, potential_et_c, actual_et_c: corretta composizione.
  4. Integrità del catalogo: tutte le specie pre-definite sono valide.
"""

import unittest

from datetime import date

from fitosim.domain.species import (
    ALL_SPECIES,
    BASIL,
    CITRUS,
    DEFAULT_ANNUAL_GROWTH_STAGES,
    DORMANCY_KC_FACTOR,
    KC_BARE_SOIL_FLOOR,
    LETTUCE,
    REST_KC_FACTOR,
    ROSEMARY,
    TOMATO,
    GrowthStage,
    PhenologicalStage,
    PhenologyAnchor,
    PhenologyMethod,
    Species,
    actual_et_c,
    dormancy_kc_factor,
    effective_kc,
    effective_kcb,
    fao56_stage_from_growth_stages,
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


# =======================================================================
#  Ancoraggio fenologico e vista botanica
# =======================================================================
#
# Le annuali hanno il ciclo ancorato all'impianto, le perenni alla
# stagione. Prima di questa distinzione le perenni, dopo qualche anno,
# restavano inchiodate per sempre in LATE_SEASON.

class TestGrowthStageVocabulary(unittest.TestCase):
    """Il vocabolario botanico condiviso con The Pot."""

    def test_values_match_the_pot_vocabulary(self):
        # Le stringhe devono coincidere esattamente con il vocabolario
        # controllato di The Pot (DEFAULT_PHENOLOGY_BY_GROUP), altrimenti
        # le due basi dati non si parlano.
        self.assertEqual(GrowthStage.DORMANCY.value, "dormienza")
        self.assertEqual(GrowthStage.REST.value, "riposo")
        self.assertEqual(GrowthStage.BUD_BREAK.value, "germogliamento")
        self.assertEqual(GrowthStage.VEGETATIVE.value, "vegetativo")
        self.assertEqual(GrowthStage.FLOWERING.value, "fioritura")
        self.assertEqual(GrowthStage.FRUITING.value, "fruttificazione")

    def test_six_stages(self):
        self.assertEqual(len(list(GrowthStage)), 6)


class TestFao56Reduction(unittest.TestCase):
    """Riduzione da stadi botanici (anche simultanei) a stadio FAO-56."""

    def test_fruiting_or_flowering_is_mid_season(self):
        for stages in (
            (GrowthStage.FRUITING,),
            (GrowthStage.FLOWERING,),
            (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),
            (GrowthStage.REST, GrowthStage.FRUITING),
        ):
            with self.subTest(stages=stages):
                self.assertEqual(
                    fao56_stage_from_growth_stages(stages),
                    PhenologicalStage.MID_SEASON,
                )

    def test_vegetative_alone_is_mid_season(self):
        self.assertEqual(
            fao56_stage_from_growth_stages((GrowthStage.VEGETATIVE,)),
            PhenologicalStage.MID_SEASON,
        )

    def test_dormancy_and_rest_are_initial(self):
        for stages in (
            (GrowthStage.DORMANCY,),
            (GrowthStage.REST,),
            (GrowthStage.BUD_BREAK,),
        ):
            with self.subTest(stages=stages):
                self.assertEqual(
                    fao56_stage_from_growth_stages(stages),
                    PhenologicalStage.INITIAL,
                )


class TestAnnualAnchoring(unittest.TestCase):
    """Le annuali restano ancorate all'impianto (comportamento storico)."""

    def test_existing_species_default_to_annual(self):
        for sp in (BASIL, TOMATO, LETTUCE):
            with self.subTest(species=sp.common_name):
                self.assertEqual(sp.phenology_anchor, PhenologyAnchor.ANNUAL)

    def test_stage_at_matches_stage_at_day(self):
        # Retrocompatibilità: per un'annuale il nuovo metodo consapevole
        # dell'ancoraggio deve dare esattamente il vecchio risultato.
        planting = date(2026, 5, 1)
        for offset in (0, 5, 19, 20, 45, 69, 70, 120):
            with self.subTest(offset=offset):
                current = date.fromordinal(planting.toordinal() + offset)
                self.assertEqual(
                    BASIL.stage_at(current, planting),
                    BASIL.stage_at_day(offset),
                )

    def test_default_botanical_mapping(self):
        planting = date(2026, 5, 1)
        # INITIAL -> vegetativo
        self.assertEqual(
            BASIL.growth_stages_at(date(2026, 5, 6), planting),
            DEFAULT_ANNUAL_GROWTH_STAGES[PhenologicalStage.INITIAL],
        )
        # MID -> vegetativo + fioritura
        mid = date.fromordinal(planting.toordinal() + 30)
        self.assertIn(GrowthStage.FLOWERING, BASIL.growth_stages_at(mid, planting))

    def test_leaf_crop_never_flowers(self):
        # La lattuga si raccoglie prima della salita a seme: in nessuno
        # stadio deve comparire la fioritura.
        planting = date(2026, 5, 1)
        for offset in (2, 20, 40, 60):
            with self.subTest(offset=offset):
                stages = LETTUCE.growth_stages_at(
                    date.fromordinal(planting.toordinal() + offset), planting,
                )
                self.assertNotIn(GrowthStage.FLOWERING, stages)
                self.assertNotIn(GrowthStage.FRUITING, stages)


class TestPerennialAnchoring(unittest.TestCase):
    """Le perenni seguono la stagione, non i giorni dall'impianto."""

    def test_perennial_species_declare_anchor_and_calendar(self):
        for sp in (CITRUS, ROSEMARY):
            with self.subTest(species=sp.common_name):
                self.assertEqual(
                    sp.phenology_anchor, PhenologyAnchor.PERENNIAL,
                )
                self.assertIsNotNone(sp.phenology_calendar)
                self.assertEqual(len(sp.phenology_calendar), 12)

    def test_old_perennial_is_not_stuck_in_late_season(self):
        # E' il bug che questo refactor risolve: con l'ancoraggio ai
        # giorni, un limone piantato cinque anni fa sarebbe per sempre
        # in LATE_SEASON.
        planting = date(2021, 3, 1)
        far_future = date(2026, 5, 15)
        self.assertEqual(
            CITRUS.stage_at_day((far_future - planting).days),
            PhenologicalStage.LATE_SEASON,
        )
        self.assertNotEqual(
            CITRUS.stage_at(far_future, planting),
            PhenologicalStage.LATE_SEASON,
        )

    def test_stage_depends_on_season_not_on_planting_date(self):
        # Due limoni piantati ad anni di distanza, osservati lo stesso
        # giorno, devono essere nello stesso stadio.
        observed = date(2026, 7, 15)
        old_plant = date(2015, 4, 1)
        young_plant = date(2025, 9, 20)
        self.assertEqual(
            CITRUS.stage_at(observed, old_plant),
            CITRUS.stage_at(observed, young_plant),
        )

    def test_rosemary_winter_consumes_less_than_summer(self):
        # Il guadagno concreto del refactor: il rosmarino in riposo
        # invernale ha un Kc nettamente più basso che in piena estate.
        planting = date(2020, 4, 1)
        winter_kc = kc_for_stage(
            ROSEMARY, ROSEMARY.stage_at(date(2026, 1, 15), planting),
        )
        summer_kc = kc_for_stage(
            ROSEMARY, ROSEMARY.stage_at(date(2026, 7, 15), planting),
        )
        self.assertLess(winter_kc, summer_kc)

    def test_rosemary_botanical_view_follows_season(self):
        planting = date(2020, 4, 1)
        self.assertEqual(
            ROSEMARY.growth_stages_at(date(2026, 1, 15), planting),
            (GrowthStage.REST,),
        )
        self.assertIn(
            GrowthStage.FLOWERING,
            ROSEMARY.growth_stages_at(date(2026, 6, 15), planting),
        )

    def test_citrus_carries_fruit_in_winter(self):
        # Caratteristica nota del catalogo: il limone porta frutti anche
        # d'inverno, quindi a gennaio dichiara riposo E fruttificazione.
        planting = date(2020, 4, 1)
        stages = CITRUS.growth_stages_at(date(2026, 1, 15), planting)
        self.assertIn(GrowthStage.REST, stages)
        self.assertIn(GrowthStage.FRUITING, stages)


class TestDormancyKcReduction(unittest.TestCase):
    """Riduzione del Kc in dormienza e riposo, col pavimento evaporativo."""

    def test_factor_by_stage(self):
        self.assertEqual(
            dormancy_kc_factor((GrowthStage.DORMANCY,)), DORMANCY_KC_FACTOR,
        )
        self.assertEqual(
            dormancy_kc_factor((GrowthStage.REST,)), REST_KC_FACTOR,
        )

    def test_no_factor_for_active_stages(self):
        for stages in (
            (GrowthStage.VEGETATIVE,),
            (GrowthStage.FLOWERING,),
            (GrowthStage.FRUITING,),
            (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),
        ):
            with self.subTest(stages=stages):
                self.assertIsNone(dormancy_kc_factor(stages))

    def test_bud_break_is_not_reduced(self):
        # La ripresa e' attivita', non riposo: la chioma ancora piccola
        # e' gia' rappresentata dal Kc dello stadio iniziale, quindi
        # applicare una riduzione sarebbe doppio conteggio.
        self.assertIsNone(dormancy_kc_factor((GrowthStage.BUD_BREAK,)))

    def test_rest_applies_even_with_fruit(self):
        # Il limone a gennaio e' in riposo E porta frutti: il suo
        # metabolismo e' quello di una pianta in riposo.
        self.assertEqual(
            dormancy_kc_factor((GrowthStage.REST, GrowthStage.FRUITING)),
            REST_KC_FACTOR,
        )

    def test_deep_dormancy_wins_over_rest(self):
        self.assertEqual(
            dormancy_kc_factor((GrowthStage.DORMANCY, GrowthStage.REST)),
            DORMANCY_KC_FACTOR,
        )

    def test_effective_kc_without_growth_stages_is_unchanged(self):
        # Retrocompatibilita': senza vista botanica nessuna riduzione.
        for stage in PhenologicalStage:
            with self.subTest(stage=stage):
                self.assertEqual(
                    effective_kc(ROSEMARY, stage),
                    kc_for_stage(ROSEMARY, stage),
                )

    def test_effective_kc_active_stages_unchanged(self):
        self.assertEqual(
            effective_kc(
                ROSEMARY, PhenologicalStage.MID_SEASON,
                (GrowthStage.VEGETATIVE,),
            ),
            kc_for_stage(ROSEMARY, PhenologicalStage.MID_SEASON),
        )

    def test_effective_kc_is_fraction_of_kc_mid(self):
        kc = effective_kc(
            ROSEMARY, PhenologicalStage.INITIAL, (GrowthStage.REST,),
        )
        self.assertAlmostEqual(kc, ROSEMARY.kc_mid * REST_KC_FACTOR)

    def test_evaporation_floor_binds_for_low_kc_species(self):
        # Una specie a Kc molto basso: la riduzione moltiplicativa
        # scenderebbe sotto il pavimento, ma il substrato continua a
        # evaporare anche se la pianta e' ferma.
        low = Species(
            common_name="Test", scientific_name="Testus testus",
            kc_initial=0.20, kc_mid=0.30, kc_late=0.25,
        )
        raw = low.kc_mid * DORMANCY_KC_FACTOR      # 0.075
        self.assertLess(raw, KC_BARE_SOIL_FLOOR)
        kc = effective_kc(
            low, PhenologicalStage.INITIAL, (GrowthStage.DORMANCY,),
        )
        self.assertEqual(kc, KC_BARE_SOIL_FLOOR)

    def test_dormant_pot_still_consumes_water(self):
        # Il pavimento non e' un dettaglio: un modello che dicesse
        # "la pianta dormiente non consuma nulla" non suggerirebbe mai
        # di irrigare, e le perenni in vaso muoiono anche di sete
        # invernale, non solo di marciume.
        for sp in (CITRUS, ROSEMARY):
            with self.subTest(species=sp.common_name):
                kc = effective_kc(
                    sp, PhenologicalStage.INITIAL, (GrowthStage.DORMANCY,),
                )
                self.assertGreaterEqual(kc, KC_BARE_SOIL_FLOOR)
                self.assertGreater(kc, 0.0)

    def test_citrus_winter_much_lower_than_summer(self):
        # Il bug che questa slice risolve: al limone in riposo
        # invernale veniva attribuito il Kc di piena attivita' estiva.
        planting = date(2020, 4, 1)
        winter = date(2026, 1, 15)
        summer = date(2026, 7, 15)
        kc_winter = effective_kc(
            CITRUS, CITRUS.stage_at(winter, planting),
            CITRUS.growth_stages_at(winter, planting),
        )
        kc_summer = effective_kc(
            CITRUS, CITRUS.stage_at(summer, planting),
            CITRUS.growth_stages_at(summer, planting),
        )
        self.assertLess(kc_winter, kc_summer)
        # Prima della correzione erano identici (entrambi kc_mid).
        self.assertLess(kc_winter, kc_summer * 0.75)

    def test_annual_species_never_reduced(self):
        planting = date(2026, 5, 1)
        for offset in (5, 30, 80):
            with self.subTest(offset=offset):
                d = date.fromordinal(planting.toordinal() + offset)
                stage = BASIL.stage_at(d, planting)
                self.assertEqual(
                    effective_kc(
                        BASIL, stage, BASIL.growth_stages_at(d, planting),
                    ),
                    kc_for_stage(BASIL, stage),
                )


class TestDormancyKcbReduction(unittest.TestCase):
    """Nel dual-Kc la riduzione non ha pavimento: Ke copre l'evaporazione."""

    def _dual_kc_species(self):
        return Species(
            common_name="Test dual", scientific_name="Testus dualis",
            kc_initial=0.50, kc_mid=1.00, kc_late=0.80,
            kcb_initial=0.35, kcb_mid=0.90, kcb_late=0.70,
        )

    def test_kcb_unchanged_without_growth_stages(self):
        sp = self._dual_kc_species()
        self.assertEqual(
            effective_kcb(sp, PhenologicalStage.MID_SEASON), sp.kcb_mid,
        )

    def test_kcb_reduced_in_dormancy(self):
        sp = self._dual_kc_species()
        kcb = effective_kcb(
            sp, PhenologicalStage.MID_SEASON, (GrowthStage.DORMANCY,),
        )
        self.assertAlmostEqual(kcb, sp.kcb_mid * DORMANCY_KC_FACTOR)

    def test_kcb_has_no_evaporation_floor(self):
        # Kcb e' traspirazione pura: puo' scendere sotto il pavimento
        # evaporativo, perche' nel dual-Kc l'evaporazione la conta Ke.
        sp = Species(
            common_name="Test", scientific_name="Testus testus",
            kc_initial=0.30, kc_mid=0.40, kc_late=0.35,
            kcb_initial=0.20, kcb_mid=0.30, kcb_late=0.25,
        )
        kcb = effective_kcb(
            sp, PhenologicalStage.MID_SEASON, (GrowthStage.DORMANCY,),
        )
        self.assertLess(kcb, KC_BARE_SOIL_FLOOR)
        self.assertGreater(kcb, 0.0)


class TestGddPhenology(unittest.TestCase):
    """Stadio guidato dal calore accumulato invece che dal calendario."""

    def test_annual_species_have_gdd_thresholds(self):
        for sp in (BASIL, TOMATO, LETTUCE):
            with self.subTest(species=sp.common_name):
                self.assertTrue(sp.supports_gdd)
                self.assertIsNotNone(sp.t_base_c)

    def test_perennials_have_no_gdd_thresholds(self):
        # I GDD non modellano l'uscita dalla dormienza delle perenni:
        # servirebbe l'accumulo di freddo invernale.
        for sp in (CITRUS, ROSEMARY):
            with self.subTest(species=sp.common_name):
                self.assertFalse(sp.supports_gdd)

    def test_cool_season_crop_has_lower_base(self):
        # La lattuga si sviluppa a temperature piu' basse del basilico.
        self.assertLess(LETTUCE.t_base_c, BASIL.t_base_c)

    def test_stage_at_gdd_thresholds(self):
        self.assertEqual(
            BASIL.stage_at_gdd(0.0), PhenologicalStage.INITIAL,
        )
        self.assertEqual(
            BASIL.stage_at_gdd(BASIL.gdd_to_mid - 1),
            PhenologicalStage.INITIAL,
        )
        self.assertEqual(
            BASIL.stage_at_gdd(BASIL.gdd_to_mid),
            PhenologicalStage.MID_SEASON,
        )
        self.assertEqual(
            BASIL.stage_at_gdd(BASIL.gdd_to_late),
            PhenologicalStage.LATE_SEASON,
        )

    def test_stage_at_gdd_requires_thresholds(self):
        with self.assertRaises(ValueError) as ctx:
            CITRUS.stage_at_gdd(500.0)
        self.assertIn("GDD", str(ctx.exception))

    def test_selector_prefers_gdd_when_available(self):
        # Stesso giorno di calendario, due accumuli termici diversi:
        # lo stadio segue il calore, non i giorni.
        planting = date(2026, 5, 1)
        day10 = date(2026, 5, 11)
        slow = BASIL.stage_at(day10, planting, gdd_accumulated=50.0)
        fast = BASIL.stage_at(day10, planting, gdd_accumulated=300.0)
        self.assertEqual(slow, PhenologicalStage.INITIAL)
        self.assertEqual(fast, PhenologicalStage.MID_SEASON)

    def test_selector_falls_back_to_days_without_gdd(self):
        # gdd_accumulated=None significa "non lo sto tracciando":
        # degradazione sicura al comportamento storico.
        planting = date(2026, 5, 1)
        for offset in (5, 25, 90):
            with self.subTest(offset=offset):
                d = date.fromordinal(planting.toordinal() + offset)
                self.assertEqual(
                    BASIL.stage_at(d, planting),
                    BASIL.stage_at_day(offset),
                )

    def test_perennial_ignores_gdd_even_if_passed(self):
        # Per una perenne il calendario stagionale vince comunque.
        planting = date(2020, 4, 1)
        january = date(2026, 1, 15)
        self.assertEqual(
            CITRUS.stage_at(january, planting, gdd_accumulated=5000.0),
            CITRUS.stage_at(january, planting),
        )

    def test_phenology_method_is_traceable(self):
        planting = date(2026, 5, 1)
        self.assertEqual(
            BASIL.phenology_method(gdd_accumulated=100.0),
            PhenologyMethod.GROWING_DEGREE_DAYS,
        )
        self.assertEqual(
            BASIL.phenology_method(), PhenologyMethod.CALENDAR_DAYS,
        )
        self.assertEqual(
            CITRUS.phenology_method(gdd_accumulated=100.0),
            PhenologyMethod.SEASONAL,
        )

    def test_growth_stages_follow_gdd_too(self):
        # La vista botanica usa lo stesso selettore dello stadio FAO-56.
        planting = date(2026, 5, 1)
        day10 = date(2026, 5, 11)
        early = BASIL.growth_stages_at(day10, planting, gdd_accumulated=50.0)
        late = BASIL.growth_stages_at(day10, planting, gdd_accumulated=300.0)
        self.assertNotIn(GrowthStage.FLOWERING, early)
        self.assertIn(GrowthStage.FLOWERING, late)


class TestGddValidation(unittest.TestCase):
    """Coerenza dei parametri GDD sulla specie."""

    def _kwargs(self, **overrides):
        kwargs = dict(
            common_name="Test", scientific_name="Testus testus",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.8,
        )
        kwargs.update(overrides)
        return kwargs

    def test_partial_gdd_params_raise(self):
        with self.assertRaises(ValueError) as ctx:
            Species(**self._kwargs(t_base_c=10.0))
        self.assertIn("tutti e tre", str(ctx.exception))

    def test_unordered_thresholds_raise(self):
        with self.assertRaises(ValueError) as ctx:
            Species(**self._kwargs(
                t_base_c=10.0, gdd_to_mid=800.0, gdd_to_late=400.0,
            ))
        self.assertIn("gdd_to_mid", str(ctx.exception))

    def test_gdd_on_perennial_raises(self):
        # I GDD non si applicano alle perenni: l'errore lo dice e
        # spiega perche'.
        with self.assertRaises(ValueError) as ctx:
            Species(**self._kwargs(
                phenology_anchor=PhenologyAnchor.PERENNIAL,
                phenology_calendar=((GrowthStage.VEGETATIVE,),) * 12,
                t_base_c=10.0, gdd_to_mid=200.0, gdd_to_late=600.0,
            ))
        self.assertIn("PERENNIAL", str(ctx.exception))

    def test_cap_below_base_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Species(**self._kwargs(
                t_base_c=10.0, gdd_to_mid=200.0, gdd_to_late=600.0,
                t_cap_c=5.0,
            ))
        self.assertIn("t_cap_c", str(ctx.exception))

    def test_no_gdd_params_is_valid(self):
        s = Species(**self._kwargs())
        self.assertFalse(s.supports_gdd)


class TestPerennialValidation(unittest.TestCase):
    """Una perenne senza calendario non saprebbe in che stadio si trova."""

    def _base_kwargs(self, **overrides):
        kwargs = dict(
            common_name="Test", scientific_name="Testus testus",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.8,
            phenology_anchor=PhenologyAnchor.PERENNIAL,
        )
        kwargs.update(overrides)
        return kwargs

    def test_perennial_without_calendar_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Species(**self._base_kwargs())
        self.assertIn("phenology_calendar", str(ctx.exception))

    def test_calendar_with_wrong_length_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Species(**self._base_kwargs(
                phenology_calendar=((GrowthStage.VEGETATIVE,),) * 11,
            ))
        self.assertIn("12", str(ctx.exception))

    def test_empty_month_raises(self):
        calendar = [(GrowthStage.VEGETATIVE,)] * 12
        calendar[5] = ()
        with self.assertRaises(ValueError) as ctx:
            Species(**self._base_kwargs(phenology_calendar=tuple(calendar)))
        self.assertIn("vuoto", str(ctx.exception))

    def test_annual_does_not_require_calendar(self):
        # Il caso di gran lunga più comune resta senza attriti.
        s = Species(
            common_name="Test", scientific_name="Testus testus",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.8,
        )
        self.assertEqual(s.phenology_anchor, PhenologyAnchor.ANNUAL)
        self.assertIsNone(s.phenology_calendar)


if __name__ == "__main__":
    unittest.main()
