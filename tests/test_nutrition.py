"""
Test del modulo science/nutrition.py (sotto-tappa D tappa 3 fascia 2).

Strategia di test
-----------------

Il modulo nutrition è composto da funzioni pure che prendono numeri
e restituiscono numeri. I test verificano:

  1. **triangular_factor** (la forma bilaterale, oggi non usata dal
     Kn): la forma matematica della funzione su tutti e cinque i
     rami (plateau interno, plateau sinistro clampato, plateau destro
     clampato, rampa sinistra, rampa destra). Casi al limite
     (boundary) compresi.

  2. **salinity_factor** (usata per l'EC): unilaterale. Vale 1 sotto
     e dentro il range, rampa e clamp solo sopra il massimo.

  3. **nutritional_factor**: il Kn per specie realistiche. Verifica
     della disabilitazione silenziosa per specie senza modello
     chimico, dell'assenza di penalità per EC bassa (un substrato
     fresco senza concime traspira come uno in range), della pendenza
     FAO-56 sopra il massimo, e — dal 2026-09-20 (A3) — che il pH
     non entra: la sua tolleranza `PH_TOLERANCE` è delle allerte.

  4. **Validazione**: errori di input → ValueError con messaggi
     diagnostici.
"""

import unittest

from fitosim.domain.species import Species
from fitosim.science.nutrition import (
    EC_STRESS_SLOPE_PCT_PER_MSCM,
    KN_MIN_DEFAULT,
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
    Il Kn dall'EC, e disabilitazione silenziosa.
    """

    def test_optimal_conditions_returns_one(self):
        # Tutto nel range ottimale: Kn = 1.0.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=1.3,    # dentro [1.0, 1.6]
        )
        self.assertEqual(kn, 1.0)

    def test_ec_stress(self):
        # EC sopra il range: Kn = ec_factor.
        # EC=2.6: 1.0 mS/cm oltre il max 1.6; la rampa perde
        # EC_STRESS_SLOPE_PCT_PER_MSCM = 12 % per mS/cm → 0.88.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=2.6,
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
                    species=narrow, ec_substrate_mscm=ec,
                )
                kn_wide = nutritional_factor(
                    species=wide, ec_substrate_mscm=ec,
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
            species=species, ec_substrate_mscm=floor_ec - 0.5,
        )
        at_floor = nutritional_factor(
            species=species, ec_substrate_mscm=floor_ec,
        )
        self.assertGreater(just_below, KN_MIN_DEFAULT)
        self.assertAlmostEqual(at_floor, KN_MIN_DEFAULT, places=9)
        # E una EC "alta ma comune" (2.2 con massimo 1.6, il vecchio
        # punto di clamp) oggi costa il 7 %, non il 70 %.
        self.assertAlmostEqual(
            nutritional_factor(species=species, ec_substrate_mscm=2.2),
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
        )
        self.assertEqual(kn, 1.0)

    # ----- pH: non entra nel Kn (A3, 2026-09-20) -----

    def test_ph_is_not_an_input_of_kn(self):
        # Il pH del vaso agisce sulla nutrizione in settimane, non sulla
        # traspirazione del giorno; FAO-56 non ha un coefficiente per il
        # pH; e nel vaso e' uno stato modellato da un default che nessuna
        # sonda domestica misura. Il Kn non lo prende nemmeno come
        # parametro: una specie con una scheda a pH 5.8-6.2 (e-GRO per
        # rosmarino, basilico, salvia) ha lo stesso Kn di una a 6.0-7.0,
        # e le due schede differiscono solo per l'allerta.
        stretta = _make_species_with_chemistry(ph_min=5.8, ph_max=6.2)
        larga = _make_species_with_chemistry(ph_min=6.0, ph_max=7.0)
        for ec in [0.0, 1.3, 2.6]:
            with self.subTest(ec=ec):
                self.assertEqual(
                    nutritional_factor(species=stretta, ec_substrate_mscm=ec),
                    nutritional_factor(species=larga, ec_substrate_mscm=ec),
                )
        with self.assertRaises(TypeError):
            nutritional_factor(
                species=larga, ec_substrate_mscm=1.3, ph_substrate=8.0,
            )

    def test_ph_tolerance_is_for_the_alerts(self):
        # La banda resta nel modulo per le allerte: e' l'unico numero del
        # modello chimico che riguarda il pH.
        from fitosim.domain.alerts import PH_TOLERANCE as banda_delle_allerte
        self.assertEqual(PH_TOLERANCE, 0.3)
        self.assertIs(banda_delle_allerte, PH_TOLERANCE)

    # ----- A4 (2026-09-20): la pendenza della specie -----

    def test_species_slope_overrides_the_global_one(self):
        # Una mediterranea a 5 %/(mS/cm) (Bernstein et al. 1972: tolleranti)
        # e un'ortiva a 9 (FAO-56 tab. 23) perdono meno del 12 globale a
        # parita' di eccesso: a +1 mS/cm, 0.95 e 0.91 contro 0.88.
        base = _make_species_with_chemistry()   # max 1.6, pendenza globale
        from dataclasses import replace
        mediterranea = replace(base, ec_stress_slope_pct_per_mscm=5.0)
        ortiva = replace(base, ec_stress_slope_pct_per_mscm=9.0)
        self.assertAlmostEqual(
            nutritional_factor(species=base, ec_substrate_mscm=2.6), 0.88, places=9,
        )
        self.assertAlmostEqual(
            nutritional_factor(species=mediterranea, ec_substrate_mscm=2.6), 0.95, places=9,
        )
        self.assertAlmostEqual(
            nutritional_factor(species=ortiva, ec_substrate_mscm=2.6), 0.91, places=9,
        )
        # Il pavimento resta 0.3, raggiunto piu' lontano: a +14 mS/cm per
        # la mediterranea invece che a +5.8.
        self.assertAlmostEqual(
            nutritional_factor(species=mediterranea, ec_substrate_mscm=1.6 + 14.0),
            KN_MIN_DEFAULT, places=9,
        )
        self.assertGreater(
            nutritional_factor(species=mediterranea, ec_substrate_mscm=1.6 + 5.8),
            KN_MIN_DEFAULT,
        )

    def test_species_slope_none_means_the_global_constant(self):
        base = _make_species_with_chemistry()
        self.assertIsNone(base.ec_stress_slope_pct_per_mscm)
        for ec in [1.0, 2.0, 4.0]:
            with self.subTest(ec=ec):
                expected = max(
                    KN_MIN_DEFAULT,
                    1.0 - EC_STRESS_SLOPE_PCT_PER_MSCM / 100.0 * max(0.0, ec - 1.6),
                )
                self.assertAlmostEqual(
                    nutritional_factor(species=base, ec_substrate_mscm=ec), expected, places=9,
                )

    def test_floor_is_kn_min_default(self):
        # Stress salino massimo: Kn = KN_MIN_DEFAULT = 0.3, e non piu'
        # 0.3 x 0.8 = 0.24 con il pH.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=10.0,        # molto sopra
        )
        self.assertAlmostEqual(kn, KN_MIN_DEFAULT, places=9)

    def test_disabled_when_species_lacks_chemistry(self):
        # CRUCIALE: specie senza modello chimico → Kn = 1.0
        # silenziosamente, indipendentemente dallo stato chimico.
        species = _make_species_without_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=15.0,        # estremo
        )
        self.assertEqual(kn, 1.0)

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
                ec_substrate_mscm=ec,
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
                ec_substrate_mscm=-0.5,
            )


if __name__ == "__main__":
    unittest.main()
