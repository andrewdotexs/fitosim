"""
Proprietà idrauliche dei substrati di coltivazione in vaso.

Ogni substrato è caratterizzato da due parametri idrologici fondamentali:

  θ_FC  (contenuto idrico volumetrico a capacità di campo)
      La quantità di acqua, espressa come frazione del volume totale,
      che il substrato trattiene dopo il drenaggio gravitazionale. È
      il "livello pieno" utile del serbatoio-vaso.

  θ_PWP (contenuto idrico volumetrico al punto di appassimento permanente)
      La soglia sotto la quale la pianta non riesce più a estrarre acqua,
      perché le forze capillari del substrato superano la suzione
      radicale. Corrisponde convenzionalmente a un potenziale matriciale
      di −1500 kPa. È il "livello vuoto" effettivo per la pianta.

Dalla coppia (θ_FC, θ_PWP) si derivano due grandezze operative:

  TAW = θ_FC − θ_PWP          Total Available Water.
                                L'intera riserva utilizzabile.
  RAW = p × TAW                 Readily Available Water.
                                La frazione estraibile senza stress,
                                con p detta "frazione di deplezione".

Moltiplicando queste frazioni volumetriche per il volume fisico del vaso
si ottengono le grandezze idrauliche in litri che il bilancio idrico
(prossimo modulo `science.balance`) userà come input.

Nota sui valori del catalogo: i numeri tabellati sono valori
rappresentativi della letteratura orticola per miscele commerciali
tipiche. In uso reale variano entro ±15-20% in funzione del produttore,
del grado di compattazione, e del tempo trascorso dal confezionamento.
Versioni future di fitosim permetteranno la calibrazione per-vaso dei
parametri sulla base dei feedback reali del sensore WH51.
"""

from dataclasses import dataclass
import math


# Frazione di deplezione di default. Il valore 0.5 è quello raccomandato
# da FAO-56 come baseline "safe" per la maggior parte delle colture
# orticole. Specie particolarmente sensibili allo stress idrico (lattughe,
# foglie tenere) vogliono valori più bassi (0.3-0.4); specie tolleranti
# o xerofite (agrumi maturi, rosmarino, succulente) tollerano valori più
# alti (0.6-0.7). Il parametro resta modificabile dalla signature delle
# funzioni che lo usano.
DEFAULT_DEPLETION_FRACTION = 0.5


@dataclass(frozen=True)
class Substrate:
    """
    Rappresentazione immutabile di un substrato di coltivazione.

    Attributi
    ---------
    name : str
        Etichetta descrittiva, usata per stampa e logging.
    theta_fc : float
        Contenuto idrico volumetrico a capacità di campo, adimensionale,
        nell'intervallo [0, 1]. Rappresenta il rapporto
        (volume di acqua) / (volume di substrato) al raggiungimento
        della capacità di campo.
    theta_pwp : float
        Contenuto idrico volumetrico al punto di appassimento
        permanente, adimensionale, nell'intervallo [0, theta_fc).
    description : str, opzionale
        Nota libera per documentare composizione o comportamento tipico.
    rew_mm, tew_mm : float | None, opzionali
        Parametri del modello dual-Kc (FAO-56 cap. 7). Vedi sezione
        dedicata sotto.
    cec_meq_per_100g : float | None, opzionale
        Capacità di scambio cationico, in milli-equivalenti per 100 g
        di sostanza secca. Aggiunto in tappa 3 della fascia 2 per
        modellare lo smorzamento delle variazioni di pH durante la
        fertirrigazione. Valori tipici:

          - sabbia silicea, lapillo, pomice : 5-15 (CEC bassa, niente
            buffering, le variazioni di pH si propagano inalterate)
          - terriccio universale commerciale : 30-60 (CEC media,
            buffering moderato)
          - miscele basate su torba acida : 100-150 (CEC alta, le
            variazioni di pH vengono smorzate significativamente)

        Quando lasciato None, il modello chimico della tappa 3 usa un
        default ragionevole (vedi `effective_cec_meq_per_100g`).
    ph_typical : float | None, opzionale
        pH "di natura" del substrato, cioè il pH atteso di un campione
        appena confezionato prima dell'uso. Aggiunto in tappa 3 della
        fascia 2 per supportare l'inizializzazione corretta del pH dei
        vasi: un'azalea piantata in terriccio per acidofile parte da
        pH 5 circa, non da pH neutro 7. Valori tipici:

          - terriccio per acidofile (rododendri, mirtilli, azalee) : 4.5-5.5
          - terriccio universale commerciale standard : 6.0-7.0
          - terriccio "calcareo" o miscele con tufo dolomitico : 7.5-8.0

        Quando lasciato None, il pH iniziale del Pot ricade sul valore
        neutro 7.0 (vedi gerarchia di inizializzazione in `Pot.__init__`).

    Vincoli
    -------
    La validazione impone: 0 ≤ θ_PWP < θ_FC ≤ 1. Un substrato con
    θ_PWP ≥ θ_FC sarebbe fisicamente contraddittorio (non esisterebbe
    acqua utilizzabile) e viene rifiutato con ValueError.

    Essendo `frozen=True`, le istanze sono immutabili e hashable: è
    possibile usarle come chiavi di dizionari o elementi di set.
    """

    name: str
    theta_fc: float
    theta_pwp: float
    description: str = ""
    # ----- Parametri per il modello dual-Kc (FAO-56 cap. 7) -----
    # Sono opzionali: quando entrambi sono None, il substrato non
    # supporta il dual-Kc e il motore ricade sul single Kc tradizionale.
    # Quando entrambi sono valorizzati, la dinamica di evaporazione
    # superficiale viene tracciata esplicitamente.
    rew_mm: float | None = None  # readily evaporable water (mm)
    tew_mm: float | None = None  # total evaporable water (mm)
    # ----- Parametro chimico per la fertirrigazione (tappa 3 fascia 2) -----
    # Capacità di scambio cationico, in meq/100g di sostanza secca.
    # Modula lo smorzamento del pH durante la fertirrigazione: substrato
    # con CEC alta resiste alle variazioni di pH, substrato con CEC bassa
    # le subisce praticamente intatte.
    cec_meq_per_100g: float | None = None
    # pH "di natura" del substrato, cioè il pH atteso di un campione
    # appena confezionato. Quando il giardiniere lo specifica, il Pot
    # lo usa come default per l'inizializzazione del ph_substrate
    # invece del neutro 7.0.
    ph_typical: float | None = None

    def __post_init__(self) -> None:
        # Controllo di consistenza fisica sui due parametri idrici.
        # Scritto come disuguaglianza incatenata per chiarezza: vogliamo
        # che i due valori vivano dentro [0, 1] e nel giusto ordine.
        if not (0.0 <= self.theta_pwp < self.theta_fc <= 1.0):
            raise ValueError(
                f"Substrato '{self.name}': i contenuti idrici devono "
                f"soddisfare 0 ≤ θ_PWP ({self.theta_pwp}) < "
                f"θ_FC ({self.theta_fc}) ≤ 1. "
                f"Controlla i parametri."
            )
        # Validazione dei parametri dual-Kc: o sono entrambi None
        # (single Kc), o entrambi presenti con REW < TEW e positivi.
        if (self.rew_mm is None) != (self.tew_mm is None):
            raise ValueError(
                f"Substrato '{self.name}': REW e TEW devono essere "
                f"specificati entrambi o nessuno. Ricevuti: "
                f"REW={self.rew_mm}, TEW={self.tew_mm}."
            )
        if self.rew_mm is not None and self.tew_mm is not None:
            if not 0.0 < self.rew_mm < self.tew_mm:
                raise ValueError(
                    f"Substrato '{self.name}': vincolo violato "
                    f"0 < REW ({self.rew_mm}) < TEW ({self.tew_mm})."
                )
        # Validazione della CEC: deve essere positiva quando specificata.
        # Il limite superiore di 300 cattura errori di trascrizione
        # evidenti (es. valori espressi in unità sbagliate) senza
        # escludere torbe acide pure che possono arrivare a 200.
        if self.cec_meq_per_100g is not None:
            if not 0.0 < self.cec_meq_per_100g <= 300.0:
                raise ValueError(
                    f"Substrato '{self.name}': cec_meq_per_100g="
                    f"{self.cec_meq_per_100g} è fuori range plausibile "
                    f"(0, 300]. Verifica le unità: la CEC va in "
                    f"meq/100g di sostanza secca. Valori tipici: "
                    f"5-15 sabbia, 30-60 terriccio universale, "
                    f"100-150 torba acida."
                )

        # Validazione del pH tipico: range fisico [0, 14] della scala.
        # In pratica i substrati reali stanno in [3, 9]; mettendo i
        # limiti chimici puri (0-14) catturiamo errori di trascrizione
        # evidenti senza escludere casi limite legittimi come i terricci
        # per acidofile più estremi (pH 4-4.5).
        if self.ph_typical is not None:
            if not 0.0 < self.ph_typical < 14.0:
                raise ValueError(
                    f"Substrato '{self.name}': ph_typical="
                    f"{self.ph_typical} è fuori scala chimica (0, 14). "
                    f"I substrati reali tipicamente stanno in [3, 9]. "
                    f"Verifica il valore."
                )

    @property
    def effective_cec_meq_per_100g(self) -> float:
        """
        CEC effettiva da usare nel modello chimico, con fallback
        ragionevole quando non è specificata.

        Aggiunto in tappa 3 della fascia 2: rende esplicito il default
        quando il giardiniere non ha caratterizzato il substrato sul
        piano chimico. Il valore 50 corrisponde a un terriccio
        universale tipico ed è un compromesso che produce un buffering
        moderato del pH, non così assertivo da nascondere errori di
        fertirrigazione né così debole da rendere il substrato
        completamente succube delle variazioni in ingresso.

        Quando il giardiniere conosce la composizione esatta del suo
        substrato (es. perché ha letto il sacchetto o perché usa una
        miscela autoprodotta documentata) può specificare
        `cec_meq_per_100g` esplicitamente al costruttore di Substrate.
        """
        if self.cec_meq_per_100g is None:
            return 50.0
        return self.cec_meq_per_100g

    @property
    def effective_ph_typical(self) -> float:
        """
        pH tipico effettivo da usare per inizializzare il pH del
        substrato di un Pot, con fallback al neutro quando non è
        specificato.

        Aggiunto in tappa 3 della fascia 2 per supportare la gerarchia
        di inizializzazione "esplicito > substrato > neutro": quando
        il chiamante costruisce un Pot senza specificare `ph_substrate`,
        il valore iniziale viene preso da questa property, che a sua
        volta ricade sul neutro 7.0 se il substrato non documenta il
        suo pH naturale.

        Per i casi pratici è importante che il giardiniere specifichi
        `ph_typical` quando conosce la natura del substrato (es. ha
        comprato terriccio per acidofile per le sue azalee): la
        differenza tra "azalea che parte da pH 5 vs pH 7" è
        significativa per il modello chimico.
        """
        if self.ph_typical is None:
            return 7.0
        return self.ph_typical


# =======================================================================
#  CATALOGO DI SUBSTRATI TIPICI
# =======================================================================
# I valori riportati sono rappresentativi di miscele commerciali standard
# per giardinaggio domestico a latitudini medie. Sono stati scelti come
# punto di partenza ragionevole per simulazioni iniziali; la calibrazione
# fine per il singolo vaso andrà fatta confrontando le previsioni del
# bilancio idrico con le letture del sensore WH51 nel tempo.

UNIVERSAL_POTTING_SOIL = Substrate(
    name="Terriccio universale",
    theta_fc=0.40,
    theta_pwp=0.15,
    description=(
        "Miscela bilanciata di torba, compost e inerti (perlite o "
        "vermiculite). Il substrato 'di default' per la maggior parte "
        "delle piante ornamentali e da orto domestiche."
    ),
)

PEAT_BASED = Substrate(
    name="Torba di sfagno",
    theta_fc=0.55,
    theta_pwp=0.20,
    description=(
        "Substrato acidofilo ad altissima ritenzione idrica. Adatto ad "
        "azalee, rododendri, mirtilli. Elevato rischio di ristagno in "
        "vasi bassi: richiede drenaggio eccellente."
    ),
)

COCO_COIR = Substrate(
    name="Fibra di cocco",
    theta_fc=0.50,
    theta_pwp=0.18,
    description=(
        "Alternativa sostenibile alla torba. Buona ritenzione con "
        "migliore aerazione e pH più neutro. Richiede spesso integrazione "
        "nutritiva iniziale perché intrinsecamente povero."
    ),
)

CACTUS_MIX = Substrate(
    name="Substrato per cactacee",
    theta_fc=0.25,
    theta_pwp=0.08,
    description=(
        "Miscela sabbiosa-ghiaiosa a basso trattenimento idrico, pensata "
        "per xerofite e succulente. Drenaggio eccellente, riserva idrica "
        "modesta. Perfetta quando il rischio maggiore è il marciume, non "
        "la siccità."
    ),
)

PERLITE_RICH = Substrate(
    name="Mix con perlite abbondante",
    theta_fc=0.30,
    theta_pwp=0.10,
    description=(
        "Miscela drenante con forte presenza di perlite o pomice. "
        "Ritenzione intermedia, grande apporto di aria alle radici. "
        "Tipica dei substrati idroponici semi-inerti e degli agrumi in vaso."
    ),
)


# Tupla di tutti i substrati del catalogo, utile per iterare (test,
# esempi, grafici di confronto). L'ordine è dal più ritentivo al più
# drenante, una progressione naturale quando si vuole visualizzare la
# gamma di comportamenti idrici.
ALL_SUBSTRATES = (
    PEAT_BASED,
    COCO_COIR,
    UNIVERSAL_POTTING_SOIL,
    PERLITE_RICH,
    CACTUS_MIX,
)


# =======================================================================
#  FUNZIONI DI CALCOLO
# =======================================================================

def total_available_water(substrate: Substrate) -> float:
    """
    Acqua totale disponibile TAW come frazione volumetrica adimensionale.

    TAW = θ_FC − θ_PWP. Rappresenta l'intera riserva idrica utilizzabile
    dalla pianta nel substrato. Moltiplicata per il volume del vaso in
    litri fornisce la riserva assoluta in litri d'acqua.
    """
    return substrate.theta_fc - substrate.theta_pwp


def readily_available_water(
    substrate: Substrate,
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION,
) -> float:
    """
    Acqua facilmente disponibile RAW come frazione volumetrica.

    RAW = p × TAW, dove p ∈ [0, 1] è la frazione di deplezione tollerata
    prima che inizi lo stress idrico (chiusura stomatica, riduzione
    della traspirazione effettiva).

    È il "margine di sicurezza" all'interno della TAW: quando il
    contenuto idrico del vaso scende oltre questo valore, l'algoritmo
    di irrigazione dovrebbe triggerare un'allerta, evitando di far
    arrivare la pianta ai regimi di stress.

    Solleva ValueError se depletion_fraction è fuori da [0, 1].
    """
    if not 0.0 <= depletion_fraction <= 1.0:
        raise ValueError(
            f"depletion_fraction deve essere in [0, 1]; "
            f"ricevuto {depletion_fraction}."
        )
    return depletion_fraction * total_available_water(substrate)


def water_volume_at_field_capacity(
    substrate: Substrate,
    pot_volume_l: float,
) -> float:
    """
    Volume d'acqua in litri trattenuto a capacità di campo in un vaso
    di volume fisico pot_volume_l (in litri).

    Conversione: 1 L di substrato × θ_FC (m³/m³) = θ_FC litri di acqua,
    perché la frazione volumetrica è adimensionale e lo stesso fattore
    vale qualunque unità si usi, purché coerente tra numeratore e
    denominatore.
    """
    _validate_pot_volume(pot_volume_l)
    return pot_volume_l * substrate.theta_fc


def water_volume_available(
    substrate: Substrate,
    pot_volume_l: float,
) -> float:
    """
    Volume d'acqua totale disponibile in litri per un vaso di volume
    pot_volume_l. È il prodotto TAW × volume_vaso.

    Questo è il numero che più intuitivamente rappresenta "quanta acqua
    utile il vaso può effettivamente dare alla pianta". Un vaso da 5 L
    di terriccio universale ha water_volume_available di 1.25 L: è quel
    poco più di un litro che sta tra "appena innaffiato" e "pianta
    appassita".
    """
    _validate_pot_volume(pot_volume_l)
    return pot_volume_l * total_available_water(substrate)


def water_volume_readily_available(
    substrate: Substrate,
    pot_volume_l: float,
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION,
) -> float:
    """
    Volume d'acqua facilmente disponibile in litri: RAW × volume_vaso.

    È il parametro operativo che il bilancio idrico confronterà con il
    deficit accumulato per decidere quando triggerare un'irrigazione.
    """
    _validate_pot_volume(pot_volume_l)
    return pot_volume_l * readily_available_water(
        substrate, depletion_fraction
    )


def _validate_pot_volume(pot_volume_l: float) -> None:
    """
    Guardia comune per i parametri di volume del vaso.

    Un volume negativo non ha senso fisico; un volume zero è
    tecnicamente valido (darebbe acqua zero, che è consistente) ma
    spesso segnala un errore di inizializzazione a monte. Accettiamo
    lo zero in silenzio ma rifiutiamo i negativi con messaggio chiaro.
    """
    if pot_volume_l < 0:
        raise ValueError(
            f"pot_volume_l non può essere negativo (ricevuto "
            f"{pot_volume_l}). Verifica il volume del vaso in litri."
        )


# =======================================================================
#  UTILITÀ GEOMETRICHE E DI CONVERSIONE DI UNITÀ
# =======================================================================
# Queste funzioni fanno da ponte tra la rappresentazione "nativa" del
# substrato — contenuto idrico volumetrico θ, adimensionale — e la
# rappresentazione "nativa" dell'agronomia FAO-56 — colonna d'acqua
# equivalente espressa in mm. La conversione richiede di conoscere la
# profondità effettiva del substrato, che per un vaso si ricava dal
# rapporto volume/area-superficiale.


def circular_pot_surface_area_m2(diameter_cm: float) -> float:
    """
    Area superficiale (sommità) di un vaso cilindrico dato il diametro.

    Ritorna l'area in m² a partire dal diametro in cm. È un piccolo
    aiuto per evitare conversioni manuali quando si descrive un vaso
    reale: i cataloghi commerciali di vasi quotano tipicamente il
    diametro in cm, mentre le formule del bilancio idrico hanno bisogno
    dell'area in m².

    Parametri
    ---------
    diameter_cm : float
        Diametro del vaso in centimetri. Positivo.

    Ritorna
    -------
    float
        Area della base circolare in m².
    """
    if diameter_cm <= 0:
        raise ValueError(
            f"diameter_cm deve essere positivo (ricevuto {diameter_cm})."
        )
    radius_m = (diameter_cm / 100.0) / 2.0
    return math.pi * radius_m * radius_m


def truncated_cone_pot_surface_area_m2(top_diameter_cm: float) -> float:
    """
    Area superficiale (sommità) di un vaso tronco-conico.

    Per il bilancio idrico ci interessa solo la superficie *superiore*,
    da cui avvengono evaporazione del substrato e ricaduta della pioggia.
    Quella superiore è circolare, quindi questa funzione è semplicemente
    un alias semantico di `circular_pot_surface_area_m2` applicato al
    diametro alla sommità — il diametro alla base è irrilevante per il
    flusso idrico in/out e serve solo come parametro estetico/strutturale.

    L'esistenza di una funzione separata è giustificata dalla chiarezza:
    quando il codice cliente descrive un vaso "tronco-conico, 22 cm di
    apertura", chiamare `truncated_cone_pot_surface_area_m2(22)` è più
    leggibile e meno suscettibile a errori di "ho passato il diametro
    sbagliato".
    """
    return circular_pot_surface_area_m2(top_diameter_cm)


def rectangular_pot_surface_area_m2(
    length_cm: float,
    width_cm: float,
) -> float:
    """
    Area superficiale di un vaso a base rettangolare (es. cassetta da
    balcone, fioriera quadrata).

    Parametri
    ---------
    length_cm, width_cm : float
        Lunghezza e larghezza interne della sommità del vaso, in cm.
        Per un quadrato si passa lo stesso valore due volte.

    Ritorna
    -------
    float
        Area della superficie superiore in m².
    """
    if length_cm <= 0 or width_cm <= 0:
        raise ValueError(
            f"Le dimensioni del vaso rettangolare devono essere "
            f"positive (ricevuto length={length_cm}, width={width_cm})."
        )
    return (length_cm / 100.0) * (width_cm / 100.0)


def oval_pot_surface_area_m2(
    major_axis_cm: float,
    minor_axis_cm: float,
) -> float:
    """
    Area superficiale di un vaso a base ovale, modellato come ellisse.

    L'area di un'ellisse di semiassi a e b è π·a·b, dove a e b sono
    metà degli assi maggiore e minore. Per coerenza con le altre
    funzioni di questa famiglia, accettiamo gli assi *interi* in cm
    (i diametri ovvero i due lati della scatola che contiene
    l'ellisse) e dividiamo internamente.
    """
    if major_axis_cm <= 0 or minor_axis_cm <= 0:
        raise ValueError(
            f"Gli assi del vaso ovale devono essere positivi "
            f"(ricevuto major={major_axis_cm}, minor={minor_axis_cm})."
        )
    a_m = (major_axis_cm / 100.0) / 2.0
    b_m = (minor_axis_cm / 100.0) / 2.0
    return math.pi * a_m * b_m


def pot_substrate_depth_mm(
    pot_volume_l: float,
    surface_area_m2: float,
) -> float:
    """
    Profondità effettiva del substrato come "colonna equivalente" in mm.

    Formula: depth_mm = pot_volume_l / surface_area_m2.

    La derivazione dimensionale è compatta. 1 L = 1 dm³ = 10⁻³ m³ = 10⁶
    mm³; 1 m² = 10⁶ mm². Quindi V_L / A_m² = 10⁶·V / (10⁶·A) = V/A in
    mm. L'identità "1 L distribuito su 1 m² equivale a 1 mm di spessore"
    è la chiave mnemonica.

    Ha significato fisico diretto per un vaso cilindrico, in cui la
    profondità media è proprio la sua altezza. Per vasi di forma
    irregolare (tronco-conici, quadrati, figurati) resta una profondità
    "equivalente" coerente per il bilancio idrico, anche se non
    corrisponde letteralmente a nessuna altezza del contenitore.
    """
    if surface_area_m2 <= 0:
        raise ValueError(
            f"surface_area_m2 deve essere positiva "
            f"(ricevuto {surface_area_m2})."
        )
    _validate_pot_volume(pot_volume_l)
    return pot_volume_l / surface_area_m2


def theta_to_mm(theta: float, depth_mm: float) -> float:
    """
    Converte contenuto idrico volumetrico θ in colonna d'acqua in mm.

    Formula: mm = θ × profondità_mm. Adimensionale × mm = mm.

    Esempio: θ = 0.40 in un vaso con profondità 150 mm → 60 mm di
    colonna d'acqua (corrispondenti a 60 litri per m² di superficie).
    """
    if depth_mm < 0:
        raise ValueError(
            f"depth_mm non può essere negativo (ricevuto {depth_mm})."
        )
    return theta * depth_mm


def mm_to_theta(mm: float, depth_mm: float) -> float:
    """
    Converte colonna d'acqua in mm in contenuto idrico volumetrico θ.

    Formula: θ = mm / profondità_mm.

    È la trasformazione inversa di theta_to_mm. Necessita che depth_mm
    sia strettamente positiva (non si può dividere per zero).
    """
    if depth_mm <= 0:
        raise ValueError(
            f"depth_mm deve essere positiva per la conversione "
            f"inversa (ricevuto {depth_mm})."
        )
    return mm / depth_mm


# =======================================================================
#  Fabbrica di substrati: composizione di materiali base
# =======================================================================
#
# Le dataclass Substrate del catalogo (UNIVERSAL_POTTING_SOIL, COCO_COIR,
# etc.) descrivono substrati "pronti all'uso": miscele commerciali
# tipiche di cui conosciamo i parametri idraulici aggregati. Ma molti
# giardinieri (e specialmente i bonsaisti) preparano i propri substrati
# mischiando materiali base in proporzioni personalizzate. Per loro
# serve una via per costruire un Substrate a partire da una "ricetta".
#
# Il modello che adottiamo è il più semplice tra quelli sensati: media
# pesata sui volumi delle frazioni di ciascun materiale. È un'approssi-
# mazione del 5-10% rispetto a misure dirette in laboratorio, perché
# trascura due effetti del secondo ordine:
#
#   1. Packing: quando si mescolano materiali con granulometrie diverse,
#      le particelle fini si infilano negli interstizi delle grosse,
#      modificando leggermente la porosità totale e quindi θ_FC.
#
#   2. Curva di ritenzione non lineare: i punti θ_FC e θ_PWP sono
#      definiti dal potenziale matricco di equilibrio (-10 kPa per
#      substrati di vaso, -1500 kPa per il PWP), non dalla composizione
#      diretta. Mischiando due materiali con curve diverse, il punto
#      di equilibrio della miscela non è esattamente la media pesata
#      dei due punti separati.
#
# Per il dominio del giardinaggio domestico l'approssimazione lineare
# è adeguata. Se in futuro servirà più precisione, la strada giusta
# non è raffinare il modello teorico ma calibrare empiricamente i
# parametri dai sensori WH51, che è la prima estensione futura della
# roadmap.

@dataclass(frozen=True)
class BaseMaterial:
    """
    Materiale puro che entra come ingrediente in una miscela.

    Si distingue da `Substrate` perché un BaseMaterial tipicamente
    NON è un substrato pronto all'uso: pomice o sabbia pure non
    forniscono la ritenzione e il nutrimento sufficienti per le piante
    da giardinaggio. Sono ingredienti, non ricette finite.

    Attributi
    ---------
    name : str
        Nome leggibile per i report e i log.
    theta_fc : float
        Capacità di campo del materiale puro (θ a -10 kPa per
        convenzione vivaistica), adimensionale, [0, 1].
    theta_pwp : float
        Punto di appassimento permanente (θ a -1500 kPa),
        adimensionale, [0, 1]. Deve essere < theta_fc.
    description : str
        Note descrittive: provenienza, granulometria tipica, range
        di valori in letteratura.
    """

    name: str
    theta_fc: float
    theta_pwp: float
    description: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.theta_pwp < self.theta_fc <= 1.0:
            raise ValueError(
                f"BaseMaterial '{self.name}': vincolo violato "
                f"0 ≤ θ_PWP={self.theta_pwp} < θ_FC={self.theta_fc} ≤ 1."
            )


# -----------------------------------------------------------------------
#  Catalogo dei materiali base
# -----------------------------------------------------------------------
#
# Valori di θ_FC e θ_PWP in letteratura agronomica vivaistica e
# bonsaistica, mediane di range pubblicati. Coperture per ciascun
# materiale documentate nelle stringhe `description`.
#
# Riferimenti principali:
#   - Beeson (2007), HortScience 42(7)
#   - Bilderback et al. (2005), Best Management Practices: Guide for
#     Producing Container-Grown Plants
#   - Wageningen UR, Substrate Hydraulic Properties Database
#   - Letteratura italo-giapponese su substrati bonsaistici

BIONDA_PEAT = BaseMaterial(
    name="Torba bionda",
    theta_fc=0.58,
    theta_pwp=0.10,
    description=(
        "Torba di sfagno poco decomposta (H1-H3 sulla scala von Post). "
        "Range pubblicato: θ_FC 0.50-0.65, θ_PWP 0.08-0.13. "
        "Alta porosità, ottima ritenzione idrica, povera di nutrienti."
    ),
)

BRUNA_PEAT = BaseMaterial(
    name="Torba bruna",
    theta_fc=0.52,
    theta_pwp=0.15,
    description=(
        "Torba più decomposta (H4-H7), particelle più fini. "
        "Range pubblicato: θ_FC 0.45-0.58, θ_PWP 0.12-0.18. "
        "Maggiore ritenzione di nutrienti rispetto alla bionda, "
        "drenaggio più lento."
    ),
)

PERLITE = BaseMaterial(
    name="Perlite",
    theta_fc=0.08,
    theta_pwp=0.02,
    description=(
        "Vetro vulcanico espanso, granulometria 2-5 mm tipica per "
        "giardinaggio. Range pubblicato: θ_FC 0.05-0.12, θ_PWP "
        "0.01-0.03. Funzione primaria: drenaggio e aerazione, "
        "pochissimo contributo idrico."
    ),
)

VERMICULITE = BaseMaterial(
    name="Vermiculite",
    theta_fc=0.42,
    theta_pwp=0.08,
    description=(
        "Mica espansa termicamente, struttura lamellare che trattiene "
        "acqua tra i fogli. Range pubblicato: θ_FC 0.35-0.50, θ_PWP "
        "0.05-0.12. Buona ritenzione idrica e di nutrienti, alternativa "
        "alla perlite quando serve più capacità d'acqua."
    ),
)

COCO_FIBER = BaseMaterial(
    name="Fibra di cocco",
    theta_fc=0.55,
    theta_pwp=0.12,
    description=(
        "Fibra dal mesocarpo della noce di cocco, prodotto rinnovabile. "
        "Range pubblicato: θ_FC 0.48-0.62, θ_PWP 0.08-0.15. Comportamento "
        "idrico simile alla torba bionda, alternativa sostenibile."
    ),
)

POMICE = BaseMaterial(
    name="Pomice",
    theta_fc=0.18,
    theta_pwp=0.05,
    description=(
        "Roccia vulcanica porosa, granulometria 3-8 mm. Range pubblicato: "
        "θ_FC 0.12-0.25, θ_PWP 0.03-0.08. Drenaggio eccellente, "
        "stabilità strutturale alta. Base per molti mix bonsai."
    ),
)

SAND = BaseMaterial(
    name="Sabbia",
    theta_fc=0.12,
    theta_pwp=0.03,
    description=(
        "Sabbia di fiume lavata, granulometria 0.5-2 mm. Range pubblicato: "
        "θ_FC 0.08-0.18, θ_PWP 0.02-0.05. Drenaggio rapido, peso "
        "specifico alto (utile per stabilizzare vasi in terrazzi ventosi)."
    ),
)

AKADAMA = BaseMaterial(
    name="Akadama",
    theta_fc=0.45,
    theta_pwp=0.10,
    description=(
        "Argilla giapponese a grani granulari (kiryu), trattamento "
        "termico. Range pubblicato: θ_FC 0.40-0.50, θ_PWP 0.08-0.13. "
        "Materiale base classico dei mix bonsai, buona ritenzione idrica "
        "e capacità di scambio cationico. Si decompone in 2-3 anni."
    ),
)

LAPILLO = BaseMaterial(
    name="Lapillo",
    theta_fc=0.20,
    theta_pwp=0.06,
    description=(
        "Lapilli vulcanici (scoria), granulometria 3-8 mm. Range "
        "pubblicato: θ_FC 0.15-0.25, θ_PWP 0.04-0.08. Comportamento "
        "intermedio tra pomice e perlite, peso più alto. Comune nei "
        "mix bonsai italiani come alternativa a kiryu."
    ),
)


# Tutti i materiali base raccolti per iterabilità.
ALL_BASE_MATERIALS: tuple[BaseMaterial, ...] = (
    BIONDA_PEAT,
    BRUNA_PEAT,
    PERLITE,
    VERMICULITE,
    COCO_FIBER,
    POMICE,
    SAND,
    AKADAMA,
    LAPILLO,
)


# -----------------------------------------------------------------------
#  Composizione di una ricetta
# -----------------------------------------------------------------------

@dataclass(frozen=True)
class MixComponent:
    """
    Una porzione di materiale base in una miscela: il "verso x parti
    di Y" di una ricetta.

    Attributi
    ---------
    material : BaseMaterial
        L'ingrediente.
    fraction : float
        Frazione volumetrica nella miscela finale, in [0, 1]. La somma
        di tutte le frazioni in un mix deve essere 1.0 (validato in
        compose_substrate).
    """

    material: BaseMaterial
    fraction: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.fraction <= 1.0:
            raise ValueError(
                f"MixComponent: fraction deve essere in [0, 1] "
                f"(ricevuto {self.fraction} per "
                f"'{self.material.name}')."
            )


def compose_substrate(
    components: list[MixComponent],
    name: str = "custom mix",
    depletion_fraction: float | None = None,
    fraction_tolerance: float = 0.001,
) -> Substrate:
    """
    Costruisce un Substrate a partire da una ricetta di materiali base.

    Calcola θ_FC e θ_PWP del mix come **media pesata sui volumi** delle
    frazioni dei singoli ingredienti. È un'approssimazione del 5-10%
    rispetto a misure dirette in laboratorio, adeguata per il dominio
    del giardinaggio domestico.

    Parametri
    ---------
    components : list[MixComponent]
        Ricetta del mix. La somma delle fractions deve essere 1.0
        (entro `fraction_tolerance`). Almeno un componente richiesto.
    name : str, opzionale
        Nome del Substrate risultante. Se non specificato, viene usato
        "custom mix".
    depletion_fraction : float, opzionale
        Frazione di depletion per il Substrate risultante. Se omesso,
        usa il default del catalogo (DEFAULT_DEPLETION_FRACTION).
    fraction_tolerance : float, opzionale
        Tolleranza sulla somma delle frazioni. Default 0.001 (0.1%).

    Ritorna
    -------
    Substrate
        Il substrato composto, con θ_FC e θ_PWP calcolati come media
        pesata.

    Esempi
    ------
    Mix professionale 70% torba bionda + 30% perlite:

        mix = compose_substrate(
            components=[
                MixComponent(BIONDA_PEAT, 0.70),
                MixComponent(PERLITE, 0.30),
            ],
            name="Mix professionale 70/30",
        )

    Mix bonsai italiano classico 40/30/30 di akadama, pomice, lapillo:

        mix_bonsai = compose_substrate(
            components=[
                MixComponent(AKADAMA, 0.40),
                MixComponent(POMICE, 0.30),
                MixComponent(LAPILLO, 0.30),
            ],
            name="Mix bonsai standard",
        )
    """
    if not components:
        raise ValueError(
            "compose_substrate richiede almeno un componente "
            "(ricevuta lista vuota)."
        )

    total_fraction = sum(c.fraction for c in components)
    if abs(total_fraction - 1.0) > fraction_tolerance:
        raise ValueError(
            f"La somma delle frazioni deve essere 1.0 entro "
            f"{fraction_tolerance} (ricevuto {total_fraction:.4f}). "
            f"Verifica che le tue percentuali sommino al 100%."
        )

    theta_fc = sum(c.fraction * c.material.theta_fc for c in components)
    theta_pwp = sum(c.fraction * c.material.theta_pwp for c in components)

    # Costruisce il Substrate. depletion_fraction usa il default del
    # catalogo se non specificato — è un parametro del modello FAO-56
    # legato alla specie più che al substrato, quindi mantenere il
    # default è la scelta più sicura.
    kwargs = {
        "name": name,
        "theta_fc": theta_fc,
        "theta_pwp": theta_pwp,
    }
    if depletion_fraction is not None:
        kwargs["depletion_fraction"] = depletion_fraction
    return Substrate(**kwargs)

