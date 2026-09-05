"""
Test per la pianta misurata dentro il Pot (H.1-c di The Pot).

Tre cose:
  1. Senza misure il vaso consuma esattamente come prima: i campi nuovi
     sono facoltativi e inerti.
  2. Una chioma più larga del vaso beve di più, una più piccola di meno,
     nel single Kc e nel dual-Kc; il tetto ferma la crescita.
  3. L'altezza misurata entra in Penman-Monteith fisico al posto di
     quella della specie, e le misure sopravvivono a JSON e SQLite.
"""

import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date

from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL, TOMATO
from fitosim.domain.weather import WeatherDay
from fitosim.io.persistence import GardenPersistence
from fitosim.io.serialization import _dict_to_pot, _pot_to_dict
from fitosim.science.canopy import COVER_CAP
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

OGGI = date(2026, 7, 15)

# Il dual-Kc vuole i Kcb sulla specie e REW/TEW sul substrato: il catalogo
# non li ha, e qui si aggiungono a un pomodoro e a un terriccio.
POMODORO_DUAL = replace(TOMATO, kcb_initial=0.15, kcb_mid=1.10, kcb_late=0.70)
TERRICCIO_DUAL = replace(UNIVERSAL_POTTING_SOIL, rew_mm=9.0, tew_mm=22.0)


def _vaso(**extra) -> Pot:
    base = dict(
        label="Basilico",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=4.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 5, 1),
        latitude_deg=45.5,
        elevation_m=150.0,
    )
    return Pot(**(base | extra))


class TestSenzaMisureNienteCambia(unittest.TestCase):

    def test_i_campi_nuovi_sono_none_e_la_copertura_non_si_calcola(self):
        vaso = _vaso()
        self.assertIsNone(vaso.plant_height_m)
        self.assertIsNone(vaso.canopy_width_m)
        self.assertIsNone(vaso.canopy_cover_fraction)
        self.assertEqual(vaso.effective_crop_height_m, BASIL.crop_height_m)
        self.assertEqual(vaso.cover_height_m, BASIL.crop_height_m)

    def test_l_et_e_quella_di_prima(self):
        # Kp = 1 (plastica, medio, pieno sole), Ks = 1 (a capacità di
        # campo), Kn = 1: ET_c = Kc × ET₀, come il FAO-56 base.
        vaso = _vaso()
        stadio = vaso.current_stage(OGGI)
        from fitosim.domain.species import kc_for_stage
        self.assertAlmostEqual(
            vaso.current_et_c(5.0, OGGI), kc_for_stage(BASIL, stadio) * 5.0, places=10,
        )


class TestLaChiomaCambiaIlConsumo(unittest.TestCase):

    def test_una_chioma_larga_come_il_vaso_e_la_copertura_piena(self):
        vaso = _vaso(canopy_width_m=0.18)
        self.assertAlmostEqual(vaso.canopy_cover_fraction, 1.0, places=10)
        self.assertAlmostEqual(
            vaso.current_et_c(5.0, OGGI), _vaso().current_et_c(5.0, OGGI), places=10,
        )

    def test_una_chioma_doppia_beve_di_piu_e_una_piccola_di_meno(self):
        base = _vaso().current_et_c(5.0, OGGI)
        larga = _vaso(canopy_width_m=0.36).current_et_c(5.0, OGGI)   # fc = 4 → tetto
        stretta = _vaso(canopy_width_m=0.09).current_et_c(5.0, OGGI)  # fc = 0.25
        self.assertAlmostEqual(larga, base * COVER_CAP, places=10)
        self.assertLess(stretta, base)
        self.assertGreater(stretta, 0.0)

    def test_nel_single_kc_una_chioma_minuscola_lascia_il_pavimento(self):
        # BASIL non ha i Kcb: cammino single Kc. Con fc ≈ 0 il Kc va al
        # pavimento del suolo nudo (0.20), non a zero.
        et_0 = 5.0
        minuscola = _vaso(canopy_width_m=0.001).current_et_c(et_0, OGGI)
        self.assertAlmostEqual(minuscola, 0.20 * et_0, delta=0.01)

    def test_nel_dual_kc_la_copertura_scala_la_traspirazione(self):
        # A superficie bagnata FAO-56 fa compensare a Ke ogni Kcb più
        # basso, fino a Kcmax: la chioma stretta non si vedrebbe. Con la
        # superficie asciutta (De = TEW, Kr = 0) resta la sola
        # traspirazione, ed è quella che la copertura scala.
        dual = dict(
            species=POMODORO_DUAL, substrate=TERRICCIO_DUAL, label="Pomodoro", de_mm=22.0,
        )
        base = _vaso(**dual)
        self.assertTrue(base.supports_dual_kc)
        largo = _vaso(**dual, canopy_width_m=0.36)
        stretto = _vaso(**dual, canopy_width_m=0.09)
        et_base, _ = base._current_et_c_dual_kc(5.0, OGGI)
        et_largo, _ = largo._current_et_c_dual_kc(5.0, OGGI)
        et_stretto, _ = stretto._current_et_c_dual_kc(5.0, OGGI)
        self.assertGreater(et_largo, et_base)
        self.assertLess(et_stretto, et_base)

    def test_l_altezza_della_chioma_entra_nell_esponente(self):
        # Stessa copertura parziale: una chioma alta traspira più di una bassa.
        bassa = _vaso(canopy_width_m=0.09, canopy_height_m=0.10, plant_height_m=0.15)
        alta = _vaso(canopy_width_m=0.09, canopy_height_m=1.00, plant_height_m=1.20)
        self.assertGreater(alta.current_et_c(5.0, OGGI), bassa.current_et_c(5.0, OGGI))
        self.assertEqual(alta.cover_height_m, 1.00)


class TestValidazione(unittest.TestCase):

    def test_le_misure_devono_essere_positive(self):
        with self.assertRaises(ValueError):
            _vaso(plant_height_m=0.0)
        with self.assertRaises(ValueError):
            _vaso(canopy_width_m=-0.1)

    def test_la_chioma_non_supera_la_pianta(self):
        with self.assertRaises(ValueError):
            _vaso(plant_height_m=0.3, canopy_height_m=0.4)
        _vaso(plant_height_m=0.4, canopy_height_m=0.4)  # uguali va bene


class TestAltezzaInPenmanMonteith(unittest.TestCase):

    def test_l_altezza_misurata_sostituisce_quella_della_specie(self):
        vaso = _vaso(plant_height_m=0.60)
        self.assertEqual(vaso.effective_crop_height_m, 0.60)
        self.assertNotEqual(vaso.effective_crop_height_m, BASIL.crop_height_m)

    def test_con_il_meteo_completo_l_altezza_cambia_il_bilancio(self):
        meteo = WeatherDay(
            date_=OGGI, t_min=18.0, t_max=30.0,
            humidity_relative=0.55, wind_speed_m_s=2.0,
            solar_radiation_mj_m2_day=22.0,
        )
        basso = _vaso(plant_height_m=0.15)
        alto = _vaso(plant_height_m=1.50)
        basso.apply_balance_step_from_weather(meteo, water_input_mm=0.0, current_date=OGGI)
        alto.apply_balance_step_from_weather(meteo, water_input_mm=0.0, current_date=OGGI)
        # Una pianta più alta ha meno resistenza aerodinamica: traspira di più.
        self.assertLess(alto.state_mm, basso.state_mm)


class TestSopravvivenzaDelleMisure(unittest.TestCase):

    def test_json_avanti_e_indietro(self):
        vaso = _vaso(plant_height_m=0.5, canopy_width_m=0.3, canopy_height_m=0.4)
        dati = _pot_to_dict(vaso)
        specie = {BASIL.common_name: BASIL}
        substrati = {UNIVERSAL_POTTING_SOIL.name: UNIVERSAL_POTTING_SOIL}
        ricostruito = _dict_to_pot(dati, specie, substrati)
        self.assertEqual(ricostruito.plant_height_m, 0.5)
        self.assertEqual(ricostruito.canopy_width_m, 0.3)
        self.assertEqual(ricostruito.canopy_height_m, 0.4)
        # E un JSON di prima, senza le chiavi, si rilegge lo stesso.
        for chiave in ("plant_height_m", "canopy_width_m", "canopy_height_m"):
            dati["static_fields"].pop(chiave)
        self.assertIsNone(_dict_to_pot(dati, specie, substrati).plant_height_m)

    def test_sqlite_avanti_e_indietro(self):
        vaso = _vaso(plant_height_m=0.5, canopy_width_m=0.3)
        giardino = Garden(name="Balcone")
        giardino.add_pot(vaso)
        with tempfile.TemporaryDirectory() as cartella:
            percorso = os.path.join(cartella, "prova.sqlite")
            with GardenPersistence(percorso) as store:
                store.register_species(BASIL)
                store.register_substrate(UNIVERSAL_POTTING_SOIL)
                store.save_garden(giardino)
            with GardenPersistence(percorso) as store:
                riletto = store.load_garden("Balcone")
        pianta = list(riletto)[0]
        self.assertEqual(pianta.plant_height_m, 0.5)
        self.assertEqual(pianta.canopy_width_m, 0.3)
        self.assertIsNone(pianta.canopy_height_m)


if __name__ == "__main__":
    unittest.main()
