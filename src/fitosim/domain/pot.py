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
from fitosim.science.dual_kc import (
    DEFAULT_FEW,
    evaporation_reduction_coefficient,
    soil_evaporation_coefficient,
    update_de,
)
from fitosim.science.pot_physics import (
    PotColor,
    PotMaterial,
    SunExposure,
    pot_correction_factor,
)
from fitosim.science.saucer import (
    capillary_transfer,
    saucer_evaporation,
)
from fitosim.science.substrate import (
    Substrate,
    circular_pot_surface_area_m2,
    mm_to_theta,
    oval_pot_surface_area_m2,
    pot_substrate_depth_mm,
    rectangular_pot_surface_area_m2,
    theta_to_mm,
    truncated_cone_pot_surface_area_m2,
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


class PotShape(Enum):
    """
    Forma del vaso, da cui dipende la geometria della superficie
    evaporante. La forma non altera direttamente il consumo idrico
    per unità di superficie (questo è compito di material/color/
    exposure), ma determina **quanta** superficie c'è per evaporare a
    parità di volume.

    Per vasi cilindrici e tronco-conici (la maggior parte dei vasi
    rotondi del giardinaggio) usiamo il diametro alla sommità: nei
    tronco-conici la superficie superiore è ciò che conta per il
    bilancio idrico, e il diametro alla base è solo un parametro
    estetico/strutturale.
    """

    CYLINDRICAL = "cylindrical"
    """Cilindrico classico (lati paralleli)."""

    TRUNCATED_CONE = "truncated_cone"
    """
    Tronco-conico con base più stretta dell'apertura. Tipico dei vasi
    in plastica e terracotta da vivaio. Geometricamente equivale al
    cilindro per il bilancio idrico (la superficie evaporante è
    quella superiore), ma viene tenuto come categoria a parte per
    chiarezza descrittiva.
    """

    RECTANGULAR = "rectangular"
    """Cassetta o fioriera a base rettangolare/quadrata."""

    OVAL = "oval"
    """Vaso a base ellittica (planter ovali, terrine)."""


@dataclass(frozen=True)
class SensorUpdateResult:
    """
    Risultato strutturato dell'aggiornamento del vaso da una lettura
    del sensore di umidità.

    Quando si chiama `Pot.update_from_sensor(theta_observed)`, il vaso
    confronta la propria previsione corrente con l'osservazione del
    sensore, calcola la discrepanza, e si aggiorna per allinearsi alla
    realtà. Questo oggetto raccoglie tutti i dati prodotti durante
    quell'operazione, in modo che il chiamante possa fare logging,
    detezione di drift, allerta automatica, o qualunque altra azione.

    Convenzione del segno della discrepanza
    ----------------------------------------
    `discrepancy_theta = observed - predicted` (e analogamente per mm).

      Valore POSITIVO: il sensore vede più acqua del previsto. Possibili
        cause: il modello ha sovrastimato il consumo, c'è stato un
        evento di bagnatura non registrato (pioggia improvvisa, vicino
        che ha innaffiato, etc.), oppure il θ_FC effettivo è superiore
        a quello che il modello sta usando.

      Valore NEGATIVO: il sensore vede meno acqua del previsto. Possibili
        cause: il modello ha sottostimato il consumo (giornata più
        calda/ventosa di quanto ET₀ catturasse), oppure il θ_FC
        effettivo è inferiore a quello che il modello sta usando.

    Una serie storica di queste discrepanze è il segnale principale
    per detectare la necessità di una ricalibrazione dei parametri
    del substrato.

    Attributi
    ---------
    predicted_theta : float
        Stato θ del vaso secondo il modello, prima dell'aggiornamento.
    observed_theta : float
        Lettura del sensore, in θ.
    predicted_mm : float
        Stesso predicted_theta ma espresso in mm di colonna d'acqua.
    observed_mm : float
        Stesso observed_theta ma espresso in mm di colonna d'acqua.
    discrepancy_theta : float
        observed_theta - predicted_theta (con segno).
    discrepancy_mm : float
        observed_mm - predicted_mm (con segno).
    relative_error_pct : float
        (discrepancy_mm / predicted_mm) × 100, con segno. Vale 0 se
        predicted_mm è zero.
    observed_temperature_c : float | None
        Temperatura del substrato letta dal sensore, in °C. Aggiunto in
        tappa 2 della fascia 2: valorizzato solo quando l'aggiornamento
        viene fatto con un SoilReading "ricco" (es. da ATO 7-in-1 via
        HttpJsonSoilSensor); None per gli aggiornamenti via float
        legacy o per sensori che non misurano la temperatura
        (es. WH51).
    observed_ec_mscm : float | None
        Conducibilità elettrica del substrato letta dal sensore, in
        mS/cm a 25°C. Per ora puramente informativa (logging
        diagnostico): la fertirrigazione della tappa 3 userà questo
        campo per aggiornare lo stato `ec_mm` del vaso.
    observed_ph : float | None
        Acidità del substrato letta dal sensore, scala 0..14. Per ora
        informativa; tappa 3 la userà per il coefficiente Kn.
    provider_specific : dict
        Dati di "secondo livello" del provider (es. NPK derivati
        dall'ATO 7-in-1) preservati opachi per logging diagnostico
        e presentazione nel dashboard. Default dict vuoto.
    predicted_ec_mscm : float | None
        EC del substrato secondo il modello, prima dell'aggiornamento
        dal sensore. Aggiunto in sotto-tappa E della tappa 3 fascia 2.
        Valorizzato solo quando il SoilReading porta un valore
        observed_ec_mscm e quando lo state_mm finale del Pot è > 0
        (altrimenti l'EC predetta sarebbe indefinita). Permette al
        chiamante di calcolare la discrepanza chimica ec → modello vs
        sensore per il logging e la detezione di drift chimico.
    predicted_ph : float | None
        pH del substrato secondo il modello, prima dell'aggiornamento.
        Valorizzato quando il SoilReading porta un valore observed_ph.
        Stessa logica diagnostica del predicted_ec_mscm.
    discrepancy_ec_mscm : float | None
        observed_ec_mscm - predicted_ec_mscm, con segno. Valorizzato
        quando entrambi i campi sono disponibili. Positivo = sensore
        vede più sali del modello (concentrazione progressiva non
        catturata, fertirrigazione misurata dal sensore prima del
        modello, ecc.). Negativo = sensore vede meno sali del modello.
    discrepancy_ph : float | None
        observed_ph - predicted_ph, con segno. Valorizzato quando
        entrambi i campi sono disponibili.
    """

    predicted_theta: float
    observed_theta: float
    predicted_mm: float
    observed_mm: float
    discrepancy_theta: float
    discrepancy_mm: float
    relative_error_pct: float
    # Campi aggiunti in tappa 2 fascia 2: dati extra dei sensori "ricchi"
    # come l'ATO 7-in-1. Tutti opzionali con default per retrocompat
    # totale: chi costruisce SensorUpdateResult senza passarli (es. il
    # codice della fascia 1) continua a funzionare senza modifiche.
    observed_temperature_c: Optional[float] = None
    observed_ec_mscm: Optional[float] = None
    observed_ph: Optional[float] = None
    provider_specific: dict = field(default_factory=dict)
    # Campi aggiunti in sotto-tappa E della tappa 3 fascia 2: stato
    # chimico predetto dal modello prima dell'aggiornamento, e
    # discrepanze rispetto al sensore. Permettono al chiamante di
    # detectare drift chimico nel tempo, esattamente come per il
    # drift idrico.
    predicted_ec_mscm: Optional[float] = None
    predicted_ph: Optional[float] = None
    discrepancy_ec_mscm: Optional[float] = None
    discrepancy_ph: Optional[float] = None

    @property
    def absolute_error_mm(self) -> float:
        """Errore assoluto in mm, sempre non-negativo."""
        return abs(self.discrepancy_mm)

    @property
    def is_significant(self) -> bool:
        """
        True se la discrepanza supera la soglia tipica del rumore del
        sensore. Usa una soglia di 0.02 in θ (corrisponde a ~2 deviazioni
        standard del rumore tipico del WH51 dopo aggregazione giornaliera).
        Discrepanze inferiori sono compatibili col rumore e non vanno
        considerate "vere" deviazioni.
        """
        return abs(self.discrepancy_theta) > 0.02


# =======================================================================
#  Risultati strutturati per la fertirrigazione (sotto-tappa C tappa 3)
# =======================================================================

@dataclass(frozen=True)
class FertigationResult:
    """
    Esito di un singolo evento di fertirrigazione applicato al vaso.

    Restituito da `Pot.apply_fertigation_step` e `Pot.apply_rainfall_step`.
    Contiene tutti i dati prodotti dal calcolo chimico, in formato adatto
    al logging diagnostico, alla detezione di anomalie, e alla
    presentazione nel dashboard del giardiniere.

    Attributi
    ---------
    event_date : date
        Data dell'evento, propagata per il logging.
    volume_input_l : float
        Volume di soluzione in arrivo, in litri.
    volume_input_mm : float
        Stessa quantità espressa in mm di colonna d'acqua sul vaso.
    ec_input_mscm : float
        Conducibilità elettrica della soluzione in arrivo, in mS/cm.
    ph_input : float
        pH della soluzione in arrivo, scala 0-14.
    salt_mass_before_meq, salt_mass_after_meq : float
        Massa salina del vaso prima e dopo l'evento, in
        milli-equivalenti.
    salt_mass_added_meq : float
        Massa salina entrata con la soluzione (= EC × V × 10).
    salt_mass_drained_meq : float
        Massa salina uscita col drenaggio (zero se non c'è stato
        drenaggio).
    water_drained_l, water_drained_mm : float
        Volume di acqua drenato, in litri e in mm rispettivamente.
    ph_before, ph_after : float
        pH del substrato prima e dopo l'evento.
    ph_delta : float
        ph_after - ph_before, con segno. Positivo = pH è salito,
        negativo = pH è sceso.
    """

    event_date: date
    volume_input_l: float
    volume_input_mm: float
    ec_input_mscm: float
    ph_input: float
    salt_mass_before_meq: float
    salt_mass_after_meq: float
    salt_mass_added_meq: float
    salt_mass_drained_meq: float
    water_drained_l: float
    water_drained_mm: float
    ph_before: float
    ph_after: float
    ph_delta: float


@dataclass(frozen=True)
class FullStepResult:
    """
    Esito aggregato di un passo completo del vaso (sotto-tappa C tappa 3).

    Restituito da `Pot.apply_step`. Aggrega i risultati di tutti gli
    eventi possibili di un giorno: bilancio idrico (sempre presente),
    pioggia naturale (opzionale), fertirrigazione (opzionale).

    Attributi
    ---------
    event_date : date
        Data del passo.
    balance_result : BalanceStepResult
        Risultato del bilancio idrico giornaliero (ET, drenaggio,
        nuovo stato). Sempre presente.
    rainfall_result : FertigationResult | None
        Risultato dell'evento pioggia, se presente. None altrimenti.
    fertigation_result : FertigationResult | None
        Risultato dell'evento fertirrigazione, se presente. None
        altrimenti.
    """

    event_date: date
    balance_result: "BalanceStepResult"
    rainfall_result: Optional[FertigationResult] = None
    fertigation_result: Optional[FertigationResult] = None


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
        Diametro principale della superficie superiore in cm. Il suo
        ruolo dipende da `pot_shape`: per CYLINDRICAL e TRUNCATED_CONE
        è il diametro circolare; per RECTANGULAR è la lunghezza del
        lato lungo (e va affiancato da `pot_width_cm`); per OVAL è
        l'asse maggiore. Restando questo l'unico parametro
        dimensionale richiesto, vasi non circolari devono fornire
        anche `pot_width_cm`.
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
    pot_shape : PotShape, opzionale
        Forma del vaso. Default CYLINDRICAL per retrocompatibilità.
    pot_width_cm : float | None, opzionale
        Seconda dimensione lineare richiesta per forme non rotonde
        (RECTANGULAR: larghezza; OVAL: asse minore). Per CYLINDRICAL e
        TRUNCATED_CONE viene ignorato.
    pot_material : PotMaterial, opzionale
        Materiale del contenitore. Default PLASTIC (riferimento neutro).
        Influenza la perdita laterale per evaporazione.
    pot_color : PotColor, opzionale
        Colore prevalente. Default MEDIUM (neutro). Modula
        l'assorbimento solare.
    sun_exposure : SunExposure, opzionale
        Esposizione solare effettiva del vaso. Default FULL_SUN
        (ipotesi conservativa = massimo consumo). È il fattore
        correttivo con effetto più grande dei tre.
    active_depth_fraction : float, opzionale
        Frazione di profondità del substrato che è davvero attiva per
        la pianta, ovvero non occupata da uno strato drenante in
        fondo. 1.0 = nessuno strato drenante (default); 0.85 =
        drenaggio standard di pomice/argilla espansa di ~15% del
        volume; 0.70 = drenaggio importante tipico del bonsai.
    notes : str, opzionale
        Note libere (es. "trapiantato dal balcone alla veranda
        a settembre", "potatura il 15/3", ecc.).

    Geometria derivata
    ------------------
    Le quantità `surface_area_m2`, `substrate_depth_mm`, `fc_mm`,
    `pwp_mm`, `alert_mm`, e il nuovo coefficiente di vaso `kp`, non
    sono campi ma proprietà calcolate al volo dai campi base. È una
    scelta di progetto: queste quantità sono derivabili in modo
    deterministico, e duplicarle introdurrebbe rischio di incoerenza
    se modificassimo i parametri base in futuro.
    """

    label: str
    species: Species
    substrate: Substrate
    pot_volume_l: float
    pot_diameter_cm: float
    location: Location
    planting_date: date
    state_mm: float = field(default=-1.0)
    pot_shape: PotShape = PotShape.CYLINDRICAL
    pot_width_cm: Optional[float] = None
    pot_material: PotMaterial = PotMaterial.PLASTIC
    pot_color: PotColor = PotColor.MEDIUM
    sun_exposure: SunExposure = SunExposure.FULL_SUN
    active_depth_fraction: float = 1.0
    # ----- Sottovaso (opzionale) -----
    # Se saucer_capacity_mm è None, il vaso non ha sottovaso e si
    # comporta esattamente come prima dell'estensione (compatibilità
    # retroattiva totale). Se ha un valore, il sottovaso è attivo e
    # i metodi del bilancio orchestrano il trasferimento capillare e
    # l'evaporazione del piattino.
    saucer_capacity_mm: Optional[float] = None
    saucer_state_mm: float = 0.0
    saucer_capillary_rate: float = 0.4
    saucer_evap_coef: float = 0.4
    # ----- Stato del dual-Kc (FAO-56 cap. 7) -----
    # Cumulative depletion dello strato superficiale del substrato in mm.
    # Cresce giorno per giorno con l'evaporazione superficiale e si
    # riduce con gli input idrici. È usato solo quando la specie e il
    # substrato supportano entrambi il dual-Kc; in caso contrario il
    # campo è presente ma inerte. Default 0.0 = "substrato appena
    # bagnato", coerente con l'inizializzazione di state_mm a FC.
    de_mm: float = 0.0
    # ----- Stato chimico del substrato (tappa 3 fascia 2) -----
    # Massa salina totale presente nel vaso, in milli-equivalenti. È
    # lo stato canonico della "salinità" del substrato: cresce con le
    # fertirrigazioni ed è (leggermente) diminuita dal drenaggio quando
    # un'aggiunta idrica supera la capacità di campo. L'EC corrente
    # (in mS/cm) è una grandezza derivata, calcolata come property dal
    # rapporto salt_mass_meq / volume_acqua_corrente, e in questo modo
    # cattura automaticamente il fenomeno della concentrazione per
    # evapotraspirazione.
    #
    # Default 0.0: il vaso "appena rinvasato in terriccio fresco" non
    # ha praticamente sali. Per inizializzare un vaso preesistente con
    # storia di fertilizzazione, il chiamante passa il valore esplicito
    # (può stimarlo dalla lettura di un sensore EC del substrato).
    salt_mass_meq: float = 0.0
    # pH del substrato corrente, scala 0-14. È stato mutabile ed evolve
    # nel tempo per fertirrigazioni e piogge secondo il modello di
    # buffering modulato dalla CEC del substrato (sotto-tappa C).
    #
    # Sentinel -1.0: il campo non è stato specificato dal chiamante e
    # __post_init__ risolverà la gerarchia "esplicito > substrato > 7.0"
    # (vedi sotto). Quando il chiamante passa un valore esplicito (per
    # esempio perché ha appena letto il sensore ATO) quello ha la
    # precedenza; quando lascia il default si usa il ph_typical del
    # Substrate; in ultima istanza si ricade sul neutro 7.0.
    ph_substrate: float = -1.0
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
        if not 0.0 < self.active_depth_fraction <= 1.0:
            raise ValueError(
                f"Vaso '{self.label}': active_depth_fraction deve "
                f"stare in (0, 1] (ricevuto {self.active_depth_fraction})."
            )
        # Forme non-rotonde richiedono pot_width_cm.
        if self.pot_shape in (PotShape.RECTANGULAR, PotShape.OVAL):
            if self.pot_width_cm is None or self.pot_width_cm <= 0:
                raise ValueError(
                    f"Vaso '{self.label}': forma {self.pot_shape.value} "
                    f"richiede pot_width_cm positivo "
                    f"(ricevuto {self.pot_width_cm})."
                )
        # Validazione del sottovaso: se la capacità è specificata, deve
        # essere positiva, e lo stato iniziale non deve eccederla.
        if self.saucer_capacity_mm is not None:
            if self.saucer_capacity_mm <= 0:
                raise ValueError(
                    f"Vaso '{self.label}': saucer_capacity_mm deve "
                    f"essere positivo se specificato "
                    f"(ricevuto {self.saucer_capacity_mm})."
                )
            if self.saucer_state_mm < 0:
                raise ValueError(
                    f"Vaso '{self.label}': saucer_state_mm non può "
                    f"essere negativo (ricevuto {self.saucer_state_mm})."
                )
            if self.saucer_state_mm > self.saucer_capacity_mm:
                raise ValueError(
                    f"Vaso '{self.label}': saucer_state_mm "
                    f"({self.saucer_state_mm}) eccede "
                    f"saucer_capacity_mm ({self.saucer_capacity_mm})."
                )
            if self.saucer_capillary_rate <= 0:
                raise ValueError(
                    f"Vaso '{self.label}': saucer_capillary_rate deve "
                    f"essere positivo "
                    f"(ricevuto {self.saucer_capillary_rate})."
                )
            if self.saucer_evap_coef < 0:
                raise ValueError(
                    f"Vaso '{self.label}': saucer_evap_coef deve "
                    f"essere ≥ 0 (ricevuto {self.saucer_evap_coef})."
                )
        # Inizializzazione automatica dello stato a capacità di campo
        # se l'utente non ha fornito un valore esplicito (sentinella -1).
        # Usiamo questa sentinella invece di Optional[float]/None per
        # mantenere il tipo del campo coerente (sempre float) ed evitare
        # branching su None in tutti i metodi.
        if self.state_mm < 0:
            self.state_mm = self.fc_mm

        # Inizializzazione del pH del substrato secondo la gerarchia
        # "esplicito > substrato.ph_typical > neutro 7.0". La sentinella
        # -1.0 ESATTA indica che il chiamante non ha specificato un
        # valore esplicito, quindi consultiamo il substrato. Stesso
        # pattern di state_mm sopra, ma con check stretto invece che
        # "negativo": questo protegge contro errori del chiamante che
        # passa per sbaglio un pH negativo (per esempio per un bug nel
        # calcolo a monte) — un negativo non-sentinel cadrà nel check
        # di range fisico subito sotto e solleverà ValueError.
        if self.ph_substrate == -1.0:
            self.ph_substrate = self.substrate.effective_ph_typical

        # Validazione dello stato chimico finale. ph_substrate deve
        # essere nella scala chimica [0, 14]; salt_mass_meq deve essere
        # non-negativa (zero è il caso "vaso appena rinvasato" perfetta-
        # mente legittimo).
        if not 0.0 < self.ph_substrate < 14.0:
            raise ValueError(
                f"Vaso '{self.label}': ph_substrate="
                f"{self.ph_substrate} è fuori scala chimica (0, 14). "
                f"Verifica il valore passato al costruttore o il "
                f"ph_typical del substrato '{self.substrate.name}'."
            )
        if self.salt_mass_meq < 0:
            raise ValueError(
                f"Vaso '{self.label}': salt_mass_meq="
                f"{self.salt_mass_meq} non può essere negativo. "
                f"Default 0.0 per vaso appena rinvasato."
            )

    # -------------------------------------------------------------------
    #  Proprietà geometriche derivate
    # -------------------------------------------------------------------

    @property
    def surface_area_m2(self) -> float:
        """
        Area della superficie evaporante (sommità del vaso) in m².

        Dispatch sulla forma: vasi rotondi usano il diametro circolare;
        rettangolari moltiplicano i due lati; ovali usano la formula
        dell'ellisse. Il dispatch è la ragione per cui pot_shape e
        pot_width_cm sono campi separati.
        """
        if self.pot_shape == PotShape.CYLINDRICAL:
            return circular_pot_surface_area_m2(self.pot_diameter_cm)
        if self.pot_shape == PotShape.TRUNCATED_CONE:
            return truncated_cone_pot_surface_area_m2(self.pot_diameter_cm)
        if self.pot_shape == PotShape.RECTANGULAR:
            assert self.pot_width_cm is not None  # garantito da __post_init__
            return rectangular_pot_surface_area_m2(
                self.pot_diameter_cm, self.pot_width_cm,
            )
        if self.pot_shape == PotShape.OVAL:
            assert self.pot_width_cm is not None
            return oval_pot_surface_area_m2(
                self.pot_diameter_cm, self.pot_width_cm,
            )
        # Difensivo: in caso di estensione futura dell'enum senza
        # aggiornamento del dispatch, vogliamo un errore loquace
        # invece di un comportamento silenziosamente sbagliato.
        raise ValueError(
            f"Vaso '{self.label}': forma {self.pot_shape!r} non gestita."
        )

    @property
    def substrate_depth_mm(self) -> float:
        """
        Profondità *attiva* del substrato in mm, ovvero la parte
        effettivamente disponibile per le radici e quindi per il
        bilancio idrico.

        Si ottiene moltiplicando la profondità geometrica
        (volume/area) per `active_depth_fraction`. Per i vasi senza
        strato drenante (default) la frazione è 1.0 e questa quantità
        coincide con la profondità totale; per i vasi con drenaggio in
        fondo il volume "attivo" si riduce, e con esso la riserva
        idrica disponibile.
        """
        nominal_depth = pot_substrate_depth_mm(
            self.pot_volume_l, self.surface_area_m2,
        )
        return nominal_depth * self.active_depth_fraction

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

    @property
    def water_volume_liters(self) -> float:
        """
        Volume corrente di acqua nel substrato, in litri.

        Aggiunto in tappa 3 della fascia 2: serve come denominatore nel
        calcolo dell'EC e in generale in tutti i bilanci di massa
        chimici dove "concentrazione" significa "massa per unità di
        volume di acqua". Lo state_mm è già una colonna d'acqua espressa
        in millimetri sopra la superficie del vaso, e moltiplicandolo
        per l'area in m² (e convertendo l'unità: mm × m² = L) si ottiene
        direttamente il volume.
        """
        return self.state_mm * self.surface_area_m2

    @property
    def ec_substrate_mscm(self) -> float:
        """
        Conducibilità elettrica della soluzione interstiziale del
        substrato, in mS/cm a 25°C.

        Aggiunto in tappa 3 della fascia 2 come grandezza DERIVATA
        dallo stato canonico (salt_mass_meq, state_mm). NON è un campo
        memorizzato — è ricalcolata ad ogni accesso dalla relazione:

            EC [mS/cm]  =  (salt_mass [meq] / water_volume [L]) / 10

        Il fattore 10 è la costante chimica di conversione tra
        concentrazione equivalente molare e EC, valida per soluzioni
        "tipiche" di terreno con cationi misti (calcio, magnesio,
        potassio dominanti). Ha errore approssimativo del 10-15%
        rispetto al calcolo ionico esatto, completamente accettabile
        per i nostri scopi visto che il sensore ATO ha lui stesso
        errori dello stesso ordine.

        Caso degenere: se water_volume_liters è zero (vaso totalmente
        asciutto secondo il modello, situazione patologica di simulazione
        senza calibrazione da sensore), ritorniamo 0.0 per non sollevare
        ZeroDivisionError. È convenzione, non fisica: se davvero il vaso
        fosse a zero acqua i sali sarebbero cristallizzati e l'EC della
        "soluzione" è indefinita.
        """
        if self.water_volume_liters <= 0:
            return 0.0
        meq_per_liter = self.salt_mass_meq / self.water_volume_liters
        return meq_per_liter / 10.0

    @property
    def substrate_dry_mass_kg(self) -> float:
        """
        Massa secca del substrato presente nel vaso, in chilogrammi.

        Aggiunto in sotto-tappa C della tappa 3 fascia 2: serve come
        input alla formula del buffering del pH durante la fertirrigazione,
        dove il "peso" del substrato nel mescolamento è proporzionale
        alla sua massa fisica × CEC.

        Calcolo: il volume effettivo di substrato è
        `pot_volume_l × active_depth_fraction` (la frazione attiva
        tiene conto dello strato superficiale eventualmente non popolato
        da radici, modellato in tappa 4 della fascia 1). La massa secca
        si ottiene moltiplicando per la densità tipica dei terricci da
        giardinaggio domestico (0.4 kg/L). Per un vaso da 2 L con
        active_depth_fraction=1 si ottiene 0.8 kg, valore di riferimento
        usato negli esempi della docstring del modulo
        `science/fertigation.py`.

        Nota: questa è una stima a partire dal volume, non un dato
        misurato. Per il giardiniere che pesa effettivamente il substrato
        prima di rinvasare, il valore reale potrebbe differire di qualche
        decina di percento dalla stima. È un'approssimazione coerente
        con la filosofia di fitosim di "modello semplice ma calibrabile".
        """
        from fitosim.science.fertigation import (
            TYPICAL_SUBSTRATE_DENSITY_KG_PER_L,
        )
        active_volume_l = self.pot_volume_l * self.active_depth_fraction
        return active_volume_l * TYPICAL_SUBSTRATE_DENSITY_KG_PER_L

    @property
    def kp(self) -> float:
        """
        Coefficiente di vaso Kp, fattore moltiplicativo che modula
        ET_c in base alle caratteristiche fisiche del contenitore.

        Calcolato come prodotto di tre sotto-fattori indipendenti:
        materiale (porosità laterale), colore (assorbimento solare)
        ed esposizione (carico radiativo effettivo). Per un vaso con
        i default (PLASTIC, MEDIUM, FULL_SUN) Kp = 1.00, e il modello
        si comporta come il FAO-56 base.
        """
        return pot_correction_factor(
            material=self.pot_material,
            color=self.pot_color,
            exposure=self.sun_exposure,
        )

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

    @property
    def supports_dual_kc(self) -> bool:
        """
        True se il vaso ha tutti i parametri necessari per il modello
        dual-Kc di FAO-56 cap. 7, ovvero la specie ha i Kcb valorizzati
        e il substrato ha REW e TEW. Quando questo è vero, current_et_c
        e apply_balance_step usano il dual-Kc; altrimenti ricadono sul
        single Kc tradizionale.
        """
        return (
            self.species.supports_dual_kc
            and self.substrate.rew_mm is not None
            and self.substrate.tew_mm is not None
        )

    def _current_et_c_dual_kc(
        self,
        et_0_mm: float,
        current_date: date,
    ) -> tuple[float, float]:
        """
        Calcolo del dual-Kc per il giorno corrente.

        Restituisce una tupla (et_c_total, soil_evaporation), entrambi
        in mm/giorno. La separazione è utile per chi orchestra
        apply_balance_step, che ha bisogno di sapere quanta acqua è
        evaporata dalla superficie per aggiornare De.

        La formula completa è:

            ET_c,act = Kp × (Ks × Kcb + Ke) × ET_0
            E_actual = Kp × Ke × ET_0  (quota di evaporazione superf.)

        dove Ks modula solo Kcb (traspirazione, dipende dall'umidità
        del bulk), mentre Ke ha già Kr che modula la disponibilità
        della superficie.
        """
        from fitosim.science.balance import stress_coefficient_ks
        stage = self.current_stage(current_date)
        # Recupero Kcb per lo stadio corrente.
        kcb_map = {
            PhenologicalStage.INITIAL: self.species.kcb_initial,
            PhenologicalStage.MID_SEASON: self.species.kcb_mid,
            PhenologicalStage.LATE_SEASON: self.species.kcb_late,
        }
        kcb = kcb_map[stage]
        # Stress coefficient per la traspirazione (modula solo Kcb).
        ks = stress_coefficient_ks(
            current_theta=self.state_theta,
            substrate=self.substrate,
            depletion_fraction=self.species.depletion_fraction,
        )
        # Coefficiente di riduzione superficiale: dipende da De
        # corrente e dai parametri REW/TEW del substrato.
        kr = evaporation_reduction_coefficient(
            de_mm=self.de_mm,
            rew_mm=self.substrate.rew_mm,
            tew_mm=self.substrate.tew_mm,
        )
        # Coefficiente di evaporazione superficiale.
        ke = soil_evaporation_coefficient(kcb=kcb, kr=kr)
        # ET totale e sua decomposizione.
        et_c_total = self.kp * (ks * kcb + ke) * et_0_mm
        soil_evap = self.kp * ke * et_0_mm
        return et_c_total, soil_evap

    def current_et_c(self, et_0_mm: float, current_date: date) -> float:
        """
        Evapotraspirazione reale della coltura nel vaso, in mm/giorno.

        Combina ET₀ del giorno con tutti i moltiplicatori in cascata,
        scegliendo automaticamente tra modello single Kc (default,
        tradizionale FAO-56 cap. 6) e dual-Kc (FAO-56 cap. 7) in base
        ai parametri disponibili. In sotto-tappa D della tappa 3 fascia 2
        è stato aggiunto il fattore nutrizionale Kn che modula il
        risultato in base allo stato chimico del substrato.

        Single Kc (specie/substrato non supportano dual-Kc):

            ET_c,act = Kp × Ks × Kc × Kn × ET_0

        Dual-Kc (specie ha Kcb e substrato ha REW/TEW):

            ET_c,act = Kp × (Ks × Kcb + Ke) × Kn × ET_0

        dove:
          Kc/Kcb vengono dalla biologia della pianta (Species);
          Ke è dinamico nel tempo (dipende da De e dai parametri del
            substrato, calcolato via il modulo science/dual_kc.py);
          Ks viene dallo stato idrico del bulk substrato;
          Kp è il coefficiente di vaso (materiale/colore/esposizione);
          Kn è il fattore nutrizionale calcolato da
            science.nutrition.nutritional_factor a partire dall'EC e
            dal pH correnti del substrato e dai range ottimali della
            specie. Vale 1.0 silenziosamente quando la specie non ha
            il modello chimico configurato — retrocompat totale con la
            fascia 1.
        """
        # Calcolo del Kn nutrizionale. Con specie senza modello chimico
        # configurato (caso del catalogo legacy della fascia 1)
        # nutritional_factor ritorna 1.0 silenziosamente e l'estensione
        # è inerte. Import lazy per evitare cicli a livello di package.
        from fitosim.science.nutrition import nutritional_factor
        kn = nutritional_factor(
            species=self.species,
            ec_substrate_mscm=self.ec_substrate_mscm,
            ph_substrate=self.ph_substrate,
        )

        if self.supports_dual_kc:
            et_c_total, _soil_evap = self._current_et_c_dual_kc(
                et_0_mm=et_0_mm, current_date=current_date,
            )
            return et_c_total * kn
        # Cammino tradizionale single Kc.
        et_c_base = actual_et_c(
            species=self.species,
            stage=self.current_stage(current_date),
            et_0=et_0_mm,
            current_theta=self.state_theta,
            substrate=self.substrate,
        )
        return self.kp * et_c_base * kn

    def apply_balance_step(
        self,
        et_0_mm: float,
        water_input_mm: float,
        current_date: date,
    ) -> BalanceStepResult:
        """
        Esegue un passo di bilancio idrico (giornaliero) sul vaso.

        Aggiorna `state_mm` (e, se il sottovaso è presente,
        `saucer_state_mm`) in-place e restituisce il `BalanceStepResult`
        del passo. La progettazione "side-effect + return" è
        deliberatamente esplicita: il caller vede il risultato (per
        notifiche, log, allerte) e sa che lo stato del vaso è cambiato.

        Sequenza giornaliera con sottovaso
        ----------------------------------

        Se il vaso ha un sottovaso attivo (`saucer_capacity_mm` non None),
        la sequenza dei sottopassi giornalieri è:

          1. Il sottovaso perde acqua per evaporazione del piattino,
             proporzionale a ET₀.
          2. Il vaso riceve acqua per risalita capillare dal sottovaso,
             proporzionale al deficit del substrato rispetto a FC.
          3. Si calcola il bilancio idrico standard del vaso (input
             meteo + irrigazione → ET_c → drenaggio).
          4. Il drenaggio del vaso entra nel sottovaso.
          5. Se il sottovaso eccede la capacità, l'eccesso è overflow
             definitivamente perso.

        Se il vaso non ha sottovaso, la sequenza si riduce al solo
        passo 3 — comportamento identico a prima dell'estensione.

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

        Ritorna
        -------
        BalanceStepResult
            Il risultato del bilancio del *vaso* (substrato). Lo stato
            del sottovaso è disponibile direttamente in
            self.saucer_state_mm dopo la chiamata.
        """
        has_saucer = self.saucer_capacity_mm is not None

        # === Passi 1-2: dinamica del sottovaso PRIMA del bilancio ===
        # L'evaporazione e la risalita capillare avvengono "durante la
        # giornata", e il loro effetto sull'acqua disponibile per la
        # pianta è già visibile al momento del bilancio. Modellando
        # questi due flussi prima del bilancio, la pianta "beneficia"
        # dell'acqua risalita anche nel giorno corrente.
        capillary_in = 0.0
        if has_saucer:
            # Passo 1: il sottovaso evapora.
            evap = saucer_evaporation(
                saucer_water_mm=self.saucer_state_mm,
                et_0_mm=et_0_mm,
                coef=self.saucer_evap_coef,
            )
            self.saucer_state_mm -= evap

            # Passo 2: risalita capillare dal sottovaso al substrato.
            deficit = max(0.0, self.fc_mm - self.state_mm)
            capillary_in = capillary_transfer(
                saucer_water_mm=self.saucer_state_mm,
                deficit_mm=deficit,
                rate=self.saucer_capillary_rate,
            )
            self.saucer_state_mm -= capillary_in

        # === Passo 3: bilancio standard del vaso ===
        # L'input d'acqua del vaso include la pioggia/irrigazione
        # esterna più ciò che è risalito per capillarità dal sottovaso.
        # Per il dual-Kc abbiamo bisogno anche della componente di
        # evaporazione superficiale, che useremo dopo per aggiornare
        # de_mm. Quando il dual-Kc non è attivo questa componente non
        # serve e il cammino è quello tradizionale.
        if self.supports_dual_kc:
            et_c_mm, soil_evap_mm = self._current_et_c_dual_kc(
                et_0_mm=et_0_mm, current_date=current_date,
            )
        else:
            et_c_mm = self.current_et_c(et_0_mm, current_date)
            soil_evap_mm = 0.0  # non usato nel cammino single Kc

        result = water_balance_step_mm(
            current_mm=self.state_mm,
            water_input_mm=water_input_mm + capillary_in,
            et_c_mm=et_c_mm,
            substrate=self.substrate,
            substrate_depth_mm=self.substrate_depth_mm,
            depletion_fraction=self.species.depletion_fraction,
        )
        self.state_mm = result.new_state

        # === Passi 4-5: il drenaggio finisce nel sottovaso ===
        if has_saucer:
            # Il drenaggio in eccesso entra nel piattino, fino al limite
            # di capacità. L'eccesso oltre capacità trabocca ed è
            # perso definitivamente (non torna nel modello).
            self.saucer_state_mm = min(
                self.saucer_capacity_mm,  # type: ignore[type-var]
                self.saucer_state_mm + result.drainage,
            )

        # === Passo 6: aggiornamento di De per il dual-Kc ===
        # Se il dual-Kc è attivo, aggiorniamo la cumulative depletion
        # dello strato superficiale. Solo l'input esterno (water_input_mm
        # = pioggia + irrigazione) ricarica la superficie; la risalita
        # capillare entra dal basso e va al bulk substrato, non alla
        # superficie. È una semplificazione ragionevole per i vasi
        # domestici.
        if self.supports_dual_kc:
            self.de_mm = update_de(
                de_mm_previous=self.de_mm,
                evaporation_mm=soil_evap_mm,
                water_input_mm=water_input_mm,
                tew_mm=self.substrate.tew_mm,  # type: ignore[arg-type]
            )

        return result

    def update_from_sensor(
        self,
        theta_observed: Optional[float] = None,
        *,
        reading: Optional["SoilReading"] = None,
    ) -> SensorUpdateResult:
        """
        Allinea lo stato del vaso a una lettura del sensore di umidità,
        producendo un report diagnostico della discrepanza.

        Il flusso operativo è il seguente: si registra la previsione
        corrente del modello (state_mm e state_theta), si confronta
        con la lettura del sensore, si calcola la discrepanza con
        segno (observed - predicted), si aggiorna state_mm per
        allinearsi al sensore, e si restituisce un SensorUpdateResult
        con tutti i dati raccolti durante l'operazione.

        Due modalità d'uso
        -------------------

        Il metodo può essere chiamato in due modi alternativi:

          1. **Modalità classica (legacy)**: passando un singolo float
             come `theta_observed`. È la forma usata dal codice scritto
             a tappa 6 della fascia 1, quando i sensori esponevano solo
             θ. Continua a funzionare senza modifiche::

                 result = pot.update_from_sensor(theta_observed=0.32)

          2. **Modalità ricca (tappa 2 fascia 2)**: passando un
             `SoilReading` completo via il parametro keyword-only
             `reading`. È la forma da preferire quando il sensore
             fornisce anche temperatura del substrato, EC, pH,
             come l'ATO 7-in-1 via HttpJsonSoilSensor::

                 reading = http_sensor.current_state(channel_id="1")
                 result = pot.update_from_sensor(reading=reading)

        Solo uno dei due parametri va passato. Passare entrambi o
        nessuno solleva ValueError per evitare ambiguità.

        Cosa viene aggiornato e cosa NO
        --------------------------------

        Il sensore misura il contenuto idrico medio del bulk del
        substrato a una certa profondità. Lo state_mm del vaso viene
        sovrascritto con il valore desunto dal θ misurato.

        I campi extra del SoilReading (temperature_c, ec_mscm, ph,
        provider_specific) NON aggiornano stati del modello in tappa 2
        perché il modello fisico della fascia 1 non ha ancora le
        variabili `ec_mm` e `ph_current`. Questi campi vengono
        comunque conservati nel SensorUpdateResult ritornato per
        logging diagnostico, presentazione nel dashboard, e per
        future estensioni.

        Quando arriverà la tappa 3 della fascia 2 (fertirrigazione
        EC+pH+Kn), il metodo verrà esteso internamente per usare
        anche EC e pH per aggiornare i nuovi stati. Il codice del
        chiamante non avrà bisogno di modifiche: continuerà a passare
        un SoilReading, e gli effetti sul modello diventeranno più
        ricchi automaticamente.

        Le variabili latenti del modello (saucer_state_mm, de_mm)
        restano invariate per le ragioni discusse nella fascia 1.

        Parametri
        ---------
        theta_observed : float | None
            Forma legacy: lettura del sensore in θ adimensionale [0, 1].
            Solleva ValueError se passato insieme a `reading`.
        reading : SoilReading | None
            Forma ricca: lettura strutturata da un sensore via Protocol.
            Estraiamo `theta_volumetric` per l'aggiornamento di
            state_mm, e gli altri campi vengono propagati nel
            SensorUpdateResult.

        Ritorna
        -------
        SensorUpdateResult
            Report strutturato della discrepanza prima dell'aggiornamento.
            Quando l'aggiornamento è fatto via SoilReading, sono
            valorizzati anche i campi observed_temperature_c,
            observed_ec_mscm, observed_ph e provider_specific.

        Solleva
        -------
        ValueError
            Se theta_observed è fuori dal range fisico [0, 1], oppure
            se entrambi o nessuno dei due parametri viene passato.

        Esempi
        --------
        Aggiornamento singolo dopo una lettura del sensore (legacy):

            >>> pot = Pot(...)
            >>> result = pot.update_from_sensor(theta_observed=0.32)
            >>> if result.is_significant:
            ...     print(f"Drift di {result.discrepancy_mm:.1f} mm")

        Aggiornamento con SoilReading da HttpJsonSoilSensor:

            >>> from fitosim.io.sensors import HttpJsonSoilSensor
            >>> sensor = HttpJsonSoilSensor(base_url="http://esp32.local")
            >>> reading = sensor.current_state(channel_id="1")
            >>> result = pot.update_from_sensor(reading=reading)
            >>> # I campi extra sono accessibili nel result:
            >>> if result.observed_ec_mscm is not None:
            ...     print(f"EC misurata: {result.observed_ec_mscm} mS/cm")
        """
        # Validazione mutuamente esclusiva: uno dei due parametri va
        # passato, mai entrambi e mai nessuno. Un errore qui è di
        # programmazione, non di runtime: il chiamante ha sbagliato a
        # invocare il metodo.
        if theta_observed is not None and reading is not None:
            raise ValueError(
                "Passare theta_observed OPPURE reading, non entrambi. "
                "theta_observed è la forma legacy (un singolo float), "
                "reading è la forma ricca (un SoilReading completo)."
            )
        if theta_observed is None and reading is None:
            raise ValueError(
                "Specificare theta_observed (forma legacy) o reading "
                "(SoilReading da un SoilSensor). Uno dei due è "
                "obbligatorio."
            )

        # Estrazione del θ effettivo + dei campi extra dal SoilReading.
        # Tutti i campi extra default a None: per la modalità legacy
        # restano None nel SensorUpdateResult finale.
        observed_temperature_c = None
        observed_ec_mscm = None
        observed_ph = None
        provider_specific_data = {}

        if reading is not None:
            theta_effective = reading.theta_volumetric
            observed_temperature_c = reading.temperature_c
            observed_ec_mscm = reading.ec_mscm
            observed_ph = reading.ph
            provider_specific_data = reading.provider_specific
        else:
            theta_effective = theta_observed

        # Da qui in poi la logica è identica alla forma legacy: il θ
        # estratto va validato e usato per aggiornare state_mm,
        # esattamente come prima della tappa 2.
        if not 0.0 <= theta_effective <= 1.0:
            raise ValueError(
                f"theta_observed deve essere in [0, 1] "
                f"(ricevuto {theta_effective}). Verifica le unità "
                f"del sensore: WH51 fornisce direttamente θ "
                f"adimensionale, ma alcuni firmware lo restituiscono "
                f"in percentuale (0-100) — in quel caso dividi per 100."
            )

        # Snapshot della previsione del modello, prima dell'aggiornamento.
        predicted_theta = self.state_theta
        predicted_mm = self.state_mm
        # Conversione lettura → mm usando la profondità effettiva del
        # substrato (che già tiene conto di active_depth_fraction).
        observed_mm = theta_effective * self.substrate_depth_mm

        # Discrepanze con la convenzione "observed - predicted":
        # positivo = sensore vede più acqua del previsto.
        discrepancy_theta = theta_effective - predicted_theta
        discrepancy_mm = observed_mm - predicted_mm

        # Errore relativo (con segno). Caso degenere: state_mm=0
        # (vaso completamente asciutto secondo il modello). In quel
        # caso il rapporto non è ben definito; ritorniamo 0% come
        # convenzione, il chiamante può usare absolute_error_mm
        # invece se lo trova più informativo.
        if predicted_mm > 0:
            relative_error_pct = discrepancy_mm / predicted_mm * 100.0
        else:
            relative_error_pct = 0.0

        # ----- Aggiornamento dello stato chimico (sotto-tappa E tappa 3) -----
        #
        # Snapshot dello stato chimico predetto, PRIMA dell'aggiornamento
        # idrico. Lo facciamo qui perché ec_substrate_mscm è una property
        # derivata che cambia automaticamente quando state_mm si modifica:
        # se calcolassimo predicted_ec dopo l'overwrite di state_mm
        # otterremmo un valore "ibrido" che non è né predetto né osservato.
        predicted_ec_mscm = None
        predicted_ph = None
        discrepancy_ec_mscm_value = None
        discrepancy_ph_value = None

        if observed_ec_mscm is not None:
            predicted_ec_mscm = self.ec_substrate_mscm
            discrepancy_ec_mscm_value = observed_ec_mscm - predicted_ec_mscm
        if observed_ph is not None:
            predicted_ph = self.ph_substrate
            discrepancy_ph_value = observed_ph - predicted_ph

        # Aggiornamento dello state_mm: sovrascritto con il valore
        # desunto dalla lettura del sensore. È un overwrite "duro" non
        # una media pesata: assumiamo che il sensore sia più affidabile
        # della previsione del modello, che è l'ipotesi naturale per
        # un sensore di buona qualità come il WH51 o l'ATO 7-in-1.
        self.state_mm = observed_mm

        # Aggiornamento degli stati chimici. Importante: questo viene
        # DOPO l'aggiornamento di state_mm, perché la conversione
        # EC → salt_mass deve usare il nuovo volume d'acqua che è
        # coerente con il θ osservato. Se invertissimo l'ordine
        # avremmo una salt_mass calcolata su un volume "vecchio" e poi
        # uno state_mm aggiornato, producendo un'EC corrente diversa
        # da quella misurata dal sensore. La stessa filosofia che
        # governa il sequencing in apply_step.
        if observed_ec_mscm is not None and self.water_volume_liters > 0:
            # Inversione della relazione EC = salt/(volume*10):
            # salt = EC × volume × 10. Il fattore 10 è la costante
            # documentata in fertigation.py.
            self.salt_mass_meq = (
                observed_ec_mscm * self.water_volume_liters * 10.0
            )
        # Caso degenere: water_volume_liters == 0 (vaso completamente
        # asciutto secondo il sensore). In questa condizione l'EC è
        # indefinita fisicamente (non c'è soluzione). Lasciamo
        # salt_mass_meq invariata: i sali "cristallizzati" tornano
        # in soluzione alla prossima fertirrigazione.

        if observed_ph is not None:
            # Il pH è una grandezza intensiva, non scala col volume:
            # il sensore fornisce direttamente il valore corrente del
            # substrato. Sovrascrittura diretta.
            self.ph_substrate = observed_ph

        return SensorUpdateResult(
            predicted_theta=predicted_theta,
            observed_theta=theta_effective,
            predicted_mm=predicted_mm,
            observed_mm=observed_mm,
            discrepancy_theta=discrepancy_theta,
            discrepancy_mm=discrepancy_mm,
            relative_error_pct=relative_error_pct,
            # Campi extra dalla modalità ricca (None per la legacy).
            observed_temperature_c=observed_temperature_c,
            observed_ec_mscm=observed_ec_mscm,
            observed_ph=observed_ph,
            provider_specific=provider_specific_data,
            # Campi diagnostici chimici (sotto-tappa E).
            predicted_ec_mscm=predicted_ec_mscm,
            predicted_ph=predicted_ph,
            discrepancy_ec_mscm=discrepancy_ec_mscm_value,
            discrepancy_ph=discrepancy_ph_value,
        )

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

    # ===================================================================
    #  Sotto-tappa C tappa 3 fascia 2: metodi di fertirrigazione
    # ===================================================================

    def apply_fertigation_step(
        self,
        volume_l: float,
        ec_mscm: float,
        ph: float,
        current_date: date,
    ) -> "FertigationResult":
        """
        Applica un evento di fertirrigazione al vaso, aggiornando in-place
        sia lo stato idrico (state_mm, drainage) sia lo stato chimico
        (salt_mass_meq, ph_substrate).

        È il duale chimico di `apply_balance_step` per il bilancio idrico:
        prende un singolo evento (volume di soluzione, EC, pH) e
        produce un'evoluzione coerente di tutti gli stati del vaso.

        Cosa succede in sequenza
        ------------------------

        Il metodo orchestra tre operazioni:

          1. **Calcolo del bilancio chimico** via la funzione
             `fertigation_step` di `science/fertigation.py`. Questa
             determina la massa salina finale, il drenaggio salino,
             il volume drenato, e il nuovo pH.

          2. **Applicazione al stato idrico**: lo state_mm viene
             aggiornato come `state_mm + water_input_mm - drainage_mm`,
             dove water_input_mm è il volume entrante convertito in mm
             di colonna d'acqua, e drainage_mm è il volume drenato
             ottenuto dal calcolo chimico (per coerenza con la
             stessa quantità del bilancio salino).

          3. **Applicazione al stato chimico**: salt_mass_meq e
             ph_substrate vengono aggiornati ai valori finali calcolati.

        Parametri
        ---------
        volume_l : float
            Volume di soluzione in arrivo, in litri. Non-negativo.
        ec_mscm : float
            Conducibilità elettrica della soluzione, in mS/cm a 25°C.
            Non-negativa. Per acqua del rubinetto milanese tipica
            usare 0.5; per BioBizz Bio-Grow al dosaggio raccomandato
            usare 2.0-2.5; per pioggia naturale usare 0 (oppure
            chiama direttamente `apply_rainfall_step`).
        ph : float
            pH della soluzione, scala 0-14. Per acqua del rubinetto
            milanese usare 7.5; per BioBizz al dosaggio standard
            usare 6.0-6.5; per pioggia naturale 5.6.
        current_date : date
            Data dell'evento, propagata al record di risultato per il
            logging. Non influenza il calcolo (la fertirrigazione è
            modellata come istantanea).

        Ritorna
        -------
        FertigationResult
            Record strutturato con tutti i dati prodotti: massa salina
            iniziale e finale, drenaggio idrico e salino, pH iniziale
            e finale, volumi convertiti per il logging, data dell'evento.

        Solleva
        -------
        ValueError
            Per parametri fisicamente impossibili (volume negativo, EC
            negativa, pH fuori scala).
        """
        # Import lazy per evitare ciclicità tra domain e science
        # all'inizializzazione del modulo.
        from fitosim.science.fertigation import fertigation_step

        # Snapshot dello stato pre-evento per il logging del result.
        salt_before = self.salt_mass_meq
        ph_before = self.ph_substrate
        water_volume_before_l = self.water_volume_liters

        # Calcolo del bilancio chimico (delega al modulo science).
        chemistry_result = fertigation_step(
            salt_mass_before_meq=salt_before,
            ph_before=ph_before,
            water_volume_before_l=water_volume_before_l,
            water_input_l=volume_l,
            ec_input_mscm=ec_mscm,
            ph_input=ph,
            fc_water_volume_l=self.fc_mm * self.surface_area_m2,
            cec_meq_per_100g=self.substrate.effective_cec_meq_per_100g,
            substrate_dry_mass_kg=self.substrate_dry_mass_kg,
        )

        # Conversione del volume drenato da L a mm per coerenza con
        # state_mm. Il drainage in litri / area superficie = mm.
        drainage_mm = chemistry_result.water_drained_l / self.surface_area_m2

        # Conversione del volume entrante da L a mm.
        water_input_mm = volume_l / self.surface_area_m2

        # Aggiornamento dello state_mm: input - drainage. Il bilancio
        # idrico per un evento di fertirrigazione è puro: niente ET
        # (modellata in apply_balance_step su scala giornaliera
        # separata), solo input idrico ed eventuale drenaggio.
        self.state_mm = self.state_mm + water_input_mm - drainage_mm

        # Aggiornamento degli stati chimici ai valori finali.
        self.salt_mass_meq = chemistry_result.salt_mass_after_meq
        self.ph_substrate = chemistry_result.ph_after

        return FertigationResult(
            event_date=current_date,
            volume_input_l=volume_l,
            volume_input_mm=water_input_mm,
            ec_input_mscm=ec_mscm,
            ph_input=ph,
            salt_mass_before_meq=salt_before,
            salt_mass_after_meq=chemistry_result.salt_mass_after_meq,
            salt_mass_added_meq=chemistry_result.salt_mass_added_meq,
            salt_mass_drained_meq=chemistry_result.salt_mass_drained_meq,
            water_drained_l=chemistry_result.water_drained_l,
            water_drained_mm=drainage_mm,
            ph_before=ph_before,
            ph_after=chemistry_result.ph_after,
            ph_delta=chemistry_result.ph_delta,
        )

    def apply_rainfall_step(
        self,
        volume_l: float,
        current_date: date,
    ) -> "FertigationResult":
        """
        Applica un evento di pioggia naturale al vaso, internamente
        chiamando `apply_fertigation_step` con i valori canonici della
        pioggia: EC=0 e pH=5.6.

        Il pH 5.6 è il valore "letterario" della pioggia naturale,
        corrispondente all'equilibrio dell'acqua pura con la CO₂
        atmosferica. La pioggia urbana milanese può essere leggermente
        più acida (5.0-5.5) per via degli ossidi di azoto del traffico,
        ma 5.6 è il valore convenzionale dei manuali di chimica del
        suolo. Se vorrai personalizzare il valore per la tua zona
        geografica, puoi usare `apply_fertigation_step` direttamente
        passando il pH che preferisci.

        L'EC della pioggia è praticamente nulla (acqua "distillata"
        dal punto di vista del bilancio salino), quindi la pioggia
        non aggiunge sali al vaso ma può rimuoverne via drenaggio se
        è abbondante. È esattamente il fenomeno della "lisciviazione
        naturale" che lava progressivamente i substrati outdoor.

        Parametri
        ---------
        volume_l : float
            Volume di pioggia raccolta dal vaso, in litri. Va calcolato
            dal chiamante moltiplicando i mm di pioggia caduti per
            l'area di intercettazione del vaso (`surface_area_m2`).
        current_date : date
            Data dell'evento.

        Ritorna
        -------
        FertigationResult
            Stesso tipo di risultato di apply_fertigation_step.
        """
        from fitosim.science.fertigation import RAINFALL_EC_MSCM, RAINFALL_PH
        return self.apply_fertigation_step(
            volume_l=volume_l,
            ec_mscm=RAINFALL_EC_MSCM,
            ph=RAINFALL_PH,
            current_date=current_date,
        )

    def apply_step(
        self,
        et_0_mm: float,
        current_date: date,
        fertigation_volume_l: float = 0.0,
        fertigation_ec_mscm: float = 0.0,
        fertigation_ph: float = 7.0,
        rainfall_volume_l: float = 0.0,
    ) -> "FullStepResult":
        """
        Orchestratore completo del passo giornaliero del vaso: combina
        in sequenza il bilancio idrico (ET, perdite per evapotraspirazione)
        con l'eventuale evento di fertirrigazione e/o l'eventuale
        evento di pioggia naturale.

        È il metodo da preferire quando il chiamante vuole simulazione
        chimica completa, perché orchestra correttamente la sequenza
        degli eventi nella giornata e produce un report unificato.

        Sequenza degli eventi
        ---------------------

        Il metodo applica gli eventi in questo ordine:

          1. **Pioggia naturale** (se rainfall_volume_l > 0): il
             modello la considera "del mattino", quindi viene applicata
             prima che la giornata di evapotraspirazione consumi acqua.
             Questo riproduce il caso pratico della pioggia notturna
             che il giardiniere trova al mattino.

          2. **Fertirrigazione** (se fertigation_volume_l > 0):
             applicata dopo l'eventuale pioggia. Il caso "il
             giardiniere fertirriga di mattina perché ha visto che
             non ha piovuto" è ben rappresentato perché tipicamente
             c'è solo uno dei due in un giorno specifico.

          3. **Evapotraspirazione** giornaliera tramite il bilancio
             idrico standard, applicata sull'eventuale stato già
             modificato dagli eventi 1 e 2.

        Significato della sequenza
        --------------------------

        Quando piove al mattino, il vaso si bagna prima che il sole
        di mezzogiorno faccia evaporare. Quindi i sali in arrivo (zero
        per la pioggia, ma non lo sono per la fertirrigazione) vengono
        applicati al vaso "umido" e l'eventuale drenaggio ne porta via
        una parte. Solo dopo, il bilancio idrico di FAO-56 calcola
        l'evapotraspirazione del giorno sulla base dello stato idrico
        post-eventi.

        Parametri
        ---------
        et_0_mm : float
            Evapotraspirazione di riferimento del giorno, in mm.
        current_date : date
            Data del passo. Usata per il modello fenologico (Kc dello
            stadio corrente), per il logging, e per il dual-Kc.
        fertigation_volume_l : float, opzionale
            Volume di soluzione fertilizzante (default 0 = niente
            fertirrigazione).
        fertigation_ec_mscm : float, opzionale
            EC del fertilizzante (ignorato se volume_l=0).
        fertigation_ph : float, opzionale
            pH del fertilizzante (default 7.0, comunque ignorato se
            volume_l=0).
        rainfall_volume_l : float, opzionale
            Volume di pioggia raccolta (default 0 = niente pioggia).

        Ritorna
        -------
        FullStepResult
            Record che aggrega il BalanceStepResult del bilancio idrico
            e gli eventuali FertigationResult di pioggia e/o
            fertirrigazione applicati.
        """
        rainfall_result = None
        fertigation_result = None

        # Step 1: pioggia naturale (se presente).
        if rainfall_volume_l > 0:
            rainfall_result = self.apply_rainfall_step(
                volume_l=rainfall_volume_l,
                current_date=current_date,
            )

        # Step 2: fertirrigazione (se presente).
        if fertigation_volume_l > 0:
            fertigation_result = self.apply_fertigation_step(
                volume_l=fertigation_volume_l,
                ec_mscm=fertigation_ec_mscm,
                ph=fertigation_ph,
                current_date=current_date,
            )

        # Step 3: bilancio idrico giornaliero. Il water_input_mm
        # passato qui è zero perché eventuali input li abbiamo già
        # applicati ai due step precedenti.
        balance_result = self.apply_balance_step(
            et_0_mm=et_0_mm,
            water_input_mm=0.0,
            current_date=current_date,
        )

        return FullStepResult(
            event_date=current_date,
            balance_result=balance_result,
            rainfall_result=rainfall_result,
            fertigation_result=fertigation_result,
        )
