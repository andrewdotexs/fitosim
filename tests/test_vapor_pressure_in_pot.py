"""
A9 (2026-10-21) nel passo del vaso: il `WeatherDay` porta gli estremi del
giorno fino al Penman-Monteith e alla radiazione netta, e le umidità
estreme, quando ci sono, cambiano il bilancio come FAO-56 eq. 17 vuole.
"""

import unittest
from datetime import date

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.domain.weather import WeatherDay
from fitosim.science.et0 import EtMethod
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

OGGI = date(2026, 7, 19)


def _vaso() -> Pot:
    return Pot(
        label="basilico",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0,
        pot_diameter_cm=20.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 6, 1),
        state_mm=-1.0,
        latitude_deg=45.47,
        elevation_m=150.0,
    )


class TestGliEstremiNelPassoDelVaso(unittest.TestCase):
    def test_le_umidita_estreme_cambiano_il_bilancio(self):
        # Stessa media (0.60), ma con gli estremi e_a segue l'eq. 17: il
        # deficit di vapore cambia, e con lui l'ET e lo stato del vaso.
        media = WeatherDay(
            date_=OGGI, t_min=18.0, t_max=30.0,
            humidity_relative=0.60, wind_speed_m_s=2.0, solar_radiation_mj_m2_day=22.0,
        )
        estremi = WeatherDay(
            date_=OGGI, t_min=18.0, t_max=30.0,
            humidity_relative=0.60, wind_speed_m_s=2.0, solar_radiation_mj_m2_day=22.0,
            humidity_min=0.30, humidity_max=0.95,
        )
        con_media, con_estremi = _vaso(), _vaso()
        r1 = con_media.apply_balance_step_from_weather(media, 0.0, OGGI)
        r2 = con_estremi.apply_balance_step_from_weather(estremi, 0.0, OGGI)
        self.assertIs(r1.et_method, EtMethod.PENMAN_MONTEITH_PHYSICAL)
        self.assertIs(r2.et_method, EtMethod.PENMAN_MONTEITH_PHYSICAL)
        self.assertNotAlmostEqual(con_media.state_mm, con_estremi.state_mm, places=3)

    def test_gli_estremi_di_temperatura_entrano_sempre(self):
        # A parità di media, un giorno con escursione larga ha e_s più alta
        # (eq. 12, e° convessa) e consuma di più di uno con escursione nulla.
        piatto = WeatherDay(
            date_=OGGI, t_min=24.0, t_max=24.0,
            humidity_relative=0.60, wind_speed_m_s=2.0, solar_radiation_mj_m2_day=22.0,
        )
        largo = WeatherDay(
            date_=OGGI, t_min=16.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=2.0, solar_radiation_mj_m2_day=22.0,
        )
        vaso_piatto, vaso_largo = _vaso(), _vaso()
        vaso_piatto.apply_balance_step_from_weather(piatto, 0.0, OGGI)
        vaso_largo.apply_balance_step_from_weather(largo, 0.0, OGGI)
        self.assertLess(vaso_largo.state_mm, vaso_piatto.state_mm)


if __name__ == "__main__":
    unittest.main()
