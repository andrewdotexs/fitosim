"""
Vaso reale come entità unificata di dominio.

Il modulo introduce la dataclass `Pot`, che incapsula tutte le
informazioni necessarie a simulare il bilancio idrico di un singolo
vaso del tuo inventario. È il punto di sintesi dei concetti finora
sparsi: una specie, un substrato, una geometria fisica, un'ubicazione
(indoor/outdoor), una data di impianto, uno stato idrico corrente.

Perché serve un'astrazione `Pot`
--------------------------------

Le funzioni del livello scientifico hanno firme con molti parametri
indipendenti — `actual_et_c(species, stage, et_0, theta, substrate)`.
Per un singolo calcolo ad-hoc va bene, ma in un sistema reale dove
gestiamo dieci o venti vasi sul balcone, ricalcolare ogni volta
"qual è la specie? qual è il substrato? qual è il volume?" diventa
una fonte costante di errori (il classico "ho confuso il substrato di
A con la specie di B"). `Pot` risolve questo legando insieme tutto.

L'oggetto `Pot` non è completamente immutabile. La differenza dai
moduli scientifici nasce dalla natura del concetto: lo *stato idrico*
del vaso evolve nel tempo, ed è una caratteristica intrinseca del vaso
non del modello che lo simula. Per questo `Pot` ha un campo `state_mm`
mutabile, mentre tutti gli altri attributi sono immutabili. Le
operazioni di aggiornamento sono esplicite: `apply_balance_step`
restituisce un risultato e modifica `state_mm` in-place, in modo che
il flusso di simulazione sia leggibile dal codice cliente.

Il giorno fenologico viene calcolato dinamicamente dalla data
corrente meno la data di impianto, attraverso il metodo
`current_stage`: questo evita di dover memorizzare lo stadio come
campo redundant e gli permette di evolvere automaticamente nel tempo.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from fitosim.domain.species import (
    PhenologicalStage,
    Species,
    actual_et_c,
)
from fitosim.science.balance import (
    BalanceStepResult,
    water_balance_step_mm,
)
from fitosim.science.substrate import (
    Substrate,
    circular_pot_surface_area_m2,
    mm_to_theta,
    pot_substrate_depth_mm,
    theta_to_mm,
)


class Location(Enum):
    """
    Posizione del vaso rispetto al microclima a cui è esposto.

    Outdoor: il vaso vive il meteo esterno completo (radiazione solare
    diretta, vento, escursioni termiche, eventi piovosi). I dati meteo
    da cui calcolare ET₀ sono quelli della stazione esterna.

    Indoor: il vaso vive un microclima domestico stabilizzato dalla
    climatizzazione, senza pioggia e con radiazione attenuata dal
    vetro. I dati di temperatura/umidità da usare devono provenire da
    un sensore interno (es. WN31 CH1); l'uso di temperature esterne
    produrrebbe stime di ET₀ sistematicamente sbagliate.

    Il livello `io/`, in tappe future, gestirà queste distinzioni
    instradando i sensori giusti verso ogni vaso. Per ora la presenza
    del campo `location` nel `Pot` è un segnale del dominio che
    "qualcosa va trattato diversamente", e gli esempi outdoor restano
    quelli pienamente sviluppati.
    """

    OUTDOOR = "outdoor"
    INDOOR = "indoor"


@dataclass
class Pot:
    """
    Vaso fisico nel tuo inventario.

    Attributi
    ---------
    label : str
        Etichetta libera identificativa (es. "Basilico balcone-1",
        "Limone d'angolo"). Usata in stampe e log.
    species : Species
        Specie coltivata, dal catalogo `domain.species` o creata ad-hoc.
    substrate : Substrate
        Substrato in uso, dal catalogo `science.substrate` o ad-hoc.
    pot_volume_l : float
        Volume in litri di substrato realmente contenuto nel vaso.
        È il volume di riempimento, non quello geometrico esterno.
    pot_diameter_cm : float
        Diametro della superficie superiore del vaso in centimetri.
        Per vasi non cilindrici si fornisce un diametro equivalente che
        riproduce la stessa area di evaporazione.
    location : Location
        Outdoor o indoor. Determina la fonte dei dati meteorologici.
    planting_date : date
        Data di impianto/semina/trapianto, riferimento per il calcolo
        dello stadio fenologico.
    state_mm : float, opzionale
        Contenuto idrico corrente in mm di colonna equivalente. Se
        non specificato, viene inizializzato a capacità di campo
        (vaso "appena irrigato"). MUTABILE — è l'unico campo che
        evolve durante la simulazione.
    notes : str, opzionale
        Note libere (es. "trapiantato dal balcone alla veranda
        a settembre", "potatura il 15/3", ecc.).

    Geometria derivata
    ------------------
    Le tre quantità geometriche `surface_area_m2`, `substrate_depth_mm`
    e i tre livelli idrici `fc_mm`, `pwp_mm`, `alert_mm` non sono campi
    ma proprietà calcolate al volo. È una scelta di progetto: queste
    quantità sono derivabili in modo deterministico dai campi base e
    duplicarle sarebbe una fonte di incoerenza se domani volessimo
    modificare un vaso (cosa che oggi non facciamo, ma potremmo
    decidere di farlo in versioni successive).
    """

    label: str
    species: Species
    substrate: Substrate
    pot_volume_l: float
    pot_diameter_cm: float
    location: Location
    planting_date: date
    state_mm: float = field(default=-1.0)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.pot_volume_l <= 0:
            raise ValueError(
                f"Vaso '{self.label}': pot_volume_l deve essere "
                f"positivo (ricevuto {self.pot_volume_l})."
            )
        if self.pot_diameter_cm <= 0:
            raise ValueError(
                f"Vaso '{self.label}': pot_diameter_cm deve essere "
                f"positivo (ricevuto {self.pot_diameter_cm})."
            )
        # Inizializzazione automatica dello stato a capacità di campo
        # se l'utente non ha fornito un valore esplicito (sentinella -1).
        # Usiamo questa sentinella invece di Optional[float]/None per
        # mantenere il tipo del campo coerente (sempre float) ed evitare
        # branching su None in tutti i metodi.
        if self.state_mm < 0:
            self.state_mm = self.fc_mm

    # -------------------------------------------------------------------
    #  Proprietà geometriche derivate
    # -------------------------------------------------------------------

    @property
    def surface_area_m2(self) -> float:
        """Area della superficie di evaporazione del vaso."""
        return circular_pot_surface_area_m2(self.pot_diameter_cm)

    @property
    def substrate_depth_mm(self) -> float:
        """Profondità effettiva del substrato (volume / area)."""
        return pot_substrate_depth_mm(
            self.pot_volume_l, self.surface_area_m2
        )

    @property
    def fc_mm(self) -> float:
        """Capacità di campo del vaso, in mm."""
        return self.substrate.theta_fc * self.substrate_depth_mm

    @property
    def pwp_mm(self) -> float:
        """Punto di appassimento permanente del vaso, in mm."""
        return self.substrate.theta_pwp * self.substrate_depth_mm

    @property
    def alert_mm(self) -> float:
        """
        Soglia di allerta operativa in mm, calcolata con la frazione
        di deplezione specifica della specie. È sotto questo livello
        che il `apply_balance_step` setta `under_alert=True`.
        """
        taw = self.substrate.theta_fc - self.substrate.theta_pwp
        raw_fraction = self.species.depletion_fraction * taw
        return (self.substrate.theta_fc - raw_fraction) * \
            self.substrate_depth_mm

    @property
    def state_theta(self) -> float:
        """Stato corrente espresso come θ adimensionale."""
        return mm_to_theta(self.state_mm, self.substrate_depth_mm)

    # -------------------------------------------------------------------
    #  Metodi di domain logic
    # -------------------------------------------------------------------

    def days_since_planting(self, current_date: date) -> int:
        """
        Numero di giorni trascorsi dall'impianto fino alla data data.

        Può essere negativo se la data di osservazione precede
        l'impianto: in quel caso il caller deve aspettarsi un comportamento
        di "vaso non ancora attivato" — gestito dolcemente da
        `current_stage` che ritorna INITIAL.
        """
        return (current_date - self.planting_date).days

    def current_stage(self, current_date: date) -> PhenologicalStage:
        """Stadio fenologico in vigore alla data corrente."""
        return self.species.stage_at_day(
            self.days_since_planting(current_date)
        )

    def current_et_c(self, et_0_mm: float, current_date: date) -> float:
        """
        Evapotraspirazione reale della coltura nel vaso, in mm/giorno.

        Combina ET₀ del giorno con i parametri del vaso (specie, stadio
        derivato dalla data, substrato e stato idrico corrente). È la
        forma "pulita" della chiamata: l'esterno fornisce solo il
        meteo, tutto il resto è nel vaso.
        """
        return actual_et_c(
            species=self.species,
            stage=self.current_stage(current_date),
            et_0=et_0_mm,
            current_theta=self.state_theta,
            substrate=self.substrate,
        )

    def apply_balance_step(
        self,
        et_0_mm: float,
        water_input_mm: float,
        current_date: date,
    ) -> BalanceStepResult:
        """
        Esegue un passo di bilancio idrico (giornaliero) sul vaso.

        Aggiorna `state_mm` in-place e restituisce il `BalanceStepResult`
        del passo. La progettazione "side-effect + return" è
        deliberatamente esplicita: il caller vede il risultato (per
        notifiche, log, allerte) e sa che lo stato del vaso è cambiato.

        Parametri
        ---------
        et_0_mm : float
            ET di riferimento del giorno, in mm. Nel mondo reale viene
            da Hargreaves-Samani applicata ai dati meteo del sito.
        water_input_mm : float
            Acqua entrata nel vaso oggi (irrigazione + pioggia
            efficace), in mm. Non negativo.
        current_date : date
            Data corrente, usata per determinare lo stadio fenologico.
        """
        et_c_mm = self.current_et_c(et_0_mm, current_date)
        result = water_balance_step_mm(
            current_mm=self.state_mm,
            water_input_mm=water_input_mm,
            et_c_mm=et_c_mm,
            substrate=self.substrate,
            substrate_depth_mm=self.substrate_depth_mm,
            depletion_fraction=self.species.depletion_fraction,
        )
        self.state_mm = result.new_state
        return result

    def water_to_field_capacity(self) -> float:
        """
        Quantità di acqua in mm necessaria a riportare il vaso a
        capacità di campo dallo stato attuale. È il "consiglio di
        irrigazione" più semplice: se l'algoritmo decide di irrigare,
        questa è la dose suggerita.
        """
        return max(0.0, self.fc_mm - self.state_mm)

    def water_to_field_capacity_liters(self) -> float:
        """Stessa cosa di water_to_field_capacity ma in litri."""
        return self.water_to_field_capacity() * self.surface_area_m2
