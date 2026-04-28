"""
Test del modulo domain/garden.py (sotto-tappa A tappa 4 fascia 2).

Strategia di test
-----------------

Quattro famiglie tematiche di test:

  1. **Costruzione e validazione**: validità del nome, default
     della location_description, retrocompat con costruzione
     minimale.
  2. **Gestione della collezione**: add, remove, get, has, label
     uniche, errori espliciti con messaggi diagnostici.
  3. **Protocolli Python**: iter, len, contains, ordine di
     inserimento preservato.
  4. **Orchestratore apply_step_all**: conversione pioggia mm →
     litri per vaso, retrocompat con singoli apply_step, gestione
     di giardini vuoti e di vasi con esposizione diversa.
"""

import unittest
from datetime import date

from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import Species
from fitosim.science.substrate import Substrate


# =======================================================================
#  Helper di costruzione
# =======================================================================

def _make_basil_species() -> Species:
    return Species(
        common_name="basilico",
        scientific_name="Ocimum basilicum",
        kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
        ec_optimal_min_mscm=1.0,
        ec_optimal_max_mscm=1.6,
        ph_optimal_min=6.0,
        ph_optimal_max=7.0,
    )


def _make_universal_substrate() -> Substrate:
    return Substrate(
        name="terriccio universale",
        theta_fc=0.40, theta_pwp=0.10,
        cec_meq_per_100g=50.0, ph_typical=6.8,
    )


def _make_pot(label: str, **overrides) -> Pot:
    defaults = dict(
        species=_make_basil_species(),
        substrate=_make_universal_substrate(),
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
    )
    defaults.update(overrides)
    return Pot(label=label, **defaults)


# =======================================================================
#  Famiglia 1: costruzione e validazione
# =======================================================================

class TestGardenConstruction(unittest.TestCase):
    """Validazione del costruttore e dei campi statici."""

    def test_minimal_construction(self):
        # Costruzione minimale: solo il nome.
        g = Garden(name="balcone")
        self.assertEqual(g.name, "balcone")
        self.assertEqual(g.location_description, "")
        self.assertEqual(len(g), 0)

    def test_full_construction(self):
        g = Garden(
            name="balcone-milano",
            location_description="Balcone esposto a sud",
        )
        self.assertEqual(g.name, "balcone-milano")
        self.assertEqual(g.location_description, "Balcone esposto a sud")

    def test_empty_name_rejected(self):
        # Nome vuoto: respinto.
        with self.assertRaises(ValueError):
            Garden(name="")

    def test_whitespace_only_name_rejected(self):
        # Nome solo spazi: respinto.
        with self.assertRaises(ValueError):
            Garden(name="   ")

    def test_pots_dict_isolated_between_instances(self):
        # CRUCIALE: il dict default non deve essere condiviso tra
        # istanze (classico bug del default mutabile).
        g1 = Garden(name="g1")
        g2 = Garden(name="g2")
        g1.add_pot(_make_pot("vaso-g1"))
        self.assertEqual(len(g1), 1)
        self.assertEqual(len(g2), 0)


# =======================================================================
#  Famiglia 2: gestione della collezione
# =======================================================================

class TestGardenCollection(unittest.TestCase):
    """Add, remove, get, has, validazione delle label uniche."""

    def setUp(self):
        self.garden = Garden(name="balcone")
        self.pot_basilico = _make_pot("basilico-balcone")
        self.pot_pomodoro = _make_pot("pomodoro-terrazza")

    def test_add_pot_increases_size(self):
        self.garden.add_pot(self.pot_basilico)
        self.assertEqual(len(self.garden), 1)
        self.garden.add_pot(self.pot_pomodoro)
        self.assertEqual(len(self.garden), 2)

    def test_add_pot_duplicate_label_rejected(self):
        # Due vasi con la stessa label: il secondo dev'essere respinto.
        self.garden.add_pot(self.pot_basilico)
        another_basilico = _make_pot("basilico-balcone", pot_volume_l=3.0)
        with self.assertRaises(ValueError) as ctx:
            self.garden.add_pot(another_basilico)
        self.assertIn("basilico-balcone", str(ctx.exception))

    def test_get_pot_returns_correct_pot(self):
        self.garden.add_pot(self.pot_basilico)
        self.garden.add_pot(self.pot_pomodoro)
        retrieved = self.garden.get_pot("basilico-balcone")
        # È lo stesso oggetto, non una copia.
        self.assertIs(retrieved, self.pot_basilico)

    def test_get_pot_missing_raises_keyerror(self):
        with self.assertRaises(KeyError) as ctx:
            self.garden.get_pot("inesistente")
        # Il messaggio deve elencare i vasi disponibili per aiutare il
        # giardiniere a capire l'errore.
        self.assertIn("inesistente", str(ctx.exception))

    def test_has_pot(self):
        self.assertFalse(self.garden.has_pot("basilico-balcone"))
        self.garden.add_pot(self.pot_basilico)
        self.assertTrue(self.garden.has_pot("basilico-balcone"))
        self.assertFalse(self.garden.has_pot("pomodoro-terrazza"))

    def test_remove_pot_returns_pot(self):
        self.garden.add_pot(self.pot_basilico)
        removed = self.garden.remove_pot("basilico-balcone")
        # È esattamente il vaso che era stato aggiunto, intatto.
        self.assertIs(removed, self.pot_basilico)
        self.assertEqual(len(self.garden), 0)

    def test_remove_pot_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.garden.remove_pot("inesistente")

    def test_pot_labels_returns_inserted_order(self):
        # PROPRIETÀ FONDAMENTALE: l'ordine di inserimento è preservato.
        self.garden.add_pot(_make_pot("primo"))
        self.garden.add_pot(_make_pot("secondo"))
        self.garden.add_pot(_make_pot("terzo"))
        self.assertEqual(
            self.garden.pot_labels, ["primo", "secondo", "terzo"]
        )

    def test_remove_then_add_with_same_label_works(self):
        # Dopo aver rimosso un vaso, un nuovo vaso con la stessa
        # label può essere aggiunto. Caso pratico: rinvasare la
        # stessa pianta in un vaso più grande.
        self.garden.add_pot(self.pot_basilico)
        self.garden.remove_pot("basilico-balcone")
        # Niente eccezione qui:
        new_pot = _make_pot("basilico-balcone", pot_volume_l=5.0)
        self.garden.add_pot(new_pot)
        self.assertEqual(len(self.garden), 1)
        self.assertEqual(self.garden.get_pot("basilico-balcone").pot_volume_l, 5.0)


# =======================================================================
#  Famiglia 3: protocolli Python (iter, len, contains)
# =======================================================================

class TestGardenProtocols(unittest.TestCase):
    """Iterazione, lunghezza, test di appartenenza."""

    def setUp(self):
        self.garden = Garden(name="balcone")
        self.pot1 = _make_pot("vaso-1")
        self.pot2 = _make_pot("vaso-2")
        self.pot3 = _make_pot("vaso-3")

    def test_iter_yields_pots_in_insertion_order(self):
        self.garden.add_pot(self.pot1)
        self.garden.add_pot(self.pot2)
        self.garden.add_pot(self.pot3)
        # for pot in garden produce i vasi nell'ordine di inserimento.
        labels = [pot.label for pot in self.garden]
        self.assertEqual(labels, ["vaso-1", "vaso-2", "vaso-3"])

    def test_iter_empty_garden(self):
        # Iterazione su un giardino vuoto: nessun elemento, niente errore.
        labels = [pot.label for pot in self.garden]
        self.assertEqual(labels, [])

    def test_len_increments_with_add(self):
        self.assertEqual(len(self.garden), 0)
        self.garden.add_pot(self.pot1)
        self.assertEqual(len(self.garden), 1)
        self.garden.add_pot(self.pot2)
        self.assertEqual(len(self.garden), 2)

    def test_len_decrements_with_remove(self):
        self.garden.add_pot(self.pot1)
        self.garden.add_pot(self.pot2)
        self.garden.remove_pot("vaso-1")
        self.assertEqual(len(self.garden), 1)

    def test_contains_via_in_operator(self):
        self.garden.add_pot(self.pot1)
        # Pattern naturale: if label in garden
        self.assertIn("vaso-1", self.garden)
        self.assertNotIn("vaso-2", self.garden)


# =======================================================================
#  Famiglia 4: orchestratore apply_step_all
# =======================================================================

class TestGardenApplyStepAll(unittest.TestCase):
    """
    Validazione dell'orchestratore che evolve tutti i vasi del giardino
    in un singolo passo giornaliero.
    """

    def setUp(self):
        self.garden = Garden(name="balcone")
        # Un vaso esposto, uno sotto balcone parzialmente coperto.
        self.pot_open = _make_pot("vaso-aperto", rainfall_exposure=1.0)
        self.pot_sheltered = _make_pot(
            "vaso-coperto", rainfall_exposure=0.5,
        )
        self.garden.add_pot(self.pot_open)
        self.garden.add_pot(self.pot_sheltered)

    def test_returns_dict_with_all_pot_labels(self):
        # Il risultato è un dict con una chiave per ogni vaso.
        results = self.garden.apply_step_all(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
        )
        self.assertEqual(set(results.keys()),
                         {"vaso-aperto", "vaso-coperto"})

    def test_results_preserve_insertion_order(self):
        # Le chiavi nel dict result sono nell'ordine di inserimento.
        results = self.garden.apply_step_all(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
        )
        self.assertEqual(
            list(results.keys()), ["vaso-aperto", "vaso-coperto"]
        )

    def test_no_rainfall_no_rainfall_result(self):
        # Senza pioggia, nessun rainfall_result.
        results = self.garden.apply_step_all(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
            rainfall_mm=0.0,
        )
        for label, result in results.items():
            self.assertIsNone(result.rainfall_result)

    def test_with_rainfall_populates_rainfall_result(self):
        # Con pioggia, ogni vaso ha rainfall_result valorizzato.
        results = self.garden.apply_step_all(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
            rainfall_mm=10.0,
        )
        for result in results.values():
            self.assertIsNotNone(result.rainfall_result)

    def test_rainfall_volume_proportional_to_area(self):
        # I due vasi del setUp hanno la stessa area (entrambi diam 18 cm),
        # quindi ricevono lo stesso volume nominale di pioggia. Ma il
        # vaso coperto ha rainfall_exposure 0.5 e quindi internamente
        # ne riceve solo metà.
        results = self.garden.apply_step_all(
            et_0_mm=0.0, current_date=date(2026, 5, 15),
            rainfall_mm=10.0,
        )
        # Volume nominale identico (stessa area):
        v_open_nominal = results["vaso-aperto"].rainfall_result.volume_input_l
        v_sheltered_nominal = (
            results["vaso-coperto"].rainfall_result.volume_input_l
            + results["vaso-coperto"].rainfall_result.volume_intercepted_l
        )
        self.assertAlmostEqual(v_open_nominal, v_sheltered_nominal, places=9)
        # Volume effettivo entrato nel vaso coperto è la metà:
        self.assertAlmostEqual(
            results["vaso-coperto"].rainfall_result.volume_input_l,
            v_open_nominal / 2.0,
            places=9,
        )

    def test_rainfall_volume_correct_for_pot_geometry(self):
        # Verifica numerica: 10 mm × area cilindrica diam 18 cm
        # Area = π × (0.09)² ≈ 0.0254 m²
        # Volume = 10 mm × 0.0254 m² = 0.254 L
        results = self.garden.apply_step_all(
            et_0_mm=0.0, current_date=date(2026, 5, 15),
            rainfall_mm=10.0,
        )
        rainfall_result = results["vaso-aperto"].rainfall_result
        expected_volume_l = 10.0 * self.pot_open.surface_area_m2
        self.assertAlmostEqual(
            rainfall_result.volume_input_l, expected_volume_l, places=6,
        )

    def test_apply_step_all_equivalent_to_individual_apply_step(self):
        # PROPRIETÀ FONDAMENTALE: il Garden è un orchestratore puro,
        # quindi apply_step_all su un giardino con un vaso solo deve
        # produrre lo stesso risultato di apply_step chiamato
        # direttamente sul vaso.
        garden = Garden(name="single")
        pot_a = _make_pot("a", rainfall_exposure=1.0, state_mm=25.0)
        pot_b = _make_pot("b", rainfall_exposure=1.0, state_mm=25.0)
        garden.add_pot(pot_a)

        # Via Garden:
        garden.apply_step_all(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
            rainfall_mm=5.0,
        )
        # Direttamente sul Pot equivalente:
        rainfall_volume_l = 5.0 * pot_b.surface_area_m2
        pot_b.apply_step(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
            rainfall_volume_l=rainfall_volume_l,
        )
        # Gli stati finali devono coincidere.
        self.assertAlmostEqual(pot_a.state_mm, pot_b.state_mm, places=6)
        self.assertAlmostEqual(
            pot_a.salt_mass_meq, pot_b.salt_mass_meq, places=6,
        )

    def test_empty_garden_returns_empty_dict(self):
        empty = Garden(name="vuoto")
        results = empty.apply_step_all(
            et_0_mm=4.5, current_date=date(2026, 5, 15),
        )
        self.assertEqual(results, {})

    def test_negative_et_rejected(self):
        with self.assertRaises(ValueError):
            self.garden.apply_step_all(
                et_0_mm=-1.0, current_date=date(2026, 5, 15),
            )

    def test_negative_rainfall_rejected(self):
        with self.assertRaises(ValueError):
            self.garden.apply_step_all(
                et_0_mm=4.5, current_date=date(2026, 5, 15),
                rainfall_mm=-1.0,
            )

    def test_pots_evolve_independently(self):
        # Due vasi nello stesso giardino con stati iniziali diversi
        # mantengono la loro evoluzione indipendente.
        garden = Garden(name="multi")
        wet_pot = _make_pot("umido", state_mm=35.0)
        dry_pot = _make_pot("secco", state_mm=10.0)
        garden.add_pot(wet_pot)
        garden.add_pot(dry_pot)

        garden.apply_step_all(
            et_0_mm=4.0, current_date=date(2026, 5, 15),
            rainfall_mm=0.0,
        )
        # Il vaso umido resta più bagnato del vaso secco
        # (entrambi hanno consumato circa lo stesso quantitativo di
        # acqua per ET, ma partono da stati molto diversi).
        self.assertGreater(wet_pot.state_mm, dry_pot.state_mm)


if __name__ == "__main__":
    unittest.main()
