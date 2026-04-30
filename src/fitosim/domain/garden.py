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

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterator, List, Optional, Tuple, Union

from fitosim.domain.alerts import ALL_RULES, Alert
from fitosim.domain.pot import FullStepResult, Pot, SensorUpdateResult
from fitosim.domain.room import Room
from fitosim.domain.scheduling import ScheduledEvent, WeatherDayForecast
from fitosim.domain.weather import WeatherDay
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
    # Dict interno delle Room indicizzato per room_id (sotto-tappa D
    # fase 1 tappa 5). Le Room rappresentano gli spazi indoor del
    # giardino e sono parallele ai Pot: un giardino può avere zero
    # Room (caso tipico per il balcone outdoor di Andrea) oppure
    # diverse Room (caso del giardino indoor multi-stanza). I Pot
    # indoor si associano alla loro Room tramite il campo room_id.
    _rooms: Dict[str, "Room"] = field(default_factory=dict, repr=False)
    # Mappa label → channel_id del gateway hardware. È una proprietà
    # configurativa del giardino: collega ogni vaso al canale del
    # sensore reale che lo monitora. Vasi senza mapping continuano
    # solo in previsione (giardini misti permessi).
    _channel_mapping: Dict[str, str] = field(
        default_factory=dict, repr=False,
    )
    # Eventi pianificati indicizzati per (pot_label, event_id) per
    # garantire l'unicità. Sono il "piano del giardiniere": cosa farò
    # nei prossimi giorni/settimane. Da non confondere con la storia
    # degli eventi (avvenuti) che vive nella tabella `events` della
    # persistenza SQLite.
    _scheduled_events: Dict[Tuple[str, str], ScheduledEvent] = field(
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

    # ----- Gestione della collezione di Room (sotto-tappa D fase 1 tappa 5) -----
    #
    # Le Room rappresentano gli spazi indoor del giardino con
    # microclima condiviso (tipicamente una stanza di casa coperta
    # da un sensore WN31 ambientale). I metodi seguenti seguono lo
    # stesso pattern dei vasi: add, get, remove, has, iter, len.
    # Aggiungiamo anche la utility pots_in_room che è specifica delle
    # Room e serve a recuperare tutti i vasi associati a una Room
    # tramite il campo room_id del Pot.

    def add_room(self, room: "Room") -> None:
        """
        Aggiunge una Room al giardino.

        Solleva ValueError se una Room con lo stesso room_id esiste
        già: vogliamo che gli identificatori siano univoci per evitare
        ambiguità nelle associazioni Pot → Room.

        Parametri
        ---------
        room : Room
            La Room da aggiungere. Il suo room_id deve essere univoco
            nel giardino.

        Solleva
        -------
        ValueError
            Se room.room_id è già presente nel giardino.
        """
        if room.room_id in self._rooms:
            raise ValueError(
                f"Garden '{self.name}': Room con room_id "
                f"'{room.room_id}' già presente. Per modificarla "
                f"recuperala con get_room e mutala direttamente, "
                f"oppure rimuovila prima con remove_room."
            )
        self._rooms[room.room_id] = room

    def get_room(self, room_id: str) -> "Room":
        """
        Recupera la Room con il room_id specificato.

        Parametri
        ---------
        room_id : str
            L'identificatore della Room da recuperare.

        Ritorna
        -------
        Room
            La Room corrispondente al room_id.

        Solleva
        -------
        ValueError
            Se non esiste una Room con quel room_id.
        """
        if room_id not in self._rooms:
            raise ValueError(
                f"Garden '{self.name}': nessuna Room con room_id "
                f"'{room_id}'. Room presenti: "
                f"{list(self._rooms.keys())}"
            )
        return self._rooms[room_id]

    def has_room(self, room_id: str) -> bool:
        """True se esiste una Room con il room_id specificato."""
        return room_id in self._rooms

    def remove_room(self, room_id: str) -> "Room":
        """
        Rimuove la Room dal giardino e la restituisce.

        Verifica che nessun vaso indoor sia ancora associato alla
        Room prima di rimuoverla, perché lasciare vasi con
        room_id orfani produrrebbe errori a runtime nel bilancio
        idrico indoor della fase D2.

        Parametri
        ---------
        room_id : str
            L'identificatore della Room da rimuovere.

        Ritorna
        -------
        Room
            La Room rimossa, utile per chi vuole conservarne un
            riferimento.

        Solleva
        -------
        ValueError
            Se non esiste una Room con quel room_id, oppure se
            esistono ancora vasi associati a quella Room.
        """
        if room_id not in self._rooms:
            raise ValueError(
                f"Garden '{self.name}': nessuna Room con room_id "
                f"'{room_id}'. Room presenti: "
                f"{list(self._rooms.keys())}"
            )
        # Verifica che nessun vaso sia ancora associato.
        vasi_associati = [
            pot.label for pot in self._pots.values()
            if pot.room_id == room_id
        ]
        if vasi_associati:
            raise ValueError(
                f"Garden '{self.name}': impossibile rimuovere Room "
                f"'{room_id}' perché vi sono ancora associati i vasi "
                f"{vasi_associati}. Disassociali prima (impostando "
                f"il loro room_id a None) o rimuovili dal giardino."
            )
        return self._rooms.pop(room_id)

    @property
    def room_ids(self) -> list[str]:
        """
        Lista degli identificatori delle Room nel giardino, in ordine
        di inserimento.

        Ritorna una **lista**, non il dict interno: il chiamante può
        modificarla liberamente (filtri, ordinamenti) senza alterare
        lo stato del giardino.
        """
        return list(self._rooms.keys())

    def iter_rooms(self) -> Iterator["Room"]:
        """
        Itera sulle Room del giardino, in ordine di inserimento.

        Pattern simmetrico a __iter__ del Garden che itera sui Pot.
        Ho preferito un metodo dedicato `iter_rooms` invece di un
        secondo `__iter__` per evitare ambiguità sull'iterazione di
        default del Garden, che resta sui Pot.
        """
        return iter(self._rooms.values())

    def pots_in_room(self, room_id: str) -> list[Pot]:
        """
        Lista dei vasi del giardino associati alla Room specificata.

        È una utility tipica del bilancio idrico indoor (fase D2): per
        applicare un IndoorMicroclimate a una stanza, vogliamo
        iterare sui vasi che condividono quel microclima.

        Parametri
        ---------
        room_id : str
            Identificatore della Room. Deve esistere nel giardino,
            altrimenti il metodo solleva ValueError per coerenza con
            get_room (un errore chiaro è meglio di una lista vuota
            silenziosa che potrebbe nascondere bug).

        Ritorna
        -------
        list[Pot]
            Lista dei vasi con pot.room_id == room_id, in ordine di
            inserimento nel giardino. Lista vuota se la Room esiste
            ma non ha vasi associati.

        Solleva
        -------
        ValueError
            Se room_id non corrisponde a una Room presente.
        """
        if room_id not in self._rooms:
            raise ValueError(
                f"Garden '{self.name}': nessuna Room con room_id "
                f"'{room_id}'. Room presenti: "
                f"{list(self._rooms.keys())}"
            )
        return [
            pot for pot in self._pots.values()
            if pot.room_id == room_id
        ]

    def num_rooms(self) -> int:
        """Numero di Room nel giardino."""
        return len(self._rooms)

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

    def apply_step_all_from_weather(
        self,
        weather: WeatherDay,
        rainfall_mm: float = 0.0,
        latitude_deg: Optional[float] = None,
        elevation_m: Optional[float] = None,
    ) -> Dict[str, FullStepResult]:
        """
        Applica un passo giornaliero a tutti i vasi del giardino a
        partire dai dati meteo grezzi.

        È il "fratello" di apply_step_all che riceve invece et_0_mm
        già calcolata. Per ogni vaso del giardino chiama
        Pot.apply_step_from_weather, lasciando al selettore di
        evapotraspirazione la scelta della formula migliore disponibile
        per quel vaso. Vasi diversi nello stesso giardino possono
        finire per usare formule diverse: un vaso con specie ben
        caratterizzata fisiologicamente userà Penman-Monteith fisico,
        un vaso con specie generica userà Penman-Monteith standard,
        anche se lo scenario meteo è identico. Il `WeatherDay` passato
        è uguale per tutti perché è una grandezza ambientale del
        giardino, ma la traduzione in ET dipende dai parametri della
        singola specie.

        Una conseguenza pratica: il dizionario di ritorno avrà
        FullStepResult con `balance_result.et_method` potenzialmente
        diversi per ogni vaso. Il chiamante che vuole fare diagnostica
        della qualità delle stime può iterare sui risultati e contare
        quali metodi sono stati selezionati per quale vaso.

        Parametri
        ---------
        weather : WeatherDay
            Dati meteo grezzi del giorno, validi per tutto il giardino.
            La data del WeatherDay (`weather.date_`) è anche la data
            del passo simulato. Le temperature sono sempre obbligatorie;
            gli altri tre dati (umidità, vento, radiazione globale)
            sono opzionali e influenzano la scelta della formula.
        rainfall_mm : float, opzionale
            Quantità di pioggia caduta sull'area aperta, in mm. Default
            0.0 (giorno asciutto). Stessa semantica di apply_step_all:
            convertita in litri per ogni vaso usando la sua surface_area_m2,
            poi modulata internamente dal rainfall_exposure del vaso.
            Lo manteniamo come parametro separato perché concettualmente
            la pioggia "del giorno" non è un dato meteo strumentale come
            T/RH/vento/radiazione: il piranometro non la misura, e nei
            sistemi reali viene tipicamente da un pluviometro distinto
            o da un'osservazione del giardiniere.
        latitude_deg, elevation_m : float, opzionali
            Coordinate geografiche del giardino. Se None, ogni Pot
            deve avere queste informazioni nei propri campi. Nota: il
            Garden non ha attualmente un campo location proprio, quindi
            le coordinate vivono al livello dei singoli Pot. In futuro
            potremmo aggiungere campi `latitude_deg` e `elevation_m`
            anche al Garden per evitare di replicarli su ogni Pot, ma
            per la sotto-tappa C lo lasciamo a livello di Pot.

        Ritorna
        -------
        Dict[str, FullStepResult]
            Dizionario {label: FullStepResult} con il risultato del
            passo per ogni vaso. L'ordine delle chiavi corrisponde
            all'ordine di inserimento dei vasi nel giardino. Ogni
            FullStepResult porta al suo interno un BalanceStepResult
            con `et_method` valorizzato col metodo che il selettore
            ha effettivamente usato per quel vaso.
        """
        if rainfall_mm < 0:
            raise ValueError(
                f"rainfall_mm deve essere non-negativa "
                f"(ricevuto {rainfall_mm})."
            )

        results: Dict[str, FullStepResult] = {}
        for label, pot in self._pots.items():
            # Conversione mm → litri identica a apply_step_all.
            rainfall_volume_l = rainfall_mm * pot.surface_area_m2

            result = pot.apply_step_from_weather(
                weather=weather,
                current_date=weather.date_,
                rainfall_volume_l=rainfall_volume_l,
                latitude_deg=latitude_deg,
                elevation_m=elevation_m,
            )
            results[label] = result

        return results

    # ----- Gestione degli eventi pianificati -----

    def add_scheduled_event(self, event: ScheduledEvent) -> None:
        """
        Aggiunge un evento al piano del giardino.

        Solleva ValueError se la pot_label dell'evento non corrisponde
        a nessun vaso nel giardino: vogliamo evitare eventi "orfani"
        che fanno riferimento a vasi inesistenti.

        Solleva ValueError anche se esiste già un evento con la stessa
        coppia (pot_label, event_id): vogliamo che le coppie siano
        uniche per evitare ambiguità in cancel_scheduled_event.

        Parametri
        ---------
        event : ScheduledEvent
            L'evento da aggiungere. La pot_label deve corrispondere
            a un vaso esistente del giardino.

        Solleva
        -------
        ValueError
            Se la pot_label è di un vaso non esistente, oppure se
            l'evento ha lo stesso (pot_label, event_id) di un evento
            già presente.
        """
        if event.pot_label not in self._pots:
            raise ValueError(
                f"Garden '{self.name}': impossibile aggiungere evento "
                f"per il vaso '{event.pot_label}' che non è presente. "
                f"Vasi presenti: {list(self._pots.keys())}"
            )
        key = (event.pot_label, event.event_id)
        if key in self._scheduled_events:
            raise ValueError(
                f"Garden '{self.name}': esiste già un evento con id "
                f"'{event.event_id}' per il vaso '{event.pot_label}'. "
                f"Per modificarlo, prima cancella quello esistente."
            )
        self._scheduled_events[key] = event

    def cancel_scheduled_event(
        self, pot_label: str, event_id: str,
    ) -> ScheduledEvent:
        """
        Rimuove un evento dal piano e lo restituisce.

        Caso d'uso tipico: il giardiniere ha appena fatto la
        fertirrigazione, quindi rimuove l'evento dal piano e
        contestualmente lo registra come storico via
        ``persistence.record_event``.

        Solleva
        -------
        KeyError
            Se non esiste un evento con quella combinazione di
            pot_label ed event_id.
        """
        key = (pot_label, event_id)
        if key not in self._scheduled_events:
            raise KeyError(
                f"Garden '{self.name}': nessun evento con id "
                f"'{event_id}' per il vaso '{pot_label}'."
            )
        return self._scheduled_events.pop(key)

    def get_scheduled_event(
        self, pot_label: str, event_id: str,
    ) -> ScheduledEvent:
        """Recupera un evento pianificato. KeyError se non esiste."""
        key = (pot_label, event_id)
        if key not in self._scheduled_events:
            raise KeyError(
                f"Garden '{self.name}': nessun evento con id "
                f"'{event_id}' per il vaso '{pot_label}'."
            )
        return self._scheduled_events[key]

    def has_scheduled_event(
        self, pot_label: str, event_id: str,
    ) -> bool:
        """Test booleano di esistenza di un evento."""
        return (pot_label, event_id) in self._scheduled_events

    @property
    def scheduled_events(self) -> List[ScheduledEvent]:
        """
        Lista di tutti gli eventi pianificati del giardino.

        Ordinati per (scheduled_date, pot_label, event_id) per
        produzione deterministica. Ritorna una nuova lista a ogni
        chiamata, modificarla non altera lo stato interno.
        """
        return sorted(
            self._scheduled_events.values(),
            key=lambda e: (e.scheduled_date, e.pot_label, e.event_id),
        )

    def events_due_today(
        self,
        current_date: date,
        pot_label: Optional[str] = None,
    ) -> List[ScheduledEvent]:
        """
        Ritorna gli eventi pianificati per il giorno corrente.

        La definizione di "due today" è restrittiva: ``scheduled_date``
        esattamente uguale a ``current_date``. Eventi con date
        precedenti (in ritardo) NON sono inclusi: per recuperarli usa
        ``events_due_in_range`` con un range che li includa, oppure
        un metodo dedicato (futuro).

        Parametri
        ---------
        current_date : date
            Il giorno per cui cercare eventi pianificati.
        pot_label : str, opzionale
            Se specificato, filtra solo gli eventi del vaso indicato.

        Ritorna
        -------
        List[ScheduledEvent]
            Eventi del giorno, ordinati per (pot_label, event_id).
        """
        result = [
            e for e in self._scheduled_events.values()
            if e.scheduled_date == current_date
            and (pot_label is None or e.pot_label == pot_label)
        ]
        return sorted(result, key=lambda e: (e.pot_label, e.event_id))

    def events_due_in_range(
        self,
        start_date: date,
        end_date: date,
        pot_label: Optional[str] = None,
    ) -> List[ScheduledEvent]:
        """
        Ritorna gli eventi pianificati in un intervallo di date.

        Range inclusivo su entrambi gli estremi. Utile per produrre
        viste "settimana corrente" o "prossimi 30 giorni" nel
        dashboard.

        Parametri
        ---------
        start_date, end_date : date
            Estremi inclusivi dell'intervallo.
        pot_label : str, opzionale
            Filtro per singolo vaso.

        Ritorna
        -------
        List[ScheduledEvent]
            Eventi nel range, ordinati per (scheduled_date, pot_label,
            event_id).
        """
        if start_date > end_date:
            raise ValueError(
                f"start_date ({start_date}) deve essere ≤ end_date "
                f"({end_date})."
            )
        result = [
            e for e in self._scheduled_events.values()
            if start_date <= e.scheduled_date <= end_date
            and (pot_label is None or e.pot_label == pot_label)
        ]
        return sorted(
            result, key=lambda e: (e.scheduled_date, e.pot_label, e.event_id),
        )

    # ----- Forecast: proiezione dello stato nei giorni futuri -----

    def forecast(
        self,
        weather_forecast: List[WeatherDayForecast],
    ) -> "ForecastResult":
        """
        Proietta lo stato del giardino nei giorni futuri.

        Per ogni giorno della previsione meteorologica, il metodo
        applica:

          1. Gli eventi pianificati del giorno (``fertigation``,
             ``leaching``) ai vasi corrispondenti — usando i metodi
             scientifici esistenti di Pot.
          2. L'evapotraspirazione e la pioggia del giorno —
             chiamando ``apply_step`` standard.

        Eventi con event_type diverso da ``fertigation`` e
        ``leaching`` sono ignorati dal forecast (effetti fisiologici
        non modellati nel sistema scientifico corrente di fitosim).

        Proprietà fondamentale: il forecast lavora su **copie deep**
        dei vasi del giardino. Lo stato dei vasi del Garden corrente
        NON viene modificato dalla chiamata. È una previsione "se
        le cose andassero così", non un'evoluzione effettiva del
        modello.

        Parametri
        ---------
        weather_forecast : List[WeatherDayForecast]
            Previsione meteorologica per i giorni successivi. La
            lista deve essere non-vuota e contenere giorni
            consecutivi (la sequenza date_ deve essere ordinata e
            senza buchi). Il metodo non valida la consecutività in
            modo stretto, ma è una proprietà che il chiamante deve
            garantire per ottenere risultati sensati.

        Ritorna
        -------
        ForecastResult
            Per ogni vaso del giardino, la traiettoria proiettata di
            stato (state_mm, salt_mass_meq, ph_substrate, ec_mscm
            derivata) per ogni giorno della previsione.
        """
        if not weather_forecast:
            raise ValueError(
                "weather_forecast deve essere una lista non vuota."
            )

        # Costruisce mappe label→Pot copia per evolvere la simulazione
        # senza toccare i vasi originali.
        pot_copies: Dict[str, Pot] = {
            label: copy.deepcopy(pot)
            for label, pot in self._pots.items()
        }

        # Inizializza le traiettorie con un'entrata per ogni vaso.
        trajectories: Dict[str, "PotForecastTrajectory"] = {
            label: PotForecastTrajectory(pot_label=label, points=[])
            for label in pot_copies
        }

        for day_forecast in weather_forecast:
            day = day_forecast.date_

            # Applica gli eventi pianificati del giorno ai vasi copia.
            for event in self.events_due_today(day):
                if event.pot_label not in pot_copies:
                    # Evento orfano (vaso rimosso dopo che l'evento è
                    # stato pianificato): salta.
                    continue
                pot_copy = pot_copies[event.pot_label]
                self._apply_scheduled_event_to_copy(
                    pot_copy, event, day,
                )

            # Step giornaliero standard (ET₀ + pioggia) su tutti i vasi.
            for label, pot_copy in pot_copies.items():
                rainfall_volume_l = (
                    day_forecast.rainfall_mm * pot_copy.surface_area_m2
                )
                pot_copy.apply_step(
                    et_0_mm=day_forecast.et_0_mm,
                    current_date=day,
                    rainfall_volume_l=rainfall_volume_l,
                )

                # Cattura il punto della traiettoria post-evoluzione.
                trajectories[label].points.append(
                    PotForecastPoint(
                        date_=day,
                        state_mm=pot_copy.state_mm,
                        state_theta=pot_copy.state_theta,
                        salt_mass_meq=pot_copy.salt_mass_meq,
                        ph_substrate=pot_copy.ph_substrate,
                        ec_substrate_mscm=pot_copy.ec_substrate_mscm,
                    )
                )

        return ForecastResult(trajectories=trajectories)

    @staticmethod
    def _apply_scheduled_event_to_copy(
        pot_copy: Pot, event: ScheduledEvent, day: date,
    ) -> None:
        """
        Applica un singolo evento pianificato a un Pot copia,
        chiamando i metodi scientifici esistenti.

        Solo gli event_type "fertigation" e "leaching" sono
        effettivamente simulati; gli altri sono ignorati senza errore
        (comportamento documentato: il forecast non modella tutti i
        tipi di evento).
        """
        if event.event_type == "fertigation":
            payload = event.payload
            pot_copy.apply_fertigation_step(
                volume_l=payload["volume_l"],
                ec_mscm=payload["ec_mscm"],
                ph=payload["ph"],
                current_date=day,
            )
        elif event.event_type == "leaching":
            # Lavaggio: anche questo è una "fertirrigazione" dal punto
            # di vista del modello, ma con acqua quasi pura. Il
            # giardiniere virtuale che pianifica il lavaggio sa che
            # ec_mscm è basso e ph è circa neutro.
            payload = event.payload
            pot_copy.apply_fertigation_step(
                volume_l=payload["volume_l"],
                ec_mscm=payload["ec_mscm"],
                ph=payload.get("ph", 7.0),
                current_date=day,
            )
        # Altri event_type ignorati per il forecast.

    # ----- Sistema di allerte -----

    def current_alerts(
        self, current_date: Optional[date] = None,
    ) -> List[Alert]:
        """
        Calcola le allerte sullo stato corrente di tutti i vasi.

        Per ogni vaso del giardino applica tutte le regole di
        ``ALL_RULES`` e raccoglie le allerte non-None. Le allerte sono
        ordinate per ``(pot_label, category)`` per produrre output
        deterministico tra chiamate consecutive.

        Le allerte **non vengono persistite**: sono il risultato
        dell'applicazione delle regole allo stato corrente. Se il
        chiamante chiama di nuovo il metodo dopo aver modificato lo
        stato (per esempio dopo una fertirrigazione che corregge l'EC
        bassa), l'allerta corrispondente sarà scomparsa.

        Parametri
        ---------
        current_date : date, opzionale
            Data di riferimento per le allerte (popolerà il campo
            ``triggered_date`` di ogni Alert e contribuirà al calcolo
            del suo ``alert_id``). Default: data odierna del sistema.

        Ritorna
        -------
        List[Alert]
            Le allerte attive sullo stato corrente, ordinate per
            ``(pot_label, category)``.
        """
        if current_date is None:
            current_date = date.today()

        alerts: List[Alert] = []
        for pot in self._pots.values():
            for rule in ALL_RULES:
                alert = rule(pot, current_date)
                if alert is not None:
                    alerts.append(alert)

        # Ordinamento deterministico per dare al chiamante un output
        # stabile tra chiamate.
        alerts.sort(key=lambda a: (a.pot_label, a.category.value))
        return alerts

    def forecast_alerts(
        self,
        weather_forecast: List[WeatherDayForecast],
    ) -> List[Alert]:
        """
        Calcola le allerte previste nei prossimi giorni dato un forecast
        meteorologico.

        Per ogni giorno della previsione, il metodo applica gli eventi
        pianificati e l'evapotraspirazione/pioggia ai vasi copia (come
        fa ``forecast``), e poi applica le regole di ``ALL_RULES`` allo
        stato risultante. Le allerte hanno ``triggered_date`` uguale
        al giorno futuro a cui si riferiscono.

        Niente deduplicazione interna: se la stessa allerta scatta per
        più giorni consecutivi nel forecast, restituiamo N allerte
        (una per giorno con id diversi). Il dashboard è responsabile
        di presentare quello che vuole presentare.

        Proprietà fondamentale: come per ``forecast``, lavora su copie
        deep dei vasi. Lo stato del Garden corrente non viene
        modificato.

        Parametri
        ---------
        weather_forecast : List[WeatherDayForecast]
            Previsione meteorologica per i giorni successivi.

        Ritorna
        -------
        List[Alert]
            Le allerte previste nei prossimi giorni, ordinate per
            ``(triggered_date, pot_label, category)``.
        """
        if not weather_forecast:
            raise ValueError(
                "weather_forecast deve essere una lista non vuota."
            )

        # Ricalca il loop interno di forecast: deep copy dei vasi e
        # iterazione giornaliera applicando eventi pianificati e
        # apply_step. Niente refactor del metodo forecast esistente
        # per non rischiare regressioni.
        pot_copies: Dict[str, Pot] = {
            label: copy.deepcopy(pot)
            for label, pot in self._pots.items()
        }

        all_alerts: List[Alert] = []

        for day_forecast in weather_forecast:
            day = day_forecast.date_

            # Applica eventi pianificati del giorno ai vasi copia.
            for event in self.events_due_today(day):
                if event.pot_label not in pot_copies:
                    continue
                pot_copy = pot_copies[event.pot_label]
                self._apply_scheduled_event_to_copy(pot_copy, event, day)

            # Step giornaliero standard.
            for label, pot_copy in pot_copies.items():
                rainfall_volume_l = (
                    day_forecast.rainfall_mm * pot_copy.surface_area_m2
                )
                pot_copy.apply_step(
                    et_0_mm=day_forecast.et_0_mm,
                    current_date=day,
                    rainfall_volume_l=rainfall_volume_l,
                )

            # Applica le regole di alerts allo stato post-evoluzione
            # del giorno per ogni vaso copia.
            for pot_copy in pot_copies.values():
                for rule in ALL_RULES:
                    alert = rule(pot_copy, day)
                    if alert is not None:
                        all_alerts.append(alert)

        all_alerts.sort(
            key=lambda a: (a.triggered_date, a.pot_label, a.category.value),
        )
        return all_alerts


# =======================================================================
#  Strutture di ritorno del forecast
# =======================================================================

@dataclass(frozen=True)
class PotForecastPoint:
    """Singolo punto della traiettoria proiettata di un vaso."""
    date_: date
    state_mm: float
    state_theta: float
    salt_mass_meq: float
    ph_substrate: float
    ec_substrate_mscm: float


@dataclass
class PotForecastTrajectory:
    """Traiettoria proiettata di un singolo vaso nei giorni futuri."""
    pot_label: str
    points: List[PotForecastPoint]


@dataclass(frozen=True)
class ForecastResult:
    """
    Risultato di un forecast del giardino.

    Contiene una traiettoria per ogni vaso del giardino, indicizzata
    per label. Ogni traiettoria è una sequenza di
    ``PotForecastPoint``, una per ogni giorno della previsione
    meteorologica fornita.
    """
    trajectories: Dict[str, PotForecastTrajectory]

