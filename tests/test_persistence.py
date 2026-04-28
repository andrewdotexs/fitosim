"""
Test del modulo io/persistence.py (sotto-tappa B fase 1 tappa 4).

Strategia di test
-----------------

Sei famiglie tematiche di test, ciascuna concentrata su un aspetto
specifico della persistenza:

  1. **Inizializzazione e schema versioning**: creazione del database,
     versioning, gestione di database con versioni incompatibili.

  2. **Catalogo**: registrazione e recupero di specie, materiali base,
     substrati puri e misture; idempotenza degli update; gestione
     dei materiali non registrati nelle ricette delle misture.

  3. **Garden round-trip**: salvataggio e caricamento di un giardino
     con i suoi vasi; preservazione di tutti i campi statici e
     mutabili; gestione della rimozione di vasi.

  4. **Snapshot multipli**: salvataggio di stati successivi nel tempo;
     caricamento dell'ultimo snapshot; caricamento "as_of" di uno
     snapshot specifico; query del range temporale.

  5. **Integrità referenziale**: cancellazione a cascata (cancellando
     un giardino spariscono i vasi e i loro stati ed eventi); errori
     espliciti per vasi non registrati nel catalogo.

  6. **Eventi**: registrazione di eventi storici con payload JSON,
     query per tipo e per range temporale.

Tutti i test usano un database in-memory (`":memory:"`) per essere
veloci e isolati, senza scrittura su disco.
"""

import unittest
from datetime import date, datetime, timedelta, timezone

from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot
from fitosim.domain.scheduling import ScheduledEvent
from fitosim.domain.species import Species
from fitosim.io.persistence import (
    CatalogMissingError,
    GardenPersistence,
    PersistenceError,
    PotStateSnapshot,
    SCHEMA_VERSION,
    SchemaVersionMismatch,
)
from fitosim.science.substrate import (
    BaseMaterial,
    MixComponent,
    Substrate,
    compose_substrate,
)


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


def _make_pomice() -> BaseMaterial:
    return BaseMaterial(
        name="pomice",
        theta_fc=0.30, theta_pwp=0.05,
        description="Roccia vulcanica leggera, drenante",
    )


def _make_akadama() -> BaseMaterial:
    return BaseMaterial(
        name="akadama",
        theta_fc=0.55, theta_pwp=0.15,
        description="Argilla giapponese per bonsai",
    )


def _make_basic_pot(label: str = "basilico-1") -> Pot:
    return Pot(
        label=label,
        species=_make_basil(),
        substrate=_make_universal_substrate(),
        pot_volume_l=2.0, pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        state_mm=25.0, salt_mass_meq=10.0, ph_substrate=6.8,
    )


# =======================================================================
#  Famiglia 1: inizializzazione e schema
# =======================================================================

class TestSchemaInitialization(unittest.TestCase):
    """Creazione del database e gestione dello schema."""

    def test_in_memory_database_initializes(self):
        # Apertura su :memory: deve produrre un database utilizzabile.
        with GardenPersistence(":memory:") as p:
            self.assertEqual(p.list_species(), [])
            self.assertEqual(p.list_gardens(), [])

    def test_schema_metadata_has_correct_version(self):
        # La tabella schema_metadata viene popolata con la versione
        # corrente al primo accesso.
        with GardenPersistence(":memory:") as p:
            cursor = p._conn.execute(
                "SELECT version FROM schema_metadata LIMIT 1"
            )
            row = cursor.fetchone()
            self.assertEqual(row["version"], SCHEMA_VERSION)

    def test_reopening_database_does_not_reset(self):
        # Aprendo e chiudendo il database (non in-memory ma persistente)
        # i dati salvati vengono preservati. Per testarlo usiamo un
        # database in memoria condiviso tra istanze... in realtà non
        # è facile farlo con sqlite3 standard, quindi testiamo il
        # comportamento idempotente dello schema sulla stessa istanza.
        with GardenPersistence(":memory:") as p:
            # Il primo accesso crea lo schema. Un secondo accesso non
            # deve fallire né duplicare le tabelle.
            p._initialize_schema()  # chiamata esplicita per ri-test
            # Non deve sollevare errori e la versione deve essere ancora
            # corretta:
            cursor = p._conn.execute(
                "SELECT COUNT(*) AS c FROM schema_metadata"
            )
            # Una sola riga di metadata anche dopo doppia init.
            self.assertEqual(cursor.fetchone()["c"], 1)


# =======================================================================
#  Famiglia 2: catalogo
# =======================================================================

class TestCatalogSpecies(unittest.TestCase):
    """Registrazione e recupero delle specie."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")

    def tearDown(self):
        self.persistence.close()

    def test_register_and_retrieve_species(self):
        basil = _make_basil()
        self.persistence.register_species(basil)
        retrieved = self.persistence.get_species("basilico")
        self.assertEqual(retrieved.common_name, basil.common_name)
        self.assertEqual(retrieved.scientific_name, basil.scientific_name)
        self.assertEqual(retrieved.kc_mid, basil.kc_mid)
        self.assertEqual(
            retrieved.ec_optimal_min_mscm, basil.ec_optimal_min_mscm,
        )

    def test_register_species_idempotent(self):
        # Chiamare register_species due volte con la stessa specie
        # non deve causare errori e deve aggiornare i parametri.
        basil_v1 = _make_basil()
        self.persistence.register_species(basil_v1)
        basil_v2 = Species(
            common_name="basilico",
            scientific_name="Ocimum basilicum",
            kc_initial=0.55, kc_mid=1.20, kc_late=0.90,  # parametri aggiornati
            ec_optimal_min_mscm=1.0, ec_optimal_max_mscm=1.6,
            ph_optimal_min=6.0, ph_optimal_max=7.0,
        )
        self.persistence.register_species(basil_v2)
        retrieved = self.persistence.get_species("basilico")
        self.assertEqual(retrieved.kc_mid, 1.20)  # valore aggiornato

    def test_get_species_missing_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.persistence.get_species("inesistente")

    def test_is_species_registered(self):
        self.assertFalse(self.persistence.is_species_registered("basilico"))
        self.persistence.register_species(_make_basil())
        self.assertTrue(self.persistence.is_species_registered("basilico"))

    def test_list_species_returns_all(self):
        self.persistence.register_species(_make_basil())
        self.persistence.register_species(_make_tomato())
        species_list = self.persistence.list_species()
        self.assertEqual(len(species_list), 2)
        names = [s.common_name for s in species_list]
        self.assertIn("basilico", names)
        self.assertIn("pomodoro", names)


class TestCatalogSubstrate(unittest.TestCase):
    """Registrazione di substrati puri e misture."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")

    def tearDown(self):
        self.persistence.close()

    def test_register_pure_substrate(self):
        # Substrato puro: parametri direttamente preservati.
        sub = _make_universal_substrate()
        self.persistence.register_substrate(sub)
        retrieved = self.persistence.get_substrate("terriccio universale")
        self.assertEqual(retrieved.name, sub.name)
        self.assertEqual(retrieved.theta_fc, sub.theta_fc)
        self.assertEqual(retrieved.cec_meq_per_100g, sub.cec_meq_per_100g)
        self.assertEqual(retrieved.ph_typical, sub.ph_typical)

    def test_register_substrate_mixture(self):
        # Substrato come mistura: ricetta salvata, parametri ricalcolati
        # al caricamento.
        pomice = _make_pomice()
        akadama = _make_akadama()
        self.persistence.register_base_material(pomice)
        self.persistence.register_base_material(akadama)

        components = [
            MixComponent(material=pomice, fraction=0.4),
            MixComponent(material=akadama, fraction=0.6),
        ]
        # Componiamo a mano per ottenere il nome e i parametri target.
        composed = compose_substrate(components, name="bonsai mix")
        self.persistence.register_substrate(composed, components=components)

        # Quando ricarichiamo la mistura, otteniamo gli stessi parametri.
        retrieved = self.persistence.get_substrate("bonsai mix")
        self.assertAlmostEqual(retrieved.theta_fc, composed.theta_fc, places=6)
        self.assertAlmostEqual(retrieved.theta_pwp, composed.theta_pwp, places=6)

    def test_mixture_recipe_recalculates_at_load(self):
        # PROPRIETÀ FONDAMENTALE: i parametri della mistura sono
        # ricalcolati al load, quindi se aggiorniamo i materiali base
        # le misture che li usano vedono i nuovi valori.
        pomice = _make_pomice()
        akadama = _make_akadama()
        self.persistence.register_base_material(pomice)
        self.persistence.register_base_material(akadama)
        components = [
            MixComponent(material=pomice, fraction=0.5),
            MixComponent(material=akadama, fraction=0.5),
        ]
        composed = compose_substrate(components, name="50-50 mix")
        self.persistence.register_substrate(composed, components=components)

        # Aggiorniamo i parametri della pomice nel catalogo.
        new_pomice = BaseMaterial(
            name="pomice",
            theta_fc=0.40,  # cambiato da 0.30 a 0.40
            theta_pwp=0.05,
            description="Roccia vulcanica leggera, drenante",
        )
        self.persistence.register_base_material(new_pomice)

        # Ricaricando la mistura, il theta_fc è ricalcolato:
        # nuovo theta_fc = 0.5 * 0.40 + 0.5 * 0.55 = 0.475
        retrieved = self.persistence.get_substrate("50-50 mix")
        self.assertAlmostEqual(retrieved.theta_fc, 0.475, places=6)

    def test_register_mixture_with_unknown_base_material_fails(self):
        # Se la ricetta referenzia un materiale non registrato, errore.
        unknown = BaseMaterial(
            name="materiale-non-registrato",
            theta_fc=0.30, theta_pwp=0.10,
        )
        # NON lo registriamo nel catalogo!
        components = [MixComponent(material=unknown, fraction=1.0)]
        composed = compose_substrate(components, name="problematic mix")
        with self.assertRaises(CatalogMissingError):
            self.persistence.register_substrate(
                composed, components=components,
            )

    def test_register_substrate_idempotent(self):
        sub = _make_universal_substrate()
        self.persistence.register_substrate(sub)
        # Aggiornamento dei parametri.
        sub_v2 = Substrate(
            name="terriccio universale",
            theta_fc=0.42,  # cambiato
            theta_pwp=0.10,
            cec_meq_per_100g=55.0,  # cambiato
            ph_typical=6.8,
        )
        self.persistence.register_substrate(sub_v2)
        retrieved = self.persistence.get_substrate("terriccio universale")
        self.assertEqual(retrieved.theta_fc, 0.42)
        self.assertEqual(retrieved.cec_meq_per_100g, 55.0)


# =======================================================================
#  Famiglia 3: garden round-trip
# =======================================================================

class TestGardenRoundTrip(unittest.TestCase):
    """Salvataggio e caricamento completo di un giardino."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")
        # Pre-registra il catalogo che useremo.
        self.persistence.register_species(_make_basil())
        self.persistence.register_substrate(_make_universal_substrate())

    def tearDown(self):
        self.persistence.close()

    def test_save_and_load_empty_garden(self):
        garden = Garden(name="balcone", location_description="balcone sud")
        self.persistence.save_garden(garden)
        loaded = self.persistence.load_garden("balcone")
        self.assertEqual(loaded.name, "balcone")
        self.assertEqual(loaded.location_description, "balcone sud")
        self.assertEqual(len(loaded), 0)

    def test_save_and_load_garden_with_one_pot(self):
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot())
        self.persistence.save_garden(garden)

        loaded = self.persistence.load_garden("balcone")
        self.assertEqual(len(loaded), 1)
        pot = loaded.get_pot("basilico-1")
        # Tutti i campi statici preservati.
        self.assertEqual(pot.label, "basilico-1")
        self.assertEqual(pot.pot_volume_l, 2.0)
        self.assertEqual(pot.pot_diameter_cm, 18.0)
        self.assertEqual(pot.location, Location.OUTDOOR)
        self.assertEqual(pot.planting_date, date(2026, 4, 1))
        # Stato mutabile preservato.
        self.assertEqual(pot.state_mm, 25.0)
        self.assertEqual(pot.salt_mass_meq, 10.0)
        self.assertEqual(pot.ph_substrate, 6.8)

    def test_save_garden_missing_species_in_catalog(self):
        # Vaso che usa una specie non registrata: errore esplicito.
        unknown_species = Species(
            common_name="specie-misteriosa",
            scientific_name="Mysteria mysteriosa",
            kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
        )
        pot = Pot(
            label="vaso", species=unknown_species,
            substrate=_make_universal_substrate(),
            pot_volume_l=2.0, pot_diameter_cm=18.0,
            location=Location.OUTDOOR, planting_date=date(2026, 4, 1),
        )
        garden = Garden(name="balcone")
        garden.add_pot(pot)
        with self.assertRaises(CatalogMissingError) as ctx:
            self.persistence.save_garden(garden)
        self.assertIn("specie-misteriosa", str(ctx.exception))

    def test_save_garden_missing_substrate_in_catalog(self):
        unknown_substrate = Substrate(
            name="substrato-misterioso",
            theta_fc=0.40, theta_pwp=0.10,
        )
        pot = Pot(
            label="vaso", species=_make_basil(),
            substrate=unknown_substrate,
            pot_volume_l=2.0, pot_diameter_cm=18.0,
            location=Location.OUTDOOR, planting_date=date(2026, 4, 1),
        )
        garden = Garden(name="balcone")
        garden.add_pot(pot)
        with self.assertRaises(CatalogMissingError):
            self.persistence.save_garden(garden)

    def test_pot_removed_from_garden_is_deleted_on_save(self):
        # Aggiungi due vasi, salva, rimuovi un vaso, salva di nuovo:
        # il vaso rimosso scompare dal database.
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("vaso-1"))
        garden.add_pot(_make_basic_pot("vaso-2"))
        self.persistence.save_garden(garden)

        garden.remove_pot("vaso-1")
        self.persistence.save_garden(garden)

        loaded = self.persistence.load_garden("balcone")
        self.assertEqual(loaded.pot_labels, ["vaso-2"])

    def test_load_nonexistent_garden_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.persistence.load_garden("inesistente")

    def test_garden_exists(self):
        self.assertFalse(self.persistence.garden_exists("balcone"))
        garden = Garden(name="balcone")
        self.persistence.save_garden(garden)
        self.assertTrue(self.persistence.garden_exists("balcone"))

    def test_list_gardens(self):
        for name in ["balcone", "terrazzo", "indoor"]:
            self.persistence.save_garden(Garden(name=name))
        gardens = self.persistence.list_gardens()
        self.assertEqual(set(gardens), {"balcone", "terrazzo", "indoor"})

    def test_delete_garden(self):
        self.persistence.save_garden(Garden(name="balcone"))
        self.persistence.delete_garden("balcone")
        self.assertFalse(self.persistence.garden_exists("balcone"))
        # Cancellazione di giardino inesistente: KeyError.
        with self.assertRaises(KeyError):
            self.persistence.delete_garden("inesistente")


# =======================================================================
#  Famiglia 4: snapshot multipli e selezione temporale
# =======================================================================

class TestMultipleSnapshots(unittest.TestCase):
    """Salvataggi successivi e caricamento as_of."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")
        self.persistence.register_species(_make_basil())
        self.persistence.register_substrate(_make_universal_substrate())

    def tearDown(self):
        self.persistence.close()

    def test_multiple_saves_create_multiple_snapshots(self):
        # Salvataggi successivi della stessa garden creano snapshot
        # multipli nella tabella pot_states (la storia è preservata).
        garden = Garden(name="balcone")
        pot = _make_basic_pot()
        garden.add_pot(pot)

        t1 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)

        self.persistence.save_garden(garden, snapshot_timestamp=t1)
        pot.state_mm = 22.0
        self.persistence.save_garden(garden, snapshot_timestamp=t2)
        pot.state_mm = 18.0
        self.persistence.save_garden(garden, snapshot_timestamp=t3)

        # Tre snapshot nel pot_states
        snapshots = self.persistence.query_states("balcone", "basilico-1")
        self.assertEqual(len(snapshots), 3)
        # Ordine cronologico crescente
        self.assertEqual(snapshots[0].state_mm, 25.0)
        self.assertEqual(snapshots[1].state_mm, 22.0)
        self.assertEqual(snapshots[2].state_mm, 18.0)

    def test_load_uses_latest_snapshot_by_default(self):
        garden = Garden(name="balcone")
        pot = _make_basic_pot()
        garden.add_pot(pot)

        t1 = datetime(2026, 5, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 5, 10, tzinfo=timezone.utc)
        self.persistence.save_garden(garden, snapshot_timestamp=t1)
        pot.state_mm = 18.0
        self.persistence.save_garden(garden, snapshot_timestamp=t2)

        # Senza as_of, carica l'ultimo snapshot (state_mm=18.0)
        loaded = self.persistence.load_garden("balcone")
        self.assertEqual(loaded.get_pot("basilico-1").state_mm, 18.0)

    def test_load_with_as_of_returns_snapshot_at_that_time(self):
        garden = Garden(name="balcone")
        pot = _make_basic_pot()
        garden.add_pot(pot)

        t1 = datetime(2026, 5, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 5, 5, tzinfo=timezone.utc)
        t3 = datetime(2026, 5, 10, tzinfo=timezone.utc)
        self.persistence.save_garden(garden, snapshot_timestamp=t1)
        pot.state_mm = 22.0
        self.persistence.save_garden(garden, snapshot_timestamp=t2)
        pot.state_mm = 18.0
        self.persistence.save_garden(garden, snapshot_timestamp=t3)

        # as_of intermedio: il più recente ≤ t_intermedio
        as_of_intermedio = datetime(2026, 5, 7, tzinfo=timezone.utc)
        loaded = self.persistence.load_garden("balcone", as_of=as_of_intermedio)
        # Il più recente ≤ 5/7 è quello del 5/5 con state_mm=22.0
        self.assertEqual(loaded.get_pot("basilico-1").state_mm, 22.0)

    def test_query_states_with_time_range(self):
        garden = Garden(name="balcone")
        pot = _make_basic_pot()
        garden.add_pot(pot)

        for day in range(1, 11):
            t = datetime(2026, 5, day, tzinfo=timezone.utc)
            pot.state_mm = 30.0 - day  # 29, 28, 27, ...
            self.persistence.save_garden(garden, snapshot_timestamp=t)

        # Query: dal 4 al 7 maggio (4 snapshot)
        since = datetime(2026, 5, 4, tzinfo=timezone.utc)
        until = datetime(2026, 5, 7, tzinfo=timezone.utc)
        snapshots = self.persistence.query_states(
            "balcone", "basilico-1", since=since, until=until,
        )
        self.assertEqual(len(snapshots), 4)
        # state_mm decrescente da 26 a 23
        self.assertEqual(
            [s.state_mm for s in snapshots], [26.0, 25.0, 24.0, 23.0],
        )


# =======================================================================
#  Famiglia 5: integrità referenziale
# =======================================================================

class TestReferentialIntegrity(unittest.TestCase):
    """Cancellazioni a cascata e integrità referenziale."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")
        self.persistence.register_species(_make_basil())
        self.persistence.register_substrate(_make_universal_substrate())

    def tearDown(self):
        self.persistence.close()

    def test_delete_garden_cascades_to_pots_and_states(self):
        # Cancellando un giardino, i suoi vasi, stati ed eventi
        # vengono cancellati a cascata.
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("vaso-1"))
        self.persistence.save_garden(garden)
        self.persistence.record_event(
            "balcone", "vaso-1", "fertigation",
            datetime.now(timezone.utc), {"volume_l": 0.3},
        )

        # Pre-cancellazione: tutti i record presenti
        cursor = self.persistence._conn.execute("SELECT COUNT(*) AS c FROM pots")
        self.assertEqual(cursor.fetchone()["c"], 1)

        self.persistence.delete_garden("balcone")

        # Dopo la cancellazione, vasi, stati ed eventi spariscono
        cursor = self.persistence._conn.execute("SELECT COUNT(*) AS c FROM pots")
        self.assertEqual(cursor.fetchone()["c"], 0)
        cursor = self.persistence._conn.execute(
            "SELECT COUNT(*) AS c FROM pot_states"
        )
        self.assertEqual(cursor.fetchone()["c"], 0)
        cursor = self.persistence._conn.execute(
            "SELECT COUNT(*) AS c FROM events"
        )
        self.assertEqual(cursor.fetchone()["c"], 0)

    def test_pots_in_different_gardens_can_have_same_label(self):
        # Vincolo di unicità è (garden_id, label), non solo label.
        # Quindi due giardini diversi possono avere vasi con stessa label.
        g1 = Garden(name="balcone")
        g1.add_pot(_make_basic_pot("basilico"))
        g2 = Garden(name="terrazzo")
        g2.add_pot(_make_basic_pot("basilico"))
        # Niente errore: ognuno nel suo giardino.
        self.persistence.save_garden(g1)
        self.persistence.save_garden(g2)

        loaded1 = self.persistence.load_garden("balcone")
        loaded2 = self.persistence.load_garden("terrazzo")
        self.assertEqual(loaded1.get_pot("basilico").label, "basilico")
        self.assertEqual(loaded2.get_pot("basilico").label, "basilico")


# =======================================================================
#  Famiglia 6: eventi storici
# =======================================================================

class TestEvents(unittest.TestCase):
    """Registrazione e query di eventi storici."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")
        self.persistence.register_species(_make_basil())
        self.persistence.register_substrate(_make_universal_substrate())
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot())
        self.persistence.save_garden(garden)

    def tearDown(self):
        self.persistence.close()

    def test_record_and_retrieve_event(self):
        t = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)
        payload = {"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2}
        self.persistence.record_event(
            "balcone", "basilico-1", "fertigation", t, payload,
        )
        events = self.persistence.query_events("balcone", "basilico-1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "fertigation")
        self.assertEqual(events[0]["payload"], payload)
        # Il timestamp è preservato come datetime con timezone
        self.assertEqual(events[0]["timestamp"], t)

    def test_query_events_filter_by_type(self):
        t1 = datetime(2026, 5, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 5, 2, tzinfo=timezone.utc)
        t3 = datetime(2026, 5, 3, tzinfo=timezone.utc)
        self.persistence.record_event(
            "balcone", "basilico-1", "fertigation", t1, {"volume_l": 0.3},
        )
        self.persistence.record_event(
            "balcone", "basilico-1", "rainfall", t2, {"volume_mm": 5.0},
        )
        self.persistence.record_event(
            "balcone", "basilico-1", "fertigation", t3, {"volume_l": 0.4},
        )

        # Filtra solo le fertirrigazioni
        fert_events = self.persistence.query_events(
            "balcone", "basilico-1", event_type="fertigation",
        )
        self.assertEqual(len(fert_events), 2)
        for e in fert_events:
            self.assertEqual(e["event_type"], "fertigation")

    def test_query_events_filter_by_time_range(self):
        for day in range(1, 11):
            t = datetime(2026, 5, day, tzinfo=timezone.utc)
            self.persistence.record_event(
                "balcone", "basilico-1", "rainfall", t, {"volume_mm": 1.0},
            )
        # Range: dal 4 al 7
        since = datetime(2026, 5, 4, tzinfo=timezone.utc)
        until = datetime(2026, 5, 7, tzinfo=timezone.utc)
        events = self.persistence.query_events(
            "balcone", "basilico-1", since=since, until=until,
        )
        self.assertEqual(len(events), 4)

    def test_event_for_nonexistent_pot_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.persistence.record_event(
                "balcone", "vaso-fantasma",
                "fertigation",
                datetime.now(timezone.utc),
                {"volume_l": 0.1},
            )


# =======================================================================
#  Famiglia 7: persistenza della mappa channel_id e migrazione schema
# =======================================================================

class TestChannelIdPersistence(unittest.TestCase):
    """
    Persistenza della mappa label → channel_id introdotta nella
    sotto-tappa C, e migrazione automatica da schema v1.
    """

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")
        self.persistence.register_species(_make_basil())
        self.persistence.register_substrate(_make_universal_substrate())

    def tearDown(self):
        self.persistence.close()

    def test_channel_id_round_trip(self):
        # Salvataggio e caricamento di un giardino con mappa parziale.
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.add_pot(_make_basic_pot("basilico-2"))
        garden.set_channel_id("basilico-1", "wh51_ch1")
        # basilico-2 senza mapping
        self.persistence.save_garden(garden)

        loaded = self.persistence.load_garden("balcone")
        self.assertEqual(loaded.get_channel_id("basilico-1"), "wh51_ch1")
        self.assertIsNone(loaded.get_channel_id("basilico-2"))

    def test_channel_id_update_on_resave(self):
        # Cambio del channel_id e successivo salvataggio: il valore
        # nel database viene aggiornato.
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.set_channel_id("basilico-1", "wh51_ch1")
        self.persistence.save_garden(garden)

        # Cambio del canale (es. il sensore è stato spostato).
        garden.set_channel_id("basilico-1", "wh51_ch5")
        self.persistence.save_garden(garden)

        loaded = self.persistence.load_garden("balcone")
        self.assertEqual(loaded.get_channel_id("basilico-1"), "wh51_ch5")

    def test_channel_id_removal_on_resave(self):
        # Rimozione del mapping e successivo salvataggio: il
        # channel_id nel database diventa NULL.
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.set_channel_id("basilico-1", "wh51_ch1")
        self.persistence.save_garden(garden)

        garden.remove_channel_id("basilico-1")
        self.persistence.save_garden(garden)

        loaded = self.persistence.load_garden("balcone")
        self.assertIsNone(loaded.get_channel_id("basilico-1"))

    def test_schema_version_is_current(self):
        # Database nuovo: schema_version uguale alla SCHEMA_VERSION
        # corrente (3 dalla sotto-tappa D).
        cursor = self.persistence._conn.execute(
            "SELECT version FROM schema_metadata "
            "ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(cursor.fetchone()["version"], SCHEMA_VERSION)

    def test_v1_database_migrates_to_v2_automatically(self):
        # Simuliamo un database creato con lo schema v1: applichiamo
        # solo le tabelle iniziali e poi forziamo version=1, infine
        # apriamo il database con il codice corrente che deve fare
        # la migrazione.
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        # Schema v1: stesso del v2 ma SENZA channel_id sulla tabella pots
        conn.execute("""
            CREATE TABLE schema_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE pots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                garden_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                species_id INTEGER NOT NULL,
                substrate_id INTEGER NOT NULL,
                pot_volume_l REAL NOT NULL,
                pot_diameter_cm REAL NOT NULL,
                pot_shape TEXT NOT NULL,
                pot_width_cm REAL,
                pot_material TEXT NOT NULL,
                pot_color TEXT NOT NULL,
                location TEXT NOT NULL,
                sun_exposure TEXT NOT NULL,
                active_depth_fraction REAL NOT NULL,
                rainfall_exposure REAL NOT NULL,
                saucer_capacity_mm REAL,
                saucer_capillary_rate REAL,
                saucer_evap_coef REAL,
                planting_date TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("INSERT INTO schema_metadata (version) VALUES (1)")
        conn.commit()

        # Adesso simuliamo l'apertura dello stesso database via
        # GardenPersistence (versione 2). La migrazione deve applicarsi.
        # Per farlo creiamo un GardenPersistence appoggiato su questa
        # connessione esistente.
        # Non possiamo riusare la stessa connessione perché :memory:
        # è isolato per connessione. Usiamo un file temporaneo invece.
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # Costruisci v1 sul file
            conn2 = sqlite3.connect(tmp_path)
            conn2.execute("PRAGMA foreign_keys = ON")
            conn2.execute("""
                CREATE TABLE schema_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL
                )
            """)
            conn2.execute("""
                CREATE TABLE pots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL
                )
            """)
            conn2.execute("INSERT INTO schema_metadata (version) VALUES (1)")
            conn2.commit()
            conn2.close()

            # Ora apri con GardenPersistence v2: deve migrare.
            with GardenPersistence(tmp_path) as p:
                cursor = p._conn.execute(
                    "SELECT version FROM schema_metadata "
                    "ORDER BY id DESC LIMIT 1"
                )
                self.assertEqual(cursor.fetchone()["version"], 3)
                # E la colonna channel_id esiste:
                cursor = p._conn.execute("PRAGMA table_info(pots)")
                cols = [r["name"] for r in cursor.fetchall()]
                self.assertIn("channel_id", cols)
        finally:
            os.unlink(tmp_path)


# =======================================================================
#  Famiglia 8: persistenza degli eventi pianificati (sotto-tappa D)
# =======================================================================

class TestScheduledEventsPersistence(unittest.TestCase):
    """Persistenza SQLite degli eventi pianificati e migrazione v2→v3."""

    def setUp(self):
        self.persistence = GardenPersistence(":memory:")
        self.persistence.register_species(_make_basil())
        self.persistence.register_substrate(_make_universal_substrate())

    def tearDown(self):
        self.persistence.close()

    def test_schema_version_is_3(self):
        cursor = self.persistence._conn.execute(
            "SELECT version FROM schema_metadata "
            "ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(cursor.fetchone()["version"], 3)

    def test_round_trip_with_scheduled_events(self):
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.add_scheduled_event(ScheduledEvent(
            event_id="fert-001", pot_label="basilico-1",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18),
            payload={"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2},
        ))
        garden.add_scheduled_event(ScheduledEvent(
            event_id="treat-001", pot_label="basilico-1",
            event_type="treatment",
            scheduled_date=date(2026, 5, 25),
            payload={"product": "antifungino"},
        ))

        self.persistence.save_garden(garden)
        loaded = self.persistence.load_garden("balcone")

        events = loaded.scheduled_events
        self.assertEqual(len(events), 2)
        # Ordinati per scheduled_date.
        self.assertEqual(events[0].event_id, "fert-001")
        self.assertEqual(events[1].event_id, "treat-001")
        # Payload completo preservato.
        self.assertEqual(
            events[0].payload,
            {"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2},
        )

    def test_resave_synchronizes_events(self):
        # Salvataggio iniziale con due eventi.
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.add_scheduled_event(ScheduledEvent(
            event_id="e1", pot_label="basilico-1",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18), payload={},
        ))
        garden.add_scheduled_event(ScheduledEvent(
            event_id="e2", pot_label="basilico-1",
            event_type="treatment",
            scheduled_date=date(2026, 5, 25), payload={},
        ))
        self.persistence.save_garden(garden)

        # Cancella e2, aggiungi e3, risalva.
        garden.cancel_scheduled_event("basilico-1", "e2")
        garden.add_scheduled_event(ScheduledEvent(
            event_id="e3", pot_label="basilico-1",
            event_type="leaching",
            scheduled_date=date(2026, 6, 1), payload={},
        ))
        self.persistence.save_garden(garden)

        # Il database riflette il nuovo stato.
        loaded = self.persistence.load_garden("balcone")
        ids = [e.event_id for e in loaded.scheduled_events]
        self.assertEqual(set(ids), {"e1", "e3"})

    def test_query_scheduled_events_with_filters(self):
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.add_pot(_make_basic_pot("basilico-2"))
        for i, day in enumerate([15, 20, 25]):
            garden.add_scheduled_event(ScheduledEvent(
                event_id=f"e{i}", pot_label="basilico-1",
                event_type="fertigation",
                scheduled_date=date(2026, 5, day), payload={},
            ))
        garden.add_scheduled_event(ScheduledEvent(
            event_id="e-b2", pot_label="basilico-2",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18), payload={},
        ))
        self.persistence.save_garden(garden)

        # Filtro per pot_label.
        b1_events = self.persistence.query_scheduled_events(
            "balcone", pot_label="basilico-1",
        )
        self.assertEqual(len(b1_events), 3)
        # Filtro per range di date.
        in_range = self.persistence.query_scheduled_events(
            "balcone", since=date(2026, 5, 17), until=date(2026, 5, 22),
        )
        # In range: e1 (20), e-b2 (18). Non e0 (15) né e2 (25).
        ids = [e.event_id for e in in_range]
        self.assertEqual(set(ids), {"e1", "e-b2"})

    def test_delete_garden_cascades_to_scheduled_events(self):
        garden = Garden(name="balcone")
        garden.add_pot(_make_basic_pot("basilico-1"))
        garden.add_scheduled_event(ScheduledEvent(
            event_id="e1", pot_label="basilico-1",
            event_type="fertigation",
            scheduled_date=date(2026, 5, 18), payload={},
        ))
        self.persistence.save_garden(garden)
        self.persistence.delete_garden("balcone")

        # Tabella scheduled_events svuotata dalla cascata
        cursor = self.persistence._conn.execute(
            "SELECT COUNT(*) AS c FROM scheduled_events"
        )
        self.assertEqual(cursor.fetchone()["c"], 0)

    def test_v2_database_migrates_to_v3_automatically(self):
        # Crea un database v2 a mano e verifica che venga migrato.
        import sqlite3, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            conn = sqlite3.connect(tmp_path)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("""
                CREATE TABLE schema_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL
                )
            """)
            conn.execute("INSERT INTO schema_metadata (version) VALUES (2)")
            conn.commit()
            conn.close()

            # Apri con il codice v3: deve creare scheduled_events.
            with GardenPersistence(tmp_path) as p:
                cursor = p._conn.execute(
                    "SELECT version FROM schema_metadata "
                    "ORDER BY id DESC LIMIT 1"
                )
                self.assertEqual(cursor.fetchone()["version"], 3)
                # La tabella scheduled_events esiste.
                cursor = p._conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='scheduled_events'"
                )
                self.assertIsNotNone(cursor.fetchone())
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
