"""
Garden: orchestratore di più vasi del balcone.

Il modulo introduce nella sotto-tappa A della tappa 4 della fascia 2
la dataclass Garden, che è il contenitore semantico di tutti i vasi
del balcone (o di qualsiasi raggruppamento logico di vasi). È il
pezzo che effettivamente trasforma fitosim da "libreria che gestisce
un singolo vaso" a "sistema operativo per il dashboard del giardiniere".

Cosa fa il Garden
-----------------

Il Garden tiene una collezione di Pot indicizzati per label e li
gestisce come un'unità coerente. Le operazioni di base sono:

  * **Aggiunta e rimozione** di vasi dalla collezione
  * **Iterazione** sui vasi (ordine di inserimento preservato)
  * **Accesso per label** con KeyError se non esiste
  * **Orchestrazione** dell'evoluzione giornaliera di tutti i vasi
    insieme tramite il metodo `apply_step_all`

Il Garden NON contiene direttamente la logica scientifica del modello
fitosim — quella vive nel Pot e nei moduli science/. Il Garden è
puramente un orchestratore: prende la pioggia in mm e la converte in
litri per ogni vaso usando la sua geometria, chiama apply_step su
ogni vaso, raccoglie i risultati, e li ritorna come dizionario per
il logging del chiamante.

Ordinamento e identità
----------------------

Il Garden ha un nome come identificatore (es. "balcone-milano",
"terrazzo-mare"), che è una caratteristica immutabile della sua
identità: cambiare nome significa avere un altro giardino. Una
description opzionale documenta la sua localizzazione e caratteristiche
in forma libera.

L'ordine di iterazione sui vasi preserva l'ordine di inserimento (lo
stesso comportamento del dict standard di Python). È utile per il
chiamante che vuole stampare l'output in un ordine consistente tra
le sessioni.

Filosofia di disaccoppiamento
-----------------------------

Il Garden è in-memory puro nella sotto-tappa A: non sa nulla di
persistenza, di sensori, di calendari di eventi. Queste estensioni
arrivano nelle sotto-tappe successive e sono completamente
indipendenti tra loro:

  * Sotto-tappa B: persistenza SQLite + JSON export/import
  * Sotto-tappa C: integrazione col gateway ESP32
  * Sotto-tappa D: eventi pianificati e previsioni future
  * Sotto-tappa E: sistema di allerte

Ognuna estende il Garden con nuove capacità senza toccare il cuore
in-memory che costruiamo qui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterator, Optional

from fitosim.domain.pot import FullStepResult, Pot


@dataclass
class Garden:
    """
    Contenitore semantico di più vasi del balcone, con orchestrazione
    delle operazioni a livello di insieme.

    Attributi
    ---------
    name : str
        Identificatore del giardino. Caratteristica immutabile della
        sua identità: due Garden con name diverso sono concettualmente
        diversi anche se contengono gli stessi vasi. Esempi:
        "balcone-milano", "terrazzo-mare", "indoor-cucina".
    location_description : str, opzionale
        Descrizione libera della posizione e caratteristiche del
        giardino, per il logging del chiamante. Esempio:
        "Balcone esposto a sud, parzialmente coperto da balcone
        superiore, in città con inquinamento moderato". Default:
        stringa vuota.

    Attributi interni
    -----------------
    Il Garden tiene internamente un dict ordinato dei vasi, indicizzato
    per label. La struttura è di tipo dict[str, Pot] e sfrutta
    l'ordinamento per inserimento del dict standard di Python (≥ 3.7)
    per garantire iterazione in ordine deterministico.

    Esempio di utilizzo
    -------------------
    ::

        from fitosim.domain.garden import Garden
        from fitosim.domain.pot import Pot
        # ... costruzione di pot1, pot2, pot3 ...

        garden = Garden(
            name="balcone-milano",
            location_description="Balcone sud, parzialmente coperto",
        )
        garden.add_pot(pot1)
        garden.add_pot(pot2)
        garden.add_pot(pot3)

        # Evolvere tutti i vasi insieme per un giorno con pioggia
        # di 5 mm e ET₀ di 4.5 mm
        results = garden.apply_step_all(
            et_0_mm=4.5,
            current_date=date(2026, 5, 15),
            rainfall_mm=5.0,
        )

        # Iterazione e ispezione
        for pot in garden:
            print(f"{pot.label}: θ={pot.state_theta:.3f}, "
                  f"EC={pot.ec_substrate_mscm:.2f}")
    """

    name: str
    location_description: str = ""
    # Dict interno dei vasi indicizzato per label. Dichiarato con
    # default_factory=dict per evitare il classico bug del default
    # mutabile condiviso tra istanze.
    _pots: Dict[str, Pot] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Validazione: il nome non può essere vuoto."""
        if not self.name or not self.name.strip():
            raise ValueError(
                "Garden.name non può essere vuoto. È l'identificatore "
                "del giardino e dev'essere significativo."
            )

    # ----- Gestione della collezione di vasi -----

    def add_pot(self, pot: Pot) -> None:
        """
        Aggiunge un vaso al giardino.

        Solleva ValueError se un vaso con lo stesso label esiste già.
        Le label devono essere uniche all'interno di un giardino —
        è la chiave di accesso che il chiamante userà per tutta la vita
        del giardino.

        Parametri
        ---------
        pot : Pot
            Il vaso da aggiungere. Tutte le sue caratteristiche
            (specie, substrato, geometria, stato corrente) sono
            preservate; il Garden non modifica il Pot in nessun modo.

        Solleva
        -------
        ValueError
            Se un vaso con lo stesso label è già presente.
        """
        if pot.label in self._pots:
            raise ValueError(
                f"Garden '{self.name}': il vaso con label '{pot.label}' "
                f"è già presente. Le label devono essere uniche all'interno "
                f"di un giardino. Se vuoi sostituire il vaso usa prima "
                f"remove_pot(), oppure scegli una label diversa."
            )
        self._pots[pot.label] = pot

    def remove_pot(self, label: str) -> Pot:
        """
        Rimuove un vaso dal giardino e lo restituisce.

        Il chiamante può salvare il vaso restituito se vuole
        conservarne lo stato per spostarlo in un altro giardino o
        per archiviarlo. Se non ne ha bisogno, può semplicemente
        ignorare il valore di ritorno.

        Solleva KeyError se non esiste un vaso con quella label.

        Parametri
        ---------
        label : str
            La label identificativa del vaso da rimuovere.

        Ritorna
        -------
        Pot
            Il vaso rimosso, con tutto il suo stato corrente.

        Solleva
        -------
        KeyError
            Se non esiste un vaso con la label specificata.
        """
        if label not in self._pots:
            raise KeyError(
                f"Garden '{self.name}': nessun vaso con label '{label}'. "
                f"Vasi presenti: {list(self._pots.keys())}"
            )
        return self._pots.pop(label)

    def get_pot(self, label: str) -> Pot:
        """
        Restituisce il vaso con la label specificata.

        Solleva KeyError se non esiste. Per controllare l'esistenza
        senza eccezioni usare has_pot().

        Parametri
        ---------
        label : str
            La label identificativa del vaso.

        Ritorna
        -------
        Pot
            Il vaso (riferimento, non copia: modifiche al Pot ritornato
            si riflettono nel Garden).

        Solleva
        -------
        KeyError
            Se non esiste un vaso con la label specificata.
        """
        if label not in self._pots:
            raise KeyError(
                f"Garden '{self.name}': nessun vaso con label '{label}'. "
                f"Vasi presenti: {list(self._pots.keys())}"
            )
        return self._pots[label]

    def has_pot(self, label: str) -> bool:
        """Test di esistenza non eccezionale: True se label è presente."""
        return label in self._pots

    @property
    def pot_labels(self) -> list[str]:
        """
        Lista delle label dei vasi nell'ordine di inserimento.

        È la "vista pubblica" delle chiavi del giardino. Il chiamante
        può usarla per iterare in modo controllato, per validare
        configurazioni esterne, o per generare interfacce utente.
        """
        return list(self._pots.keys())

    # ----- Protocollo di iterazione -----

    def __iter__(self) -> Iterator[Pot]:
        """
        Itera sui vasi nell'ordine di inserimento.

        Permette il pattern naturale ``for pot in garden:``. L'ordine
        è garantito stabile tra chiamate consecutive (corrisponde
        all'ordine di add_pot).
        """
        return iter(self._pots.values())

    def __len__(self) -> int:
        """Numero di vasi attualmente nel giardino."""
        return len(self._pots)

    def __contains__(self, label: str) -> bool:
        """
        Permette il pattern ``if label in garden:`` come scorciatoia
        per ``garden.has_pot(label)``.
        """
        return label in self._pots

    # ----- Orchestratore: evoluzione giornaliera di tutti i vasi -----

    def apply_step_all(
        self,
        et_0_mm: float,
        current_date: date,
        rainfall_mm: float = 0.0,
    ) -> Dict[str, FullStepResult]:
        """
        Applica un passo giornaliero a tutti i vasi del giardino.

        Per ogni vaso del giardino chiama Pot.apply_step con:

          * et_0_mm: lo stesso per tutti i vasi (è una grandezza
            ambientale del giardino, non del singolo vaso)
          * current_date: la data del passo
          * rainfall_volume_l: convertito da rainfall_mm × area del
            singolo vaso, in modo che ogni vaso riceva la sua
            quantità di pioggia coerente con la sua geometria

        Il coefficiente rainfall_exposure del singolo vaso (introdotto
        in tappa 3 sotto-tappa F) viene poi applicato internamente da
        Pot.apply_rainfall_step, quindi vasi parzialmente coperti
        riceveranno meno pioggia anche se questo metodo passa loro il
        volume nominale calcolato dall'area.

        Cosa NON fa
        -----------

        Questo metodo applica solo gli eventi "ambientali" a livello
        di giardino: pioggia ed evapotraspirazione. NON gestisce le
        fertirrigazioni manuali o le bagnature di lavaggio, che sono
        eventi puntuali per singolo vaso. Il chiamante che vuole
        fertirrigare un vaso specifico chiama direttamente:

            garden.get_pot(label).apply_fertigation_step(...)

        Questa separazione tiene l'API del Garden pulita e semantica:
        gli eventi del giardino sono ambientali, gli eventi del vaso
        sono manuali.

        Parametri
        ---------
        et_0_mm : float
            Evapotraspirazione di riferimento del giorno, in mm.
            Lo stesso valore si applica a tutti i vasi del giardino.
        current_date : date
            Data del passo. Usata dal modello fenologico (Kc dello
            stadio corrente) e per il logging.
        rainfall_mm : float, opzionale
            Quantità di pioggia caduta sull'area aperta, in mm.
            Default 0.0 (giorno asciutto). Viene convertita in litri
            per ogni singolo vaso usando la sua surface_area_m2.

        Ritorna
        -------
        Dict[str, FullStepResult]
            Dizionario {label: FullStepResult} con il risultato del
            passo per ogni vaso. L'ordine delle chiavi corrisponde
            all'ordine di inserimento dei vasi nel giardino.
        """
        if et_0_mm < 0:
            raise ValueError(
                f"et_0_mm deve essere non-negativa (ricevuto {et_0_mm})."
            )
        if rainfall_mm < 0:
            raise ValueError(
                f"rainfall_mm deve essere non-negativa "
                f"(ricevuto {rainfall_mm})."
            )

        results: Dict[str, FullStepResult] = {}
        for label, pot in self._pots.items():
            # Conversione mm → litri usando l'area del singolo vaso.
            # Formula: V[L] = pioggia[mm] × area[m²].
            # Il rainfall_exposure del Pot verrà applicato internamente
            # da apply_rainfall_step, riducendo ulteriormente il volume
            # effettivo entrante nei vasi parzialmente coperti.
            rainfall_volume_l = rainfall_mm * pot.surface_area_m2

            result = pot.apply_step(
                et_0_mm=et_0_mm,
                current_date=current_date,
                rainfall_volume_l=rainfall_volume_l,
            )
            results[label] = result

        return results
