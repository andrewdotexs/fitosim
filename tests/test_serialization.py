"""
Test del modulo io/serialization.py (sotto-tappa B fase 2 tappa 4).

Strategia di test
-----------------

Tre famiglie tematiche di test:

  1. **Round-trip**: serializzazione e deserializzazione di Garden
     diversi, dal più semplice (un vaso, substrato puro, specie
     minimale) al più complesso (più vasi con esposizioni e
     posizionamenti diversi, sottovaso, parametri dual-Kc).

  2. **Catalogo**: il JSON contiene solo specie e substrati
     effettivamente usati, ordine deterministico delle entrate del
     catalogo, autocontenuto (non dipende da risorse esterne).

  3. **Errori**: gestione di JSON malformato, format_version
     superiore, riferimenti mancanti nel catalogo, struttura del
     JSON incompleta.
"""

import json
import unittest
from datetime import date

from fitosim.domain.garden import Garden
from fitosim.domain.pot import (
    Location,
    Pot,
    PotColor,
    PotMaterial,
    PotShape,
    SunExposure,
)
from fitosim.domain.species import Species
from fitosim.io.serialization import (
    FORMAT_VERSION,
    SerializationError,
    export_garden_json,
    import_garden_json,
)
from fitosim.science.substrate import Substrate


# =======================================================================
#  Helper di costruzione
# =======================================================================

def _make_basil() -> Species:
    return Species(
        common_name="basilico",
        scientific_name="Ocimum basilicum",
        kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
        ec_optimal_min_mscm=1.0, ec_optimal_max_mscm=1.6,
        ph_optimal_min=6.0, ph_optimal_max=7.0,
    )


def _make_tomato() -> Species:
    return Species(
        common_name="pomodoro",
        scientific_name="Solanum lycopersicum",
        kc_initial=0.60, kc_mid=1.15, kc_late=0.80,
        initial_stage_days=35, mid_stage_days=70,
    )


def _make_universal_substrate() -> Substrate:
    return Substrate(
        name="terriccio universale",
        theta_fc=0.40, theta_pwp=0.10,
        cec_meq_per_100g=50.0, ph_typical=6.8,
    )


def _make_acidofile_substrate() -> Substrate:
    return Substrate(
        name="terriccio acidofile",
        theta_fc=0.45, theta_pwp=0.08,
        cec_meq_per_100g=140.0, ph_typical=4.8,
    )


def _make_basic_pot(label: str = "basilico-1", **overrides) -> Pot:
    defaults = dict(
        species=_make_basil(),
        substrate=_make_universal_substrate(),
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        state_mm=25.0,
        salt_mass_meq=10.0,
    )
    defaults.update(overrides)
    return Pot(label=label, **defaults)


# =======================================================================
#  Famiglia 1: round-trip di Garden
# =======================================================================

class TestRoundTripBasic(unittest.TestCase):
    """Round-trip di Garden semplici: lo stato è preservato al byte."""

    def test_empty_garden_round_trip(self):
        # Garden senza vasi: solo metadati.
        g = Garden(
            name="balcone-vuoto",
            location_description="In fase di pianificazione",
        )
        json_str = export_garden_json(g)
        g2 = import_garden_json(json_str)
        self.assertEqual(g2.name, "balcone-vuoto")
        self.assertEqual(g2.location_description, "In fase di pianificazione")
        self.assertEqual(len(g2), 0)

    def test_single_pot_round_trip(self):
        # Vaso singolo con tutti i parametri base.
        g = Garden(name="balcone")
        g.add_pot(_make_basic_pot())
        g2 = import_garden_json(export_garden_json(g))

        pot = g2.get_pot("basilico-1")
        self.assertEqual(pot.label, "basilico-1")
        self.assertEqual(pot.pot_volume_l, 2.0)
        self.assertEqual(pot.pot_diameter_cm, 18.0)
        self.assertEqual(pot.location, Location.OUTDOOR)
        self.assertEqual(pot.planting_date, date(2026, 4, 1))
        # Stato mutabile preservato.
        self.assertEqual(pot.state_mm, 25.0)
        self.assertEqual(pot.salt_mass_meq, 10.0)
        # Specie
        self.assertEqual(pot.species.common_name, "basilico")
        self.assertEqual(pot.species.scientific_name, "Ocimum basilicum")
        # Substrato
        self.assertEqual(pot.substrate.name, "terriccio universale")
        self.assertEqual(pot.substrate.theta_fc, 0.40)
        self.assertEqual(pot.substrate.cec_meq_per_100g, 50.0)

    def test_multiple_pots_preserve_insertion_order(self):
        # L'ordine di inserimento dei vasi è preservato dal round-trip.
        g = Garden(name="balcone")
        for label in ["primo", "secondo", "terzo"]:
            g.add_pot(_make_basic_pot(label=label))
        g2 = import_garden_json(export_garden_json(g))
        self.assertEqual(g2.pot_labels, ["primo", "secondo", "terzo"])

    def test_pot_with_full_geometry_round_trip(self):
        # Vaso con tutti i parametri di geometria (forma rettangolare,
        # materiale specifico, colore, esposizione solare).
        pot = _make_basic_pot(
            label="rettangolare",
            pot_shape=PotShape.RECTANGULAR,
            pot_width_cm=15.0,
            pot_material=PotMaterial.TERRACOTTA,
            pot_color=PotColor.DARK,
            sun_exposure=SunExposure.PARTIAL_SHADE,
            active_depth_fraction=0.85,
            rainfall_exposure=0.7,
            notes="Vaso speciale con drenaggio extra",
        )
        g = Garden(name="balcone")
        g.add_pot(pot)
        g2 = import_garden_json(export_garden_json(g))
        pot2 = g2.get_pot("rettangolare")
        self.assertEqual(pot2.pot_shape, PotShape.RECTANGULAR)
        self.assertEqual(pot2.pot_width_cm, 15.0)
        self.assertEqual(pot2.pot_material, PotMaterial.TERRACOTTA)
        self.assertEqual(pot2.pot_color, PotColor.DARK)
        self.assertEqual(pot2.sun_exposure, SunExposure.PARTIAL_SHADE)
        self.assertEqual(pot2.active_depth_fraction, 0.85)
        self.assertEqual(pot2.rainfall_exposure, 0.7)
        self.assertEqual(pot2.notes, "Vaso speciale con drenaggio extra")

    def test_pot_with_saucer_round_trip(self):
        # Vaso con sottovaso configurato.
        pot = _make_basic_pot(
            saucer_capacity_mm=8.0,
            saucer_state_mm=2.0,
        )
        g = Garden(name="balcone")
        g.add_pot(pot)
        g2 = import_garden_json(export_garden_json(g))
        pot2 = g2.get_pot("basilico-1")
        self.assertEqual(pot2.saucer_capacity_mm, 8.0)
        self.assertEqual(pot2.saucer_state_mm, 2.0)

    def test_pot_chemistry_state_round_trip(self):
        # CRUCIALE: lo stato chimico (salt_mass_meq, ph_substrate) è
        # preservato esattamente, e l'EC come property derivata
        # produce lo stesso valore.
        pot = _make_basic_pot(
            state_mm=30.0,
            salt_mass_meq=15.5,
            ph_substrate=6.4,
        )
        g = Garden(name="balcone")
        g.add_pot(pot)
        original_ec = pot.ec_substrate_mscm

        g2 = import_garden_json(export_garden_json(g))
        pot2 = g2.get_pot("basilico-1")
        self.assertEqual(pot2.salt_mass_meq, 15.5)
        self.assertEqual(pot2.ph_substrate, 6.4)
        self.assertEqual(pot2.state_mm, 30.0)
        # L'EC come property derivata produce lo stesso valore.
        self.assertAlmostEqual(pot2.ec_substrate_mscm, original_ec, places=9)

    def test_pots_with_different_species_and_substrates(self):
        # Garden con vasi che usano specie e substrati diversi.
        g = Garden(name="balcone-misto")
        g.add_pot(_make_basic_pot(
            label="basilico",
            species=_make_basil(),
            substrate=_make_universal_substrate(),
        ))
        g.add_pot(_make_basic_pot(
            label="azalea",
            species=_make_tomato(),  # uso pomodoro come secondo esempio
            substrate=_make_acidofile_substrate(),
        ))

        g2 = import_garden_json(export_garden_json(g))
        # Entrambi i vasi presenti col loro catalog corretto
        self.assertEqual(
            g2.get_pot("basilico").species.common_name, "basilico",
        )
        self.assertEqual(
            g2.get_pot("azalea").species.common_name, "pomodoro",
        )
        self.assertEqual(
            g2.get_pot("basilico").substrate.name, "terriccio universale",
        )
        self.assertEqual(
            g2.get_pot("azalea").substrate.name, "terriccio acidofile",
        )

    def test_substrate_with_dual_kc_parameters(self):
        # Substrato con parametri dual-Kc valorizzati (REW, TEW).
        sub_with_dual = Substrate(
            name="terriccio dual-kc",
            theta_fc=0.40, theta_pwp=0.10,
            rew_mm=8.0, tew_mm=18.0,
            cec_meq_per_100g=50.0, ph_typical=6.8,
        )
        pot = _make_basic_pot(substrate=sub_with_dual)
        g = Garden(name="balcone")
        g.add_pot(pot)

        g2 = import_garden_json(export_garden_json(g))
        substrate2 = g2.get_pot("basilico-1").substrate
        self.assertEqual(substrate2.rew_mm, 8.0)
        self.assertEqual(substrate2.tew_mm, 18.0)

    def test_channel_mapping_round_trip(self):
        # La mappa label → channel_id è preservata dal round-trip JSON.
        g = Garden(name="balcone")
        g.add_pot(_make_basic_pot("b1"))
        g.add_pot(_make_basic_pot("b2"))
        g.add_pot(_make_basic_pot("b3"))
        # Mapping parziale (giardino misto).
        g.set_channel_id("b1", "wh51_ch1")
        g.set_channel_id("b3", "ato_001")

        g2 = import_garden_json(export_garden_json(g))
        self.assertEqual(g2.get_channel_id("b1"), "wh51_ch1")
        self.assertIsNone(g2.get_channel_id("b2"))
        self.assertEqual(g2.get_channel_id("b3"), "ato_001")
        self.assertEqual(
            g2.channel_mapping, {"b1": "wh51_ch1", "b3": "ato_001"},
        )

    def test_no_channel_mapping_round_trip(self):
        # Garden senza mapping: il JSON non deve creare problemi e
        # tutti i vasi ricaricati sono "non mappati".
        g = Garden(name="balcone")
        g.add_pot(_make_basic_pot("b1"))
        g.add_pot(_make_basic_pot("b2"))

        g2 = import_garden_json(export_garden_json(g))
        self.assertIsNone(g2.get_channel_id("b1"))
        self.assertIsNone(g2.get_channel_id("b2"))
        self.assertEqual(g2.channel_mapping, {})


# =======================================================================
#  Famiglia 2: catalogo
# =======================================================================

class TestCatalogStructure(unittest.TestCase):
    """Il catalog del JSON è autocontenuto e minimale."""

    def test_catalog_contains_only_used_species_and_substrates(self):
        # Garden con un vaso solo: il catalog contiene una specie e
        # un substrato.
        g = Garden(name="balcone")
        g.add_pot(_make_basic_pot())

        json_str = export_garden_json(g)
        data = json.loads(json_str)

        self.assertEqual(len(data["catalog"]["species"]), 1)
        self.assertEqual(len(data["catalog"]["substrates"]), 1)
        self.assertEqual(
            data["catalog"]["species"][0]["common_name"], "basilico",
        )
        self.assertEqual(
            data["catalog"]["substrates"][0]["name"], "terriccio universale",
        )

    def test_catalog_deduplicates_repeated_species(self):
        # Tre vasi che usano la stessa specie: nel catalog appare
        # una volta sola.
        g = Garden(name="balcone")
        for label in ["v1", "v2", "v3"]:
            g.add_pot(_make_basic_pot(label=label))

        data = json.loads(export_garden_json(g))
        self.assertEqual(len(data["catalog"]["species"]), 1)
        self.assertEqual(len(data["catalog"]["substrates"]), 1)

    def test_catalog_in_deterministic_order(self):
        # Le entrate del catalog sono ordinate alfabeticamente per
        # nome, in modo che il JSON sia deterministico.
        g = Garden(name="balcone")
        # Aggiungo prima un pomodoro e poi un basilico.
        g.add_pot(_make_basic_pot(
            label="pomodoro-1", species=_make_tomato(),
        ))
        g.add_pot(_make_basic_pot(
            label="basilico-1", species=_make_basil(),
        ))

        data = json.loads(export_garden_json(g))
        names = [s["common_name"] for s in data["catalog"]["species"]]
        # Alfabetico: basilico prima di pomodoro
        self.assertEqual(names, ["basilico", "pomodoro"])

    def test_format_version_present(self):
        # Il JSON contiene sempre format_version.
        g = Garden(name="balcone")
        data = json.loads(export_garden_json(g))
        self.assertEqual(data["format_version"], FORMAT_VERSION)

    def test_json_compact_mode(self):
        # Quando indent=None, il JSON è compatto (utile per ridurre
        # la dimensione di backup).
        g = Garden(name="balcone")
        g.add_pot(_make_basic_pot())

        compact = export_garden_json(g, indent=None)
        readable = export_garden_json(g, indent=2)
        self.assertLess(len(compact), len(readable))
        # Entrambi devono essere parseable e produrre lo stesso Garden.
        g2_compact = import_garden_json(compact)
        g2_readable = import_garden_json(readable)
        self.assertEqual(
            g2_compact.get_pot("basilico-1").state_mm,
            g2_readable.get_pot("basilico-1").state_mm,
        )


# =======================================================================
#  Famiglia 3: gestione degli errori
# =======================================================================

class TestErrorHandling(unittest.TestCase):
    """Errori espliciti per JSON malformato e incoerente."""

    def test_malformed_json_raises_serialization_error(self):
        with self.assertRaises(SerializationError):
            import_garden_json("{not valid json")

    def test_non_object_top_level_rejected(self):
        # Il JSON top-level deve essere un oggetto, non una lista o
        # scalare.
        with self.assertRaises(SerializationError):
            import_garden_json("[]")
        with self.assertRaises(SerializationError):
            import_garden_json('"just a string"')

    def test_missing_format_version_rejected(self):
        # JSON senza format_version: errore.
        bad_json = json.dumps({"garden": {"name": "x"}})
        with self.assertRaises(SerializationError) as ctx:
            import_garden_json(bad_json)
        self.assertIn("format_version", str(ctx.exception))

    def test_future_format_version_rejected(self):
        # format_version > FORMAT_VERSION: errore esplicito.
        future_json = json.dumps({
            "format_version": FORMAT_VERSION + 1,
            "garden": {"name": "x"},
            "catalog": {"species": [], "base_materials": [], "substrates": []},
            "pots": [],
        })
        with self.assertRaises(SerializationError) as ctx:
            import_garden_json(future_json)
        self.assertIn(str(FORMAT_VERSION + 1), str(ctx.exception))

    def test_missing_garden_section_rejected(self):
        bad_json = json.dumps({
            "format_version": FORMAT_VERSION,
            "catalog": {"species": [], "base_materials": [], "substrates": []},
            "pots": [],
        })
        with self.assertRaises(SerializationError) as ctx:
            import_garden_json(bad_json)
        self.assertIn("garden", str(ctx.exception))

    def test_missing_catalog_section_rejected(self):
        bad_json = json.dumps({
            "format_version": FORMAT_VERSION,
            "garden": {"name": "x"},
            "pots": [],
        })
        with self.assertRaises(SerializationError) as ctx:
            import_garden_json(bad_json)
        self.assertIn("catalog", str(ctx.exception))

    def test_pot_referencing_unknown_species_rejected(self):
        # Vaso che referenzia una specie non presente nel catalog.
        bad_json = json.dumps({
            "format_version": FORMAT_VERSION,
            "garden": {"name": "x", "location_description": ""},
            "catalog": {
                "species": [],  # vuoto!
                "base_materials": [],
                "substrates": [{
                    "name": "sub", "theta_fc": 0.4, "theta_pwp": 0.1,
                    "description": "", "rew_mm": None, "tew_mm": None,
                    "cec_meq_per_100g": None, "ph_typical": None,
                    "is_mixture": False,
                }],
            },
            "pots": [{
                "label": "vaso",
                "species_name": "specie-fantasma",
                "substrate_name": "sub",
                "static_fields": {
                    "pot_volume_l": 2.0, "pot_diameter_cm": 18.0,
                    "pot_shape": "circular", "pot_width_cm": None,
                    "pot_material": "plastic", "pot_color": "medium",
                    "location": "outdoor", "sun_exposure": "full_sun",
                    "active_depth_fraction": 1.0, "rainfall_exposure": 1.0,
                    "saucer_capacity_mm": None,
                    "saucer_capillary_rate": None,
                    "saucer_evap_coef": None,
                    "planting_date": "2026-04-01", "notes": "",
                },
                "state_fields": {
                    "state_mm": 25.0, "salt_mass_meq": 0.0,
                    "ph_substrate": 7.0, "saucer_state_mm": 0.0,
                    "de_mm": 0.0,
                },
            }],
        })
        with self.assertRaises(SerializationError) as ctx:
            import_garden_json(bad_json)
        self.assertIn("specie-fantasma", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
