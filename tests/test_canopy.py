"""
Test per fitosim.science.canopy: la chioma nel vaso.

Tre famiglie:
  1. La frazione coperta: aree, e il rapporto che può superare 1.
  2. Il fattore di copertura: FAO-56 eq. 76 sotto la copertura piena,
     il rapporto fra le aree sopra, con continuità a fc = 1 e il tetto.
  3. Kcb e Kc: senza pavimento il primo, con pavimento il secondo, e
     «non misurata» che lascia tutto com'è.
"""

import math
import unittest

from fitosim.science.canopy import (
    COVER_CAP,
    KC_MIN_DEFAULT,
    cover_factor,
    cover_fraction,
    kc_from_cover,
    kcb_from_cover,
)


class TestCoverFraction(unittest.TestCase):

    def test_una_chioma_larga_come_il_vaso_copre_esattamente_1(self):
        area_vaso = math.pi * 0.09 ** 2  # vaso da 18 cm
        self.assertAlmostEqual(cover_fraction(0.18, area_vaso), 1.0, places=12)

    def test_una_chioma_doppia_copre_quattro_volte(self):
        area_vaso = math.pi * 0.09 ** 2
        self.assertAlmostEqual(cover_fraction(0.36, area_vaso), 4.0, places=12)

    def test_rifiuta_i_non_positivi(self):
        with self.assertRaises(ValueError):
            cover_fraction(0.0, 0.1)
        with self.assertRaises(ValueError):
            cover_fraction(0.3, 0.0)


class TestCoverFactor(unittest.TestCase):
    """FAO-56 eq. 76: min(1, 2·fc, fc^(1/(1+h)))."""

    def test_l_esempio_di_fao56_meta_copertura_pianta_alta_un_metro(self):
        # fc = 0.5, h = 1 m: min(1, 1.0, 0.5^0.5) = 0.707.
        self.assertAlmostEqual(cover_factor(0.5, 1.0), math.sqrt(0.5), places=10)

    def test_una_chioma_rada_e_limitata_da_due_fc(self):
        # fc = 0.1, h = 2 m: fc^(1/3) = 0.464, ma 2·fc = 0.2 vince.
        self.assertAlmostEqual(cover_factor(0.1, 2.0), 0.2, places=10)

    def test_senza_altezza_il_fattore_e_lineare(self):
        # Esponente 1: min(1, 2·fc, fc) = fc.
        self.assertAlmostEqual(cover_factor(0.5, None), 0.5, places=10)
        self.assertAlmostEqual(cover_factor(0.5, 0.0), 0.5, places=10)

    def test_continuita_alla_copertura_piena(self):
        self.assertEqual(cover_factor(1.0, 0.5), 1.0)
        self.assertAlmostEqual(cover_factor(0.999999, 0.5), 1.0, places=5)
        self.assertAlmostEqual(cover_factor(1.000001, 0.5), 1.0, places=5)

    def test_sopra_la_copertura_piena_scala_con_le_aree_fino_al_tetto(self):
        self.assertAlmostEqual(cover_factor(1.8, 0.5), 1.8, places=10)
        self.assertEqual(cover_factor(4.0, 0.5), COVER_CAP)
        self.assertEqual(cover_factor(100.0, None), COVER_CAP)

    def test_rifiuta_fc_negativa(self):
        with self.assertRaises(ValueError):
            cover_factor(-0.1, 0.5)


class TestKcbAndKc(unittest.TestCase):

    def test_non_misurata_lascia_il_coefficiente_com_e(self):
        self.assertEqual(kcb_from_cover(0.9, None), 0.9)
        self.assertEqual(kc_from_cover(1.05, None), 1.05)

    def test_il_kcb_non_ha_pavimento(self):
        # Chioma piccolissima: il Kcb va verso zero, l'evaporazione è di Ke.
        self.assertAlmostEqual(kcb_from_cover(1.0, 0.01, 0.3), 0.02, places=10)

    def test_il_kc_ha_il_pavimento_del_suolo_nudo(self):
        # Stessa chioma piccolissima: il Kc resta sopra Kc_min.
        kc = kc_from_cover(1.0, 0.01, 0.3)
        self.assertGreater(kc, KC_MIN_DEFAULT)
        self.assertLess(kc, 0.25)
        # E a chioma zero è esattamente il pavimento.
        self.assertAlmostEqual(kc_from_cover(1.0, 0.0, 0.3), KC_MIN_DEFAULT, places=10)

    def test_il_pavimento_non_supera_il_kc_pieno(self):
        # Una specie con Kc sotto il pavimento (succulenta in riposo): il
        # pavimento è il suo Kc, non qualcosa di più.
        self.assertAlmostEqual(kc_from_cover(0.15, 0.0), 0.15, places=10)

    def test_a_meta_copertura_e_un_metro_di_altezza(self):
        # Kc = 0.2 + (1.0 − 0.2) · 0.707 = 0.766 (FAO-56 eq. 76 completa).
        self.assertAlmostEqual(
            kc_from_cover(1.0, 0.5, 1.0), 0.2 + 0.8 * math.sqrt(0.5), places=10,
        )

    def test_sopra_la_copertura_piena_tutti_e_due_scalano_uguale(self):
        self.assertAlmostEqual(kcb_from_cover(0.9, 2.0, 0.5), 1.8, places=10)
        self.assertAlmostEqual(kc_from_cover(0.9, 2.0, 0.5), 1.8, places=10)


if __name__ == "__main__":
    unittest.main()
