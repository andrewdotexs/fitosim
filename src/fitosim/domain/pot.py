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
        ai parametri disponibili.

        Single Kc (specie/substrato non supportano dual-Kc):

            ET_c,act = Kp × Ks × Kc × ET_0

        Dual-Kc (specie ha Kcb e substrato ha REW/TEW):

            ET_c,act = Kp × (Ks × Kcb + Ke) × ET_0

        dove:
          Kc/Kcb vengono dalla biologia della pianta (Species);
          Ke è dinamico nel tempo (dipende da De e dai parametri del
            substrato, calcolato via il modulo science/dual_kc.py);
          Ks viene dallo stato idrico del bulk substrato;
          Kp è il coefficiente di vaso (materiale/colore/esposizione).
        """
        if self.supports_dual_kc:
            et_c_total, _soil_evap = self._current_et_c_dual_kc(
                et_0_mm=et_0_mm, current_date=current_date,
            )
            return et_c_total
        # Cammino tradizionale single Kc.
        et_c_base = actual_et_c(
            species=self.species,
            stage=self.current_stage(current_date),
            et_0=et_0_mm,
            current_theta=self.state_theta,
            substrate=self.substrate,
        )
        return self.kp * et_c_base

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
