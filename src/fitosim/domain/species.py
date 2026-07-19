"""
Specie coltivabili e calcoli di evapotraspirazione della coltura.

Questo è il primo modulo del livello `domain/`: non descrive più
fenomeni universali (come il livello `science/`), bensì caratterizza
le *entità biologiche specifiche* che vogliamo simulare — il basilico,
il pomodoro, il rosmarino, eccetera — associando a ciascuna i parametri
agronomici che ne determinano il comportamento idrico.

Concetti chiave
---------------

Coefficiente colturale Kc
    Rapporto adimensionale tra l'evapotraspirazione della coltura
    specifica e quella del prato di riferimento:

        ET_c = Kc × ET_0

    Ogni specie ha un profilo di Kc che varia con lo stadio fenologico:
    basso all'impianto (quando la pianta ha poche foglie), massimo in
    piena vegetazione (quando la copertura fogliare è massima), ridotto
    a maturazione/senescenza (quando i tessuti invecchiano). FAO-56
    tabula Kc_ini, Kc_mid e Kc_end per centinaia di specie.

Stadio fenologico
    La fase di sviluppo in cui si trova la pianta. In questa prima
    versione usiamo tre stadi discreti (iniziale, piena vegetazione,
    fine ciclo). Versioni future potranno interpolare linearmente tra
    gli stadi in base al giorno del ciclo colturale, come suggerito da
    FAO-56 cap. 6.

Frazione di deplezione p
    Quota della TAW che la pianta può perdere prima di entrare in
    stress idrico. È specifica della specie: lattughe e foglie tenere
    hanno p≈0.30 (allerta precoce), pomodori p≈0.40, agrumi p≈0.50,
    xerofite mediterranee (rosmarino) fino a p≈0.60.

Evapotraspirazione potenziale vs reale
    ET_c "potenziale" è il consumo che la pianta avrebbe in assenza
    di limitazione idrica: ET_c = Kc × ET_0. ET_c "reale" (ET_c,act)
    include il coefficiente di stress Ks che riduce il consumo quando
    il substrato si asciuga oltre la soglia RAW: ET_c,act = Ks × Kc × ET_0.
    Nella zona di comfort le due coincidono; nella zona di stress
    la reale è strettamente minore.

Riferimento: Allen, Pereira, Raes, Smith (1998), FAO-56 cap. 6-8.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum

from fitosim.science.balance import stress_coefficient_ks
from fitosim.science.substrate import DEFAULT_DEPLETION_FRACTION, Substrate


class PhenologicalStage(Enum):
    """
    Stadio fenologico della pianta.

    Usiamo tre stadi discreti corrispondenti ai plateau del profilo Kc
    classico FAO-56. Le fasi intermedie (sviluppo, senescenza) che nel
    paper sono interpolate linearmente verranno aggiunte in futuro,
    insieme al conteggio dei giorni di ciclo colturale.
    """

    INITIAL = "initial"           # impianto, germinazione, radicamento
    MID_SEASON = "mid_season"     # piena vegetazione, fioritura, fruttificazione
    LATE_SEASON = "late_season"   # maturazione, senescenza, raccolta


class GrowthStage(Enum):
    """
    Stadio botanico osservabile, vocabolario condiviso con The Pot.

    Mentre `PhenologicalStage` è l'astrazione FAO-56 che pilota il Kc
    (tre plateau, mutuamente esclusivi), questo enum è il vocabolario
    che il **giardiniere osserva e riporta**: "sta germogliando", "è
    in fiore". È il linguaggio del diario, e quindi la chiave con cui
    il feedback fenologico entra nel modello.

    I due vocabolari convivono per design: sono due viste della stessa
    posizione temporale, non uno la traduzione lossy dell'altro. La
    vista botanica serve all'utente e al feedback, quella FAO-56 serve
    al calcolo del Kc.

    A differenza degli stadi FAO-56, questi possono essere
    **simultanei**: un agrume a maggio è contemporaneamente in
    vegetazione e in fioritura.

    I valori delle stringhe corrispondono esattamente al vocabolario
    controllato di The Pot (`DEFAULT_PHENOLOGY_BY_GROUP` nel catalogo),
    così che le due basi dati parlino la stessa lingua senza mappature.
    """

    DORMANCY = "dormienza"            # riposo profondo, gemme chiuse
    REST = "riposo"                   # riposo leggero, attività ridotta
    BUD_BREAK = "germogliamento"      # rottura gemme, ripresa
    VEGETATIVE = "vegetativo"         # crescita di foglie e rami
    FLOWERING = "fioritura"           # emissione dei fiori
    FRUITING = "fruttificazione"      # allegagione e maturazione


class PhenologyAnchor(Enum):
    """
    A cosa è ancorato il ciclo fenologico della specie.

    È la distinzione che i due modelli precedenti sbagliavano in modo
    speculare, ciascuno assumendo universale il proprio caso:

      - Le **annuali** hanno il ciclo ancorato alla semina. Un basilico
        seminato a luglio è in fase iniziale a luglio, non "in piena
        vegetazione" come direbbe il calendario stagionale.
      - Le **perenni** hanno il ciclo ancorato alla stagione. Un limone
        di cinque anni fiorisce a maggio a prescindere da quando è
        stato messo a dimora, e i "giorni dall'impianto" non dicono
        più nulla di utile.

    Prima di questa distinzione le perenni usavano durate di stadio
    dichiaratamente convenzionali (vedi le note di CITRUS e ROSEMARY),
    che con l'andare degli anni collassavano permanentemente
    nell'ultimo stadio.
    """

    ANNUAL = "annual"          # ciclo ancorato alla data di impianto
    PERENNIAL = "perennial"    # ciclo ancorato alla stagione


# Mappatura di default dagli stadi FAO-56 a quelli botanici per le
# specie ANNUALI che non dichiarano una mappatura propria. Il modello
# di fitosim parte da una piantina già insediata (l'impianto è il
# momento in cui la metti nel vaso), quindi la germinazione vera e
# propria non è modellata e `BUD_BREAK` resta un concetto da perenni.
DEFAULT_ANNUAL_GROWTH_STAGES: dict[PhenologicalStage, tuple] = {
    PhenologicalStage.INITIAL: (GrowthStage.VEGETATIVE,),
    PhenologicalStage.MID_SEASON: (
        GrowthStage.VEGETATIVE, GrowthStage.FLOWERING,
    ),
    PhenologicalStage.LATE_SEASON: (GrowthStage.FRUITING,),
}


@dataclass(frozen=True)
class Species:
    """
    Descrizione agronomica immutabile di una specie coltivabile.

    Attributi
    ---------
    common_name : str
        Nome comune italiano (es. "Basilico", "Pomodoro").
    scientific_name : str
        Nome scientifico binomiale latino (es. "Ocimum basilicum").
    kc_initial : float
        Coefficiente colturale allo stadio iniziale, adimensionale.
    kc_mid : float
        Coefficiente colturale in piena vegetazione, adimensionale.
    kc_late : float
        Coefficiente colturale al termine del ciclo, adimensionale.
    depletion_fraction : float
        Frazione p della TAW tollerata prima dello stress, in (0, 1].
    initial_stage_days : int
        Durata in giorni dello stadio iniziale, contati a partire
        dall'impianto. Tipicamente 20-40 giorni per orticole annuali;
        per le perenni è puramente convenzionale (sempreverdi).
    mid_stage_days : int
        Durata in giorni dello stadio di piena vegetazione, dopo lo
        stadio iniziale. Per orticole annuali è il periodo di
        accrescimento attivo + fioritura/fruttificazione (40-90 giorni).
        Per perenni indica il periodo "di punta" annuale.
    notes : str, opzionale
        Nota libera per documentare fonte dei dati, comportamento tipico,
        ambiente di coltivazione raccomandato.
    kcb_initial, kcb_mid, kcb_late : float | None, opzionali
        Coefficienti basali per il modello dual-Kc (FAO-56 cap. 7).
        Tutti e tre o nessuno; quando valorizzati il motore usa il
        modello dual-Kc se anche il substrato è caratterizzato.
    ec_optimal_min_mscm, ec_optimal_max_mscm : float | None, opzionali
        Range ottimale di conducibilità elettrica del substrato per la
        specie, in mS/cm a 25 °C. Aggiunto in tappa 3 della fascia 2.
        Quando l'EC del substrato cade dentro questo intervallo, il
        coefficiente nutrizionale Kn vale 1.0 dal lato della salinità;
        scende sotto 1.0 quando si esce dal range. Tutti e quattro i
        parametri chimici (i due EC e i due pH) devono essere
        specificati insieme o nessuno.
    ph_optimal_min, ph_optimal_max : float | None, opzionali
        Range ottimale di pH del substrato per la specie. Stessa
        logica del range EC, applicato al fattore pH-dipendente di Kn.

    Vincoli
    -------
    - Ogni kc_* deve essere in (0, 2): valori tipici vanno da 0.3 a 1.2;
      imporre un limite superiore di 2 cattura errori di trascrizione
      evidenti senza escludere casi estremi (es. Kc di colture ad alta
      densità fogliare in specifici microclimi).
    - depletion_fraction deve essere in (0, 1]; valori tipici 0.3-0.7.
    - initial_stage_days e mid_stage_days devono essere positivi.

    Modello fenologico
    ------------------
    Le due durate definiscono implicitamente le tre fasi:
      [0, initial_stage_days)                       → INITIAL
      [initial_stage_days, initial+mid_stage_days)  → MID_SEASON
      [initial+mid_stage_days, +∞)                  → LATE_SEASON

    Per le specie perenni sempreverdi (come il limone) ha senso pensare
    al ciclo come ricominciante ogni anno: in queste specie le durate
    sono interpretate come riferimento entro un anno solare e Kc resta
    sostanzialmente costante tra gli stadi (per indicare appunto la
    natura sempreverde).
    """

    common_name: str
    scientific_name: str
    kc_initial: float
    kc_mid: float
    kc_late: float
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION
    initial_stage_days: int = 30
    mid_stage_days: int = 60
    notes: str = ""
    # ----- Coefficienti basali per il modello dual-Kc -----
    # Quando sono None la specie usa il single Kc tradizionale; quando
    # sono valorizzati il motore (in presenza anche di REW/TEW sul
    # substrato) usa il modello dual-Kc di FAO-56 cap. 7. I Kcb sono
    # tipicamente 0.10-0.25 più bassi dei corrispondenti Kc, perché
    # tolgono la componente di evaporazione superficiale.
    kcb_initial: float | None = None
    kcb_mid: float | None = None
    kcb_late: float | None = None
    # ----- Range ottimali di EC e pH (tappa 3 fascia 2) -----
    # Questi quattro parametri descrivono le esigenze nutrizionali della
    # specie e alimentano il calcolo del coefficiente Kn (sotto-tappa D).
    # Quando sono tutti None la specie non supporta il modello chimico
    # e il motore ignora le considerazioni nutrizionali (Kn=1 sempre).
    # Quando sono tutti valorizzati, il modello sa giudicare se le
    # condizioni del substrato sono ottimali, accettabili o stressanti
    # per la pianta.
    #
    # Valori indicativi per alcune specie comuni:
    #   - basilico:  EC 1.0-1.6, pH 6.0-7.0
    #   - pomodoro:  EC 2.0-3.5, pH 6.0-6.8
    #   - mirtillo:  EC 0.8-1.4, pH 4.5-5.5 (specie acidofila)
    #   - lattuga:   EC 1.2-1.8, pH 6.0-7.0
    ec_optimal_min_mscm: float | None = None
    ec_optimal_max_mscm: float | None = None
    ph_optimal_min: float | None = None
    ph_optimal_max: float | None = None
    # ----- Parametri fisiologici per Penman-Monteith fisico (tappa 5 sotto-tappa C) -----
    # Questi due parametri caratterizzano la specie ai fini del modello
    # fisico di Penman-Monteith, che applica direttamente l'equazione
    # alla coltura reale invece di usare la coltura di riferimento
    # standardizzata di FAO-56. Quando entrambi sono valorizzati, il
    # selettore "best available" del modulo science/et0.py userà
    # Penman-Monteith fisico se anche i dati meteo sono completi; se
    # uno solo è valorizzato (o nessuno) ricadrà su Penman-Monteith
    # standard FAO-56 + Kc.
    #
    # Valori indicativi per le specie del catalogo, da letteratura:
    #   - coltura erbacea di riferimento: rs=70 s/m, h=0.12 m
    #   - basilico:                       rs=100 s/m, h=0.30 m
    #   - lattuga:                        rs=100 s/m, h=0.20 m
    #   - pomodoro:                       rs=130 s/m, h=0.60 m
    #   - rosmarino (semi-mediterraneo):  rs=200 s/m, h=0.60 m
    #   - agrumi (sempreverdi):           rs=140 s/m, h=2.00 m
    #   - succulente CAM:                 rs=500+ s/m, h=0.10 m
    #
    # La resistenza stomatica varia di un fattore 5-10 tra mesofile e
    # xerofile, e riflette quanto la pianta "tiene chiusi" gli stomi
    # in condizioni standard. È il parametro fisiologico più importante
    # per differenziare le specie nel modello.
    stomatal_resistance_s_m: float | None = None
    crop_height_m: float | None = None
    # ----- Ancoraggio fenologico e vista botanica -----
    # `phenology_anchor` dichiara se il ciclo della specie è ancorato
    # all'impianto (annuali) o alla stagione (perenni). Il default
    # ANNUAL preserva il comportamento storico di tutte le specie
    # esistenti.
    #
    # `phenology_calendar` è obbligatorio per le PERENNI: dodici
    # elementi, uno per mese da gennaio a dicembre, ciascuno con la
    # tupla degli stadi botanici attivi in quel mese (possono essere
    # più d'uno). Gli stessi dati vivono in The Pot come
    # DEFAULT_PHENOLOGY_BY_GROUP.
    #
    # `annual_growth_stages` permette a una specie ANNUALE di
    # sovrascrivere la mappatura FAO-56 → botanica di default, che
    # assume un ciclo con fioritura e fruttificazione. Serve per le
    # colture da foglia raccolte prima della fioritura (la lattuga
    # che va a seme è un difetto, non uno stadio previsto).
    phenology_anchor: PhenologyAnchor = PhenologyAnchor.ANNUAL
    phenology_calendar: tuple[tuple[GrowthStage, ...], ...] | None = None
    annual_growth_stages: (
        tuple[tuple[GrowthStage, ...], tuple[GrowthStage, ...],
              tuple[GrowthStage, ...]] | None
    ) = None

    def __post_init__(self) -> None:
        # Validazione dei Kc: scorriamo la terna con zip per un
        # messaggio d'errore informativo se qualcuno è fuori range.
        for name, value in (
            ("kc_initial", self.kc_initial),
            ("kc_mid", self.kc_mid),
            ("kc_late", self.kc_late),
        ):
            if not 0.0 < value < 2.0:
                raise ValueError(
                    f"Specie '{self.common_name}': {name}={value} è "
                    f"fuori range plausibile (0, 2). Controlla il valore."
                )
        if not 0.0 < self.depletion_fraction <= 1.0:
            raise ValueError(
                f"Specie '{self.common_name}': depletion_fraction="
                f"{self.depletion_fraction} deve essere in (0, 1]."
            )
        if self.initial_stage_days <= 0 or self.mid_stage_days <= 0:
            raise ValueError(
                f"Specie '{self.common_name}': initial_stage_days e "
                f"mid_stage_days devono essere positivi. Ricevuti: "
                f"{self.initial_stage_days}, {self.mid_stage_days}."
            )
        # Validazione dei Kcb: o sono tutti None (single Kc), o tutti
        # valorizzati e fisicamente sensati (positivi, sotto i Kc).
        kcb_values = (self.kcb_initial, self.kcb_mid, self.kcb_late)
        kcb_present = sum(1 for k in kcb_values if k is not None)
        if 0 < kcb_present < 3:
            raise ValueError(
                f"Specie '{self.common_name}': i Kcb devono essere "
                f"specificati tutti e tre o nessuno. Ricevuti: "
                f"kcb_initial={self.kcb_initial}, "
                f"kcb_mid={self.kcb_mid}, kcb_late={self.kcb_late}."
            )
        if kcb_present == 3:
            for name, kcb_value, kc_value in (
                ("kcb_initial", self.kcb_initial, self.kc_initial),
                ("kcb_mid", self.kcb_mid, self.kc_mid),
                ("kcb_late", self.kcb_late, self.kc_late),
            ):
                if not 0.0 < kcb_value < 2.0:
                    raise ValueError(
                        f"Specie '{self.common_name}': {name}={kcb_value} "
                        f"è fuori range plausibile (0, 2)."
                    )
                if kcb_value > kc_value:
                    raise ValueError(
                        f"Specie '{self.common_name}': {name}={kcb_value} "
                        f"non può eccedere il corrispondente Kc="
                        f"{kc_value} (il basale è la sola traspirazione, "
                        f"deve essere ≤ del Kc totale)."
                    )

        # Validazione del modello chimico (tappa 3 fascia 2): i quattro
        # parametri EC/pH devono essere tutti None o tutti valorizzati.
        # Una specie con tre su quattro sarebbe in uno stato indefinito
        # in cui il motore non saprebbe se applicare o no il calcolo
        # del Kn nutrizionale.
        chemistry_values = (
            self.ec_optimal_min_mscm,
            self.ec_optimal_max_mscm,
            self.ph_optimal_min,
            self.ph_optimal_max,
        )
        chemistry_present = sum(1 for v in chemistry_values if v is not None)
        if 0 < chemistry_present < 4:
            raise ValueError(
                f"Specie '{self.common_name}': i quattro parametri "
                f"chimici (ec_optimal_min_mscm, ec_optimal_max_mscm, "
                f"ph_optimal_min, ph_optimal_max) devono essere "
                f"specificati tutti o nessuno. "
                f"Ricevuti: ec=({self.ec_optimal_min_mscm}, "
                f"{self.ec_optimal_max_mscm}), pH=("
                f"{self.ph_optimal_min}, {self.ph_optimal_max})."
            )
        if chemistry_present == 4:
            # Range EC: deve essere ordinato e dentro i limiti fisici
            # tipici del substrato (EC > 8 mS/cm sono già condizioni
            # di stress salino acuto; il range di OPTIMA non può
            # arrivare là).
            if not 0.0 < self.ec_optimal_min_mscm < self.ec_optimal_max_mscm <= 8.0:
                raise ValueError(
                    f"Specie '{self.common_name}': il range ottimale di EC "
                    f"deve soddisfare 0 < min ({self.ec_optimal_min_mscm}) "
                    f"< max ({self.ec_optimal_max_mscm}) ≤ 8 mS/cm."
                )
            # Range pH: ordinato e dentro la scala chimica.
            if not 0.0 < self.ph_optimal_min < self.ph_optimal_max <= 14.0:
                raise ValueError(
                    f"Specie '{self.common_name}': il range ottimale di pH "
                    f"deve soddisfare 0 < min ({self.ph_optimal_min}) "
                    f"< max ({self.ph_optimal_max}) ≤ 14."
                )

        # Coerenza dell'ancoraggio fenologico: una perenne senza
        # calendario non saprebbe in che stadio si trova, perché per
        # lei i giorni dall'impianto non sono informativi.
        if self.phenology_anchor is PhenologyAnchor.PERENNIAL:
            if self.phenology_calendar is None:
                raise ValueError(
                    f"Specie '{self.common_name}': una specie PERENNIAL "
                    f"richiede phenology_calendar (12 mesi), perché il suo "
                    f"ciclo è ancorato alla stagione e non all'impianto."
                )
            if len(self.phenology_calendar) != 12:
                raise ValueError(
                    f"Specie '{self.common_name}': phenology_calendar deve "
                    f"avere esattamente 12 elementi (gennaio-dicembre), "
                    f"ricevuti {len(self.phenology_calendar)}."
                )
            for month_idx, stages in enumerate(self.phenology_calendar, 1):
                if not stages:
                    raise ValueError(
                        f"Specie '{self.common_name}': il mese {month_idx} "
                        f"del phenology_calendar è vuoto. Ogni mese deve "
                        f"dichiarare almeno uno stadio botanico."
                    )

    @property
    def supports_dual_kc(self) -> bool:
        """
        True se la specie ha tutti i Kcb valorizzati e supporta quindi
        il modello dual-Kc. Usato dal motore per decidere quale
        cammino di calcolo seguire.
        """
        return (
            self.kcb_initial is not None
            and self.kcb_mid is not None
            and self.kcb_late is not None
        )

    @property
    def supports_chemistry_model(self) -> bool:
        """
        True se la specie ha tutti i quattro parametri chimici
        valorizzati e supporta quindi il modello nutrizionale (Kn,
        valutazione delle condizioni di EC e pH del substrato).

        Aggiunto in tappa 3 della fascia 2. Usato dal motore di
        fertirrigazione per decidere se calcolare Kn dinamicamente
        o ricadere su Kn=1 quando la specie non è caratterizzata sul
        piano chimico.
        """
        return (
            self.ec_optimal_min_mscm is not None
            and self.ec_optimal_max_mscm is not None
            and self.ph_optimal_min is not None
            and self.ph_optimal_max is not None
        )

    def stage_at_day(self, days_since_planting: int) -> "PhenologicalStage":
        """
        Calcola lo stadio fenologico in base al numero di giorni
        trascorsi dall'impianto.

        La logica è la mappatura discreta a tre fasi descritta nella
        docstring della classe. È un metodo della specie (non una
        funzione esterna) perché le soglie di transizione sono parte
        dei suoi dati intrinseci e variano di specie in specie.

        I giorni negativi (impianto futuro?) e i giorni infiniti vengono
        gestiti dolcemente: prima dell'impianto trattiamo come INITIAL,
        oltre la fine del ciclo continuiamo a riportare LATE_SEASON.
        """
        if days_since_planting < self.initial_stage_days:
            return PhenologicalStage.INITIAL
        if days_since_planting < self.initial_stage_days + self.mid_stage_days:
            return PhenologicalStage.MID_SEASON
        return PhenologicalStage.LATE_SEASON

    def growth_stages_at(
        self, current_date: "date", planting_date: "date",
    ) -> tuple[GrowthStage, ...]:
        """
        Vista botanica: gli stadi osservabili attivi alla data indicata.

        È il vocabolario del diario e del feedback fenologico. Può
        restituire più stadi contemporaneamente (un agrume a maggio è
        in vegetazione *e* in fioritura).

        Per le PERENNI legge il calendario stagionale; per le ANNUALI
        deriva dallo stadio FAO-56, usando la mappatura della specie se
        dichiarata o quella di default.
        """
        if self.phenology_anchor is PhenologyAnchor.PERENNIAL:
            # Il calendario è garantito presente e completo da __post_init__.
            return self.phenology_calendar[current_date.month - 1]

        fao_stage = self.stage_at_day((current_date - planting_date).days)
        if self.annual_growth_stages is not None:
            index = {
                PhenologicalStage.INITIAL: 0,
                PhenologicalStage.MID_SEASON: 1,
                PhenologicalStage.LATE_SEASON: 2,
            }[fao_stage]
            return self.annual_growth_stages[index]
        return DEFAULT_ANNUAL_GROWTH_STAGES[fao_stage]

    def stage_at(
        self, current_date: "date", planting_date: "date",
    ) -> PhenologicalStage:
        """
        Stadio FAO-56 in vigore, consapevole dell'ancoraggio della specie.

        È il metodo che il motore deve usare per il Kc, al posto del
        più vecchio `stage_at_day`: quest'ultimo assume implicitamente
        l'ancoraggio annuale ed è corretto solo per le annuali.

        Per le ANNUALI il comportamento è identico a `stage_at_day`.
        Per le PERENNI lo stadio viene dedotto dalla stagione: senza
        questo, una pianta perenne dopo qualche anno resterebbe
        inchiodata per sempre in LATE_SEASON, perché i giorni
        dall'impianto crescono senza limite.
        """
        if self.phenology_anchor is PhenologyAnchor.ANNUAL:
            return self.stage_at_day((current_date - planting_date).days)

        stages = self.growth_stages_at(current_date, planting_date)
        return fao56_stage_from_growth_stages(stages)


# =======================================================================
#  Funzioni di dominio
# =======================================================================

def fao56_stage_from_growth_stages(
    stages: tuple[GrowthStage, ...],
) -> PhenologicalStage:
    """
    Riduce un insieme di stadi botanici (anche simultanei) allo stadio
    FAO-56 corrispondente, che è mutuamente esclusivo.

    È la cerniera tra i due vocabolari, e serve perché il Kc deve
    essere un numero solo in ogni istante mentre la vista botanica può
    dichiarare più stadi insieme.

    Regola di priorità, dalla domanda idrica più alta alla più bassa:

      - fruttificazione o fioritura  → MID_SEASON (picco di domanda)
      - vegetativo                   → MID_SEASON (crescita attiva)
      - germogliamento               → INITIAL (ripresa, chioma ridotta)
      - dormienza o riposo           → INITIAL (domanda minima)

    Nota: LATE_SEASON non viene mai prodotto da questa riduzione. Per
    le perenni non esiste una "fine ciclo" annuale come per le colture
    seminate: il ciclo si richiude nella dormienza. Le specie perenni
    del catalogo hanno infatti kc_late ≈ kc_initial, quindi la scelta
    non introduce distorsioni.

    La riduzione di Kc durante la dormienza vera (un sempreverde
    dormiente traspira molto meno di uno in ripresa) è un raffinamento
    successivo, deliberatamente fuori da questo passaggio perché
    cambierebbe i numeri del bilancio idrico e non solo il vocabolario.
    """
    stage_set = set(stages)
    if stage_set & {GrowthStage.FRUITING, GrowthStage.FLOWERING}:
        return PhenologicalStage.MID_SEASON
    if GrowthStage.VEGETATIVE in stage_set:
        return PhenologicalStage.MID_SEASON
    return PhenologicalStage.INITIAL

# =======================================================================
#  Riduzione del Kc in dormienza
# =======================================================================
#
# Il problema
# -----------
# FAO-56 modella colture annuali, che non dormono: si seminano, crescono,
# si raccolgono. I suoi tre stadi non hanno un concetto di riposo. Ma una
# perenne in vaso passa metà dell'anno in dormienza o riposo, e in quello
# stato consuma molta meno acqua di quando è in piena attività.
#
# Senza questa correzione il modello sbagliava in modo evidente sul
# limone: a gennaio, in riposo con i frutti appesi, gli veniva attribuito
# lo stesso Kc di piena attività estiva.
#
# Il pavimento evaporativo (la parte che è facile sbagliare)
# ----------------------------------------------------------
# Kc è il rapporto ET_coltura / ET₀, e mette insieme DUE flussi:
# traspirazione della pianta ed evaporazione dalla superficie del
# substrato. In dormienza la traspirazione crolla, ma l'evaporazione
# resta: il substrato nudo continua a perdere acqua.
#
# Quindi il Kc di dormienza NON può tendere a zero. Ha un pavimento
# fisico dato dalla sola evaporazione, che per un vaso domestico (dove
# la superficie è interamente esposta) vale circa 0.20 secondo i valori
# di Kc_ini per suolo nudo di FAO-56 con bagnature poco frequenti.
#
# Sbagliare questo punto sarebbe pericoloso nella direzione peggiore:
# un modello che dice "la pianta dormiente non consuma nulla" non
# suggerirebbe mai di irrigare, e le perenni in vaso muoiono anche di
# sete invernale, non solo di marciume.
#
# Nel dual-Kc il pavimento NON si applica: lì l'evaporazione è già
# contabilizzata a parte da Ke, e Kcb è traspirazione pura, quindi può
# scendere liberamente.
#
# I valori
# --------
# Sono stime ragionevoli, non misure: la fascia 3 li taterà contro i
# dati reali. La riduzione si calcola sul kc_mid della specie, cioè
# sulla sua attività di picco, perché "dormienza" significa proprio
# "una frazione della piena attività" a prescindere da quale stadio
# FAO-56 la macchina degli stadi avrebbe altrimenti scelto.

KC_BARE_SOIL_FLOOR = 0.20
"""Kc minimo di un vaso in dormienza: sola evaporazione dal substrato."""

DORMANCY_KC_FACTOR = 0.25
"""Frazione del kc_mid in dormienza profonda (gemme chiuse, metabolismo
quasi fermo)."""

REST_KC_FACTOR = 0.50
"""Frazione del kc_mid in riposo leggero (attività ridotta, chioma
presente e funzionante)."""


def dormancy_kc_factor(
    growth_stages: tuple[GrowthStage, ...],
) -> float | None:
    """
    Fattore di riduzione del Kc per gli stadi botanici indicati.

    Ritorna `None` quando nessuna riduzione si applica, così il
    chiamante distingue "nessuna riduzione" da "riduzione pari a 1.0".

    Gli stadi possono essere simultanei: la presenza di dormienza o
    riposo determina la riduzione a prescindere da cosa altro la
    pianta stia facendo. Un limone a gennaio è in riposo *e* porta
    frutti, ma il suo metabolismo è quello di una pianta in riposo.

    Il germogliamento non riceve riduzione: la pianta è in ripresa
    attiva, e la chioma ancora piccola è già rappresentata dal Kc
    dello stadio iniziale.
    """
    if GrowthStage.DORMANCY in growth_stages:
        return DORMANCY_KC_FACTOR
    if GrowthStage.REST in growth_stages:
        return REST_KC_FACTOR
    return None


def effective_kc(
    species: Species,
    stage: PhenologicalStage,
    growth_stages: tuple[GrowthStage, ...] | None = None,
) -> float:
    """
    Kc della specie con la riduzione di dormienza applicata.

    Senza `growth_stages` (o con stadi di piena attività) coincide con
    `kc_for_stage`: il comportamento delle annuali è invariato.

    In dormienza o riposo restituisce una frazione del kc_mid, mai
    inferiore al pavimento evaporativo `KC_BARE_SOIL_FLOOR` — perché
    il substrato continua a evaporare anche quando la pianta è ferma.
    """
    base = kc_for_stage(species, stage)
    if growth_stages is None:
        return base
    factor = dormancy_kc_factor(growth_stages)
    if factor is None:
        return base
    return max(KC_BARE_SOIL_FLOOR, species.kc_mid * factor)


def effective_kcb(
    species: Species,
    stage: PhenologicalStage,
    growth_stages: tuple[GrowthStage, ...] | None = None,
) -> float:
    """
    Kcb (traspirazione basale) con la riduzione di dormienza applicata.

    Come `effective_kc` ma **senza pavimento evaporativo**: nel modello
    dual-Kc l'evaporazione dalla superficie è contabilizzata a parte da
    Ke, quindi Kcb è traspirazione pura e in dormienza può scendere
    liberamente verso valori molto bassi.

    Richiede una specie con i Kcb valorizzati (`supports_dual_kc`).
    """
    base_map = {
        PhenologicalStage.INITIAL: species.kcb_initial,
        PhenologicalStage.MID_SEASON: species.kcb_mid,
        PhenologicalStage.LATE_SEASON: species.kcb_late,
    }
    base = base_map[stage]
    if growth_stages is None:
        return base
    factor = dormancy_kc_factor(growth_stages)
    if factor is None:
        return base
    return species.kcb_mid * factor


def kc_for_stage(species: Species, stage: PhenologicalStage) -> float:
    """
    Restituisce il coefficiente colturale Kc della specie nello stadio
    richiesto, leggendo la tabella interna di Species.

    È un semplice lookup ma merita una funzione dedicata: centralizza il
    mapping stadio→attributo in un unico punto, così che se in futuro
    aggiungeremo nuovi stadi (sviluppo, transizioni) la logica viva qui
    e non sia duplicata in chi usa Species.
    """
    mapping = {
        PhenologicalStage.INITIAL: species.kc_initial,
        PhenologicalStage.MID_SEASON: species.kc_mid,
        PhenologicalStage.LATE_SEASON: species.kc_late,
    }
    return mapping[stage]


def potential_et_c(
    species: Species,
    stage: PhenologicalStage,
    et_0: float,
    growth_stages: tuple[GrowthStage, ...] | None = None,
) -> float:
    """
    Evapotraspirazione potenziale della coltura: ET_c = Kc × ET_0.

    È la quantità di acqua che la pianta consumerebbe in assenza di
    qualunque limitazione idrica. Utile come valore di riferimento
    "teorico", ma nella maggior parte delle simulazioni realistiche
    si preferisce `actual_et_c`, che include la riduzione per stress.

    Passando `growth_stages` (la vista botanica alla data corrente) il
    Kc viene ridotto se la pianta è in dormienza o riposo. Omettendolo
    il comportamento è quello storico, senza riduzione.

    L'unità di misura di ritorno è la stessa di et_0 (tipicamente mm/giorno).
    """
    return effective_kc(species, stage, growth_stages) * et_0


def actual_et_c(
    species: Species,
    stage: PhenologicalStage,
    et_0: float,
    current_theta: float,
    substrate: Substrate,
    growth_stages: tuple[GrowthStage, ...] | None = None,
) -> float:
    """
    Evapotraspirazione reale della coltura: ET_c,act = Ks × Kc × ET_0.

    Include il coefficiente di stress idrico Ks (FAO-56 eq. 84), che
    riduce linearmente il consumo quando il substrato si asciuga oltre
    la soglia di deplezione specifica della specie. Questa è la
    formulazione raccomandata per simulazioni realistiche: nella zona
    di comfort coincide con `potential_et_c`, nella zona di stress
    scende progressivamente verso zero quando θ si avvicina a θ_PWP.

    Il Ks viene calcolato con la depletion_fraction della specie, non
    con il default globale: ad esempio per la lattuga (p=0.30) la zona
    di stress parte prima che per il rosmarino (p=0.60), a parità di
    substrato.

    Passando `growth_stages` il Kc viene ridotto in dormienza o riposo
    (vedi `effective_kc`). Ks e la riduzione di dormienza sono
    indipendenti e si moltiplicano: una perenne dormiente in substrato
    asciutto consuma poco per entrambe le ragioni.
    """
    ks = stress_coefficient_ks(
        current_theta=current_theta,
        substrate=substrate,
        depletion_fraction=species.depletion_fraction,
    )
    return ks * effective_kc(species, stage, growth_stages) * et_0


# =======================================================================
#  CATALOGO DI SPECIE
# =======================================================================
# Cinque specie rappresentative dei regimi agronomici più comuni nel
# giardinaggio domestico italiano. I valori di Kc sono tratti da FAO-56
# Tabella 12 (colture orticole) e Tabella 17 (colture arboree); le
# frazioni di deplezione da FAO-56 Tabella 22. Per il rosmarino, non
# coperto direttamente da FAO-56, i valori sono stimati dalla letteratura
# mediterranea su erbe aromatiche xerofite.
#
# Questi sono punti di partenza ragionevoli per l'avvio delle
# simulazioni; in uso prolungato vanno calibrati confrontando le
# previsioni con le letture reali dei sensori WH51 sul singolo vaso.

BASIL = Species(
    common_name="Basilico",
    scientific_name="Ocimum basilicum",
    kc_initial=0.50,
    kc_mid=1.05,
    kc_late=0.80,
    depletion_fraction=0.40,
    initial_stage_days=20,
    mid_stage_days=50,
    notes=(
        "Erba aromatica a foglia larga. Kc da FAO-56 Tab. 12 "
        "(categoria 'Herbs'). Sensibile allo stress idrico, p=0.40: "
        "irrigazioni frequenti in estate. Coltivabile indoor tutto "
        "l'anno, outdoor da maggio a settembre a latitudini padane. "
        "Ciclo colturale tipico: 20+50+30 giorni dalla semina."
    ),
    stomatal_resistance_s_m=100.0,
    crop_height_m=0.30,
)

TOMATO = Species(
    common_name="Pomodoro",
    scientific_name="Solanum lycopersicum",
    kc_initial=0.60,
    kc_mid=1.15,
    kc_late=0.80,
    depletion_fraction=0.40,
    initial_stage_days=30,
    mid_stage_days=60,
    notes=(
        "Orticola da frutto outdoor. Kc_mid=1.15 durante fruttificazione. "
        "Kc_late=0.80 a fine stagione per riduzione del fabbisogno "
        "quando i frutti stanno maturando. Sensibile al marciume apicale "
        "in caso di irrigazione irregolare. Durate da FAO-56 Tab. 11."
    ),
    stomatal_resistance_s_m=130.0,
    crop_height_m=0.60,
)

LETTUCE = Species(
    common_name="Lattuga",
    scientific_name="Lactuca sativa",
    kc_initial=0.70,
    kc_mid=1.00,
    kc_late=0.95,
    depletion_fraction=0.30,
    initial_stage_days=15,
    mid_stage_days=25,
    notes=(
        "Ortaggio a foglia tenera, molto sensibile allo stress idrico. "
        "p=0.30 significa soglia di allerta precoce (appena il 30% della "
        "TAW si è esaurito): richiede monitoraggio frequente in estate. "
        "Ciclo colturale breve (15+25+10 ≈ 50 giorni), Kc_late alto "
        "perché la coltura è ancora pienamente verde alla raccolta."
    ),
    stomatal_resistance_s_m=100.0,
    crop_height_m=0.20,
    # Coltura da foglia: si raccoglie sempre prima della fioritura
    # (la salita a seme è un difetto, non uno stadio previsto).
    annual_growth_stages=(
        (GrowthStage.VEGETATIVE,),   # INITIAL
        (GrowthStage.VEGETATIVE,),   # MID_SEASON
        (GrowthStage.VEGETATIVE,),   # LATE_SEASON
    ),
)

CITRUS = Species(
    common_name="Limone in vaso",
    scientific_name="Citrus limon",
    kc_initial=0.70,
    kc_mid=0.65,
    kc_late=0.70,
    depletion_fraction=0.50,
    initial_stage_days=60,
    mid_stage_days=240,
    notes=(
        "Agrume sempreverde coltivato in grandi vasi. Kc relativamente "
        "basso e quasi costante tutto l'anno, tipico dei sempreverdi a "
        "foglie cerose. Tollera meglio lo stress (p=0.50) grazie alla "
        "cuticola spessa che limita la traspirazione. Richiede "
        "ricovero invernale al riparo dal gelo a latitudini padane. "
        "Specie PERENNIAL: lo stadio segue la stagione, non i giorni "
        "dall'impianto. Le durate initial/mid_stage_days restano per "
        "retrocompatibilità ma non vengono usate nel calcolo."
    ),
    stomatal_resistance_s_m=140.0,
    crop_height_m=2.00,
    phenology_anchor=PhenologyAnchor.PERENNIAL,
    # Sempreverde: fioritura primaverile, fruttificazione lunga fino
    # all'inverno. Stessi dati del gruppo "agrume" di The Pot.
    phenology_calendar=(
        (GrowthStage.REST, GrowthStage.FRUITING),          # gennaio
        (GrowthStage.VEGETATIVE, GrowthStage.FRUITING),    # febbraio
        (GrowthStage.VEGETATIVE,),                         # marzo
        (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),   # aprile
        (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),   # maggio
        (GrowthStage.VEGETATIVE, GrowthStage.FRUITING),    # giugno
        (GrowthStage.FRUITING,),                           # luglio
        (GrowthStage.FRUITING,),                           # agosto
        (GrowthStage.FRUITING,),                           # settembre
        (GrowthStage.FRUITING,),                           # ottobre
        (GrowthStage.REST, GrowthStage.FRUITING),          # novembre
        (GrowthStage.REST, GrowthStage.FRUITING),          # dicembre
    ),
)

ROSEMARY = Species(
    common_name="Rosmarino",
    scientific_name="Salvia rosmarinus",
    kc_initial=0.40,
    kc_mid=0.75,
    kc_late=0.65,
    depletion_fraction=0.60,
    initial_stage_days=45,
    mid_stage_days=240,
    notes=(
        "Arbusto aromatico mediterraneo, xerofita adattata a climi "
        "aridi estivi. Kc contenuto, tolleranza allo stress elevata "
        "(p=0.60): preferisce terreno asciutto tra un'irrigazione e "
        "l'altra. Substrato drenante obbligatorio per evitare marciume "
        "radicale. Perenne outdoor a latitudini italiane: lo stadio "
        "segue la stagione, non i giorni dall'impianto."
    ),
    stomatal_resistance_s_m=200.0,
    crop_height_m=0.60,
    phenology_anchor=PhenologyAnchor.PERENNIAL,
    # Aromatica perenne mediterranea: riposo invernale, ripresa a
    # marzo, fioritura tarda primavera-estate. Stessi dati del gruppo
    # "aromatica" di The Pot.
    phenology_calendar=(
        (GrowthStage.REST,),                               # gennaio
        (GrowthStage.REST,),                               # febbraio
        (GrowthStage.VEGETATIVE,),                         # marzo
        (GrowthStage.VEGETATIVE,),                         # aprile
        (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),   # maggio
        (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),   # giugno
        (GrowthStage.VEGETATIVE, GrowthStage.FLOWERING),   # luglio
        (GrowthStage.VEGETATIVE,),                         # agosto
        (GrowthStage.VEGETATIVE,),                         # settembre
        (GrowthStage.REST,),                               # ottobre
        (GrowthStage.REST,),                               # novembre
        (GrowthStage.REST,),                               # dicembre
    ),
)


ALL_SPECIES = (BASIL, TOMATO, LETTUCE, CITRUS, ROSEMARY)
