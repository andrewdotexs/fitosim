"""
Effetti fisici del contenitore sull'evapotraspirazione di un vaso.

Il modello FAO-56 di base, che abbiamo implementato in `science/balance.py`
e `domain/species.py`, tratta il vaso come un serbatoio idraulico ideale:
l'acqua esce solo per evapotraspirazione della coltura (ET_c = Kc × ET_0)
e per drenaggio quando si supera la capacità di campo. Questa
schematizzazione funziona perfettamente per colture di pieno campo,
dove il "vaso" è il terreno stesso e non ci sono pareti laterali. Per
i vasi domestici, però, il contenitore introduce due effetti fisici
che il modello base ignora e che possono essere significativi.

Effetto del materiale del vaso
------------------------------

La terracotta è porosa: l'acqua percola attraverso le pareti laterali
e si trasferisce all'aria esterna per evaporazione, in aggiunta a
quella che esce dalla superficie superiore. Per un vaso piccolo
(2-4 litri) in piena estate questo "leak laterale" può raggiungere
il 25-40% della perdita totale, ed è il motivo per cui i giardinieri
sanno che il basilico in vasetto di terracotta richiede irrigazioni
più frequenti che lo stesso vasetto di plastica. La plastica è invece
sostanzialmente impermeabile, e la ceramica smaltata anche.

Effetto del colore del vaso
---------------------------

Un vaso scuro al sole può raggiungere temperature interne del substrato
di 40-45 °C, contro i 28-30 °C di un vaso chiaro nelle stesse
condizioni. Questa differenza modula direttamente l'evapotraspirazione
attraverso la temperatura delle radici e della superficie evaporante.
È un effetto piccolo (5-15%) ma sistematico nei mesi caldi.

Effetto dell'esposizione solare
-------------------------------

Un vaso in pieno sole riceve il massimo del carico radiativo modellato
da ET₀; un vaso all'ombra parziale (mattino o pomeriggio in ombra,
oppure ombra leggera di alberi) ne riceve significativamente meno; un
vaso completamente all'ombra (cortile interno, esposizione nord)
ancora meno. Questo è probabilmente l'effetto più sostanzioso dei tre
(può essere -30% o -50%), ed è anche il più facile per il giardiniere
da osservare e classificare a vista.

Approccio modellistico
----------------------

Tutti e tre questi effetti vengono codificati come **fattori
moltiplicativi adimensionali** che modulano ET_c. La forma finale del
bilancio idrico diventa:

    ET_c,act = Ks × Kp × Kc × ET_0

dove Kp è un "coefficiente di vaso" (pot coefficient) che è il
prodotto di tre sotto-coefficienti indipendenti:

    Kp = f_material × f_color × f_exposure

I valori delle tabelle sono ricavati dalla letteratura agronomica
sulla coltivazione in vivaio (in particolare gli studi sull'irrigazione
dei contenitori per produzione ornamentale, che documentano
estensivamente le differenze tra materiali e colori) e tarati sul
buon senso del giardinaggio domestico. Sono **stime ragionevoli, non
misure esatte**: un giardiniere con dati WH51 reali del proprio vaso
li potrà calibrare nel tempo.

Riferimento di letteratura: Beeson (2007), "Determining plant-available
water of plants in containers from measurements of evapotranspiration",
HortScience 42(7).
"""

from enum import Enum


class PotMaterial(Enum):
    """
    Materiale del contenitore. Determina la permeabilità laterale e
    quindi la perdita per evaporazione attraverso le pareti.
    """

    PLASTIC = "plastic"
    """Plastica liscia, sostanzialmente impermeabile. Riferimento neutro."""

    GLAZED_CERAMIC = "glazed_ceramic"
    """Ceramica smaltata. Impermeabile come la plastica."""

    TERRACOTTA = "terracotta"
    """
    Terracotta non smaltata, porosa. Perde acqua per evaporazione
    laterale; questo effetto è particolarmente forte nei vasi piccoli.
    """

    WOOD = "wood"
    """
    Legno (cassette di legno, tronchetti scavati). Comportamento
    intermedio tra plastica e terracotta a seconda dell'essenza e del
    trattamento. Convenzione: prendiamo un valore medio.
    """

    METAL = "metal"
    """Metallo (zinco, acciaio). Impermeabile."""


class PotColor(Enum):
    """
    Colore prevalente del contenitore. Determina l'assorbimento di
    radiazione solare nelle ore diurne.
    """

    LIGHT = "light"
    """Bianco, beige, terracotta naturale chiara. Riflette molta radiazione."""

    MEDIUM = "medium"
    """Marrone, terracotta scura, grigio chiaro."""

    DARK = "dark"
    """Nero, antracite, verde scuro. Assorbe molta radiazione."""


class SunExposure(Enum):
    """
    Quantità di luce solare diretta che il vaso riceve in una giornata
    tipica della stagione di crescita. È un'autovalutazione del
    giardiniere, non una grandezza misurabile direttamente con un
    sensore (il sensore solare della stazione meteo misura la
    radiazione "in cielo aperto", non quella che arriva sul singolo
    vaso dietro un palazzo).
    """

    FULL_SUN = "full_sun"
    """
    Pieno sole: almeno 6 ore di luce diretta al giorno in piena stagione.
    Tipicamente terrazzi e balconi a sud, esposti.
    """

    PARTIAL_SHADE = "partial_shade"
    """
    Sole parziale: 3-5 ore di luce diretta al giorno. Balconi a est o
    ovest, oppure interni di balcone più profondi al sud.
    """

    SHADE = "shade"
    """
    Ombra: meno di 2 ore di sole diretto, oppure sole diffuso filtrato
    da chiome arboree o tessuti. Esposizioni a nord, cortili interni,
    angoli ombreggiati.
    """


# =======================================================================
#  Tabelle dei fattori moltiplicativi
# =======================================================================
# I valori scelti riflettono la "intuizione di letteratura" descritta
# nel docstring del modulo. Mantengono la plastica al sole come
# riferimento centrale (1.0) e quotano gli altri casi come delta da
# quel riferimento. Possono essere ri-tarati in futuro se la
# calibrazione coi sensori reali rivelerà bias sistematici.

_MATERIAL_FACTOR: dict[PotMaterial, float] = {
    PotMaterial.PLASTIC: 1.00,
    PotMaterial.GLAZED_CERAMIC: 0.98,  # leggera differenza per inerzia termica
    PotMaterial.TERRACOTTA: 1.30,      # +30% per evaporazione laterale
    PotMaterial.WOOD: 1.10,            # intermedio
    PotMaterial.METAL: 1.05,           # leggermente più caldo (alta conducibilità)
}

_COLOR_FACTOR: dict[PotColor, float] = {
    PotColor.LIGHT: 0.95,              # rifletti più radiazione
    PotColor.MEDIUM: 1.00,             # riferimento neutro
    PotColor.DARK: 1.10,               # +10% per maggior assorbimento
}

# L'esposizione è quella con effetto più grande. I valori sono
# multiplicatori netti (cioè già rapporti rispetto a "pieno sole").
# Una pianta in piena ombra perde molta meno acqua di una stessa pianta
# al sole, anche a parità di tutti gli altri parametri.
_EXPOSURE_FACTOR: dict[SunExposure, float] = {
    SunExposure.FULL_SUN: 1.00,
    SunExposure.PARTIAL_SHADE: 0.70,
    SunExposure.SHADE: 0.45,
}


# =======================================================================
#  Funzioni di lookup e composizione
# =======================================================================

def material_correction_factor(material: PotMaterial) -> float:
    """Fattore moltiplicativo per il materiale del contenitore."""
    return _MATERIAL_FACTOR[material]


def color_correction_factor(color: PotColor) -> float:
    """Fattore moltiplicativo per il colore prevalente del contenitore."""
    return _COLOR_FACTOR[color]


def exposure_correction_factor(exposure: SunExposure) -> float:
    """Fattore moltiplicativo per l'esposizione solare del vaso."""
    return _EXPOSURE_FACTOR[exposure]


def pot_correction_factor(
    material: PotMaterial,
    color: PotColor,
    exposure: SunExposure,
) -> float:
    """
    Coefficiente di vaso composto Kp = f_material × f_color × f_exposure.

    È il fattore moltiplicativo da applicare a ET_c per ottenere il
    consumo idrico reale del vaso. Per un vaso "neutro" (plastica,
    colore medio, pieno sole) vale esattamente 1.00 e l'output del
    motore è identico al modello FAO-56 base. Per i casi reali si
    discosta in entrambe le direzioni: un vaso piccolo di terracotta
    nera al sole può arrivare a 1.43 (molto più assetato del previsto),
    un vaso di plastica chiara all'ombra a 0.43 (molto meno assetato).

    Parametri
    ---------
    material : PotMaterial
        Materiale del contenitore.
    color : PotColor
        Colore prevalente.
    exposure : SunExposure
        Esposizione solare tipica.

    Ritorna
    -------
    float
        Kp adimensionale, tipicamente nell'intervallo [0.4, 1.5].
    """
    return (
        material_correction_factor(material)
        * color_correction_factor(color)
        * exposure_correction_factor(exposure)
    )


# Riferimento neutro pubblico, per i casi in cui il chiamante vuole
# documentare esplicitamente che sta usando "il vaso di default".
NEUTRAL_POT_CORRECTION = 1.00
