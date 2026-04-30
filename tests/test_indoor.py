"""
Test del modulo science/indoor.py introdotto dalla fase D2 della
sotto-tappa D tappa 5.

Il modulo offre tre funzioni di utility per stimare la radiazione
indoor in MJ/m²/giorno: il modo categoriale (valori fissi), il modo
continuo (frazione della radiazione outdoor), e il selettore "best
available" che sceglie tra i due in base ai dati disponibili.
"""

import unittest

from fitosim.domain.room import LightExposure
from fitosim.science.indoor import (
    DARK_FRACTION_OF_OUTDOOR,
    DARK_RADIATION_MJ_M2_DAY,
    DIRECT_SUN_FRACTION_OF_OUTDOOR,
    DIRECT_SUN_RADIATION_MJ_M2_DAY,
    INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR,
    INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY,
    categorical_indoor_radiation,
    continuous_indoor_radiation,
    estimate_indoor_radiation,
)


class TestCategoricalIndoorRadiation(unittest.TestCase):
    """
    Verifica della mappatura categoriale: ogni LightExposure produce
    il valore di radiazione fissa associato.
    """

    def test_dark_returns_dark_constant(self):
        # DARK → valore basso ~1.5 MJ/m²/d.
        rad = categorical_indoor_radiation(exposure=LightExposure.DARK)
        self.assertEqual(rad, DARK_RADIATION_MJ_M2_DAY)

    def test_indirect_bright_returns_indirect_constant(self):
        # INDIRECT_BRIGHT → valore intermedio ~4.0 MJ/m²/d.
        rad = categorical_indoor_radiation(
            exposure=LightExposure.INDIRECT_BRIGHT,
        )
        self.assertEqual(rad, INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY)

    def test_direct_sun_returns_sun_constant(self):
        # DIRECT_SUN → valore alto ~8.0 MJ/m²/d.
        rad = categorical_indoor_radiation(
            exposure=LightExposure.DIRECT_SUN,
        )
        self.assertEqual(rad, DIRECT_SUN_RADIATION_MJ_M2_DAY)

    def test_categorical_ordering(self):
        # I tre valori devono essere in ordine crescente:
        # DARK < INDIRECT_BRIGHT < DIRECT_SUN.
        # Questo è il vincolo fisico di base che il modello deve
        # rispettare a prescindere dai numeri specifici scelti.
        rad_dark = categorical_indoor_radiation(LightExposure.DARK)
        rad_indirect = categorical_indoor_radiation(
            LightExposure.INDIRECT_BRIGHT,
        )
        rad_sun = categorical_indoor_radiation(LightExposure.DIRECT_SUN)
        self.assertLess(rad_dark, rad_indirect)
        self.assertLess(rad_indirect, rad_sun)


class TestContinuousIndoorRadiation(unittest.TestCase):
    """
    Verifica del modo continuo: la radiazione indoor è una frazione
    della radiazione outdoor, e cattura naturalmente la stagionalità.
    """

    def test_dark_is_dark_fraction_of_outdoor(self):
        # Outdoor 24, DARK → 24 * fraction_dark.
        rad = continuous_indoor_radiation(
            exposure=LightExposure.DARK,
            outdoor_radiation_mj_m2_day=24.0,
        )
        expected = 24.0 * DARK_FRACTION_OF_OUTDOOR
        self.assertAlmostEqual(rad, expected, places=6)

    def test_indirect_bright_is_indirect_fraction_of_outdoor(self):
        rad = continuous_indoor_radiation(
            exposure=LightExposure.INDIRECT_BRIGHT,
            outdoor_radiation_mj_m2_day=24.0,
        )
        expected = 24.0 * INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR
        self.assertAlmostEqual(rad, expected, places=6)

    def test_direct_sun_is_sun_fraction_of_outdoor(self):
        rad = continuous_indoor_radiation(
            exposure=LightExposure.DIRECT_SUN,
            outdoor_radiation_mj_m2_day=24.0,
        )
        expected = 24.0 * DIRECT_SUN_FRACTION_OF_OUTDOOR
        self.assertAlmostEqual(rad, expected, places=6)

    def test_seasonal_difference_captured(self):
        # La proprietà fisica chiave del modo continuo: in giornata
        # invernale (outdoor=5) il vaso DIRECT_SUN riceve molto meno
        # che in giornata estiva (outdoor=24). Il modo categoriale
        # NON cattura questa differenza, il modo continuo SÌ.
        rad_summer = continuous_indoor_radiation(
            exposure=LightExposure.DIRECT_SUN,
            outdoor_radiation_mj_m2_day=24.0,
        )
        rad_winter = continuous_indoor_radiation(
            exposure=LightExposure.DIRECT_SUN,
            outdoor_radiation_mj_m2_day=5.0,
        )
        # Inverno almeno tre volte meno dell'estate.
        self.assertLess(rad_winter, rad_summer / 3)

    def test_negative_outdoor_radiation_raises(self):
        # Validazione dell'input: outdoor negativa è un errore.
        with self.assertRaises(ValueError):
            continuous_indoor_radiation(
                exposure=LightExposure.DARK,
                outdoor_radiation_mj_m2_day=-5.0,
            )

    def test_zero_outdoor_radiation_returns_zero(self):
        # Outdoor zero (per esempio "giornata di tempesta totale,
        # zero radiazione") produce indoor zero coerentemente.
        rad = continuous_indoor_radiation(
            exposure=LightExposure.DIRECT_SUN,
            outdoor_radiation_mj_m2_day=0.0,
        )
        self.assertEqual(rad, 0.0)


class TestEstimateIndoorRadiation(unittest.TestCase):
    """
    Verifica del selettore "best available" che sceglie tra modo
    continuo e categoriale in base ai dati disponibili.
    """

    def test_with_outdoor_uses_continuous(self):
        # Con outdoor passato, il selettore usa il modo continuo.
        rad = estimate_indoor_radiation(
            exposure=LightExposure.INDIRECT_BRIGHT,
            outdoor_radiation_mj_m2_day=24.0,
        )
        expected = 24.0 * INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR
        self.assertAlmostEqual(rad, expected, places=6)

    def test_without_outdoor_uses_categorical(self):
        # Senza outdoor, il selettore usa il modo categoriale.
        rad = estimate_indoor_radiation(
            exposure=LightExposure.INDIRECT_BRIGHT,
            outdoor_radiation_mj_m2_day=None,
        )
        self.assertEqual(rad, INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY)

    def test_default_outdoor_none(self):
        # Default del parametro outdoor: None (modo categoriale).
        rad = estimate_indoor_radiation(exposure=LightExposure.DARK)
        self.assertEqual(rad, DARK_RADIATION_MJ_M2_DAY)


if __name__ == "__main__":
    unittest.main()
