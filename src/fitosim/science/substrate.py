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
