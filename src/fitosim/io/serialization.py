"""
Serializzazione di Garden in JSON come formato di trasporto.

Il modulo introduce nella fase 2 della sotto-tappa B della tappa 4
della fascia 2 le funzioni di export e import di un giardino in
formato JSON. È completamente disaccoppiato dalla persistenza SQLite
del modulo `persistence.py`: queste funzioni operano su `Garden`
in-memory, niente database, nessuna dipendenza incrociata.

Casi d'uso
----------

Il formato JSON serve come **formato di trasporto** per:

  * **Backup di sicurezza**: salvare uno snapshot del giardino in un
    file di testo che può essere archiviato, copiato altrove, o
    inviato via email.

  * **Migrazione tra ambienti**: spostare un giardino dal PC di
    sviluppo al Raspberry Pi 5 di produzione, o viceversa.

  * **Condivisione**: inviare a un altro giardiniere uno snapshot
    del proprio giardino per confronto o consulenza.

  * **Portabilità del sistema**: ricostruire il giardino in caso di
    necessità di ricominciare con un database vergine.

Cosa NON fa
-----------

Il JSON prodotto è uno **snapshot puntuale** del giardino: contiene
i metadati, i vasi col loro stato corrente, e il catalogo delle
specie/substrati referenziati. **Non contiene la storia degli
snapshot precedenti né gli eventi storici**. Il backup completo con
storia è un'estensione futura che vivrà in un'altra funzione (es.
``export_garden_history_json``) che si appoggerà al
``GardenPersistence``.

Filosofia di disaccoppiamento
-----------------------------

Le due funzioni di questo modulo sono **funzioni pure**: prendono
oggetti Python e producono o consumano stringhe JSON, senza altri
side effect. Niente file I/O, niente database, niente eccezioni
fuori dalla famiglia ``SerializationError``.

Il chiamante che vuole salvare un giardino su file:

    import json
    json_str = export_garden_json(garden)
    with open("backup.json", "w") as f:
        f.write(json_str)

Il chiamante che vuole caricare un giardino da file:

    with open("backup.json") as f:
        json_str = f.read()
    garden = import_garden_json(json_str)

Il chiamante che vuole salvare il giardino importato anche nel
database SQLite:

    garden = import_garden_json(json_str)
    # Itera i vasi per registrare il catalogo nel persistence
    for pot in garden:
        if not persistence.is_species_registered(pot.species.common_name):
            persistence.register_species(pot.species)
        if not persistence.is_substrate_registered(pot.substrate.name):
            persistence.register_substrate(pot.substrate)
    persistence.save_garden(garden)

Niente helper magici tra i due moduli: le responsabilità sono
chiare e separate.

Struttura del JSON
------------------

Il JSON prodotto ha quattro chiavi top-level::

    {
        "format_version": 1,
        "garden": {
            "name": "balcone-milano",
            "location_description": "Balcone esposto a sud"
        },
        "catalog": {
            "species": [...],
            "base_materials": [...],
            "substrates": [...]
        },
        "pots": [
            {
                "label": "basilico-1",
                "species_name": "basilico",
                "substrate_name": "terriccio universale",
                "static_fields": {...},
                "state_fields": {...}
            }
        ]
    }

Il catalogo include solo le specie, materiali base e substrati
effettivamente referenziati dai vasi del giardino, niente di più.
Questo rende il JSON autocontenuto e di dimensione coerente col
contenuto reale.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

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
from fitosim.science.substrate import (
    BaseMaterial,
    MixComponent,
    Substrate,
    compose_substrate,
)


# Versione corrente del formato JSON. Quando il formato evolverà in
# futuro (per esempio se aggiungeremo la storia o nuovi campi del
# Pot), incrementeremo questo numero. Le funzioni di import sapranno
# come gestire le versioni precedenti tramite migrazioni applicate
# alla struttura del dict prima della ricostruzione del Garden.
FORMAT_VERSION = 1


# =======================================================================
#  Eccezione canonica
# =======================================================================

class SerializationError(Exception):
    """
    Errore generico di serializzazione/deserializzazione.

    Sollevato per JSON malformato, format_version non supportata,
    riferimenti a oggetti del catalogo mancanti, e altri errori di
    integrità del JSON.
    """


# =======================================================================
#  Helper di conversione: Pot, Species, Substrate, BaseMaterial → dict
# =======================================================================

def _species_to_dict(species: Species) -> Dict[str, Any]:
    """Converte una Species in dict serializzabile."""
    return {
        "common_name": species.common_name,
        "scientific_name": species.scientific_name,
        "kc_initial": species.kc_initial,
        "kc_mid": species.kc_mid,
        "kc_late": species.kc_late,
        "kcb_initial": species.kcb_initial,
        "kcb_mid": species.kcb_mid,
        "kcb_late": species.kcb_late,
        "initial_stage_days": species.initial_stage_days,
        "mid_stage_days": species.mid_stage_days,
        "ec_optimal_min_mscm": species.ec_optimal_min_mscm,
        "ec_optimal_max_mscm": species.ec_optimal_max_mscm,
        "ph_optimal_min": species.ph_optimal_min,
        "ph_optimal_max": species.ph_optimal_max,
    }


def _dict_to_species(data: Dict[str, Any]) -> Species:
    """Ricostruisce una Species dal suo dict serializzato."""
    return Species(
        common_name=data["common_name"],
        scientific_name=data["scientific_name"],
        kc_initial=data["kc_initial"],
        kc_mid=data["kc_mid"],
        kc_late=data["kc_late"],
        kcb_initial=data.get("kcb_initial"),
        kcb_mid=data.get("kcb_mid"),
        kcb_late=data.get("kcb_late"),
        initial_stage_days=data.get("initial_stage_days", 30),
        mid_stage_days=data.get("mid_stage_days", 60),
        ec_optimal_min_mscm=data.get("ec_optimal_min_mscm"),
        ec_optimal_max_mscm=data.get("ec_optimal_max_mscm"),
        ph_optimal_min=data.get("ph_optimal_min"),
        ph_optimal_max=data.get("ph_optimal_max"),
    )


def _base_material_to_dict(material: BaseMaterial) -> Dict[str, Any]:
    """Converte un BaseMaterial in dict."""
    return {
        "name": material.name,
        "theta_fc": material.theta_fc,
        "theta_pwp": material.theta_pwp,
        "description": material.description,
    }


def _dict_to_base_material(data: Dict[str, Any]) -> BaseMaterial:
    return BaseMaterial(
        name=data["name"],
        theta_fc=data["theta_fc"],
        theta_pwp=data["theta_pwp"],
        description=data.get("description", ""),
    )


def _substrate_to_dict(
    substrate: Substrate,
    components: Optional[List[MixComponent]] = None,
) -> Dict[str, Any]:
    """
    Converte un Substrate in dict.

    Se ``components`` è specificato, il substrato viene serializzato
    come mistura: viene aggiunta la chiave ``is_mixture: True`` e la
    lista dei componenti. Se ``components`` è None, il substrato è
    "puro" e i suoi parametri theta_fc/theta_pwp vengono salvati
    direttamente.
    """
    out: Dict[str, Any] = {
        "name": substrate.name,
        "theta_fc": substrate.theta_fc,
        "theta_pwp": substrate.theta_pwp,
        "description": substrate.description,
        "rew_mm": substrate.rew_mm,
        "tew_mm": substrate.tew_mm,
        "cec_meq_per_100g": substrate.cec_meq_per_100g,
        "ph_typical": substrate.ph_typical,
        "is_mixture": components is not None,
    }
    if components is not None:
        out["components"] = [
            {
                "base_material_name": c.material.name,
                "fraction": c.fraction,
            }
            for c in components
        ]
    return out


def _dict_to_substrate(
    data: Dict[str, Any],
    base_materials_by_name: Dict[str, BaseMaterial],
) -> Substrate:
    """
    Ricostruisce un Substrate dal suo dict.

    Per i substrati puri costruisce direttamente l'istanza con i
    parametri salvati. Per le misture chiama ``compose_substrate``
    sui componenti, e poi trasferisce i parametri "di mistura"
    (description, dual-Kc, parametri chimici) dal dict perché sono
    caratteristiche della mistura nel suo insieme che
    ``compose_substrate`` non conosce.

    Parametri
    ---------
    data : dict
        Il dict del substrato dal JSON.
    base_materials_by_name : dict
        Mappa nome → BaseMaterial dei materiali base disponibili.
        Necessaria solo per i substrati mistura: per i puri viene
        ignorata.

    Solleva
    -------
    SerializationError
        Se la mistura referenzia un materiale base non presente nella
        mappa fornita.
    """
    if not data.get("is_mixture", False):
        return Substrate(
            name=data["name"],
            theta_fc=data["theta_fc"],
            theta_pwp=data["theta_pwp"],
            description=data.get("description", ""),
            rew_mm=data.get("rew_mm"),
            tew_mm=data.get("tew_mm"),
            cec_meq_per_100g=data.get("cec_meq_per_100g"),
            ph_typical=data.get("ph_typical"),
        )

    # Mistura: ricostruisci la ricetta e ricalcola i parametri.
    components_data = data.get("components", [])
    if not components_data:
        raise SerializationError(
            f"Substrato '{data.get('name')}' è marcato is_mixture=True "
            f"ma non ha componenti."
        )

    components: List[MixComponent] = []
    for cd in components_data:
        bm_name = cd["base_material_name"]
        if bm_name not in base_materials_by_name:
            raise SerializationError(
                f"Substrato '{data['name']}' referenzia il materiale "
                f"base '{bm_name}' che non è presente nel catalog del "
                f"JSON. Il catalog è incoerente."
            )
        components.append(MixComponent(
            material=base_materials_by_name[bm_name],
            fraction=cd["fraction"],
        ))

    composed = compose_substrate(components=components, name=data["name"])
    # Trasferisci i parametri "di mistura" che compose_substrate non
    # conosce ma il JSON ha preservato.
    return Substrate(
        name=composed.name,
        theta_fc=composed.theta_fc,
        theta_pwp=composed.theta_pwp,
        description=data.get("description", ""),
        rew_mm=data.get("rew_mm"),
        tew_mm=data.get("tew_mm"),
        cec_meq_per_100g=data.get("cec_meq_per_100g"),
        ph_typical=data.get("ph_typical"),
    )


def _pot_to_dict(
    pot: Pot,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Converte un Pot in dict, separando campi statici da mutabili."""
    static_fields = {
        "pot_volume_l": pot.pot_volume_l,
        "pot_diameter_cm": pot.pot_diameter_cm,
        "pot_shape": pot.pot_shape.value,
        "pot_width_cm": pot.pot_width_cm,
        "pot_material": pot.pot_material.value,
        "pot_color": pot.pot_color.value,
        "location": pot.location.value,
        "sun_exposure": pot.sun_exposure.value,
        "active_depth_fraction": pot.active_depth_fraction,
        "rainfall_exposure": pot.rainfall_exposure,
        "saucer_capacity_mm": pot.saucer_capacity_mm,
        "saucer_capillary_rate": pot.saucer_capillary_rate,
        "saucer_evap_coef": pot.saucer_evap_coef,
        "planting_date": pot.planting_date.isoformat(),
        "notes": pot.notes,
        "channel_id": channel_id,
    }
    state_fields = {
        "state_mm": pot.state_mm,
        "salt_mass_meq": pot.salt_mass_meq,
        "ph_substrate": pot.ph_substrate,
        "saucer_state_mm": pot.saucer_state_mm,
        "de_mm": pot.de_mm,
    }
    return {
        "label": pot.label,
        "species_name": pot.species.common_name,
        "substrate_name": pot.substrate.name,
        "static_fields": static_fields,
        "state_fields": state_fields,
    }


def _dict_to_pot(
    data: Dict[str, Any],
    species_by_name: Dict[str, Species],
    substrates_by_name: Dict[str, Substrate],
) -> Pot:
    """Ricostruisce un Pot dal suo dict, risolvendo i riferimenti."""
    species_name = data["species_name"]
    substrate_name = data["substrate_name"]
    if species_name not in species_by_name:
        raise SerializationError(
            f"Vaso '{data['label']}' referenzia la specie "
            f"'{species_name}' non presente nel catalog del JSON."
        )
    if substrate_name not in substrates_by_name:
        raise SerializationError(
            f"Vaso '{data['label']}' referenzia il substrato "
            f"'{substrate_name}' non presente nel catalog del JSON."
        )

    static = data["static_fields"]
    state = data["state_fields"]

    kwargs: Dict[str, Any] = dict(
        label=data["label"],
        species=species_by_name[species_name],
        substrate=substrates_by_name[substrate_name],
        pot_volume_l=static["pot_volume_l"],
        pot_diameter_cm=static["pot_diameter_cm"],
        pot_shape=PotShape(static["pot_shape"]),
        pot_material=PotMaterial(static["pot_material"]),
        pot_color=PotColor(static["pot_color"]),
        location=Location(static["location"]),
        sun_exposure=SunExposure(static["sun_exposure"]),
        active_depth_fraction=static["active_depth_fraction"],
        rainfall_exposure=static["rainfall_exposure"],
        planting_date=date.fromisoformat(static["planting_date"]),
        notes=static.get("notes", ""),
    )
    if static.get("pot_width_cm") is not None:
        kwargs["pot_width_cm"] = static["pot_width_cm"]
    if static.get("saucer_capacity_mm") is not None:
        kwargs["saucer_capacity_mm"] = static["saucer_capacity_mm"]
    if static.get("saucer_capillary_rate") is not None:
        kwargs["saucer_capillary_rate"] = static["saucer_capillary_rate"]
    if static.get("saucer_evap_coef") is not None:
        kwargs["saucer_evap_coef"] = static["saucer_evap_coef"]
    # Stati mutabili (sempre presenti).
    kwargs["state_mm"] = state["state_mm"]
    kwargs["salt_mass_meq"] = state["salt_mass_meq"]
    kwargs["ph_substrate"] = state["ph_substrate"]
    kwargs["saucer_state_mm"] = state["saucer_state_mm"]
    kwargs["de_mm"] = state["de_mm"]

    return Pot(**kwargs)


# =======================================================================
#  Catalog inference: cosa serve effettivamente al giardino
# =======================================================================

def _build_minimal_catalog(garden: Garden) -> Tuple[
    Dict[str, Species],
    Dict[str, Substrate],
    Dict[str, BaseMaterial],
]:
    """
    Estrae dal giardino il catalogo minimale necessario per ricostruirlo.

    Il principio è "JSON autocontenuto e minimale": serializziamo solo
    ciò che effettivamente serve. Il chiamante che ha un catalogo più
    grande nel suo database SQLite non vuole ritrovarsi tutto il
    catalogo nel file di backup di un singolo giardino.

    NOTA: i Substrate del Garden in-memory NON portano con sé la loro
    eventuale ricetta come componenti. La ricetta è un'informazione
    persistente che vive solo nel database SQLite (tabella
    substrate_components). Quando esportiamo da Garden in-memory non
    abbiamo la ricetta, quindi i substrati nel JSON sono sempre
    serializzati come "puri" (is_mixture=False) anche se nella loro
    storia originale erano misture. È una limitazione voluta della
    fase 2: chi vuole preservare le ricette deve usare il backup
    completo con storia (estensione futura).

    Conseguenza pratica: il catalog del JSON contiene solo specie e
    substrati; i base_materials sono sempre vuoti dato che non si
    può inferire la composizione di una mistura da un Substrate
    in-memory.

    Ritorna
    -------
    tuple di tre dict:
      species_by_name, substrates_by_name, base_materials_by_name
    """
    species_by_name: Dict[str, Species] = {}
    substrates_by_name: Dict[str, Substrate] = {}
    base_materials_by_name: Dict[str, BaseMaterial] = {}

    for pot in garden:
        species_by_name[pot.species.common_name] = pot.species
        substrates_by_name[pot.substrate.name] = pot.substrate

    return species_by_name, substrates_by_name, base_materials_by_name


# =======================================================================
#  Funzione principale: export
# =======================================================================

def export_garden_json(
    garden: Garden,
    indent: Optional[int] = 2,
) -> str:
    """
    Serializza un Garden in formato JSON.

    Il risultato è una stringa JSON autocontenuta che include i
    metadati del giardino, tutti i vasi col loro stato corrente, e
    il catalogo minimale (specie e substrati effettivamente
    referenziati dai vasi).

    Parametri
    ---------
    garden : Garden
        Il giardino da serializzare.
    indent : int, opzionale
        Indentazione del JSON per leggibilità. Default 2 (compatto
        ma leggibile). Passa None per JSON compatto su una riga
        (più piccolo ma meno leggibile).

    Ritorna
    -------
    str
        La stringa JSON serializzata.
    """
    species_by_name, substrates_by_name, base_materials_by_name = (
        _build_minimal_catalog(garden)
    )

    catalog = {
        "species": [
            _species_to_dict(s)
            for s in sorted(species_by_name.values(),
                            key=lambda x: x.common_name)
        ],
        "base_materials": [
            _base_material_to_dict(m)
            for m in sorted(base_materials_by_name.values(),
                            key=lambda x: x.name)
        ],
        "substrates": [
            _substrate_to_dict(s)
            for s in sorted(substrates_by_name.values(),
                            key=lambda x: x.name)
        ],
    }

    payload = {
        "format_version": FORMAT_VERSION,
        "garden": {
            "name": garden.name,
            "location_description": garden.location_description,
        },
        "catalog": catalog,
        "pots": [
            _pot_to_dict(pot, channel_id=garden.get_channel_id(pot.label))
            for pot in garden
        ],
    }

    return json.dumps(payload, indent=indent, ensure_ascii=False)


# =======================================================================
#  Funzione principale: import
# =======================================================================

def import_garden_json(json_str: str) -> Garden:
    """
    Deserializza un Garden dalla sua rappresentazione JSON.

    La ricostruzione segue questa sequenza:

      1. Parsing della stringa JSON.
      2. Validazione di format_version.
      3. Ricostruzione del catalogo (base_materials, substrates,
         species) in dict locali.
      4. Ricostruzione di ogni vaso risolvendo i riferimenti al
         catalogo.
      5. Costruzione del Garden e aggiunta dei vasi nell'ordine in
         cui appaiono nel JSON.

    Parametri
    ---------
    json_str : str
        La stringa JSON prodotta da `export_garden_json`.

    Ritorna
    -------
    Garden
        Il giardino ricostruito in-memory.

    Solleva
    -------
    SerializationError
        Per JSON malformato, format_version superiore a quella
        supportata, o riferimenti del catalogo mancanti.
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise SerializationError(
            f"JSON malformato: {e}"
        ) from e

    if not isinstance(data, dict):
        raise SerializationError(
            f"Il JSON top-level deve essere un oggetto, non "
            f"{type(data).__name__}."
        )

    # Validazione della versione del formato.
    fmt_version = data.get("format_version")
    if fmt_version is None:
        raise SerializationError(
            "Manca il campo 'format_version' nel JSON."
        )
    if not isinstance(fmt_version, int):
        raise SerializationError(
            f"format_version deve essere un intero, ricevuto "
            f"{type(fmt_version).__name__}."
        )
    if fmt_version > FORMAT_VERSION:
        raise SerializationError(
            f"Il JSON è in formato versione {fmt_version} ma il codice "
            f"supporta solo fino alla versione {FORMAT_VERSION}. "
            f"Aggiorna fitosim per leggerlo."
        )
    # In futuro, se fmt_version < FORMAT_VERSION, applicheremo qui
    # le migrazioni alla struttura del dict prima della ricostruzione.

    # Ricostruzione del catalog in dict locali, in ordine di dipendenza:
    # prima i materiali base (no dipendenze), poi i substrati (puri o
    # misture, le ultime usano i materiali base), infine le specie
    # (no dipendenze, ma le mettiamo per ultime per coerenza).
    if "catalog" not in data:
        raise SerializationError("Manca la chiave 'catalog' nel JSON.")
    catalog = data["catalog"]

    base_materials_by_name: Dict[str, BaseMaterial] = {}
    for bm_data in catalog.get("base_materials", []):
        bm = _dict_to_base_material(bm_data)
        base_materials_by_name[bm.name] = bm

    substrates_by_name: Dict[str, Substrate] = {}
    for sub_data in catalog.get("substrates", []):
        sub = _dict_to_substrate(sub_data, base_materials_by_name)
        substrates_by_name[sub.name] = sub

    species_by_name: Dict[str, Species] = {}
    for sp_data in catalog.get("species", []):
        sp = _dict_to_species(sp_data)
        species_by_name[sp.common_name] = sp

    # Costruzione del Garden.
    if "garden" not in data:
        raise SerializationError("Manca la chiave 'garden' nel JSON.")
    garden_data = data["garden"]
    if "name" not in garden_data:
        raise SerializationError(
            "Manca il nome del giardino in data['garden']['name']."
        )

    garden = Garden(
        name=garden_data["name"],
        location_description=garden_data.get("location_description", ""),
    )

    # Ricostruzione dei vasi.
    for pot_data in data.get("pots", []):
        pot = _dict_to_pot(pot_data, species_by_name, substrates_by_name)
        garden.add_pot(pot)
        # Se il pot_data contiene channel_id (presente dal format_version
        # 1 della sotto-tappa C in poi), applica la mappatura.
        channel_id = pot_data.get("static_fields", {}).get("channel_id")
        if channel_id is not None:
            garden.set_channel_id(pot.label, channel_id)

    return garden
