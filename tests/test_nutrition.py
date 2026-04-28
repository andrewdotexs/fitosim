"""
Test del modulo science/nutrition.py (sotto-tappa D tappa 3 fascia 2).

Strategia di test
-----------------

Il modulo nutrition è composto da funzioni pure che prendono numeri
e restituiscono numeri. I test verificano:

  1. **triangular_factor**: la forma matematica della funzione su
     tutti e cinque i rami (plateau interno, plateau sinistro
     clampato, plateau destro clampato, rampa sinistra, rampa
     destra). Casi al limite (boundary) compresi.

  2. **nutritional_factor**: combinazione di EC e pH per specie
     realistiche. Verifica della disabilitazione silenziosa per
     specie senza modello chimico, e del prodotto come
     combinazione dei due fattori.

  3. **Validazione**: errori di input → ValueError con messaggi
     diagnostici.
"""

import unittest

from fitosim.domain.species import Species
from fitosim.science.nutrition import (
    KN_MIN_DEFAULT,
    PH_STRESS_HALF_WIDTH,
    nutritional_factor,
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
#  Famiglia 2: nutritional_factor — facade EC × pH
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
        # EC fuori range, pH ottimale: Kn = ec_factor × 1.
        # EC=1.9: 0.3 oltre il max 1.6, half_width = ampiezza range = 0.6
        # ec_factor: rampa destra, posizione = 0.3/0.6 = 0.5
        # ec_factor = 1 - 0.5 × (1 - 0.3) = 0.65
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=1.9,
            ph_substrate=6.5,
        )
        self.assertAlmostEqual(kn, 0.65, places=9)

    def test_ph_stress_only(self):
        # pH fuori range, EC ottimale: Kn = 1 × ph_factor.
        # pH=8.0: 1.0 oltre il max 7.0, half_width = 2.0
        # ph_factor: rampa destra, posizione = 1.0/2.0 = 0.5
        # ph_factor = 1 - 0.5 × (1 - 0.3) = 0.65
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=1.3,
            ph_substrate=8.0,
        )
        self.assertAlmostEqual(kn, 0.65, places=9)

    def test_combined_stress_multiplicative(self):
        # Sia EC sia pH fuori range: Kn = ec_factor × ph_factor.
        # EC=1.9 → 0.65, pH=8.0 → 0.65, Kn = 0.65 × 0.65 = 0.4225.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=1.9,
            ph_substrate=8.0,
        )
        self.assertAlmostEqual(kn, 0.4225, places=9)

    def test_extreme_stress_floor(self):
        # Stress massimo simultaneo: Kn = KN_MIN × KN_MIN = 0.09.
        species = _make_species_with_chemistry()
        kn = nutritional_factor(
            species=species,
            ec_substrate_mscm=10.0,        # molto sopra
            ph_substrate=12.0,             # molto sopra
        )
        expected_floor = KN_MIN_DEFAULT * KN_MIN_DEFAULT
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
        # pH 7.0 = 1.5 oltre max=5.5, half_width=2.0
        # ph_factor: rampa destra, posizione = 0.75
        # ph_factor = 1 - 0.75 × 0.7 = 0.475
        kn_alkaline = nutritional_factor(
            species=myrtle,
            ec_substrate_mscm=1.0, ph_substrate=7.0,
        )
        self.assertAlmostEqual(kn_alkaline, 0.475, places=9)

    def test_kn_monotonic_decreasing_outside_range(self):
        # PROPRIETÀ FONDAMENTALE: Kn deve essere monotonamente
        # decrescente all'aumentare della distanza dal range ottimale.
        # Verifichiamolo con una sequenza di EC crescenti oltre il max.
        species = _make_species_with_chemistry()
        ec_values = [1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2]
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
#  Famiglia 3: validazione degli input
# =======================================================================

class TestInputValidation(unittest.TestCase):
    """Errori di input → ValueError."""

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
