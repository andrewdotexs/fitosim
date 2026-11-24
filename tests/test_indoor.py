"""
Test del modulo science/indoor.py introdotto dalla fase D2 della
sotto-tappa D tappa 5.

Il modulo offre tre funzioni di utility per stimare la radiazione
indoor in MJ/m²/giorno: il modo categoriale (valori fissi), il modo
continuo (frazione della radiazione outdoor), e il selettore "best
available" che sceglie tra i due in base ai dati disponibili.
"""

import unittest
from datetime import date

from fitosim.domain.pot import Location, Pot
from fitosim.domain.room import (
    DEFAULT_INDOOR_WIND_M_S,
    IndoorMicroclimate,
    LightExposure,
    MicroclimateKind,
)
from fitosim.domain.species import Species
from fitosim.science.et0 import EtMethod, compute_et
from fitosim.science.indoor import (
    DARK_FRACTION_OF_OUTDOOR,
    DARK_RADIATION_MJ_M2_DAY,
    DIRECT_SUN_FRACTION_OF_OUTDOOR,
    DIRECT_SUN_RADIATION_MJ_M2_DAY,
    INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR,
    INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY,
    INDOOR_ALBEDO,
    categorical_indoor_radiation,
    continuous_indoor_radiation,
    estimate_indoor_net_radiation,
    estimate_indoor_radiation,
    net_indoor_radiation,
)
from fitosim.science.pot_physics import SunExposure
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import Substrate


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


class TestNetIndoorRadiation(unittest.TestCase):
    """
    Dalla globale alla netta (N2, 2026-11-24): la parte riflessa via,
    l'onda lunga a zero. È la radiazione che va a Penman-Monteith.
    """

    def test_the_albedo_is_that_of_the_reference_crop(self):
        self.assertEqual(INDOOR_ALBEDO, 0.23)

    def test_the_net_is_the_part_not_reflected(self):
        self.assertAlmostEqual(net_indoor_radiation(10.0), 7.7)
        self.assertEqual(net_indoor_radiation(0.0), 0.0)
        self.assertAlmostEqual(net_indoor_radiation(10.0, albedo=0.0), 10.0)

    def test_wrong_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            net_indoor_radiation(-1.0)
        for wrong in (-0.1, 1.0, 1.5):
            with self.assertRaises(ValueError):
                net_indoor_radiation(10.0, albedo=wrong)

    def test_the_estimate_is_the_global_one_less_the_albedo(self):
        for exposure in LightExposure:
            with self.subTest(exposure=exposure):
                # Col sole vero…
                self.assertAlmostEqual(
                    estimate_indoor_net_radiation(exposure, 20.0),
                    (1.0 - INDOOR_ALBEDO) * estimate_indoor_radiation(exposure, 20.0),
                )
                # …e col numero fisso del livello.
                self.assertAlmostEqual(
                    estimate_indoor_net_radiation(exposure),
                    (1.0 - INDOOR_ALBEDO) * estimate_indoor_radiation(exposure),
                )


JUNE = date(2026, 6, 15)
OUTDOOR_MJ = 20.0
ROOM = IndoorMicroclimate(
    kind=MicroclimateKind.DAILY, temperature_c=22.0, humidity_relative=0.5,
    t_min=20.0, t_max=24.0,
)


def _indoor_pot(**overrides) -> Pot:
    defaults = dict(
        species=Species(
            common_name="media", scientific_name="Planta media",
            kc_initial=0.6, kc_mid=1.0, kc_late=0.8,
        ),
        substrate=Substrate(name="universale", theta_fc=0.40, theta_pwp=0.10),
        pot_volume_l=4.0, pot_diameter_cm=20.0, location=Location.INDOOR,
        light_exposure=LightExposure.INDIRECT_BRIGHT, planting_date=date(2025, 4, 1),
    )
    defaults.update(overrides)
    pot = Pot(label="vaso", **defaults)
    pot.state_mm = pot.fc_mm
    return pot


def _room_et0(net_radiation_mj: float) -> float:
    """L'ET₀ della stanza come la calcola il passo in casa, con quella netta."""
    result = compute_et(
        t_min=ROOM.t_min, t_max=ROOM.t_max, latitude_deg=45.0, j=day_of_year(JUNE),
        humidity_relative=ROOM.humidity_relative, wind_speed_m_s=DEFAULT_INDOOR_WIND_M_S,
        net_radiation_mj_m2_day=net_radiation_mj, elevation_m=100.0,
    )
    assert result.method is EtMethod.PENMAN_MONTEITH_STANDARD
    return result.value_mm


class TestIndoorStep(unittest.TestCase):
    """
    Il passo in casa del vaso (docs/proposta_radiazione_indoor.md): a
    Penman-Monteith va la netta, e la luce si conta una volta sola.
    """

    def test_the_step_uses_the_net_radiation(self):
        global_at_pot = OUTDOOR_MJ * INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR
        stepped, by_hand, as_before = _indoor_pot(), _indoor_pot(), _indoor_pot()
        stepped.apply_balance_step_from_indoor(
            ROOM, 0.0, JUNE, outdoor_solar_radiation_mj_m2_day=OUTDOOR_MJ,
        )
        by_hand.apply_balance_step(
            et_0_mm=_room_et0((1.0 - INDOOR_ALBEDO) * global_at_pot),
            water_input_mm=0.0, current_date=JUNE,
        )
        as_before.apply_balance_step(
            et_0_mm=_room_et0(global_at_pot), water_input_mm=0.0, current_date=JUNE,
        )
        self.assertAlmostEqual(stepped.state_mm, by_hand.state_mm)
        # Con la globale passata come netta il vaso perdeva più acqua.
        self.assertGreater(stepped.state_mm, as_before.state_mm)

    def test_the_fixed_radiation_loses_its_albedo_too(self):
        stepped, by_hand = _indoor_pot(), _indoor_pot()
        stepped.apply_balance_step_from_indoor(ROOM, 0.0, JUNE)
        by_hand.apply_balance_step(
            et_0_mm=_room_et0((1.0 - INDOOR_ALBEDO) * INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY),
            water_input_mm=0.0, current_date=JUNE,
        )
        self.assertAlmostEqual(stepped.state_mm, by_hand.state_mm)

    def test_the_light_is_counted_once(self):
        # La luce del vaso sta nella radiazione della stanza: l'esposizione
        # al sole, che all'aperto riduce l'ET con Kp, qui non la tocca più.
        states = {}
        for exposure in SunExposure:
            pot = _indoor_pot(sun_exposure=exposure)
            pot.apply_balance_step_from_indoor(
                ROOM, 0.0, JUNE, outdoor_solar_radiation_mj_m2_day=OUTDOOR_MJ,
            )
            states[exposure] = pot.state_mm
        self.assertAlmostEqual(states[SunExposure.SHADE], states[SunExposure.FULL_SUN])
        self.assertAlmostEqual(states[SunExposure.PARTIAL_SHADE], states[SunExposure.FULL_SUN])
        # Kp resta quello di sempre: è il passo in casa che non lo conta due volte.
        self.assertAlmostEqual(_indoor_pot(sun_exposure=SunExposure.SHADE).kp, 0.45)
        # E con l'ET₀ di fuori l'esposizione continua a ridurre.
        shade, sun = _indoor_pot(sun_exposure=SunExposure.SHADE), _indoor_pot()
        for pot in (shade, sun):
            pot.apply_balance_step(et_0_mm=4.0, water_input_mm=0.0, current_date=JUNE)
        self.assertGreater(shade.state_mm, sun.state_mm)

    def test_the_light_at_the_pot_stays_the_global_one(self):
        # Il DLI si calcola dalla globale: l'albedo riguarda l'energia, non
        # i fotoni che arrivano alla pianta.
        pot = _indoor_pot()
        pot.apply_balance_step_from_indoor(
            ROOM, 0.0, JUNE, outdoor_solar_radiation_mj_m2_day=OUTDOOR_MJ,
        )
        self.assertAlmostEqual(
            pot.last_nutrient_step.dli_mol_m2_day,
            OUTDOOR_MJ * INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR * 0.45 * 4.48,
        )


if __name__ == "__main__":
    unittest.main()
