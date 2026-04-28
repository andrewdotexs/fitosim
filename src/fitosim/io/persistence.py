"""
Persistenza SQLite per Garden, Pot e tutto il loro contesto.

Il modulo introduce nella sotto-tappa B della tappa 4 della fascia 2
il layer di persistenza che permette di salvare e ricaricare l'intero
stato di un giardino — compreso il catalogo delle specie e dei
substrati — in un database SQLite. È il pezzo che trasforma fitosim
da "libreria che vive in RAM durante una sessione Python" a "sistema
operativo persistente" per il dashboard "Il Mio Giardino".

Filosofia
---------

Il `GardenPersistence` è un layer **separato e opzionale**: il
Garden in-memory della sotto-tappa A continua a funzionare
identicamente senza dipendere da SQLite, e chi vuole la persistenza
la attiva esplicitamente importando questo modulo. Niente magia di
autosave nascosta dentro al Garden. Il chiamante crea un
`GardenPersistence` puntandolo a un file SQLite (o a `:memory:` per
i test), e poi usa la sua API esplicita.

Schema del database
-------------------

Otto tabelle, organizzate in tre famiglie funzionali.

**Famiglia di metadata** (1 tabella):

  - ``schema_metadata`` : versione corrente dello schema, per le
    migrazioni future. Una sola riga.

**Famiglia del catalogo** (4 tabelle): definizioni semanticamente
indipendenti dai giardini, condivise tra tutti.

  - ``species``               : catalogo delle specie disponibili.
  - ``base_materials``        : materiali puri (pomice, lapillo, ecc.)
                                che possono entrare in misture.
  - ``substrates``            : catalogo dei substrati (sia "puri"
                                sia "misture").
  - ``substrate_components``  : ricette delle misture, una riga per
                                ogni componente di ogni mistura.

**Famiglia dei giardini** (4 tabelle): stato dei giardini operativi.

  - ``gardens``     : identità dei giardini.
  - ``pots``        : vasi statici (geometria, posizionamento, riferi-
                      menti a specie e substrato).
  - ``pot_states``  : storia degli stati mutabili dei vasi (snapshot
                      con timestamp).
  - ``events``      : storia degli eventi (fertirrigazioni, piogge,
                      letture sensore, lavaggi).

Convenzioni schema
------------------

Per coerenza e leggibilità tutte le tabelle seguono queste
convenzioni:

  * Ogni tabella ha una primary key sintetica chiamata ``id``,
    intero auto-incrementante.
  * Le foreign key tra tabelle hanno lo stesso nome del campo
    referenziato preceduto dal nome della tabella (es. ``garden_id``
    nella tabella ``pots`` referenzia ``gardens.id``).
  * I vincoli di unicità semantica sono espressi come constraint
    UNIQUE separati (es. ``UNIQUE(garden_id, label)`` nella tabella
    ``pots``).
  * Le foreign key sono sempre con ON DELETE CASCADE per garantire
    integrità referenziale: cancellando un giardino vengono
    cancellati i suoi vasi, i loro stati e i loro eventi.

Sotto-tappa B fase 1
--------------------

Questa è la fase 1 della sotto-tappa B: solo persistenza SQLite.
La fase 2 (export/import JSON) vive in un modulo separato
``io/serialization.py`` e non si conosce con questo modulo.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot, PotMaterial, PotColor, PotShape, SunExposure
from fitosim.domain.scheduling import ScheduledEvent
from fitosim.domain.species import Species
from fitosim.science.substrate import (
    BaseMaterial,
    MixComponent,
    Substrate,
    compose_substrate,
)


# Versione corrente dello schema. Quando in futuro lo schema evolverà
# (per esempio quando aggiungeremo gli eventi pianificati nella sotto-
# tappa D), incrementeremo questo numero e aggiungeremo una funzione
# `_migrate_v1_to_v2()` che applica le modifiche al database esistente.
#
# Versione 2 (sotto-tappa C tappa 4): aggiunto il campo channel_id
# nullable alla tabella pots per la mappa label → channel_id del
# gateway hardware. Database alla versione 1 vengono migrati
# automaticamente con un ALTER TABLE.
#
# Versione 3 (sotto-tappa D tappa 4): aggiunta la tabella
# scheduled_events per persistere gli eventi pianificati del Garden.
# Database alla versione 2 vengono migrati automaticamente creando
# la nuova tabella vuota.
SCHEMA_VERSION = 3


# =======================================================================
#  Schema SQL
# =======================================================================

# Lo schema è organizzato come una lista di statement DDL. Vengono
# eseguiti in sequenza nell'ordine giusto perché alcune tabelle
# referenziano altre via foreign key.
SCHEMA_STATEMENTS: List[str] = [
    # ----- Metadata dello schema -----
    """
    CREATE TABLE IF NOT EXISTS schema_metadata (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        version      INTEGER NOT NULL
    )
    """,

    # ----- Catalogo delle specie -----
    """
    CREATE TABLE IF NOT EXISTS species (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        name                     TEXT NOT NULL UNIQUE,
        scientific_name          TEXT NOT NULL,
        kc_initial               REAL NOT NULL,
        kc_mid                   REAL NOT NULL,
        kc_late                  REAL NOT NULL,
        kcb_initial              REAL,
        kcb_mid                  REAL,
        kcb_late                 REAL,
        initial_stage_days       INTEGER NOT NULL,
        mid_stage_days           INTEGER NOT NULL,
        ec_optimal_min_mscm      REAL,
        ec_optimal_max_mscm      REAL,
        ph_optimal_min           REAL,
        ph_optimal_max           REAL
    )
    """,

    # ----- Catalogo dei materiali base -----
    """
    CREATE TABLE IF NOT EXISTS base_materials (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL UNIQUE,
        theta_fc     REAL NOT NULL,
        theta_pwp    REAL NOT NULL,
        description  TEXT NOT NULL DEFAULT ''
    )
    """,

    # ----- Catalogo dei substrati -----
    # Per i substrati puri (is_mixture=0) i campi theta_fc/theta_pwp
    # sono i valori autoritari del substrato.
    # Per le misture (is_mixture=1) i campi theta_fc/theta_pwp sono
    # ridondanti: vengono ricalcolati da `compose_substrate(components)`
    # al momento del load_garden, in modo che eventuali aggiornamenti
    # ai parametri dei materiali base si propaghino automaticamente
    # alle misture che li usano.
    """
    CREATE TABLE IF NOT EXISTS substrates (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        name                TEXT NOT NULL UNIQUE,
        theta_fc            REAL NOT NULL,
        theta_pwp           REAL NOT NULL,
        description         TEXT NOT NULL DEFAULT '',
        rew_mm              REAL,
        tew_mm              REAL,
        cec_meq_per_100g    REAL,
        ph_typical          REAL,
        is_mixture          INTEGER NOT NULL DEFAULT 0
    )
    """,

    # ----- Componenti delle misture -----
    """
    CREATE TABLE IF NOT EXISTS substrate_components (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        substrate_id        INTEGER NOT NULL,
        base_material_id    INTEGER NOT NULL,
        fraction            REAL NOT NULL,
        FOREIGN KEY (substrate_id) REFERENCES substrates(id)
            ON DELETE CASCADE,
        FOREIGN KEY (base_material_id) REFERENCES base_materials(id)
            ON DELETE RESTRICT
    )
    """,

    # ----- Giardini -----
    """
    CREATE TABLE IF NOT EXISTS gardens (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        name                     TEXT NOT NULL UNIQUE,
        location_description     TEXT NOT NULL DEFAULT ''
    )
    """,

    # ----- Vasi -----
    """
    CREATE TABLE IF NOT EXISTS pots (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        garden_id                INTEGER NOT NULL,
        label                    TEXT NOT NULL,
        species_id               INTEGER NOT NULL,
        substrate_id             INTEGER NOT NULL,
        pot_volume_l             REAL NOT NULL,
        pot_diameter_cm          REAL NOT NULL,
        pot_shape                TEXT NOT NULL,
        pot_width_cm             REAL,
        pot_material             TEXT NOT NULL,
        pot_color                TEXT NOT NULL,
        location                 TEXT NOT NULL,
        sun_exposure             TEXT NOT NULL,
        active_depth_fraction    REAL NOT NULL,
        rainfall_exposure        REAL NOT NULL,
        saucer_capacity_mm       REAL,
        saucer_capillary_rate    REAL,
        saucer_evap_coef         REAL,
        planting_date            TEXT NOT NULL,
        notes                    TEXT NOT NULL DEFAULT '',
        channel_id               TEXT,
        UNIQUE (garden_id, label),
        FOREIGN KEY (garden_id) REFERENCES gardens(id) ON DELETE CASCADE,
        FOREIGN KEY (species_id) REFERENCES species(id) ON DELETE RESTRICT,
        FOREIGN KEY (substrate_id) REFERENCES substrates(id)
            ON DELETE RESTRICT
    )
    """,

    # ----- Snapshot degli stati mutabili dei vasi -----
    """
    CREATE TABLE IF NOT EXISTS pot_states (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        pot_id            INTEGER NOT NULL,
        timestamp         TEXT NOT NULL,
        state_mm          REAL NOT NULL,
        salt_mass_meq     REAL NOT NULL,
        ph_substrate      REAL NOT NULL,
        saucer_state_mm   REAL NOT NULL,
        de_mm             REAL NOT NULL,
        UNIQUE (pot_id, timestamp),
        FOREIGN KEY (pot_id) REFERENCES pots(id) ON DELETE CASCADE
    )
    """,

    # ----- Storia degli eventi -----
    # payload_json contiene tutti i parametri dell'evento serializzati
    # come JSON. Permette di evolvere lo schema degli eventi senza
    # modificare la tabella: aggiungere un nuovo tipo di evento è
    # gratis dal punto di vista DDL.
    """
    CREATE TABLE IF NOT EXISTS events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        pot_id        INTEGER NOT NULL,
        timestamp     TEXT NOT NULL,
        event_type    TEXT NOT NULL,
        payload_json  TEXT NOT NULL,
        FOREIGN KEY (pot_id) REFERENCES pots(id) ON DELETE CASCADE
    )
    """,

    # ----- Eventi pianificati (sotto-tappa D) -----
    # Sono il "piano del giardiniere": cosa farò nei prossimi giorni.
    # Da non confondere con events (sopra) che è la storia di cosa è
    # avvenuto. Quando il giardiniere fa effettivamente l'azione,
    # cancella l'evento da scheduled_events e ne registra uno
    # corrispondente in events.
    """
    CREATE TABLE IF NOT EXISTS scheduled_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        pot_id          INTEGER NOT NULL,
        event_id        TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        scheduled_date  TEXT NOT NULL,
        payload_json    TEXT NOT NULL,
        UNIQUE (pot_id, event_id),
        FOREIGN KEY (pot_id) REFERENCES pots(id) ON DELETE CASCADE
    )
    """,

    # ----- Indici per le query più frequenti -----
    "CREATE INDEX IF NOT EXISTS idx_pot_states_pot_timestamp "
    "ON pot_states(pot_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_pot_timestamp "
    "ON events(pot_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_type "
    "ON events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_scheduled_events_pot_date "
    "ON scheduled_events(pot_id, scheduled_date)",
]


# =======================================================================
#  Dataclass di supporto
# =======================================================================

@dataclass(frozen=True)
class PotStateSnapshot:
    """
    Singolo snapshot dello stato mutabile di un vaso, con il timestamp
    al quale lo stato è stato registrato.

    È il tipo di ritorno di `query_states`: una sequenza di questi
    snapshot rappresenta la storia di un vaso nel tempo, utile per
    produrre grafici di evoluzione nel dashboard.
    """

    timestamp: datetime
    state_mm: float
    salt_mass_meq: float
    ph_substrate: float
    saucer_state_mm: float
    de_mm: float


# =======================================================================
#  Eccezioni canoniche
# =======================================================================

class PersistenceError(Exception):
    """Errore generico di persistenza."""


class SchemaVersionMismatch(PersistenceError):
    """
    Il database è stato creato da una versione futura di fitosim, e il
    codice corrente non sa come gestirlo. Il chiamante deve aggiornare
    il codice o usare un database diverso.
    """


class CatalogMissingError(PersistenceError):
    """
    Tentativo di salvare un giardino che usa una specie o un substrato
    non registrato nel catalogo del database. Il chiamante deve prima
    chiamare `register_species` o `register_substrate`.
    """


# =======================================================================
#  GardenPersistence
# =======================================================================

class GardenPersistence:
    """
    Layer di persistenza SQLite per Garden, Pot, specie e substrati.

    Esempio di utilizzo
    -------------------
    ::

        from fitosim.io.persistence import GardenPersistence

        # Apri (o crea) un database
        persistence = GardenPersistence("/var/lib/fitosim/garden.db")

        # Registra il catalogo
        persistence.register_species(BASIL)
        persistence.register_substrate(UNIVERSAL_POTTING_SOIL)

        # Salva un giardino
        persistence.save_garden(my_garden)

        # In una sessione successiva, ricarica
        garden = persistence.load_garden("balcone-milano")

        # Chiudi la connessione (opzionale, viene fatto al __del__)
        persistence.close()

    Tutte le operazioni di scrittura sono in transazione: se qualcosa
    fallisce a metà strada, il database resta nello stato precedente.

    Uso con context manager
    -----------------------
    Per garantire chiusura pulita anche in caso di eccezione::

        with GardenPersistence("garden.db") as persistence:
            persistence.save_garden(my_garden)
        # connessione chiusa automaticamente
    """

    def __init__(self, db_path: str) -> None:
        """
        Apre (o crea) un database SQLite al percorso indicato.

        Per i test si può usare il valore speciale ``":memory:"`` che
        crea un database in memoria che viene distrutto alla chiusura
        della connessione.

        Parametri
        ---------
        db_path : str
            Percorso del file SQLite, o ``":memory:"`` per database
            in-memory. Se il file non esiste, viene creato e lo schema
            viene inizializzato. Se esiste, viene aperto e la versione
            dello schema viene verificata.

        Solleva
        -------
        SchemaVersionMismatch
            Se il database esistente è di una versione superiore a
            quella che il codice corrente sa gestire.
        """
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        # Per garantire integrità referenziale (le FK devono essere
        # esplicitamente abilitate in SQLite per ogni connessione).
        self._conn.execute("PRAGMA foreign_keys = ON")
        # Per accedere alle righe con sintassi a dizionario (riga[colonna])
        # invece che con indici numerici, più leggibile.
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    # ----- Lifecycle -----

    def close(self) -> None:
        """Chiude la connessione al database."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "GardenPersistence":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        # Cleanup di sicurezza: se il chiamante dimentica di chiudere
        # esplicitamente, lo facciamo noi al GC.
        if getattr(self, "_conn", None) is not None:
            try:
                self._conn.close()
            except Exception:
                pass

    # ----- Inizializzazione e versioning dello schema -----

    def _initialize_schema(self) -> None:
        """
        Inizializza lo schema se il database è nuovo, oppure verifica
        la versione se il database esiste già.

        L'inizializzazione applica tutti gli statement DDL e inserisce
        la versione corrente nella tabella schema_metadata.
        """
        # Controllo se il database è "vergine": se la tabella
        # schema_metadata non esiste, lo è.
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_metadata'"
        )
        is_new = cursor.fetchone() is None

        if is_new:
            # Database nuovo: applica tutto lo schema.
            with self._conn:
                for stmt in SCHEMA_STATEMENTS:
                    self._conn.execute(stmt)
                self._conn.execute(
                    "INSERT INTO schema_metadata (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
        else:
            # Database esistente: verifica versione.
            cursor = self._conn.execute(
                "SELECT version FROM schema_metadata "
                "ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row is None:
                # Tabella schema_metadata esiste ma è vuota: situazione
                # patologica, trattiamola come database nuovo.
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO schema_metadata (version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
            elif row["version"] > SCHEMA_VERSION:
                raise SchemaVersionMismatch(
                    f"Il database è alla versione {row['version']} "
                    f"ma il codice supporta solo fino alla versione "
                    f"{SCHEMA_VERSION}. Aggiorna fitosim per leggerlo."
                )
            elif row["version"] < SCHEMA_VERSION:
                # Database più vecchio del codice: applica migrazioni.
                self._apply_migrations(from_version=row["version"])

    def _apply_migrations(self, from_version: int) -> None:
        """
        Applica le migrazioni dello schema dal version corrente fino
        a SCHEMA_VERSION.

        Le migrazioni sono cumulative: applichiamo in ordine
        v1→v2, v2→v3, etc., fino a raggiungere la versione corrente
        del codice.
        """
        with self._conn:
            current = from_version
            if current < 2:
                self._migrate_v1_to_v2()
                current = 2
            if current < 3:
                self._migrate_v2_to_v3()
                current = 3
            # In futuro:
            # if current < 4:
            #     self._migrate_v3_to_v4()
            #     current = 4
            # Aggiorna la versione registrata.
            self._conn.execute(
                "INSERT INTO schema_metadata (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def _migrate_v1_to_v2(self) -> None:
        """
        Migrazione dalla versione 1 alla versione 2.

        Cambiamento: aggiunto campo channel_id nullable alla tabella
        pots per la mappa label → channel_id del gateway hardware.

        Database alla versione 1 vengono aggiornati senza perdita di
        dati: tutti i vasi esistenti avranno channel_id NULL (cioè
        "non mappato"), comportamento equivalente a quello pre-migrazione.
        """
        self._conn.execute(
            "ALTER TABLE pots ADD COLUMN channel_id TEXT"
        )

    def _migrate_v2_to_v3(self) -> None:
        """
        Migrazione dalla versione 2 alla versione 3.

        Cambiamento: aggiunta tabella scheduled_events per gli eventi
        pianificati introdotti dalla sotto-tappa D.

        Database alla versione 2 vengono aggiornati senza perdita di
        dati: la tabella scheduled_events viene creata vuota, i
        giardini esistenti non hanno eventi pianificati pre-esistenti.
        """
        self._conn.execute("""
            CREATE TABLE scheduled_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pot_id          INTEGER NOT NULL,
                event_id        TEXT NOT NULL,
                event_type      TEXT NOT NULL,
                scheduled_date  TEXT NOT NULL,
                payload_json    TEXT NOT NULL,
                UNIQUE (pot_id, event_id),
                FOREIGN KEY (pot_id) REFERENCES pots(id) ON DELETE CASCADE
            )
        """)
        self._conn.execute(
            "CREATE INDEX idx_scheduled_events_pot_date "
            "ON scheduled_events(pot_id, scheduled_date)"
        )

    # ====================================================================
    #  Catalogo: specie
    # ====================================================================

    def register_species(self, species: Species) -> int:
        """
        Registra una specie nel catalogo, o aggiorna i suoi parametri
        se già esiste.

        Comportamento idempotente: chiamare register_species più volte
        con la stessa specie aggiorna silenziosamente i parametri
        all'ultimo valore. Il chiamante può anche chiamare la
        funzione su una specie già registrata per aggiornare i suoi
        parametri (per esempio dopo aver calibrato i Kc sui dati reali
        del balcone).

        Parametri
        ---------
        species : Species
            La specie da registrare.

        Ritorna
        -------
        int
            L'id della specie nel database.
        """
        with self._conn:
            cursor = self._conn.execute(
                "SELECT id FROM species WHERE name = ?", (species.common_name,),
            )
            existing = cursor.fetchone()
            if existing:
                self._conn.execute(
                    """
                    UPDATE species SET
                        scientific_name = ?,
                        kc_initial = ?, kc_mid = ?, kc_late = ?,
                        kcb_initial = ?, kcb_mid = ?, kcb_late = ?,
                        initial_stage_days = ?, mid_stage_days = ?,
                        ec_optimal_min_mscm = ?, ec_optimal_max_mscm = ?,
                        ph_optimal_min = ?, ph_optimal_max = ?
                    WHERE id = ?
                    """,
                    (
                        species.scientific_name,
                        species.kc_initial, species.kc_mid, species.kc_late,
                        species.kcb_initial, species.kcb_mid, species.kcb_late,
                        species.initial_stage_days, species.mid_stage_days,
                        species.ec_optimal_min_mscm,
                        species.ec_optimal_max_mscm,
                        species.ph_optimal_min, species.ph_optimal_max,
                        existing["id"],
                    ),
                )
                return existing["id"]

            cursor = self._conn.execute(
                """
                INSERT INTO species (
                    name, scientific_name,
                    kc_initial, kc_mid, kc_late,
                    kcb_initial, kcb_mid, kcb_late,
                    initial_stage_days, mid_stage_days,
                    ec_optimal_min_mscm, ec_optimal_max_mscm,
                    ph_optimal_min, ph_optimal_max
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    species.common_name, species.scientific_name,
                    species.kc_initial, species.kc_mid, species.kc_late,
                    species.kcb_initial, species.kcb_mid, species.kcb_late,
                    species.initial_stage_days, species.mid_stage_days,
                    species.ec_optimal_min_mscm, species.ec_optimal_max_mscm,
                    species.ph_optimal_min, species.ph_optimal_max,
                ),
            )
            return cursor.lastrowid

    def get_species(self, name: str) -> Species:
        """Recupera una specie per nome. Solleva KeyError se non esiste."""
        cursor = self._conn.execute(
            "SELECT * FROM species WHERE name = ?", (name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(
                f"Specie '{name}' non registrata nel catalogo. "
                f"Usa register_species() prima di referenziarla."
            )
        return self._row_to_species(row)

    def is_species_registered(self, name: str) -> bool:
        """Test non-eccezionale di esistenza di una specie nel catalogo."""
        cursor = self._conn.execute(
            "SELECT 1 FROM species WHERE name = ?", (name,),
        )
        return cursor.fetchone() is not None

    def list_species(self) -> List[Species]:
        """Ritorna tutte le specie registrate, ordinate per nome."""
        cursor = self._conn.execute(
            "SELECT * FROM species ORDER BY name"
        )
        return [self._row_to_species(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_species(row: sqlite3.Row) -> Species:
        return Species(
            common_name=row["name"],
            scientific_name=row["scientific_name"],
            kc_initial=row["kc_initial"],
            kc_mid=row["kc_mid"],
            kc_late=row["kc_late"],
            kcb_initial=row["kcb_initial"],
            kcb_mid=row["kcb_mid"],
            kcb_late=row["kcb_late"],
            initial_stage_days=row["initial_stage_days"],
            mid_stage_days=row["mid_stage_days"],
            ec_optimal_min_mscm=row["ec_optimal_min_mscm"],
            ec_optimal_max_mscm=row["ec_optimal_max_mscm"],
            ph_optimal_min=row["ph_optimal_min"],
            ph_optimal_max=row["ph_optimal_max"],
        )

    # ====================================================================
    #  Catalogo: materiali base
    # ====================================================================

    def register_base_material(self, material: BaseMaterial) -> int:
        """Registra un materiale base, o aggiorna se già esiste."""
        with self._conn:
            cursor = self._conn.execute(
                "SELECT id FROM base_materials WHERE name = ?",
                (material.name,),
            )
            existing = cursor.fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE base_materials SET theta_fc = ?, theta_pwp = ?, "
                    "description = ? WHERE id = ?",
                    (
                        material.theta_fc, material.theta_pwp,
                        material.description, existing["id"],
                    ),
                )
                return existing["id"]
            cursor = self._conn.execute(
                "INSERT INTO base_materials (name, theta_fc, theta_pwp, "
                "description) VALUES (?, ?, ?, ?)",
                (material.name, material.theta_fc, material.theta_pwp,
                 material.description),
            )
            return cursor.lastrowid

    def get_base_material(self, name: str) -> BaseMaterial:
        cursor = self._conn.execute(
            "SELECT * FROM base_materials WHERE name = ?", (name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(
                f"Materiale base '{name}' non registrato nel catalogo."
            )
        return BaseMaterial(
            name=row["name"], theta_fc=row["theta_fc"],
            theta_pwp=row["theta_pwp"], description=row["description"],
        )

    def is_base_material_registered(self, name: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM base_materials WHERE name = ?", (name,),
        )
        return cursor.fetchone() is not None

    # ====================================================================
    #  Catalogo: substrati (puri e misture)
    # ====================================================================

    def register_substrate(
        self,
        substrate: Substrate,
        components: Optional[List[MixComponent]] = None,
    ) -> int:
        """
        Registra un substrato nel catalogo, o aggiorna se già esiste.

        Se ``components`` è ``None`` il substrato viene salvato come
        "puro" (is_mixture=0) con i parametri direttamente preservati.
        Se ``components`` è una lista di MixComponent il substrato viene
        salvato come "mistura" (is_mixture=1) e la sua ricetta viene
        salvata nella tabella ``substrate_components``. I materiali
        base referenziati devono essere già stati registrati.

        Comportamento idempotente: chiamare register_substrate più volte
        con lo stesso nome aggiorna i parametri (e la ricetta, per le
        misture) silenziosamente.

        Parametri
        ---------
        substrate : Substrate
            Il substrato da registrare.
        components : List[MixComponent], opzionale
            La ricetta del substrato come mistura. Se None, il
            substrato viene salvato come "puro".

        Ritorna
        -------
        int
            L'id del substrato nel database.

        Solleva
        -------
        CatalogMissingError
            Se la mistura referenzia un materiale base non registrato.
        """
        is_mixture = components is not None

        with self._conn:
            cursor = self._conn.execute(
                "SELECT id FROM substrates WHERE name = ?",
                (substrate.name,),
            )
            existing = cursor.fetchone()

            if existing:
                substrate_id = existing["id"]
                self._conn.execute(
                    """
                    UPDATE substrates SET
                        theta_fc = ?, theta_pwp = ?, description = ?,
                        rew_mm = ?, tew_mm = ?,
                        cec_meq_per_100g = ?, ph_typical = ?,
                        is_mixture = ?
                    WHERE id = ?
                    """,
                    (
                        substrate.theta_fc, substrate.theta_pwp,
                        substrate.description,
                        substrate.rew_mm, substrate.tew_mm,
                        substrate.cec_meq_per_100g, substrate.ph_typical,
                        1 if is_mixture else 0,
                        substrate_id,
                    ),
                )
                # Se è una mistura, ricostruisci la ricetta:
                # cancelliamo i vecchi componenti e inseriamo i nuovi.
                self._conn.execute(
                    "DELETE FROM substrate_components WHERE substrate_id = ?",
                    (substrate_id,),
                )
            else:
                cursor = self._conn.execute(
                    """
                    INSERT INTO substrates (
                        name, theta_fc, theta_pwp, description,
                        rew_mm, tew_mm, cec_meq_per_100g, ph_typical,
                        is_mixture
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        substrate.name, substrate.theta_fc,
                        substrate.theta_pwp, substrate.description,
                        substrate.rew_mm, substrate.tew_mm,
                        substrate.cec_meq_per_100g, substrate.ph_typical,
                        1 if is_mixture else 0,
                    ),
                )
                substrate_id = cursor.lastrowid

            # Per le misture, popola i componenti.
            if is_mixture:
                for component in components:
                    cursor = self._conn.execute(
                        "SELECT id FROM base_materials WHERE name = ?",
                        (component.material.name,),
                    )
                    bm_row = cursor.fetchone()
                    if bm_row is None:
                        raise CatalogMissingError(
                            f"Materiale base '{component.material.name}' "
                            f"referenziato dalla mistura '{substrate.name}' "
                            f"non è registrato nel catalogo. Chiama "
                            f"register_base_material() prima."
                        )
                    self._conn.execute(
                        "INSERT INTO substrate_components "
                        "(substrate_id, base_material_id, fraction) "
                        "VALUES (?, ?, ?)",
                        (substrate_id, bm_row["id"], component.fraction),
                    )

            return substrate_id

    def get_substrate(self, name: str) -> Substrate:
        """
        Recupera un substrato per nome.

        Per i substrati puri restituisce direttamente l'istanza con i
        parametri salvati. Per le misture **ricalcola** i parametri
        chiamando ``compose_substrate(components)`` al momento del
        caricamento, in modo che eventuali aggiornamenti ai parametri
        dei materiali base si propaghino automaticamente.
        """
        cursor = self._conn.execute(
            "SELECT * FROM substrates WHERE name = ?", (name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(
                f"Substrato '{name}' non registrato nel catalogo."
            )

        if not row["is_mixture"]:
            # Substrato puro: parametri direttamente dal database.
            return Substrate(
                name=row["name"],
                theta_fc=row["theta_fc"],
                theta_pwp=row["theta_pwp"],
                description=row["description"],
                rew_mm=row["rew_mm"], tew_mm=row["tew_mm"],
                cec_meq_per_100g=row["cec_meq_per_100g"],
                ph_typical=row["ph_typical"],
            )

        # Mistura: ricostruisci la ricetta e ricalcola i parametri.
        components = self._load_substrate_components(row["id"])
        # Componiamo il substrato con i parametri attuali dei materiali
        # base. I parametri chimici (CEC, ph_typical) e dual-Kc che
        # sono caratteristiche della mistura nel suo insieme vengono
        # trasferiti dal database al risultato.
        composed = compose_substrate(
            components=components,
            name=row["name"],
        )
        # compose_substrate calcola theta_fc/theta_pwp ma non i
        # parametri opzionali della mistura — li trasferisco a mano.
        return Substrate(
            name=composed.name,
            theta_fc=composed.theta_fc,
            theta_pwp=composed.theta_pwp,
            description=row["description"],
            rew_mm=row["rew_mm"], tew_mm=row["tew_mm"],
            cec_meq_per_100g=row["cec_meq_per_100g"],
            ph_typical=row["ph_typical"],
        )

    def _load_substrate_components(
        self, substrate_id: int,
    ) -> List[MixComponent]:
        """Carica i componenti di una mistura come lista di MixComponent."""
        cursor = self._conn.execute(
            """
            SELECT sc.fraction, bm.name AS bm_name,
                   bm.theta_fc AS bm_theta_fc,
                   bm.theta_pwp AS bm_theta_pwp,
                   bm.description AS bm_description
            FROM substrate_components sc
            JOIN base_materials bm ON bm.id = sc.base_material_id
            WHERE sc.substrate_id = ?
            ORDER BY sc.id
            """,
            (substrate_id,),
        )
        components = []
        for row in cursor.fetchall():
            material = BaseMaterial(
                name=row["bm_name"], theta_fc=row["bm_theta_fc"],
                theta_pwp=row["bm_theta_pwp"],
                description=row["bm_description"],
            )
            components.append(MixComponent(
                material=material, fraction=row["fraction"],
            ))
        return components

    def is_substrate_registered(self, name: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM substrates WHERE name = ?", (name,),
        )
        return cursor.fetchone() is not None

    # ====================================================================
    #  Garden: salvataggio
    # ====================================================================

    def save_garden(
        self,
        garden: Garden,
        snapshot_timestamp: Optional[datetime] = None,
    ) -> int:
        """
        Salva l'intero giardino con tutti i suoi vasi e uno snapshot
        del loro stato corrente.

        Comportamento per giardino esistente: aggiorna i metadati,
        sincronizza i vasi (aggiunge i nuovi, aggiorna gli esistenti,
        rimuove quelli non più presenti), e aggiunge un nuovo snapshot
        dello stato corrente alla tabella pot_states (preservando la
        storia degli snapshot precedenti).

        Tutte le specie e i substrati referenziati dai vasi devono
        essere già registrati nel catalogo. Se manca qualcosa, alza
        CatalogMissingError con un messaggio diagnostico.

        Parametri
        ---------
        garden : Garden
            Il giardino da salvare.
        snapshot_timestamp : datetime, opzionale
            Timestamp per lo snapshot dello stato dei vasi. Default:
            datetime.now(timezone.utc) al momento della chiamata.
            Va passato in UTC; se viene passato un datetime naive,
            viene assunto come UTC.

        Ritorna
        -------
        int
            L'id del giardino nel database.

        Solleva
        -------
        CatalogMissingError
            Se una specie o un substrato referenziato non è nel catalogo.
        """
        if snapshot_timestamp is None:
            snapshot_timestamp = datetime.now(timezone.utc)
        elif snapshot_timestamp.tzinfo is None:
            snapshot_timestamp = snapshot_timestamp.replace(
                tzinfo=timezone.utc,
            )

        # Pre-validazione: tutte le specie e i substrati referenziati
        # devono essere registrati. Lo controlliamo PRIMA di iniziare
        # la transazione per dare al chiamante un errore chiaro.
        for pot in garden:
            if not self.is_species_registered(pot.species.common_name):
                raise CatalogMissingError(
                    f"Vaso '{pot.label}' del giardino '{garden.name}' usa "
                    f"la specie '{pot.species.common_name}' che non è "
                    f"registrata nel catalogo. Chiama register_species() "
                    f"prima di salvare il giardino."
                )
            if not self.is_substrate_registered(pot.substrate.name):
                raise CatalogMissingError(
                    f"Vaso '{pot.label}' del giardino '{garden.name}' usa "
                    f"il substrato '{pot.substrate.name}' che non è "
                    f"registrato nel catalogo. Chiama register_substrate() "
                    f"prima di salvare il giardino."
                )

        with self._conn:
            # Insert o update del giardino.
            cursor = self._conn.execute(
                "SELECT id FROM gardens WHERE name = ?", (garden.name,),
            )
            existing = cursor.fetchone()
            if existing:
                garden_id = existing["id"]
                self._conn.execute(
                    "UPDATE gardens SET location_description = ? "
                    "WHERE id = ?",
                    (garden.location_description, garden_id),
                )
            else:
                cursor = self._conn.execute(
                    "INSERT INTO gardens (name, location_description) "
                    "VALUES (?, ?)",
                    (garden.name, garden.location_description),
                )
                garden_id = cursor.lastrowid

            # Sincronizzazione dei vasi: cancelliamo quelli che non sono
            # più nel giardino corrente. La cascata ON DELETE elimina
            # automaticamente i loro stati ed eventi.
            current_labels = set(garden.pot_labels)
            cursor = self._conn.execute(
                "SELECT id, label FROM pots WHERE garden_id = ?",
                (garden_id,),
            )
            for row in cursor.fetchall():
                if row["label"] not in current_labels:
                    self._conn.execute(
                        "DELETE FROM pots WHERE id = ?", (row["id"],),
                    )

            # Insert/update di ciascun vaso e snapshot del suo stato.
            for pot in garden:
                channel_id = garden.get_channel_id(pot.label)
                pot_id = self._save_pot(garden_id, pot, channel_id)
                self._save_pot_state(pot_id, pot, snapshot_timestamp)

            # Sincronizza gli eventi pianificati: cancella quelli che
            # non sono più nel piano e (re)inserisci quelli attuali.
            # È coerente con la sincronizzazione dei vasi: il database
            # rispecchia lo stato del Garden in-memory.
            self._sync_scheduled_events(garden_id, garden)

            return garden_id

    def _sync_scheduled_events(
        self, garden_id: int, garden: Garden,
    ) -> None:
        """
        Sincronizza gli eventi pianificati del database con quelli
        del Garden in-memory.

        Strategia: cancella tutti gli eventi attualmente nel database
        per i vasi del giardino, poi reinserisce quelli del Garden.
        Più semplice di un diff puntuale e coerente per piani di
        dimensioni tipiche del balcone (decine di eventi).
        """
        # Mappa label → pot_id per i vasi del giardino.
        pot_id_by_label: Dict[str, int] = {}
        cursor = self._conn.execute(
            "SELECT id, label FROM pots WHERE garden_id = ?",
            (garden_id,),
        )
        for row in cursor.fetchall():
            pot_id_by_label[row["label"]] = row["id"]

        # Cancella tutti gli eventi pianificati dei vasi del giardino.
        # ON DELETE CASCADE non si applica qui perché stiamo
        # cancellando da scheduled_events direttamente, non da pots.
        if pot_id_by_label:
            placeholders = ",".join("?" * len(pot_id_by_label))
            self._conn.execute(
                f"DELETE FROM scheduled_events WHERE pot_id IN "
                f"({placeholders})",
                tuple(pot_id_by_label.values()),
            )

        # Reinserisci gli eventi del Garden corrente.
        for event in garden.scheduled_events:
            if event.pot_label not in pot_id_by_label:
                # Evento orfano: il vaso non è più nel garden.
                # Non dovrebbe accadere perché add_scheduled_event
                # rifiuta gli orfani, ma per robustezza saltiamo.
                continue
            pot_id = pot_id_by_label[event.pot_label]
            self._conn.execute(
                """
                INSERT INTO scheduled_events (
                    pot_id, event_id, event_type, scheduled_date,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    pot_id, event.event_id, event.event_type,
                    event.scheduled_date.isoformat(),
                    json.dumps(event.payload),
                ),
            )

    def _save_pot(
        self, garden_id: int, pot: Pot,
        channel_id: Optional[str] = None,
    ) -> int:
        """
        Insert o update di un singolo vaso. Ritorna l'id del vaso.
        """
        # Risolve gli id del catalogo per le foreign key.
        species_id = self._conn.execute(
            "SELECT id FROM species WHERE name = ?",
            (pot.species.common_name,),
        ).fetchone()["id"]
        substrate_id = self._conn.execute(
            "SELECT id FROM substrates WHERE name = ?",
            (pot.substrate.name,),
        ).fetchone()["id"]

        # Cerca il vaso esistente nel giardino con questa label.
        existing = self._conn.execute(
            "SELECT id FROM pots WHERE garden_id = ? AND label = ?",
            (garden_id, pot.label),
        ).fetchone()

        params = (
            species_id, substrate_id,
            pot.pot_volume_l, pot.pot_diameter_cm,
            pot.pot_shape.value,
            pot.pot_width_cm,
            pot.pot_material.value, pot.pot_color.value,
            pot.location.value, pot.sun_exposure.value,
            pot.active_depth_fraction, pot.rainfall_exposure,
            pot.saucer_capacity_mm,
            pot.saucer_capillary_rate, pot.saucer_evap_coef,
            pot.planting_date.isoformat(),
            pot.notes,
            channel_id,
        )

        if existing:
            self._conn.execute(
                """
                UPDATE pots SET
                    species_id = ?, substrate_id = ?,
                    pot_volume_l = ?, pot_diameter_cm = ?,
                    pot_shape = ?, pot_width_cm = ?,
                    pot_material = ?, pot_color = ?,
                    location = ?, sun_exposure = ?,
                    active_depth_fraction = ?, rainfall_exposure = ?,
                    saucer_capacity_mm = ?,
                    saucer_capillary_rate = ?, saucer_evap_coef = ?,
                    planting_date = ?, notes = ?, channel_id = ?
                WHERE id = ?
                """,
                params + (existing["id"],),
            )
            return existing["id"]

        cursor = self._conn.execute(
            """
            INSERT INTO pots (
                garden_id, label,
                species_id, substrate_id,
                pot_volume_l, pot_diameter_cm,
                pot_shape, pot_width_cm,
                pot_material, pot_color,
                location, sun_exposure,
                active_depth_fraction, rainfall_exposure,
                saucer_capacity_mm, saucer_capillary_rate, saucer_evap_coef,
                planting_date, notes, channel_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (garden_id, pot.label) + params,
        )
        return cursor.lastrowid

    def _save_pot_state(
        self, pot_id: int, pot: Pot, timestamp: datetime,
    ) -> None:
        """Salva uno snapshot dello stato mutabile del vaso."""
        # INSERT OR REPLACE: se per questo (pot_id, timestamp) esiste già
        # uno snapshot, lo sovrascrive. Permette di salvare più volte
        # nello stesso istante senza errori.
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pot_states (
                pot_id, timestamp,
                state_mm, salt_mass_meq, ph_substrate,
                saucer_state_mm, de_mm
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pot_id, timestamp.isoformat(),
                pot.state_mm, pot.salt_mass_meq, pot.ph_substrate,
                pot.saucer_state_mm, pot.de_mm,
            ),
        )

    # ====================================================================
    #  Garden: caricamento
    # ====================================================================

    def load_garden(
        self,
        name: str,
        as_of: Optional[datetime] = None,
    ) -> Garden:
        """
        Ricarica un giardino dal database, ricostruendo i vasi col loro
        stato all'ultimo snapshot disponibile (o all'`as_of` specificato).

        Per ogni vaso del giardino, lo stato ricaricato è quello dello
        snapshot più recente con timestamp ≤ `as_of`. Se `as_of` è None
        viene usato l'ultimo snapshot in assoluto. Vasi senza snapshot
        nel range vengono ricaricati con i loro stati di default
        (state_mm=0, salt_mass_meq=0, etc.) — situazione patologica
        che indica un Garden appena creato senza save_garden ancora
        chiamato.

        Parametri
        ---------
        name : str
            Nome del giardino da caricare.
        as_of : datetime, opzionale
            Timestamp di riferimento per il caricamento. Default:
            None (ultimo snapshot disponibile).

        Ritorna
        -------
        Garden
            Il giardino ricostruito con tutti i suoi vasi.

        Solleva
        -------
        KeyError
            Se non esiste un giardino col nome specificato.
        """
        if as_of is not None and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)

        cursor = self._conn.execute(
            "SELECT * FROM gardens WHERE name = ?", (name,),
        )
        garden_row = cursor.fetchone()
        if garden_row is None:
            raise KeyError(
                f"Giardino '{name}' non trovato nel database. "
                f"Usa save_garden() per crearlo."
            )

        garden = Garden(
            name=garden_row["name"],
            location_description=garden_row["location_description"],
        )

        # Carica i vasi del giardino in ordine di inserimento (id).
        cursor = self._conn.execute(
            """
            SELECT p.*, s.name AS species_name, sub.name AS substrate_name
            FROM pots p
            JOIN species s ON s.id = p.species_id
            JOIN substrates sub ON sub.id = p.substrate_id
            WHERE p.garden_id = ?
            ORDER BY p.id
            """,
            (garden_row["id"],),
        )
        for pot_row in cursor.fetchall():
            pot = self._load_pot(pot_row, as_of)
            garden.add_pot(pot)
            # Se il vaso ha un channel_id salvato, ricostruisci la
            # mappatura nel garden.
            if pot_row["channel_id"] is not None:
                garden.set_channel_id(pot.label, pot_row["channel_id"])

        # Carica gli eventi pianificati per i vasi del giardino.
        cursor = self._conn.execute(
            """
            SELECT se.event_id, se.event_type, se.scheduled_date,
                   se.payload_json, p.label AS pot_label
            FROM scheduled_events se
            JOIN pots p ON p.id = se.pot_id
            WHERE p.garden_id = ?
            ORDER BY se.scheduled_date, p.label, se.event_id
            """,
            (garden_row["id"],),
        )
        for ev_row in cursor.fetchall():
            event = ScheduledEvent(
                event_id=ev_row["event_id"],
                pot_label=ev_row["pot_label"],
                event_type=ev_row["event_type"],
                scheduled_date=date.fromisoformat(ev_row["scheduled_date"]),
                payload=json.loads(ev_row["payload_json"]),
            )
            garden.add_scheduled_event(event)

        return garden

    def _load_pot(self, pot_row: sqlite3.Row, as_of: Optional[datetime]) -> Pot:
        """Ricostruisce un Pot da una riga della tabella pots e dal
        suo snapshot di stato più recente."""
        species = self.get_species(pot_row["species_name"])
        substrate = self.get_substrate(pot_row["substrate_name"])

        # Carica l'ultimo snapshot di stato disponibile (≤ as_of se
        # specificato).
        if as_of is not None:
            cursor = self._conn.execute(
                """
                SELECT * FROM pot_states
                WHERE pot_id = ? AND timestamp <= ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (pot_row["id"], as_of.isoformat()),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT * FROM pot_states
                WHERE pot_id = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (pot_row["id"],),
            )
        state_row = cursor.fetchone()

        # Costruisce il Pot. Se non c'è snapshot, gli state_* restano
        # ai loro default del costruttore.
        kwargs: Dict[str, Any] = dict(
            label=pot_row["label"],
            species=species,
            substrate=substrate,
            pot_volume_l=pot_row["pot_volume_l"],
            pot_diameter_cm=pot_row["pot_diameter_cm"],
            pot_shape=PotShape(pot_row["pot_shape"]),
            pot_material=PotMaterial(pot_row["pot_material"]),
            pot_color=PotColor(pot_row["pot_color"]),
            location=Location(pot_row["location"]),
            sun_exposure=SunExposure(pot_row["sun_exposure"]),
            active_depth_fraction=pot_row["active_depth_fraction"],
            rainfall_exposure=pot_row["rainfall_exposure"],
            planting_date=date.fromisoformat(pot_row["planting_date"]),
            notes=pot_row["notes"],
        )
        if pot_row["pot_width_cm"] is not None:
            kwargs["pot_width_cm"] = pot_row["pot_width_cm"]
        if pot_row["saucer_capacity_mm"] is not None:
            kwargs["saucer_capacity_mm"] = pot_row["saucer_capacity_mm"]
        if pot_row["saucer_capillary_rate"] is not None:
            kwargs["saucer_capillary_rate"] = pot_row["saucer_capillary_rate"]
        if pot_row["saucer_evap_coef"] is not None:
            kwargs["saucer_evap_coef"] = pot_row["saucer_evap_coef"]
        if state_row is not None:
            kwargs["state_mm"] = state_row["state_mm"]
            kwargs["salt_mass_meq"] = state_row["salt_mass_meq"]
            kwargs["ph_substrate"] = state_row["ph_substrate"]
            kwargs["saucer_state_mm"] = state_row["saucer_state_mm"]
            kwargs["de_mm"] = state_row["de_mm"]

        return Pot(**kwargs)

    # ====================================================================
    #  Garden: utility di query
    # ====================================================================

    def list_gardens(self) -> List[str]:
        """Ritorna i nomi di tutti i giardini salvati, ordinati."""
        cursor = self._conn.execute(
            "SELECT name FROM gardens ORDER BY name"
        )
        return [row["name"] for row in cursor.fetchall()]

    def garden_exists(self, name: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM gardens WHERE name = ?", (name,),
        )
        return cursor.fetchone() is not None

    def delete_garden(self, name: str) -> None:
        """Cancella un giardino e tutti i suoi vasi, stati ed eventi."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM gardens WHERE name = ?", (name,),
            )
            if cursor.rowcount == 0:
                raise KeyError(
                    f"Giardino '{name}' non trovato nel database."
                )

    def query_states(
        self,
        garden_name: str,
        pot_label: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[PotStateSnapshot]:
        """
        Ritorna la storia degli stati di un vaso in un range temporale.

        Utile per produrre grafici di evoluzione nel dashboard. I
        risultati sono ordinati per timestamp crescente.

        Parametri
        ---------
        garden_name : str
            Nome del giardino.
        pot_label : str
            Label del vaso.
        since : datetime, opzionale
            Timestamp inferiore inclusivo. Default: dall'inizio.
        until : datetime, opzionale
            Timestamp superiore inclusivo. Default: fino a ora.
        """
        # Risolve l'id del vaso.
        cursor = self._conn.execute(
            """
            SELECT p.id FROM pots p
            JOIN gardens g ON g.id = p.garden_id
            WHERE g.name = ? AND p.label = ?
            """,
            (garden_name, pot_label),
        )
        pot_row = cursor.fetchone()
        if pot_row is None:
            raise KeyError(
                f"Vaso '{pot_label}' nel giardino '{garden_name}' "
                f"non trovato."
            )

        sql = "SELECT * FROM pot_states WHERE pot_id = ?"
        params: list = [pot_row["id"]]
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            sql += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until is not None:
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            sql += " AND timestamp <= ?"
            params.append(until.isoformat())
        sql += " ORDER BY timestamp ASC"

        snapshots = []
        for row in self._conn.execute(sql, params).fetchall():
            snapshots.append(PotStateSnapshot(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                state_mm=row["state_mm"],
                salt_mass_meq=row["salt_mass_meq"],
                ph_substrate=row["ph_substrate"],
                saucer_state_mm=row["saucer_state_mm"],
                de_mm=row["de_mm"],
            ))
        return snapshots

    # ====================================================================
    #  Eventi
    # ====================================================================

    def record_event(
        self,
        garden_name: str,
        pot_label: str,
        event_type: str,
        timestamp: datetime,
        payload: Dict[str, Any],
    ) -> int:
        """
        Registra un evento storico per un vaso.

        Parametri
        ---------
        garden_name : str
            Nome del giardino.
        pot_label : str
            Label del vaso.
        event_type : str
            Tipo dell'evento (es. ``"fertigation"``, ``"rainfall"``,
            ``"sensor_reading"``, ``"leaching"``).
        timestamp : datetime
            Quando l'evento è avvenuto. Va passato in UTC.
        payload : dict
            Parametri dell'evento, serializzabili in JSON.

        Ritorna
        -------
        int
            L'id dell'evento nel database.
        """
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        with self._conn:
            cursor = self._conn.execute(
                """
                SELECT p.id FROM pots p
                JOIN gardens g ON g.id = p.garden_id
                WHERE g.name = ? AND p.label = ?
                """,
                (garden_name, pot_label),
            )
            pot_row = cursor.fetchone()
            if pot_row is None:
                raise KeyError(
                    f"Vaso '{pot_label}' nel giardino '{garden_name}' "
                    f"non trovato."
                )

            cursor = self._conn.execute(
                "INSERT INTO events (pot_id, timestamp, event_type, "
                "payload_json) VALUES (?, ?, ?, ?)",
                (
                    pot_row["id"], timestamp.isoformat(),
                    event_type, json.dumps(payload),
                ),
            )
            return cursor.lastrowid

    def query_events(
        self,
        garden_name: str,
        pot_label: str,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ritorna gli eventi storici di un vaso.

        Ogni elemento della lista è un dict con i campi:
        ``timestamp``, ``event_type``, ``payload`` (deserializzato dal
        JSON). I risultati sono ordinati per timestamp crescente.
        """
        cursor = self._conn.execute(
            """
            SELECT p.id FROM pots p
            JOIN gardens g ON g.id = p.garden_id
            WHERE g.name = ? AND p.label = ?
            """,
            (garden_name, pot_label),
        )
        pot_row = cursor.fetchone()
        if pot_row is None:
            raise KeyError(
                f"Vaso '{pot_label}' nel giardino '{garden_name}' "
                f"non trovato."
            )

        sql = "SELECT * FROM events WHERE pot_id = ?"
        params: list = [pot_row["id"]]
        if event_type is not None:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            sql += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until is not None:
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            sql += " AND timestamp <= ?"
            params.append(until.isoformat())
        sql += " ORDER BY timestamp ASC"

        events = []
        for row in self._conn.execute(sql, params).fetchall():
            events.append({
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
            })
        return events

    # ====================================================================
    #  Eventi pianificati
    # ====================================================================

    def query_scheduled_events(
        self,
        garden_name: str,
        pot_label: Optional[str] = None,
        since: Optional[date] = None,
        until: Optional[date] = None,
    ) -> List[ScheduledEvent]:
        """
        Ritorna gli eventi pianificati di un giardino, con filtri.

        Utile per il dashboard che vuole consultare il piano senza
        caricare l'intero Garden (per esempio per produrre la vista
        "calendario degli eventi del mese").

        Parametri
        ---------
        garden_name : str
            Nome del giardino.
        pot_label : str, opzionale
            Filtra per singolo vaso. Default: tutti i vasi del giardino.
        since, until : date, opzionali
            Range inclusivo di date. Default: nessun filtro temporale.

        Ritorna
        -------
        List[ScheduledEvent]
            Eventi ordinati per (scheduled_date, pot_label, event_id).

        Solleva
        -------
        KeyError
            Se il giardino non esiste.
        """
        # Verifica esistenza del giardino.
        cursor = self._conn.execute(
            "SELECT id FROM gardens WHERE name = ?", (garden_name,),
        )
        garden_row = cursor.fetchone()
        if garden_row is None:
            raise KeyError(
                f"Giardino '{garden_name}' non trovato nel database."
            )

        sql = """
            SELECT se.event_id, se.event_type, se.scheduled_date,
                   se.payload_json, p.label AS pot_label
            FROM scheduled_events se
            JOIN pots p ON p.id = se.pot_id
            WHERE p.garden_id = ?
        """
        params: list = [garden_row["id"]]
        if pot_label is not None:
            sql += " AND p.label = ?"
            params.append(pot_label)
        if since is not None:
            sql += " AND se.scheduled_date >= ?"
            params.append(since.isoformat())
        if until is not None:
            sql += " AND se.scheduled_date <= ?"
            params.append(until.isoformat())
        sql += " ORDER BY se.scheduled_date, p.label, se.event_id"

        events = []
        for row in self._conn.execute(sql, params).fetchall():
            events.append(ScheduledEvent(
                event_id=row["event_id"],
                pot_label=row["pot_label"],
                event_type=row["event_type"],
                scheduled_date=date.fromisoformat(row["scheduled_date"]),
                payload=json.loads(row["payload_json"]),
            ))
        return events
