"""
Test del modulo science/nutrition.py (sotto-tappa D tappa 3 fascia 2).

Strategia di test
-----------------

Il modulo nutrition è composto da funzioni pure che prendono numeri
e restituiscono numeri. I test verificano:

  1. **triangular_factor** (usata per il pH): la forma matematica
     della funzione su tutti e cinque i rami (plateau interno,
     plateau sinistro clampato, plateau destro clampato, rampa
     sinistra, rampa destra). Casi al limite (boundary) compresi.

  2. **salinity_factor** (usata per l'EC): unilaterale. Vale 1 sotto
     e dentro il range, rampa e clamp solo sopra il massimo.

  3. **nutritional_factor**: combinazione di EC e pH per specie
     realistiche. Verifica della disabilitazione silenziosa per
     specie senza modello chimico, del prodotto come combinazione
     dei due fattori, dell'assenza di penalità per EC bassa (un
     substrato fresco senza concime traspira come uno in range),
     della pendenza FAO-56 sopra il massimo e della banda di
     tolleranza del pH condivisa con le allerte.

  4. **Validazione**: errori di input → ValueError con messaggi
     diagnostici.
"""

import unittest

from fitosim.domain.species import Species
from fitosim.science.nutrition import (
    EC_STRESS_SLOPE_PCT_PER_MSCM,
    KN_MIN_DEFAULT,
    PH_KN_MIN,
    PH_STRESS_HALF_WIDTH,
    PH_TOLERANCE,
    nutritional_factor,
    salinity_factor,
    triangular_factor,
)


# =======================================================================
#  Helper: specie configurabili per i test
# =======================================================================

def _make_species_with_chemistry(
    ec_min=1.0, ec_max=1.6, ph_min=6.0, ph_max=7.0,
) -> Species:
    """Specie con modello chimico configurato (basilico-like)."""
    return Species(
        common_name="test",
        scientific_name="Test species",
        kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
        ec_optimal_min_mscm=ec_min,
        ec_optimal_max_mscm=ec_max,
        ph_optimal_min=ph_min,
        ph_optimal_max=ph_max,
    )


def _make_species_without_chemistry() -> Species:
    """Specie senza modello chimico (legacy della fascia 1)."""
    return Species(
        common_name="legacy",
        scientific_name="Legacy species",
        kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
    )


# =======================================================================
#  Famiglia 1: triangular_factor — forma matematica
# =======================================================================

class TestTriangularFactor(unittest.TestCase):
    """
    Verifica i cinque rami della funzione triangolare-trapezoidale.
    """

    # Parametri canonici per i test (basilico-like).
    a = 1.0   # optimal_min
    b = 1.6   # optimal_max
    h = 0.6   # half_width
    m = KN_MIN_DEFAULT  # 0.3

    # ----- Plateau interno -----

    def test_inside_range_returns_one(self):
        # Dentro il range ottimale, il fattore vale esattamente 1.0.
        for x in [self.a, self.b, 1.3, 1.5]:
            with self.subTest(current=x):
                self.assertEqual(
                    triangular_factor(
                        current=x, optimal_min=self.a,
                        optimal_max=self.b, half_width=self.h,
                    ),
                    1.0,
                )

    def test_at_boundaries_inclusive(self):
        # I due estremi del range sono inclusi nel plateau (non sulla
        # rampa).
        self.assertEqual(
            triangular_factor(
                current=self.a, optimal_min=self.a,
                optimal_max=self.b, half_width=self.h,
            ),
            1.0,
        )
        self.assertEqual(
            triangular_factor(
                current=self.b, optimal_min=self.a,
                optimal_max=self.b, half_width=self.h,
            ),
            1.0,
        )

    # ----- Rampa sinistra -----

    def test_left_ramp_at_midpoint(self):
        # A metà rampa sinistra (x = a - h/2 = 0.7), il fattore è a
        # metà strada tra m e 1: 0.3 + 0.5 × (1 - 0.3) = 0.65.
        x = self.a - self.h / 2.0
        f = triangular_factor(
            current=x, optimal_min=self.a,
            optimal_max=self.b, half_width=self.h,
        )
        self.assertAlmostEqual(f, 0.65, places=9)

    def test_left_ramp_quarter(self):
        # A un quarto della rampa (x = a - 3h/4 = 0.55), siamo a 25%
        # della rampa: 0.3 + 0.25 × 0.7 = 0.475.
        x = self.a - 3.0 * self.h / 4.0
        f = triangular_factor(
            current=x, optimal_min=self.a,
            optimal_max=self.b, half_width=self.h,
        )
        self.assertAlmostEqual(f, 0.475, places=9)

    def test_left_ramp_at_inner_boundary(self):
        # Esattamente al limite del range (x = a), siamo nel plateau:
        # quindi il fattore è 1.0, non sulla rampa.
        f = triangular_factor(
            current=self.a, optimal_min=self.a,
            optimal_max=self.b, half_width=self.h,
        )
        self.assertEqual(f, 1.0)

    # ----- Rampa destra -----

    def test_right_ramp_at_midpoint(self):
        # A metà rampa destra (x = b + h/2 = 1.9), il fattore è 0.65
        # (simmetrico alla rampa sinistra).
        x = self.b + self.h / 2.0
        f = triangular_factor(
            current=x, optimal_min=self.a,
            optimal_max=self.b, half_width=self.h,
        )
        self.assertAlmostEqual(f, 0.65, places=9)

    def test_right_ramp_quarter(self):
        x = self.b + self.h / 4.0
        f = triangular_factor(
            current=x, optimal_min=self.a,
            optimal_max=self.b, half_width=self.h,
        )
        # A 25% nella rampa: 1 - 0.25 × (1 - 0.3) = 0.825
        self.assertAlmostEqual(f, 0.825, places=9)

    # ----- Plateau esterni clampati -----

    def test_clamped_far_left(self):
        # Molto a sinistra (x ≤ a - h): clampato a kn_min.
        for x in [self.a - self.h, self.a - 2 * self.h, -10.0]:
            with self.subTest(current=x):
                self.assertEqual(
                    triangular_factor(
                        current=x, optimal_min=self.a,
                        optimal_max=self.b, half_width=self.h,
                    ),
                    self.m,
                )

    def test_clamped_far_right(self):
        # Molto a destra (x ≥ b + h): clampato a kn_min.
        for x in [self.b + self.h, self.b + 5 * self.h, 100.0]:
            with self.subTest(current=x):
                self.assertEqual(
                    triangular_factor(
                        current=x, optimal_min=self.a,
                        optimal_max=self.b, half_width=self.h,
                    ),
                    self.m,
                )

    # ----- Custom kn_min -----

    def test_custom_kn_min(self):
        # Possibilità di passare kn_min diverso dal default.
        x = self.a - self.h / 2.0
        f = triangular_factor(
            current=x, optimal_min=self.a,
            optimal_max=self.b, half_width=self.h,
            kn_min=0.5,   # personalizzato
        )
        # 0.5 + 0.5 × (1 - 0.5) = 0.75
        self.assertAlmostEqual(f, 0.75, places=9)


# =======================================================================
#  Famiglia 2: salinity_factor — unilaterale, solo eccesso di sali
# =======================================================================

class TestSalinityFactor(unittest.TestCase):
    """
    La metà destra della triangolare: sotto il massimo nessuna
    penalità, sopra rampa e clamp identici a `triangular_factor`.
    """

    # Parametri canonici (basilico-like): range 1.0-1.6, rampa 0.6.
    b = 1.6   # optimal_max
    h = 0.6   # half_width
    m = KN_MIN_DEFAULT  # 0.3

    def _f(self, x, **kwargs):
        return salinity_factor(
            current=x, optimal_max=self.b, half_width=self.h, **kwargs,
        )

    # ----- Sotto e dentro il range: fattore pieno -----

    def test_below_and_inside_range_returns_one(self):
        # L'EC bassa non è uno stress osmotico: 0.0 (substrato fresco),
        # 0.5 (sotto il minimo 1.0), dentro il range, e il massimo
        # compreso valgono tutti esattamente 1.0.
        for x in [0.0, 0.15, 0.5, 1.0, 1.3, self.b]:
            with self.subTest(current=x):
                self.assertEqual(self._f(x), 1.0)

    # ----- Rampa sopra il massimo -----

    def test_ramp_at_midpoint(self):
        # A metà rampa (x = b + h/2 = 1.9): 1 - 0.5 × 0.7 = 0.65,
        # lo stesso valore della rampa destra di triangular_factor.
        self.assertAlmostEqual(self._f(self.b + self.h / 2.0), 0.65, places=9)

    def test_ramp_quarter(self):
        # A un quarto della rampa: 1 - 0.25 × 0.7 = 0.825.
        self.assertAlmostEqual(self._f(self.b + self.h / 4.0), 0.825, places=9)

    def test_ramp_matches_triangular_right_side(self):
        # Sopra il massimo le due funzioni coincidono punto per punto.
        for x in [1.65, 1.8, 1.95, 2.1, 2.2, 3.0]:
            with self.subTest(current=x):
                self.assertAlmostEqual(
                    self._f(x),
                    triangular_factor(
                        current=x, optimal_min=1.0,
                        optimal_max=self.b, half_width=self.h,
                    ),
                    places=12,
                )

    # ----- Plateau clampato -----

    def test_clamped_far_right(self):
        for x in [self.b + self.h, self.b + 5 * self.h, 100.0]:
            with self.subTest(current=x):
                self.assertEqual(self._f(x), self.m)

    # ----- Custom kn_min -----

    def test_custom_kn_min(self):
        # 1 - 0.5 × (1 - 0.5) = 0.75
        self.assertAlmostEqual(
            self._f(self.b + self.h / 2.0, kn_min=0.5), 0.75, places=9,
        )

    def test_monotonic_non_increasing(self):
        # Mai crescente al crescere dell'EC, da zero fino oltre il clamp.
        xs = [0.0, 0.3, 0.9, 1.0, 1.6, 1.7, 1.9, 2.2, 2.5, 5.0]
        values = [self._f(x) for x in xs]
        for i in range(1, len(values)):
            with self.subTest(current=xs[i]):
                self.assertLessEqual(values[i], values[i - 1])


# =======================================================================
#  Famiglia 3: nutritional_factor — facade EC × pH
# =======================================================================

class TestNutritionalFactor(unittest.TestCase):
    """
    Combinazione EC + pH e disabilitazione silenziosa.
    """

    def test_optimal_conditions_returns_one(self):
        # Tutto nel range ottimale: Kn = 1.0.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=1.3,    # dentro [1.0, 1.6]
            ph_substrate=6.5,         # dentro [6.0, 7.0]
        )
        self.assertEqual(kn, 1.0)

    def test_ec_stress_only(self):
        # EC sopra il range, pH ottimale: Kn = ec_factor × 1.
        # EC=2.6: 1.0 mS/cm oltre il max 1.6; la rampa perde
        # EC_STRESS_SLOPE_PCT_PER_MSCM = 12 % per mS/cm → 0.88.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=2.6,
            ph_substrate=6.5,
        )
        self.assertAlmostEqual(kn, 0.88, places=9)

    def test_ec_slope_is_fao56_like_not_range_width(self):
        # PROPRIETÀ: la pendenza sopra il massimo è una costante in
        # %/(mS/cm) (FAO-56 eq. 83), indipendente dall'ampiezza del
        # range della specie. Due specie con lo stesso massimo e range
        # di ampiezza diversa danno lo stesso Kn alla stessa EC.
        narrow = _make_species_with_chemistry(ec_min=1.4, ec_max=1.6)
        wide = _make_species_with_chemistry(ec_min=0.4, ec_max=1.6)
        for ec in [1.6, 2.0, 3.0, 5.0, 9.0]:
            with self.subTest(ec=ec):
                kn_narrow = nutritional_factor(
                    species=narrow, ec_substrate_mscm=ec, ph_substrate=6.5,
                )
                kn_wide = nutritional_factor(
                    species=wide, ec_substrate_mscm=ec, ph_substrate=6.5,
                )
                self.assertAlmostEqual(kn_narrow, kn_wide, places=12)
                expected = max(
                    KN_MIN_DEFAULT,
                    1.0 - EC_STRESS_SLOPE_PCT_PER_MSCM / 100.0 * (ec - 1.6),
                )
                self.assertAlmostEqual(kn_narrow, expected, places=12)

    def test_ec_floor_is_several_mscm_above_max(self):
        # Con pendenza 12 %/(mS/cm) il pavimento 0.3 si tocca a
        # (1 − 0.3) × 100 / 12 ≈ 5.83 mS/cm sopra il massimo: uno
        # stress salino è un fenomeno di diversi mS/cm, non di decimi.
        species = _make_species_with_chemistry()   # max 1.6
        floor_ec = 1.6 + (1.0 - KN_MIN_DEFAULT) * 100.0 / EC_STRESS_SLOPE_PCT_PER_MSCM
        just_below = nutritional_factor(
            species=species, ec_substrate_mscm=floor_ec - 0.5, ph_substrate=6.5,
        )
        at_floor = nutritional_factor(
            species=species, ec_substrate_mscm=floor_ec, ph_substrate=6.5,
        )
        self.assertGreater(just_below, KN_MIN_DEFAULT)
        self.assertAlmostEqual(at_floor, KN_MIN_DEFAULT, places=9)
        # E una EC "alta ma comune" (2.2 con massimo 1.6, il vecchio
        # punto di clamp) oggi costa il 7 %, non il 70 %.
        self.assertAlmostEqual(
            nutritional_factor(species=species, ec_substrate_mscm=2.2, ph_substrate=6.5),
            1.0 - 0.12 * 0.6, places=9,
        )

    def test_ec_below_range_is_not_an_et_penalty(self):
        # L'EC bassa limita la nutrizione (segnalata dalle allerte
        # ec_too_low / fertilization_due), non l'assorbimento d'acqua:
        # sotto il minimo del range il Kn resta esattamente 1.0, a
        # qualsiasi distanza dal minimo.
        species = _make_species_with_chemistry()   # range 1.0-1.6
        for ec in [0.0, 0.15, 0.4, 0.5, 0.7, 0.9, 0.999]:
            with self.subTest(ec=ec):
                kn = nutritional_factor(
                    species=species,
                    ec_substrate_mscm=ec,
                    ph_substrate=6.5,
                )
                self.assertEqual(kn, 1.0)

    def test_fresh_substrate_without_salts_has_kn_one(self):
        # Il caso operativo: un Pot appena creato ha salt_mass_meq = 0,
        # quindi EC modellata 0. Deve traspirare come un vaso in range,
        # altrimenti ogni calibrazione del Kc su substrato fresco parte
        # con il 70 % di ET in meno.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=0.0,
            ph_substrate=6.5,
        )
        self.assertEqual(kn, 1.0)

    def test_ec_below_range_does_not_mask_ph_stress(self):
        # EC bassa e pH fuori range: resta solo il fattore pH.
        # pH=8.0 → 0.93 (vedi test_ph_stress_only); ec_factor = 1.0.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=0.0,
            ph_substrate=8.0,
        )
        self.assertAlmostEqual(kn, 0.93, places=9)

    # ----- pH: banda di tolleranza, rampa lieve, pavimento -----

    def test_ph_within_tolerance_band_no_penalty(self):
        # Entro ±PH_TOLERANCE dal range il fattore pH vale 1: è la
        # stessa banda in cui check_ph_out_of_range non emette allerte.
        species = _make_species_with_chemistry()   # pH 6.0-7.0
        for ph in [6.0 - PH_TOLERANCE, 5.8, 6.0, 6.5, 7.0, 7.2, 7.0 + PH_TOLERANCE]:
            with self.subTest(ph=ph):
                kn = nutritional_factor(
                    species=species, ec_substrate_mscm=1.3, ph_substrate=ph,
                )
                self.assertEqual(kn, 1.0)

    def test_ph_stress_only(self):
        # pH fuori range, EC ottimale: Kn = 1 × ph_factor.
        # pH=8.0: 1.0 oltre il max 7.0, di cui 0.3 di tolleranza →
        # 0.7 nella rampa di 2.0 → posizione 0.35.
        # ph_factor = 1 - 0.35 × (1 - PH_KN_MIN) = 1 - 0.35 × 0.2 = 0.93
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=1.3,
            ph_substrate=8.0,
        )
        self.assertAlmostEqual(kn, 0.93, places=9)

    def test_ph_default_seven_on_narrow_sheet_is_mild(self):
        # Il caso operativo: scheda a pH 5.8-6.2 (e-GRO per basilico,
        # rosmarino, salvia) e vaso che parte dal default 7.0 perché
        # nessuno ha misurato il pH. 0.8 sopra il massimo, 0.5 oltre la
        # banda → 1 - 0.25 × 0.2 = 0.95: il 5 %, non il 28 % di prima.
        species = _make_species_with_chemistry(ph_min=5.8, ph_max=6.2)
        kn = nutritional_factor(
            species=species, ec_substrate_mscm=1.3, ph_substrate=7.0,
        )
        self.assertAlmostEqual(kn, 0.95, places=9)

    def test_ph_floor_is_ph_kn_min(self):
        # Molto fuori in entrambe le direzioni: pavimento PH_KN_MIN, non
        # KN_MIN_DEFAULT. Il pH è un modulatore lieve.
        species = _make_species_with_chemistry()
        for ph in [1.0, 3.0, 3.7, 9.3, 12.0, 14.0]:
            with self.subTest(ph=ph):
                kn = nutritional_factor(
                    species=species, ec_substrate_mscm=1.3, ph_substrate=ph,
                )
                self.assertAlmostEqual(kn, PH_KN_MIN, places=9)

    def test_combined_stress_multiplicative(self):
        # Sia EC sia pH fuori range: Kn = ec_factor × ph_factor.
        # EC=2.6 → 0.88, pH=8.0 → 0.93, Kn = 0.88 × 0.93 = 0.8184.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=2.6,
            ph_substrate=8.0,
        )
        self.assertAlmostEqual(kn, 0.88 * 0.93, places=9)

    def test_extreme_stress_floor(self):
        # Stress massimo simultaneo: Kn = KN_MIN_DEFAULT × PH_KN_MIN
        # = 0.3 × 0.8 = 0.24.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=10.0,        # molto sopra
            ph_substrate=12.0,             # molto sopra
        )
        expected_floor = KN_MIN_DEFAULT * PH_KN_MIN
        self.assertAlmostEqual(kn, expected_floor, places=9)

    def test_disabled_when_species_lacks_chemistry(self):
        # CRUCIALE: specie senza modello chimico → Kn = 1.0
        # silenziosamente, indipendentemente dallo stato chimico.
        species = _make_species_without_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=15.0,        # estremo
            ph_substrate=10.0,             # estremo
        )
        self.assertEqual(kn, 1.0)

    def test_acidophilic_species(self):
        # Mirtillo: range pH 4.5-5.5 (acido). pH=5.0 è ottimale,
        # pH=7.0 è fuori range.
        myrtle = _make_species_with_chemistry(
            ec_min=0.8, ec_max=1.4, ph_min=4.5, ph_max=5.5,
        )
        # pH ottimale
        kn_optimal = nutritional_factor(
            species=myrtle,
            ec_substrate_mscm=1.0, ph_substrate=5.0,
        )
        self.assertEqual(kn_optimal, 1.0)
        # pH 7.0 = 1.5 oltre max=5.5, meno 0.3 di tolleranza = 1.2
        # nella rampa di 2.0 → posizione 0.6
        # ph_factor = 1 - 0.6 × (1 - 0.8) = 0.88
        kn_alkaline = nutritional_factor(
            species=myrtle,
            ec_substrate_mscm=1.0, ph_substrate=7.0,
        )
        self.assertAlmostEqual(kn_alkaline, 0.88, places=9)

    def test_kn_monotonic_decreasing_outside_range(self):
        # PROPRIETÀ FONDAMENTALE: Kn deve essere monotonamente
        # decrescente all'aumentare della distanza dal range ottimale.
        # Verifichiamolo con una sequenza di EC crescenti oltre il max,
        # fino oltre il pavimento.
        species = _make_species_with_chemistry()
        ec_values = [1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 3.0, 5.0, 7.5, 9.0]
        kn_values = [
            nutritional_factor(
                species=species,
                ec_substrate_mscm=ec, ph_substrate=6.5,
            )
            for ec in ec_values
        ]
        # Ogni valore deve essere ≤ del precedente.
        for i in range(1, len(kn_values)):
            with self.subTest(ec=ec_values[i]):
                self.assertLessEqual(kn_values[i], kn_values[i-1])


# =======================================================================
#  Famiglia 4: validazione degli input
# =======================================================================

class TestInputValidation(unittest.TestCase):
    """Errori di input → ValueError."""

    def test_salinity_non_positive_half_width_rejected(self):
        for half_width in [0.0, -0.5]:
            with self.subTest(half_width=half_width):
                with self.assertRaises(ValueError):
                    salinity_factor(
                        current=1.0, optimal_max=1.5, half_width=half_width,
                    )

    def test_salinity_kn_min_out_of_range_rejected(self):
        for kn_min in [1.5, 0.0]:
            with self.subTest(kn_min=kn_min):
                with self.assertRaises(ValueError):
                    salinity_factor(
                        current=1.0, optimal_max=1.5, half_width=0.5,
                        kn_min=kn_min,
                    )

    def test_triangular_inverted_range_rejected(self):
        with self.assertRaises(ValueError):
            triangular_factor(
                current=1.0, optimal_min=2.0,
                optimal_max=1.0, half_width=0.5,
            )

    def test_triangular_zero_half_width_rejected(self):
        with self.assertRaises(ValueError):
            triangular_factor(
                current=1.0, optimal_min=1.0,
                optimal_max=1.5, half_width=0.0,
            )

    def test_triangular_negative_half_width_rejected(self):
        with self.assertRaises(ValueError):
            triangular_factor(
                current=1.0, optimal_min=1.0,
                optimal_max=1.5, half_width=-0.5,
            )

    def test_triangular_kn_min_out_of_range_rejected(self):
        # kn_min > 1 non ha senso (Kn dovrebbe essere ≤ 1).
        with self.assertRaises(ValueError):
            triangular_factor(
                current=1.0, optimal_min=1.0,
                optimal_max=1.5, half_width=0.5,
                kn_min=1.5,
            )
        # kn_min = 0 sarebbe Kn=0 in stress completo (pianta morta),
        # tecnicamente consistente ma scelta operativa: rifiutiamo.
        with self.assertRaises(ValueError):
            triangular_factor(
                current=1.0, optimal_min=1.0,
                optimal_max=1.5, half_width=0.5,
                kn_min=0.0,
            )

    def test_nutritional_negative_ec_rejected(self):
        species = _make_species_with_chemistry()
        with self.assertRaises(ValueError):
            nutritional_factor(
                species=species,
                ec_substrate_mscm=-0.5, ph_substrate=6.5,
            )

    def test_nutritional_invalid_ph_rejected(self):
        species = _make_species_with_chemistry()
        with self.assertRaises(ValueError):
            nutritional_factor(
                species=species,
                ec_substrate_mscm=1.3, ph_substrate=15.0,
            )
        with self.assertRaises(ValueError):
            nutritional_factor(
                species=species,
                ec_substrate_mscm=1.3, ph_substrate=-1.0,
            )


if __name__ == "__main__":
    unittest.main()
