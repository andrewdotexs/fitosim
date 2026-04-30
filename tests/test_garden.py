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
from datetime import date, datetime, timedelta, timezone
from typing import Dict

from fitosim.domain.alerts import AlertCategory, AlertSeverity
from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot
from fitosim.domain.scheduling import ScheduledEvent, WeatherDayForecast
from fitosim.domain.species import Species
from fitosim.io.sensors import (
    SensorDataQualityError,
    SensorPermanentError,
    SensorTemporaryError,
    SoilReading,
)
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


# =======================================================================
#  Famiglia 5: gestione della mappa channel_id
# =======================================================================

class TestGardenChannelMapping(unittest.TestCase):
    """Mappa label → channel_id del gateway hardware."""

    def setUp(self):
        self.garden = Garden(name="balcone")
        self.garden.add_pot(_make_pot("basilico"))
        self.garden.add_pot(_make_pot("pomodoro"))

    def test_set_and_get_channel_id(self):
        self.garden.set_channel_id("basilico", "wh51_ch1")
        self.assertEqual(
            self.garden.get_channel_id("basilico"), "wh51_ch1",
        )

    def test_get_channel_id_returns_none_if_unmapped(self):
        # Un vaso senza mapping ritorna None senza errore.
        self.assertIsNone(self.garden.get_channel_id("basilico"))

    def test_get_channel_id_returns_none_for_unknown_label(self):
        # Anche per label che non sono mai esistite nel garden:
        # restituisce None (non solleva errore). È coerente con
        # l'uso "test non eccezionale" della funzione.
        self.assertIsNone(self.garden.get_channel_id("inesistente"))

    def test_set_channel_id_rejects_unknown_label(self):
        # Mappare una label che non esiste è quasi sempre un errore
        # di configurazione. Solleviamo subito.
        with self.assertRaises(KeyError) as ctx:
            self.garden.set_channel_id("inesistente", "wh51_ch9")
        self.assertIn("inesistente", str(ctx.exception))

    def test_has_channel_id(self):
        self.assertFalse(self.garden.has_channel_id("basilico"))
        self.garden.set_channel_id("basilico", "wh51_ch1")
        self.assertTrue(self.garden.has_channel_id("basilico"))

    def test_remove_channel_id(self):
        self.garden.set_channel_id("basilico", "wh51_ch1")
        self.garden.remove_channel_id("basilico")
        self.assertFalse(self.garden.has_channel_id("basilico"))
        # Idempotente: rimuovere da non mappato è no-op.
        self.garden.remove_channel_id("basilico")  # niente errore

    def test_channel_mapping_returns_copy_not_reference(self):
        # PROPRIETÀ FONDAMENTALE: channel_mapping ritorna una COPIA.
        # Modificare la copia NON deve modificare lo stato interno.
        self.garden.set_channel_id("basilico", "wh51_ch1")
        copy = self.garden.channel_mapping
        copy["pomodoro"] = "wh51_ch99"  # modifica la copia
        # Lo stato interno del garden NON è cambiato.
        self.assertFalse(self.garden.has_channel_id("pomodoro"))

    def test_channel_mapping_preserves_pots_with_no_mapping(self):
        # Mapping di un solo vaso: l'altro è correttamente "non mappato".
        self.garden.set_channel_id("basilico", "wh51_ch1")
        mapping = self.garden.channel_mapping
        self.assertIn("basilico", mapping)
        self.assertNotIn("pomodoro", mapping)


# =======================================================================
#  Famiglia 6: update_all_from_sensors
# =======================================================================

class _FakeSoilSensor:
    """
    SoilSensor fake per i test, configurabile per ritornare letture
    arbitrarie o sollevare eccezioni specifiche per canali specifici.
    """

    def __init__(
        self,
        readings: Dict[str, SoilReading] = None,
        errors: Dict[str, Exception] = None,
    ):
        self._readings = readings or {}
        self._errors = errors or {}
        self.calls = []  # registra le chiamate per test diagnostici

    def current_state(self, channel_id: str) -> SoilReading:
        self.calls.append(channel_id)
        if channel_id in self._errors:
            raise self._errors[channel_id]
        if channel_id in self._readings:
            return self._readings[channel_id]
        # Default: lettura "neutra" basata sul nome del canale
        return SoilReading(
            timestamp=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
            theta_volumetric=0.30,
        )


class TestGardenUpdateFromSensors(unittest.TestCase):
    """
    Validazione dell'orchestratore di aggiornamento dai sensori.
    """

    def setUp(self):
        self.garden = Garden(name="balcone")
        self.garden.add_pot(_make_pot("basilico", state_mm=20.0))
        self.garden.add_pot(_make_pot("pomodoro", state_mm=15.0))
        self.garden.add_pot(_make_pot("solo_previsione", state_mm=18.0))
        # Mappiamo solo i primi due. Il terzo resta "solo previsione".
        self.garden.set_channel_id("basilico", "ch1")
        self.garden.set_channel_id("pomodoro", "ch2")

    def test_updates_only_mapped_pots(self):
        # I vasi senza mapping sono saltati: il dict di ritorno
        # contiene solo i due vasi mappati.
        sensor = _FakeSoilSensor(readings={
            "ch1": SoilReading(
                timestamp=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
                theta_volumetric=0.35,
            ),
            "ch2": SoilReading(
                timestamp=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
                theta_volumetric=0.25,
            ),
        })
        results = self.garden.update_all_from_sensors(sensor)
        self.assertEqual(set(results.keys()), {"basilico", "pomodoro"})
        self.assertNotIn("solo_previsione", results)

    def test_unmapped_pots_continue_in_prediction(self):
        # Il vaso "solo_previsione" mantiene il suo state_mm originale
        # perché non viene toccato dall'aggiornamento.
        sensor = _FakeSoilSensor()
        before = self.garden.get_pot("solo_previsione").state_mm
        self.garden.update_all_from_sensors(sensor)
        after = self.garden.get_pot("solo_previsione").state_mm
        self.assertEqual(before, after)

    def test_sensor_called_with_correct_channel_ids(self):
        # Il sensore viene chiamato con i channel_id corretti.
        sensor = _FakeSoilSensor()
        self.garden.update_all_from_sensors(sensor)
        self.assertEqual(set(sensor.calls), {"ch1", "ch2"})

    def test_temporary_error_skips_pot_continues_others(self):
        # Errore transitorio sul ch1: il vaso basilico non viene
        # aggiornato ma l'orchestratore continua col pomodoro.
        sensor = _FakeSoilSensor(
            readings={
                "ch2": SoilReading(
                    timestamp=datetime(2026, 5, 15, 12, 0,
                                       tzinfo=timezone.utc),
                    theta_volumetric=0.25,
                ),
            },
            errors={"ch1": SensorTemporaryError("batteria scarica")},
        )
        results = self.garden.update_all_from_sensors(sensor)
        # Per basilico, il risultato è l'eccezione preservata.
        self.assertIsInstance(results["basilico"], SensorTemporaryError)
        # Per pomodoro, il risultato è regolare.
        self.assertNotIsInstance(results["pomodoro"], Exception)

    def test_permanent_error_propagates(self):
        # Errore permanente: propaga subito, niente skip.
        sensor = _FakeSoilSensor(
            errors={"ch1": SensorPermanentError("canale inesistente")},
        )
        with self.assertRaises(SensorPermanentError):
            self.garden.update_all_from_sensors(sensor)

    def test_data_quality_error_propagates(self):
        # SensorDataQualityError: propaga, indica letture impossibili
        # che contaminerebbero il modello se silenziate.
        sensor = _FakeSoilSensor(
            errors={"ch1": SensorDataQualityError("theta < 0")},
        )
        with self.assertRaises(SensorDataQualityError):
            self.garden.update_all_from_sensors(sensor)

    def test_empty_garden_returns_empty_dict(self):
        # Garden senza vasi mappati: dict vuoto, nessuna chiamata
        # al sensore.
        empty = Garden(name="vuoto")
        sensor = _FakeSoilSensor()
        results = empty.update_all_from_sensors(sensor)
        self.assertEqual(results, {})
        self.assertEqual(sensor.calls, [])

    def test_orphan_mapping_ignored_silently(self):
        # Caso patologico: un vaso viene rimosso dal garden senza
        # rimuovere prima il suo mapping. La mappatura "orfana" non
        # blocca l'orchestratore — è semplicemente ignorata.
        # Per simularlo, accediamo direttamente al dict interno.
        self.garden._channel_mapping["fantasma"] = "ch99"
        sensor = _FakeSoilSensor()
        results = self.garden.update_all_from_sensors(sensor)
        # La mappatura orfana non causa errori e non appare nei risultati.
        self.assertNotIn("fantasma", results)
        # Le altre mappature funzionano normalmente.
        self.assertIn("basilico", results)


# =======================================================================
#  Famiglia 7: gestione degli eventi pianificati
# =======================================================================

class TestGardenScheduledEvents(unittest.TestCase):
    """Pianificazione di eventi futuri (fertirrigazioni, trattamenti)."""

    def setUp(self):
        self.garden = Garden(name="balcone")
        self.garden.add_pot(_make_pot("basilico"))
        self.garden.add_pot(_make_pot("pomodoro"))

    def test_add_and_query_scheduled_event(self):
        ev = ScheduledEvent(
            event_id="fert-001", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
            payload={"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2},
        )
        self.garden.add_scheduled_event(ev)
        retrieved = self.garden.get_scheduled_event("basilico", "fert-001")
        self.assertEqual(retrieved, ev)
        self.assertTrue(
            self.garden.has_scheduled_event("basilico", "fert-001"),
        )

    def test_add_event_for_unknown_pot_rejected(self):
        # Eventi orfani (per vasi inesistenti): rifiutati subito.
        ev = ScheduledEvent(
            event_id="fert-x", pot_label="vaso-fantasma",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
            payload={},
        )
        with self.assertRaises(ValueError) as ctx:
            self.garden.add_scheduled_event(ev)
        self.assertIn("vaso-fantasma", str(ctx.exception))

    def test_add_duplicate_event_rejected(self):
        # Stesso (pot_label, event_id) due volte: rifiutato.
        ev1 = ScheduledEvent(
            event_id="fert-001", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
            payload={},
        )
        ev2 = ScheduledEvent(
            event_id="fert-001", pot_label="basilico",
            event_type="leaching",  # diverso ma stesso event_id
            scheduled_date=date(2026, 5, 20),
            payload={},
        )
        self.garden.add_scheduled_event(ev1)
        with self.assertRaises(ValueError):
            self.garden.add_scheduled_event(ev2)

    def test_same_event_id_in_different_pots_allowed(self):
        # event_id univoco solo all'interno del singolo vaso. Lo
        # stesso event_id può apparire in vasi diversi.
        for pot_label in ["basilico", "pomodoro"]:
            self.garden.add_scheduled_event(ScheduledEvent(
                event_id="fert-weekly",
                pot_label=pot_label,
                event_type="fertigation",
                scheduled_date=date(2026, 5, 18),
                payload={},
            ))
        # Entrambi gli eventi presenti, indipendenti.
        self.assertEqual(len(self.garden.scheduled_events), 2)

    def test_cancel_scheduled_event(self):
        ev = ScheduledEvent(
            event_id="fert-001", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
            payload={},
        )
        self.garden.add_scheduled_event(ev)
        cancelled = self.garden.cancel_scheduled_event("basilico", "fert-001")
        self.assertEqual(cancelled, ev)
        self.assertFalse(
            self.garden.has_scheduled_event("basilico", "fert-001"),
        )
        # Cancellare un evento inesistente: KeyError.
        with self.assertRaises(KeyError):
            self.garden.cancel_scheduled_event("basilico", "fert-001")

    def test_events_due_today_filters_by_date(self):
        # Tre eventi su date diverse; events_due_today ritorna solo
        # quelli di oggi.
        for i, day in enumerate([15, 16, 17]):
            self.garden.add_scheduled_event(ScheduledEvent(
                event_id=f"e{i}", pot_label="basilico",
                event_type="fertigation",
                scheduled_date=date(2026, 5, day),
                payload={},
            ))
        today = self.garden.events_due_today(date(2026, 5, 16))
        self.assertEqual(len(today), 1)
        self.assertEqual(today[0].event_id, "e1")

    def test_events_due_today_filters_by_pot(self):
        # Due vasi con eventi nello stesso giorno; filtro per vaso.
        for pot in ["basilico", "pomodoro"]:
            self.garden.add_scheduled_event(ScheduledEvent(
                event_id=f"e-{pot}", pot_label=pot,
                event_type="fertigation",
                scheduled_date=date(2026, 5, 18),
                payload={},
            ))
        only_basil = self.garden.events_due_today(
            date(2026, 5, 18), pot_label="basilico",
        )
        self.assertEqual(len(only_basil), 1)
        self.assertEqual(only_basil[0].pot_label, "basilico")

    def test_events_due_in_range(self):
        # Cinque eventi distribuiti in giorni diversi; range middle.
        for i, day in enumerate([10, 12, 15, 18, 22]):
            self.garden.add_scheduled_event(ScheduledEvent(
                event_id=f"e{i}", pot_label="basilico",
                event_type="fertigation",
                scheduled_date=date(2026, 5, day),
                payload={},
            ))
        # Range 14-19 inclusivo: eventi di 15 e 18.
        in_range = self.garden.events_due_in_range(
            date(2026, 5, 14), date(2026, 5, 19),
        )
        days = [e.scheduled_date.day for e in in_range]
        self.assertEqual(days, [15, 18])

    def test_scheduled_events_sorted_deterministically(self):
        # La proprietà scheduled_events ritorna eventi ordinati per
        # (scheduled_date, pot_label, event_id) per garantire output
        # stabile.
        self.garden.add_scheduled_event(ScheduledEvent(
            event_id="z-evento", pot_label="pomodoro",
            event_type="treatment",
            scheduled_date=date(2026, 5, 20), payload={},
        ))
        self.garden.add_scheduled_event(ScheduledEvent(
            event_id="a-evento", pot_label="basilico",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 15), payload={},
        ))
        events = self.garden.scheduled_events
        # Ordinati per data ascendente: prima basilico (15/5), poi
        # pomodoro (20/5).
        self.assertEqual(events[0].pot_label, "basilico")
        self.assertEqual(events[1].pot_label, "pomodoro")


# =======================================================================
#  Famiglia 8: forecast (proiezione dello stato nei giorni futuri)
# =======================================================================

class TestGardenForecast(unittest.TestCase):
    """Proiezione dello stato del giardino nei giorni futuri."""

    def setUp(self):
        self.garden = Garden(name="balcone")
        self.garden.add_pot(_make_pot(
            "basilico-1", state_mm=25.0, salt_mass_meq=8.0,
        ))
        self.garden.add_pot(_make_pot(
            "basilico-2", state_mm=20.0, salt_mass_meq=10.0,
        ))

    def _make_forecast(self, num_days, et_0=4.0, rainfall=0.0,
                       start_day=15):
        return [
            WeatherDayForecast(
                date_=date(2026, 5, start_day + i),
                et_0_mm=et_0, rainfall_mm=rainfall,
            )
            for i in range(num_days)
        ]

    def test_forecast_does_not_modify_pot_state(self):
        # PROPRIETÀ FONDAMENTALE: il forecast lavora su copie.
        # Lo stato dei vasi del Garden corrente NON cambia.
        before_states = {
            label: (p.state_mm, p.salt_mass_meq, p.ph_substrate)
            for label, p in self.garden._pots.items()
        }
        self.garden.forecast(self._make_forecast(7))
        after_states = {
            label: (p.state_mm, p.salt_mass_meq, p.ph_substrate)
            for label, p in self.garden._pots.items()
        }
        self.assertEqual(before_states, after_states)

    def test_forecast_returns_trajectory_per_pot(self):
        # Il risultato contiene una traiettoria per ogni vaso.
        result = self.garden.forecast(self._make_forecast(5))
        self.assertEqual(
            set(result.trajectories.keys()),
            {"basilico-1", "basilico-2"},
        )
        for traj in result.trajectories.values():
            self.assertEqual(len(traj.points), 5)

    def test_forecast_dates_are_consecutive(self):
        # Ogni traiettoria ha le date corrispondenti al weather_forecast.
        result = self.garden.forecast(self._make_forecast(3, start_day=10))
        traj = result.trajectories["basilico-1"]
        dates = [p.date_ for p in traj.points]
        self.assertEqual(dates, [
            date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 12),
        ])

    def test_forecast_drying_under_no_rainfall(self):
        # 7 giorni di sole senza pioggia: i vasi si seccano.
        result = self.garden.forecast(self._make_forecast(7, et_0=5.0))
        traj = result.trajectories["basilico-1"]
        # Lo state_mm finale è inferiore a quello iniziale (25.0).
        self.assertLess(traj.points[-1].state_mm, 25.0)
        # E l'EC è salita per concentrazione (sali invariati, acqua diminuita).
        # initial EC = 8 / V_acqua (stato 25 mm); final EC > initial.
        # Lo verifichiamo solo qualitativamente.

    def test_forecast_applies_scheduled_fertigation(self):
        # Pianifica una fertirrigazione il 17/5; verifica che l'evento
        # produca un salto chimico nella traiettoria.
        self.garden.add_scheduled_event(ScheduledEvent(
            event_id="fert-mid", pot_label="basilico-1",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 17),
            payload={"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2},
        ))
        result = self.garden.forecast(self._make_forecast(5))
        traj = result.trajectories["basilico-1"]
        # Punti: 15, 16, 17, 18, 19 — l'evento è il 17 (indice 2).
        # Prima dell'evento (15-16): salt_mass_meq invariato a 8.0
        # (l'evapotraspirazione concentra ma non aggiunge sali).
        self.assertAlmostEqual(traj.points[0].salt_mass_meq, 8.0, places=2)
        self.assertAlmostEqual(traj.points[1].salt_mass_meq, 8.0, places=2)
        # Il giorno dell'evento (17): salt_mass cresce per la fertirrigazione.
        self.assertGreater(traj.points[2].salt_mass_meq, 8.0)

    def test_forecast_ignores_unmodelable_event_types(self):
        # Eventi treatment/pruning/repotting sono ignorati dal forecast
        # (effetti non modellati). Il forecast con o senza eventi non
        # simulati produce lo stesso risultato.
        baseline = self.garden.forecast(self._make_forecast(5))

        self.garden.add_scheduled_event(ScheduledEvent(
            event_id="treat-1", pot_label="basilico-1",
            event_type="treatment",
            scheduled_date=date(2026, 5, 17),
            payload={"product": "antifungino"},
        ))
        with_treatment = self.garden.forecast(self._make_forecast(5))

        # Le traiettorie sono identiche perché treatment non è modellato.
        for pt_baseline, pt_treat in zip(
            baseline.trajectories["basilico-1"].points,
            with_treatment.trajectories["basilico-1"].points,
        ):
            self.assertAlmostEqual(
                pt_baseline.state_mm, pt_treat.state_mm, places=6,
            )
            self.assertAlmostEqual(
                pt_baseline.salt_mass_meq, pt_treat.salt_mass_meq, places=6,
            )

    def test_forecast_rejects_empty_weather(self):
        with self.assertRaises(ValueError):
            self.garden.forecast([])

    def test_forecast_only_affects_targeted_pot(self):
        # Una fertirrigazione su basilico-1 non deve influenzare basilico-2.
        self.garden.add_scheduled_event(ScheduledEvent(
            event_id="fert-1", pot_label="basilico-1",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 17),
            payload={"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2},
        ))
        result = self.garden.forecast(self._make_forecast(5))
        # basilico-2: salt_mass invariato (8.0 → ?, no eventi)
        b2 = result.trajectories["basilico-2"]
        self.assertAlmostEqual(b2.points[2].salt_mass_meq, 10.0, places=2)
        # basilico-1: sali aumentati il 17
        b1 = result.trajectories["basilico-1"]
        self.assertGreater(b1.points[2].salt_mass_meq, 8.0)


# =======================================================================
#  Famiglia 9: sistema di allerte (current_alerts e forecast_alerts)
# =======================================================================

class TestGardenCurrentAlerts(unittest.TestCase):
    """Test del metodo current_alerts."""

    def setUp(self):
        self.garden = Garden(name="balcone")

    def test_empty_garden_no_alerts(self):
        # Garden vuoto: nessuna allerta.
        alerts = self.garden.current_alerts(date(2026, 5, 15))
        self.assertEqual(alerts, [])

    def test_optimal_pots_no_alerts(self):
        # Vasi in condizioni ottimali: nessuna allerta.
        # state_mm=25, salt=8.27 → EC=1.3 in range, pH 6.5 in range.
        for label in ["v1", "v2"]:
            self.garden.add_pot(_make_pot(
                label=label, state_mm=25.0, salt_mass_meq=8.27,
                ph_substrate=6.5,
            ))
        alerts = self.garden.current_alerts(date(2026, 5, 15))
        self.assertEqual(alerts, [])

    def test_dry_pot_produces_irrigation_alert(self):
        # Un vaso secco produce un'allerta irrigation.
        self.garden.add_pot(_make_pot(
            label="secco", state_mm=2.0,
        ))
        alerts = self.garden.current_alerts(date(2026, 5, 15))
        irrigation_alerts = [
            a for a in alerts
            if a.category == AlertCategory.IRRIGATION_NEEDED
        ]
        self.assertEqual(len(irrigation_alerts), 1)
        self.assertEqual(irrigation_alerts[0].pot_label, "secco")

    def test_alerts_sorted_deterministically(self):
        # Più vasi e più allerte: ordinamento per (pot_label, category).
        self.garden.add_pot(_make_pot(
            label="z-vaso", state_mm=2.0, ph_substrate=8.5,
        ))
        self.garden.add_pot(_make_pot(
            label="a-vaso", state_mm=2.0,
        ))
        alerts = self.garden.current_alerts(date(2026, 5, 15))
        # I vasi che cominciano con 'a' vengono prima di 'z'.
        labels_in_order = [a.pot_label for a in alerts]
        # Tutti i 'a-vaso' vengono prima di tutti i 'z-vaso'.
        a_indices = [i for i, l in enumerate(labels_in_order)
                     if l == "a-vaso"]
        z_indices = [i for i, l in enumerate(labels_in_order)
                     if l == "z-vaso"]
        if a_indices and z_indices:
            self.assertLess(max(a_indices), min(z_indices))

    def test_default_current_date_is_today(self):
        # Senza parametro current_date, il metodo usa date.today().
        # Verifichiamo che il metodo non sollevi errori senza parametro.
        self.garden.add_pot(_make_pot(label="secco", state_mm=2.0))
        alerts = self.garden.current_alerts()
        # La triggered_date deve essere oggi.
        self.assertEqual(
            alerts[0].triggered_date, date.today(),
        )

    def test_no_side_effect_on_pot_state(self):
        # current_alerts non modifica lo stato dei vasi.
        self.garden.add_pot(_make_pot(label="v", state_mm=2.0))
        before = self.garden.get_pot("v").state_mm
        self.garden.current_alerts(date(2026, 5, 15))
        after = self.garden.get_pot("v").state_mm
        self.assertEqual(before, after)


class TestGardenForecastAlerts(unittest.TestCase):
    """Test del metodo forecast_alerts."""

    def setUp(self):
        self.garden = Garden(name="balcone")
        # Vaso che parte ottimale, ma asciugherà col tempo.
        self.garden.add_pot(_make_pot(
            label="basilico", state_mm=20.0, salt_mass_meq=8.27,
        ))

    def _make_dry_forecast(self, num_days: int) -> list:
        """Forecast meteorologico secco (alta ET, niente pioggia)."""
        return [
            WeatherDayForecast(
                date_=date(2026, 5, 15) + timedelta(days=i),
                et_0_mm=5.5, rainfall_mm=0.0,
            )
            for i in range(num_days)
        ]

    def test_empty_forecast_rejected(self):
        # Forecast vuoto: ValueError.
        with self.assertRaises(ValueError):
            self.garden.forecast_alerts([])

    def test_dry_forecast_predicts_irrigation_alerts(self):
        # 7 giorni di sole intenso senza pioggia: il vaso si seccherà
        # progressivamente e l'allerta irrigation scatterà a un certo
        # punto della proiezione.
        alerts = self.garden.forecast_alerts(self._make_dry_forecast(7))
        irrigation_alerts = [
            a for a in alerts
            if a.category == AlertCategory.IRRIGATION_NEEDED
        ]
        # Almeno qualche allerta irrigation nei 7 giorni.
        self.assertGreater(len(irrigation_alerts), 0)

    def test_alerts_have_future_dates(self):
        # Le triggered_date delle allerte forecast sono giorni futuri.
        forecast = self._make_dry_forecast(5)
        alerts = self.garden.forecast_alerts(forecast)
        if alerts:
            future_dates = {a.triggered_date for a in alerts}
            forecast_dates = {f.date_ for f in forecast}
            # Ogni triggered_date deve essere uno dei giorni del
            # forecast.
            self.assertTrue(future_dates.issubset(forecast_dates))

    def test_no_side_effect_on_pot_state(self):
        # Come per forecast(), forecast_alerts non modifica i vasi
        # del Garden corrente.
        before = self.garden.get_pot("basilico").state_mm
        self.garden.forecast_alerts(self._make_dry_forecast(10))
        after = self.garden.get_pot("basilico").state_mm
        self.assertEqual(before, after)

    def test_alerts_sorted_by_date_then_pot(self):
        # Le allerte sono ordinate per (triggered_date, pot_label,
        # category).
        self.garden.add_pot(_make_pot(
            label="a-altro", state_mm=15.0,
        ))
        alerts = self.garden.forecast_alerts(self._make_dry_forecast(5))
        # Verifica monotonia del triggered_date.
        for i in range(len(alerts) - 1):
            self.assertLessEqual(
                alerts[i].triggered_date, alerts[i + 1].triggered_date,
            )

    def test_no_dedup_same_alert_across_days(self):
        # Niente dedup interna: se la stessa categoria scatta per più
        # giorni di seguito, restituiamo N allerte.
        # Il vaso parte secco, quindi irrigation scatta dal giorno 1.
        self.garden.remove_pot("basilico")
        self.garden.add_pot(_make_pot(
            label="secco", state_mm=2.0,
        ))
        alerts = self.garden.forecast_alerts(self._make_dry_forecast(5))
        irrigation = [
            a for a in alerts
            if a.category == AlertCategory.IRRIGATION_NEEDED
        ]
        # Più allerte irrigation, una per ogni giorno futuro.
        self.assertGreater(len(irrigation), 1)
        # Le triggered_date sono diverse.
        dates = {a.triggered_date for a in irrigation}
        self.assertEqual(len(dates), len(irrigation))


# =====================================================================
#  Test del nuovo metodo apply_step_all_from_weather (sotto-tappa C tappa 5)
#
#  Verifichiamo che il Garden orchestri correttamente la chiamata del
#  selettore per ogni vaso, che ogni vaso possa finire per usare una
#  formula diversa in base ai propri parametri, e che la non-regressione
#  con apply_step_all sia preservata negli scenari sovrapposti.
# =====================================================================


class TestGardenApplyStepAllFromWeather(unittest.TestCase):

    def _make_garden_with_two_pots(self):
        """
        Helper: costruisce un giardino con basilico e rosmarino, entrambi
        con coordinate Milano e parametri fisiologici popolati dalla
        sotto-tappa C (le specie del catalogo li hanno).
        """
        from fitosim.domain.species import BASIL, ROSEMARY
        from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

        garden = Garden(name="Test garden")
        garden.add_pot(Pot(
            label="Basilico-1", species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 6, 1),
            latitude_deg=45.47, elevation_m=150.0,
        ))
        garden.add_pot(Pot(
            label="Rosmarino-1", species=ROSEMARY,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=5.0, pot_diameter_cm=22.0,
            location=Location.OUTDOOR,
            planting_date=date(2025, 5, 1),
            latitude_deg=45.47, elevation_m=150.0,
        ))
        return garden

    def test_returns_one_result_per_pot(self):
        # Il dizionario di ritorno ha una entry per ogni vaso del
        # giardino, indicizzato dal label.
        from fitosim.domain.weather import WeatherDay

        garden = self._make_garden_with_two_pots()
        weather = WeatherDay(
            date_=date(2026, 7, 19),
            t_min=20.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            solar_radiation_mj_m2_day=24.0,
        )
        results = garden.apply_step_all_from_weather(weather=weather)
        self.assertEqual(set(results.keys()), {"Basilico-1", "Rosmarino-1"})

    def test_each_pot_gets_its_own_method_traced(self):
        # Ogni FullStepResult del dizionario porta al suo interno un
        # BalanceStepResult con et_method valorizzato. In questo
        # scenario tutti i vasi hanno parametri specie completi e dati
        # meteo completi, quindi tutti useranno PM fisico, ma ognuno
        # con i propri parametri specifici.
        from fitosim.domain.weather import WeatherDay
        from fitosim.science.et0 import EtMethod

        garden = self._make_garden_with_two_pots()
        weather = WeatherDay(
            date_=date(2026, 7, 19),
            t_min=20.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            solar_radiation_mj_m2_day=24.0,
        )
        results = garden.apply_step_all_from_weather(weather=weather)
        for label, result in results.items():
            with self.subTest(pot=label):
                self.assertEqual(
                    result.balance_result.et_method,
                    EtMethod.PENMAN_MONTEITH_PHYSICAL,
                )

    def test_different_species_produce_different_et(self):
        # Stesso meteo ma specie diverse → ET diverse. Questa è la
        # proprietà fisica fondamentale catturata dal selettore: il
        # rosmarino (rs=200, xerofita semi-mediterranea) traspira meno
        # del basilico (rs=100, mesofila) a parità di tutto il resto.
        # Lo verifichiamo confrontando la variazione di stato dei due
        # vasi: il rosmarino dovrebbe perdere meno acqua del basilico.
        from fitosim.domain.weather import WeatherDay

        garden = self._make_garden_with_two_pots()
        # Salva gli stati iniziali prima dell'applicazione del passo.
        initial_basilico = garden.get_pot("Basilico-1").state_mm
        initial_rosmarino = garden.get_pot("Rosmarino-1").state_mm

        weather = WeatherDay(
            date_=date(2026, 7, 19),
            t_min=20.0, t_max=32.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            solar_radiation_mj_m2_day=24.0,
        )
        results = garden.apply_step_all_from_weather(weather=weather)

        loss_basilico = initial_basilico - results["Basilico-1"].balance_result.new_state
        loss_rosmarino = initial_rosmarino - results["Rosmarino-1"].balance_result.new_state

        # Il rosmarino ha resistenza stomatica doppia (200 vs 100) ma
        # altezza colturale doppia (0.60 vs 0.30) che migliora
        # l'aerodinamica. Il risultato netto è che il rosmarino perde
        # meno acqua per evapotraspirazione, ma la differenza è
        # modesta. Testiamo solo l'ordinamento qualitativo perché la
        # quantità esatta dipende dalla geometria del vaso.
        self.assertLess(loss_rosmarino, loss_basilico)

    def test_negative_rainfall_raises(self):
        # Validazione del rainfall: deve essere non negativa.
        from fitosim.domain.weather import WeatherDay

        garden = self._make_garden_with_two_pots()
        weather = WeatherDay(
            date_=date(2026, 7, 19), t_min=20.0, t_max=32.0,
        )
        with self.assertRaises(ValueError):
            garden.apply_step_all_from_weather(
                weather=weather, rainfall_mm=-1.0,
            )


# =====================================================================
#  Test della collezione di Room (sotto-tappa D fase 1 tappa 5)
#
#  La fase D1 ha esteso il Garden con un dict interno _rooms parallelo
#  ai _pots, e con metodi di gestione standard (add, get, has, remove,
#  ids, iter, num) più la utility specifica pots_in_room. Verifichiamo
#  ognuno di questi metodi e in particolare la validazione di
#  remove_room che blocca la rimozione quando ci sono ancora vasi
#  associati.
# =====================================================================


class TestGardenRooms(unittest.TestCase):

    def _make_basic_garden(self):
        """Helper: costruisce un giardino con due Room di base."""
        from fitosim.domain.room import Room
        garden = Garden(name="Casa di Andrea")
        garden.add_room(Room(room_id="salotto", name="Salotto"))
        garden.add_room(Room(room_id="camera", name="Camera da letto"))
        return garden

    def test_add_and_get_room(self):
        # add_room aggiunge correttamente una Room e get_room la
        # recupera per room_id.
        from fitosim.domain.room import Room
        garden = Garden(name="Test")
        salotto = Room(room_id="salotto", name="Salotto")
        garden.add_room(salotto)

        retrieved = garden.get_room("salotto")
        self.assertIs(retrieved, salotto)

    def test_add_duplicate_room_raises(self):
        # Aggiungere una Room con room_id già presente solleva ValueError.
        from fitosim.domain.room import Room
        garden = self._make_basic_garden()
        with self.assertRaises(ValueError):
            garden.add_room(Room(room_id="salotto", name="Altro salotto"))

    def test_get_nonexistent_room_raises(self):
        # get_room di room_id inesistente solleva ValueError.
        garden = self._make_basic_garden()
        with self.assertRaises(ValueError):
            garden.get_room("garage")

    def test_has_room(self):
        # has_room ritorna True per Room esistenti, False altrimenti.
        garden = self._make_basic_garden()
        self.assertTrue(garden.has_room("salotto"))
        self.assertFalse(garden.has_room("garage"))

    def test_room_ids_property(self):
        # room_ids è una property che ritorna la lista degli identificatori
        # in ordine di inserimento.
        garden = self._make_basic_garden()
        self.assertEqual(garden.room_ids, ["salotto", "camera"])

    def test_num_rooms(self):
        # num_rooms ritorna il numero corrente di Room.
        from fitosim.domain.room import Room
        garden = Garden(name="Test")
        self.assertEqual(garden.num_rooms(), 0)
        garden.add_room(Room(room_id="r1", name="R1"))
        self.assertEqual(garden.num_rooms(), 1)
        garden.add_room(Room(room_id="r2", name="R2"))
        self.assertEqual(garden.num_rooms(), 2)

    def test_iter_rooms(self):
        # iter_rooms itera in ordine di inserimento.
        garden = self._make_basic_garden()
        ids = [r.room_id for r in garden.iter_rooms()]
        self.assertEqual(ids, ["salotto", "camera"])

    def test_pots_in_room(self):
        # pots_in_room ritorna i Pot con room_id corrispondente.
        from fitosim.domain.species import BASIL
        from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL
        garden = self._make_basic_garden()
        pot1 = Pot(
            label="P1", species=BASIL, substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.INDOOR, planting_date=date(2026, 6, 1),
            room_id="salotto",
        )
        pot2 = Pot(
            label="P2", species=BASIL, substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.INDOOR, planting_date=date(2026, 6, 1),
            room_id="camera",
        )
        garden.add_pot(pot1)
        garden.add_pot(pot2)

        vasi_salotto = garden.pots_in_room("salotto")
        self.assertEqual([p.label for p in vasi_salotto], ["P1"])
        vasi_camera = garden.pots_in_room("camera")
        self.assertEqual([p.label for p in vasi_camera], ["P2"])

    def test_remove_room_with_associated_pots_raises(self):
        # remove_room blocca la rimozione quando ci sono vasi associati,
        # per evitare di lasciare vasi con room_id orfani.
        from fitosim.domain.species import BASIL
        from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL
        garden = self._make_basic_garden()
        pot = Pot(
            label="P1", species=BASIL, substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.INDOOR, planting_date=date(2026, 6, 1),
            room_id="salotto",
        )
        garden.add_pot(pot)

        with self.assertRaises(ValueError) as ctx:
            garden.remove_room("salotto")
        # Il messaggio di errore deve menzionare il vaso bloccante.
        self.assertIn("P1", str(ctx.exception))

    def test_remove_room_without_pots_succeeds(self):
        # Senza vasi associati la rimozione va a buon fine.
        garden = self._make_basic_garden()
        removed = garden.remove_room("salotto")
        self.assertEqual(removed.room_id, "salotto")
        self.assertFalse(garden.has_room("salotto"))
        self.assertEqual(garden.num_rooms(), 1)


# =====================================================================
#  Test del nuovo metodo apply_step_all_from_indoor (fase D2)
#
#  Verifichiamo l'iterazione corretta sulle stanze, il salto
#  silenzioso di room_id non presenti, il salto dei vasi outdoor,
#  e la propagazione dell'et_method nel FullStepResult.
# =====================================================================


class TestGardenApplyStepAllFromIndoor(unittest.TestCase):

    def _make_indoor_garden(self):
        """
        Helper: giardino con due stanze e tre vasi indoor (due nel
        salotto, uno in camera).
        """
        from fitosim.domain.room import Room, LightExposure
        from fitosim.domain.species import BASIL, ROSEMARY
        from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

        garden = Garden(name="Casa di Andrea")
        garden.add_room(Room(room_id="salotto", name="Salotto"))
        garden.add_room(Room(room_id="camera", name="Camera"))

        garden.add_pot(Pot(
            label="Basilico-cucina", species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.INDOOR,
            planting_date=date(2026, 6, 1),
            room_id="salotto",
            light_exposure=LightExposure.INDIRECT_BRIGHT,
        ))
        garden.add_pot(Pot(
            label="Rosmarino-davanzale", species=ROSEMARY,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=5.0, pot_diameter_cm=22.0,
            location=Location.INDOOR,
            planting_date=date(2025, 5, 1),
            room_id="salotto",
            light_exposure=LightExposure.DIRECT_SUN,
        ))
        garden.add_pot(Pot(
            label="Basilico-camera", species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.INDOOR,
            planting_date=date(2026, 6, 1),
            room_id="camera",
            light_exposure=LightExposure.DARK,
        ))
        return garden

    def _make_microclimate(self, t_min, t_max, humidity=0.55):
        from fitosim.domain.room import IndoorMicroclimate, MicroclimateKind
        return IndoorMicroclimate(
            kind=MicroclimateKind.DAILY,
            temperature_c=(t_min + t_max) / 2.0,
            humidity_relative=humidity,
            t_min=t_min, t_max=t_max,
        )

    def test_basic_two_room_scenario(self):
        # Scenario base: dict con due stanze, ogni stanza riceve i
        # suoi vasi processati. Verifichiamo che il dict di ritorno
        # abbia esattamente i tre vasi attesi.
        garden = self._make_indoor_garden()
        m_salotto = self._make_microclimate(t_min=22.0, t_max=25.0)
        m_camera = self._make_microclimate(t_min=19.5, t_max=21.5)

        results = garden.apply_step_all_from_indoor(
            microclimates_by_room={
                "salotto": m_salotto,
                "camera": m_camera,
            },
            current_date=date(2026, 7, 19),
        )
        self.assertEqual(
            set(results.keys()),
            {"Basilico-cucina", "Rosmarino-davanzale", "Basilico-camera"},
        )

    def test_unknown_room_id_skipped_silently(self):
        # Se il dict contiene un room_id non presente nel garden,
        # viene saltato silenziosamente senza errori.
        garden = self._make_indoor_garden()
        m_salotto = self._make_microclimate(t_min=22.0, t_max=25.0)
        m_garage = self._make_microclimate(t_min=15.0, t_max=18.0)

        # "garage" non esiste nel garden ma il metodo non solleva.
        results = garden.apply_step_all_from_indoor(
            microclimates_by_room={
                "salotto": m_salotto,
                "garage": m_garage,
            },
            current_date=date(2026, 7, 19),
        )
        # Solo i vasi del salotto sono nel risultato.
        self.assertEqual(
            set(results.keys()),
            {"Basilico-cucina", "Rosmarino-davanzale"},
        )

    def test_outdoor_pots_skipped(self):
        # Vasi outdoor del giardino non sono processati dal metodo
        # indoor. Aggiungiamo un vaso outdoor e verifichiamo che non
        # appaia nel dict di ritorno.
        from fitosim.domain.species import BASIL
        from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

        garden = self._make_indoor_garden()
        garden.add_pot(Pot(
            label="Basilico-balcone", species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=2.0, pot_diameter_cm=15.0,
            location=Location.OUTDOOR,
            planting_date=date(2026, 6, 1),
            # Niente room_id né light_exposure: vaso outdoor.
        ))

        m_salotto = self._make_microclimate(t_min=22.0, t_max=25.0)
        m_camera = self._make_microclimate(t_min=19.5, t_max=21.5)

        results = garden.apply_step_all_from_indoor(
            microclimates_by_room={
                "salotto": m_salotto,
                "camera": m_camera,
            },
            current_date=date(2026, 7, 19),
        )
        # Il vaso outdoor non è nel dict di ritorno.
        self.assertNotIn("Basilico-balcone", results)

    def test_et_method_propagated_in_full_step_result(self):
        # Il FullStepResult restituito ha al suo interno un
        # BalanceStepResult con et_method valorizzato.
        from fitosim.science.et0 import EtMethod

        garden = self._make_indoor_garden()
        m_salotto = self._make_microclimate(t_min=22.0, t_max=25.0)

        results = garden.apply_step_all_from_indoor(
            microclimates_by_room={"salotto": m_salotto},
            current_date=date(2026, 7, 19),
        )
        for label, result in results.items():
            with self.subTest(pot=label):
                # Le specie BASIL e ROSEMARY hanno parametri rs e h
                # popolati, quindi il selettore sceglie PM fisico.
                self.assertEqual(
                    result.balance_result.et_method,
                    EtMethod.PENMAN_MONTEITH_PHYSICAL,
                )


if __name__ == "__main__":
    unittest.main()
