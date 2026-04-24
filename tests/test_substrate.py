"""
Test per fitosim.science.substrate.

Copertura in tre famiglie di test:
  1. Validazione della dataclass Substrate e dei suoi vincoli fisici.
  2. Correttezza delle funzioni di calcolo TAW, RAW, volumi.
  3. Sanity check sul catalogo: tutti i substrati pre-definiti devono
     essere fisicamente consistenti e ordinati in modo ragionevole.
"""

import unittest

from fitosim.science.substrate import (
    ALL_SUBSTRATES,
    CACTUS_MIX,
    COCO_COIR,
    DEFAULT_DEPLETION_FRACTION,
    PEAT_BASED,
    PERLITE_RICH,
    Substrate,
    UNIVERSAL_POTTING_SOIL,
    readily_available_water,
    total_available_water,
    water_volume_at_field_capacity,
    water_volume_available,
    water_volume_readily_available,
)


class TestSubstrateDataclass(unittest.TestCase):
    """Verifica creazione e validazione della dataclass."""

    def test_valid_creation(self):
        # Un substrato ben formato deve potersi creare senza errori.
        s = Substrate(name="test", theta_fc=0.4, theta_pwp=0.15)
        self.assertEqual(s.name, "test")
        self.assertEqual(s.theta_fc, 0.4)
        self.assertEqual(s.theta_pwp, 0.15)

    def test_pwp_equal_to_fc_is_rejected(self):
        # Un substrato con θ_PWP = θ_FC non avrebbe acqua disponibile:
        # è fisicamente degenerato e va rifiutato a monte.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=0.3, theta_pwp=0.3)

    def test_pwp_greater_than_fc_is_rejected(self):
        # Impossibile fisicamente: il punto di appassimento non può
        # superare la capacità di campo.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=0.2, theta_pwp=0.3)

    def test_negative_values_are_rejected(self):
        # Contenuti idrici volumetrici negativi sono senza senso fisico.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=0.4, theta_pwp=-0.1)

    def test_values_above_one_are_rejected(self):
        # Frazione volumetrica > 1 significherebbe "più acqua del volume
        # totale del substrato", che è impossibile.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=1.2, theta_pwp=0.5)

    def test_immutability(self):
        # frozen=True: modificare un attributo deve sollevare eccezione.
        s = Substrate(name="test", theta_fc=0.4, theta_pwp=0.15)
        with self.assertRaises(Exception):
            s.theta_fc = 0.5  # type: ignore[misc]


class TestWaterComputations(unittest.TestCase):
    """Verifica delle funzioni di calcolo idrico."""

    def test_taw_is_difference(self):
        # TAW = θ_FC − θ_PWP è la definizione fondamentale.
        s = Substrate(name="test", theta_fc=0.40, theta_pwp=0.15)
        self.assertAlmostEqual(total_available_water(s), 0.25, places=6)

    def test_raw_default_is_half_taw(self):
        # Con la frazione di deplezione di default (0.5), RAW è
        # esattamente metà TAW.
        s = UNIVERSAL_POTTING_SOIL
        taw = total_available_water(s)
        raw = readily_available_water(s)
        self.assertAlmostEqual(raw, taw * DEFAULT_DEPLETION_FRACTION, places=6)
        self.assertAlmostEqual(raw, taw / 2.0, places=6)

    def test_raw_with_custom_depletion(self):
        # Con p custom, RAW deve scalare linearmente.
        s = UNIVERSAL_POTTING_SOIL
        raw_p3 = readily_available_water(s, depletion_fraction=0.3)
        raw_p7 = readily_available_water(s, depletion_fraction=0.7)
        # RAW a p=0.7 deve essere esattamente 7/3 di RAW a p=0.3.
        self.assertAlmostEqual(raw_p7 / raw_p3, 7.0 / 3.0, places=6)

    def test_raw_at_p_zero_is_zero(self):
        # p=0 significa "nessuna deplezione tollerata" — RAW=0.
        raw = readily_available_water(UNIVERSAL_POTTING_SOIL, 0.0)
        self.assertEqual(raw, 0.0)

    def test_raw_at_p_one_equals_taw(self):
        # p=1 significa "tollera deplezione fino al PWP" — RAW=TAW.
        s = UNIVERSAL_POTTING_SOIL
        raw_full = readily_available_water(s, depletion_fraction=1.0)
        self.assertAlmostEqual(raw_full, total_available_water(s), places=6)

    def test_raw_invalid_depletion_raises(self):
        # Frazione fuori da [0, 1] deve essere rifiutata.
        with self.assertRaises(ValueError):
            readily_available_water(UNIVERSAL_POTTING_SOIL, -0.1)
        with self.assertRaises(ValueError):
            readily_available_water(UNIVERSAL_POTTING_SOIL, 1.5)

    def test_volume_at_field_capacity_scales_linearly(self):
        # Il volume a FC deve scalare linearmente con il volume del vaso.
        s = UNIVERSAL_POTTING_SOIL  # θ_FC = 0.40
        # Vaso 5 L → 2 L a FC; vaso 10 L → 4 L a FC.
        self.assertAlmostEqual(
            water_volume_at_field_capacity(s, 5.0), 2.0, places=6
        )
        self.assertAlmostEqual(
            water_volume_at_field_capacity(s, 10.0), 4.0, places=6
        )

    def test_volume_available_universal_5L(self):
        # Caso concreto calcolabile a mano: terriccio universale
        # (TAW=0.25) in un vaso da 5 L dà 1.25 L disponibili.
        vol = water_volume_available(UNIVERSAL_POTTING_SOIL, 5.0)
        self.assertAlmostEqual(vol, 1.25, places=6)

    def test_volume_readily_available_universal_5L(self):
        # Stesso vaso: RAW = 0.5 × 1.25 L = 0.625 L.
        vol = water_volume_readily_available(UNIVERSAL_POTTING_SOIL, 5.0)
        self.assertAlmostEqual(vol, 0.625, places=6)

    def test_negative_pot_volume_raises(self):
        # Nessuna delle funzioni volumetriche deve accettare un volume
        # di vaso negativo.
        with self.assertRaises(ValueError):
            water_volume_at_field_capacity(UNIVERSAL_POTTING_SOIL, -1.0)
        with self.assertRaises(ValueError):
            water_volume_available(UNIVERSAL_POTTING_SOIL, -1.0)
        with self.assertRaises(ValueError):
            water_volume_readily_available(UNIVERSAL_POTTING_SOIL, -1.0)

    def test_zero_pot_volume_yields_zero(self):
        # Vaso da 0 L è accettato come caso limite (è consistente: nessun
        # substrato, nessuna acqua).
        self.assertEqual(
            water_volume_available(UNIVERSAL_POTTING_SOIL, 0.0), 0.0
        )


class TestCatalogIntegrity(unittest.TestCase):
    """Sanity check sul catalogo di substrati predefiniti."""

    def test_all_catalog_entries_are_valid(self):
        # Ogni substrato del catalogo deve rispettare i vincoli fisici.
        # Il fatto stesso che siano stati creati senza eccezione lo
        # garantisce, ma rifarlo qui funge da regression guard: se un
        # domani qualcuno modifica un valore in modo sbagliato, questo
        # test fallisce esplicitamente.
        for s in ALL_SUBSTRATES:
            with self.subTest(name=s.name):
                self.assertGreater(s.theta_fc, s.theta_pwp)
                self.assertGreaterEqual(s.theta_pwp, 0.0)
                self.assertLessEqual(s.theta_fc, 1.0)
                self.assertGreater(total_available_water(s), 0.0)

    def test_peat_has_highest_fc(self):
        # La torba di sfagno deve avere il θ_FC più alto del catalogo:
        # è una proprietà di letteratura che vogliamo mantenere.
        fcs = [(s.name, s.theta_fc) for s in ALL_SUBSTRATES]
        top_name, top_fc = max(fcs, key=lambda x: x[1])
        self.assertEqual(top_name, PEAT_BASED.name)

    def test_cactus_has_lowest_fc(self):
        # Il substrato per cactacee deve avere θ_FC più bassa: è drenante.
        fcs = [(s.name, s.theta_fc) for s in ALL_SUBSTRATES]
        bottom_name, bottom_fc = min(fcs, key=lambda x: x[1])
        self.assertEqual(bottom_name, CACTUS_MIX.name)

    def test_catalog_ordering_matches_retention(self):
        # La tupla ALL_SUBSTRATES è documentata come ordinata dal più
        # ritentivo al più drenante. Verifichiamo che θ_FC sia
        # monotonicamente decrescente seguendo quell'ordine.
        fcs = [s.theta_fc for s in ALL_SUBSTRATES]
        for i in range(len(fcs) - 1):
            with self.subTest(position=i):
                self.assertGreater(fcs[i], fcs[i + 1])


if __name__ == "__main__":
    unittest.main()
