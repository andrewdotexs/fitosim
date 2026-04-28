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
from typing import Dict, Iterator, Optional, Union

from fitosim.domain.pot import FullStepResult, Pot, SensorUpdateResult
from fitosim.io.sensors import (
    SensorTemporaryError,
    SoilSensor,
)


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
    # Mappa label → channel_id del gateway hardware. È una proprietà
    # configurativa del giardino: collega ogni vaso al canale del
    # sensore reale che lo monitora. Vasi senza mapping continuano
    # solo in previsione (giardini misti permessi).
    _channel_mapping: Dict[str, str] = field(
        default_factory=dict, repr=False,
    )

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

    # ----- Gestione della mappa label → channel_id -----

    def set_channel_id(self, label: str, channel_id: str) -> None:
        """
        Associa un vaso al canale del sensore hardware.

        Solleva KeyError se la label non corrisponde a nessun vaso
        attualmente nel giardino. È una scelta deliberata: vogliamo
        evitare mappature "orfane" che si riferiscono a vasi non
        ancora aggiunti — è quasi sempre indicatore di un errore
        di configurazione.

        Parametri
        ---------
        label : str
            La label del vaso. Deve essere già nel giardino.
        channel_id : str
            L'identificatore del canale del sensore. Il formato
            dipende dal gateway hardware in uso (es. "1" per WH51 o
            "ato_001" per ATO 7-in-1).

        Solleva
        -------
        KeyError
            Se la label non corrisponde a nessun vaso del giardino.
        """
        if label not in self._pots:
            raise KeyError(
                f"Garden '{self.name}': nessun vaso con label '{label}' "
                f"a cui associare il channel_id '{channel_id}'. "
                f"Vasi presenti: {list(self._pots.keys())}"
            )
        self._channel_mapping[label] = channel_id

    def get_channel_id(self, label: str) -> Optional[str]:
        """
        Ritorna il channel_id mappato per il vaso, o None se non c'è.

        Test non-eccezionale: chi vuole controllare se un vaso ha un
        canale mappato può confrontare il risultato con None. Niente
        eccezione perché molti vasi possono legittimamente non avere
        un sensore (giardini misti).
        """
        return self._channel_mapping.get(label)

    def has_channel_id(self, label: str) -> bool:
        """Test booleano di presenza della mappatura."""
        return label in self._channel_mapping

    def remove_channel_id(self, label: str) -> None:
        """
        Rimuove la mappatura per un vaso. No-op se non c'è.

        Caso pratico: il sensore è stato fisicamente scollegato dal
        vaso, e da ora in poi quel vaso continua solo in previsione
        senza vincolarsi a un canale.
        """
        self._channel_mapping.pop(label, None)

    @property
    def channel_mapping(self) -> Dict[str, str]:
        """
        Vista pubblica della mappa label → channel_id.

        Ritorna una **copia** del dict per impedire modifiche dirette
        dall'esterno. Per modificare la mappa usare i metodi
        set_channel_id, remove_channel_id.
        """
        return dict(self._channel_mapping)

    # ----- Orchestratore: aggiornamento dai sensori reali -----

    def update_all_from_sensors(
        self,
        sensor: SoilSensor,
    ) -> Dict[str, Union[SensorUpdateResult, SensorTemporaryError]]:
        """
        Allinea tutti i vasi mappati alle letture dei sensori reali.

        Per ogni vaso del giardino che ha un channel_id mappato:

          1. Chiama sensor.current_state(channel_id) per ottenere la
             SoilReading corrente del canale.
          2. Chiama pot.update_from_sensor(reading=reading) per
             allineare il modello al sensore e produrre un report
             diagnostico della discrepanza.
          3. Inserisce il SensorUpdateResult nel dizionario di
             ritorno indicizzato per label.

        Vasi senza mappatura nel dizionario _channel_mapping vengono
        saltati silenziosamente: continuano solo in previsione. È il
        meccanismo che permette i "giardini misti" — alcuni vasi
        sotto sensore reale, altri solo in previsione — senza
        configurazione speciale.

        Gestione degli errori
        ---------------------
        Per gli errori transitori del sensore (SensorTemporaryError —
        timeout di rete, batteria momentaneamente debole, gateway
        congestionato), il metodo NON propaga l'eccezione: il vaso
        problematico viene saltato per quel ciclo, e il dizionario
        di ritorno contiene l'eccezione invece del SensorUpdateResult.
        Il giardiniere virtuale può poi ispezionare il risultato per
        sapere quali vasi non sono stati aggiornati e perché.

        Per gli errori permanenti (SensorPermanentError — channel_id
        inesistente, credenziali sbagliate) e di qualità dati
        (SensorDataQualityError — letture impossibili come θ
        negativa o pH > 14), il metodo PROPAGA l'eccezione perché
        indicano problemi di configurazione o malfunzionamenti che
        richiedono intervento umano. Silenziarli equivarrebbe a
        nascondere problemi che peggioreranno se non corretti.

        Parametri
        ---------
        sensor : SoilSensor
            Il client del sensore hardware. Va passato come parametro
            (e non tenuto come attributo del Garden) perché:

              * Può cambiare durante la vita del giardino (un fake
                sensor in test, l'HTTP sensor reale in produzione).
              * Tenerlo fuori dalla dataclass garantisce che il
                Garden resti serializzabile in JSON (un client HTTP
                con stato di connessione non lo è).

        Ritorna
        -------
        Dict[str, SensorUpdateResult | SensorTemporaryError]
            Un dizionario {label: result} con un'entrata per ogni
            vaso mappato. Vasi senza mappatura non sono inclusi.
            Il valore è un SensorUpdateResult per le letture
            riuscite, oppure un'istanza di SensorTemporaryError
            preservata come oggetto (non sollevata) per gli errori
            transitori.
        """
        results: Dict[str, Union[SensorUpdateResult, SensorTemporaryError]] = {}
        for label, channel_id in self._channel_mapping.items():
            # Vasi mappati ma poi rimossi dal giardino: tolleriamo
            # silenziosamente. Le mappature orfane si possono creare
            # solo via remove_pot senza prima rimuovere il mapping.
            if label not in self._pots:
                continue

            pot = self._pots[label]
            try:
                reading = sensor.current_state(channel_id)
            except SensorTemporaryError as e:
                # Errore transitorio: preserva l'eccezione nel
                # risultato e prosegui con gli altri vasi.
                results[label] = e
                continue
            # SensorPermanentError e SensorDataQualityError NON sono
            # catturati: propagano in alto come da contratto.

            update_result = pot.update_from_sensor(reading=reading)
            results[label] = update_result

        return results

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
