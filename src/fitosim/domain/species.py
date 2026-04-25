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


# =======================================================================
#  Funzioni di dominio
# =======================================================================

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
) -> float:
    """
    Evapotraspirazione potenziale della coltura: ET_c = Kc × ET_0.

    È la quantità di acqua che la pianta consumerebbe in assenza di
    qualunque limitazione idrica. Utile come valore di riferimento
    "teorico", ma nella maggior parte delle simulazioni realistiche
    si preferisce `actual_et_c`, che include la riduzione per stress.

    L'unità di misura di ritorno è la stessa di et_0 (tipicamente mm/giorno).
    """
    return kc_for_stage(species, stage) * et_0


def actual_et_c(
    species: Species,
    stage: PhenologicalStage,
    et_0: float,
    current_theta: float,
    substrate: Substrate,
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
    """
    ks = stress_coefficient_ks(
        current_theta=current_theta,
        substrate=substrate,
        depletion_fraction=species.depletion_fraction,
    )
    return ks * kc_for_stage(species, stage) * et_0


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
        "Per le perenni le durate sono convenzionali, riferite all'anno."
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
        "radicale. Perenne outdoor a latitudini italiane."
    ),
)


ALL_SPECIES = (BASIL, TOMATO, LETTUCE, CITRUS, ROSEMARY)
