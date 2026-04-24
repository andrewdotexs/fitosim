"""
Test per fitosim.science.et0.

La formula di Hargreaves-Samani è deterministica e relativamente semplice,
quindi i test mescolano:
  1. Conversioni di unità elementari (MJ/m² → mm di acqua) come sanity
     check numerici di base.
  2. Un caso di validazione calcolato a mano con input "tondi", così da
     poter verificare il codice confrontandolo con aritmetica eseguibile
     su carta.
  3. Verifica di comportamenti fisicamente attesi: stagionalità, range
     di letteratura per un clima temperato continentale, gestione dei
     casi degeneri (escursione zero, temperature invertite).
"""

import math
import unittest
from datetime import date

from fitosim.science.et0 import (
    LATENT_HEAT_VAPORIZATION,
    et0_hargreaves_samani,
    mj_per_m2_to_mm_water,
)
from fitosim.science.radiation import day_of_year


class TestUnitConversion(unittest.TestCase):
    """Controllo della costante fisica e della conversione energia→acqua."""

    def test_latent_heat_value(self):
        # Valore standard FAO-56 a circa 20 °C.
        self.assertEqual(LATENT_HEAT_VAPORIZATION, 2.45)

    def test_mj_to_mm_identity_at_one(self):
        # 1 MJ/m² deve produrre 1/2.45 ≈ 0.408 mm di acqua.
        self.assertAlmostEqual(mj_per_m2_to_mm_water(1.0), 1.0 / 2.45, places=6)

    def test_mj_to_mm_zero_is_zero(self):
        # Nessuna energia → nessuna evaporazione.
        self.assertEqual(mj_per_m2_to_mm_water(0.0), 0.0)

    def test_mj_to_mm_linearity(self):
        # La conversione è lineare: 10 MJ/m² → 10/2.45 mm.
        self.assertAlmostEqual(mj_per_m2_to_mm_water(10.0), 10.0 / 2.45, places=6)


class TestHargreavesSamani(unittest.TestCase):
    """Test sulla formula ET₀ vera e propria."""

    def test_hand_calculated_equator_near_equinox(self):
        """
        Caso di validazione calcolato a mano, scelto con input "tondi"
        per facilitare la verifica indipendente.

        Input:
            Latitudine = 0° (equatore)
            J = 80 (circa 21 marzo, equinozio di primavera)
            T_min = 20 °C
            T_max = 30 °C

        Calcolo passo-passo:
            R_a(0°, J=80) ≈ 37.8 MJ/m²/giorno  (già validato in
                                                 test_radiation.py)
            R_a in mm      = 37.8 / 2.45 ≈ 15.428 mm/giorno
            T_med          = (20 + 30) / 2 = 25 °C
            ΔT             = 30 − 20 = 10 °C
            √ΔT            ≈ 3.1623
            fattore termico = 25 + 17.8 = 42.8
            ET₀            = 0.0023 × 42.8 × 3.1623 × 15.428
                           ≈ 4.80 mm/giorno
        """
        et0 = et0_hargreaves_samani(
            t_min=20.0, t_max=30.0, latitude_deg=0.0, j=80
        )
        self.assertAlmostEqual(et0, 4.80, delta=0.05)

    def test_milan_summer_in_expected_range(self):
        """
        Per Milano (45.47° N) a metà luglio con condizioni tipiche della
        pianura padana (T_min=18, T_max=30), ET₀ deve cadere nel range
        documentato per il clima temperato continentale europeo, cioè
        circa 4-7 mm/giorno.
        """
        et0 = et0_hargreaves_samani(
            t_min=18.0, t_max=30.0, latitude_deg=45.47,
            j=day_of_year(date(2025, 7, 15)),
        )
        self.assertGreater(et0, 4.0)
        self.assertLess(et0, 7.0)

    def test_summer_higher_than_winter_same_location(self):
        """
        Stessa latitudine (Milano), condizioni meteo tipiche per la
        stagione. ET₀ estiva deve superare largamente quella invernale:
        il fattore è dovuto sia alla temperatura media (che moltiplica
        via il termine T_med + 17.8) sia alla radiazione astronomica
        R_a (molto maggiore in estate). Ci aspettiamo un rapporto di
        almeno 5x.
        """
        et0_summer = et0_hargreaves_samani(
            t_min=16.0, t_max=28.0, latitude_deg=45.47,
            j=day_of_year(date(2025, 6, 15)),
        )
        et0_winter = et0_hargreaves_samani(
            t_min=-1.0, t_max=6.0, latitude_deg=45.47,
            j=day_of_year(date(2025, 1, 15)),
        )
        self.assertGreater(et0_summer, et0_winter)
        self.assertGreater(et0_summer / et0_winter, 5.0)

    def test_zero_thermal_range_yields_zero(self):
        """
        Caso limite degenerato: se T_max = T_min, l'escursione è nulla,
        la radice quadrata produce zero e l'intera ET₀ si azzera. Il
        risultato è matematicamente corretto ma fisicamente degradato:
        segnala che la formula non è in grado di dedurre il segnale
        radiativo dalla sola escursione. In pratica una giornata reale
        ha sempre un'escursione non nulla, quindi questo caso serve
        soprattutto come test del comportamento numerico al limite.
        """
        et0 = et0_hargreaves_samani(
            t_min=20.0, t_max=20.0, latitude_deg=0.0, j=80
        )
        self.assertEqual(et0, 0.0)

    def test_inverted_temperatures_raise_value_error(self):
        """
        Input corrotto (t_max < t_min) deve provocare una ValueError
        esplicita, non un risultato silenziosamente sbagliato (la radice
        quadrata di un numero negativo in Python produce un errore di
        dominio, ma vogliamo segnalarlo prima e con un messaggio
        leggibile).
        """
        with self.assertRaises(ValueError):
            et0_hargreaves_samani(
                t_min=30.0, t_max=20.0, latitude_deg=0.0, j=80
            )

    def test_thermal_range_effect_is_monotonic(self):
        """
        A parità di T_mean, latitudine e giorno, ET₀ deve crescere con
        l'escursione termica (T_max − T_min): un'escursione maggiore
        riflette cieli più limpidi e aria più secca, quindi più
        evaporazione. Test di monotonia su tre escursioni crescenti.
        """
        common = dict(latitude_deg=45.47, j=day_of_year(date(2025, 6, 15)))
        et0_small = et0_hargreaves_samani(t_min=21.0, t_max=23.0, **common)
        et0_medium = et0_hargreaves_samani(t_min=18.0, t_max=26.0, **common)
        et0_large = et0_hargreaves_samani(t_min=14.0, t_max=30.0, **common)
        self.assertLess(et0_small, et0_medium)
        self.assertLess(et0_medium, et0_large)


if __name__ == "__main__":
    unittest.main()
