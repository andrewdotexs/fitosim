"""
Modello della radiazione solare ricevuta da vasi indoor.

Questo modulo introduce la parametrizzazione della radiazione luminosa
per vasi che vivono dentro casa, dove la radiazione misurata dal
piranometro outdoor non è direttamente applicabile. La radiazione
indoor dipende fortemente dalla posizione del vaso rispetto alle
finestre, dall'orientamento della finestra, da eventuali
ombreggiamenti, e varia stagionalmente.

L'enum `LightExposure` (in `domain/room.py`) cattura la varianza
principale in tre livelli qualitativi (DARK, INDIRECT_BRIGHT,
DIRECT_SUN) attribuibili per osservazione diretta dal giardiniere.
Questo modulo associa ai tre livelli i valori numerici che il
selettore di evapotraspirazione consuma.

Strategia: ibrida categoriale + continua
----------------------------------------

La libreria offre due modi di stimare la radiazione indoor, e il
chiamante sceglie quale usare in base ai dati disponibili.

**Modo categoriale**: tre valori fissi associati ai tre livelli di
LightExposure, indipendenti dalla data. È un fallback semplice che
funziona sempre, anche se il chiamante non ha dati outdoor del
giorno. La limitazione è che ignora la stagionalità: una pianta sul
davanzale a sud riceve molto meno sole in inverno (giorni corti,
sole basso) che in estate, ma il modo categoriale produce lo stesso
numero in entrambe le stagioni.

**Modo continuo (frazione di outdoor)**: la radiazione indoor è
stimata come una frazione della radiazione globale outdoor del
giorno, dove la frazione dipende dal LightExposure del vaso. Più
accurato perché cattura naturalmente la stagionalità (la radiazione
outdoor è già stagionale) e anche le variazioni giornaliere
(giorno nuvoloso vs sereno). Richiede che il chiamante abbia anche
i dati outdoor del giorno, tipicamente dalla stazione meteo
Ecowitt esterna.

Il metodo `apply_balance_step_from_indoor` del Pot (introdotto
dalla fase D2 della sotto-tappa D) accetta un parametro opzionale
`outdoor_solar_radiation_mj_m2_day`: se popolato il modello usa la
frazione (modo continuo), se None ricade sul valore categoriale
(modo fallback).

Calibrazione futura
-------------------

I valori numerici scelti per i due modi sono di letteratura
agronomica sulla radiazione indoor, ma riflettono valori medi
generici. Saranno raffinati in fascia 3 con calibrazione contro
osservazioni reali (per esempio confrontando il consumo idrico
osservato di un vaso indoor con la previsione del modello, e
aggiustando la frazione del LightExposure corrispondente).
"""


from dataclasses import dataclass
from enum import Enum

from fitosim.domain.room import LightExposure

# =====================================================================
#  Modo categoriale: radiazione fissa per LightExposure
# =====================================================================
#
# Tre valori in MJ/m²/giorno che riflettono la radiazione media
# annuale di un vaso al rispettivo livello di esposizione luminosa
# in una casa di latitudine padana (Milano e dintorni). Sono valori
# medi che ignorano la stagionalità.
#
# Ordine di grandezza per riferimento:
#   - radiazione outdoor in giornata estiva di pieno sole: 24 MJ/m²/d
#   - radiazione outdoor in giornata invernale serena: 6 MJ/m²/d
#   - radiazione outdoor in giornata invernale nuvolosa: 2 MJ/m²/d
#
# I valori indoor sono tutti più bassi della radiazione outdoor
# corrispondente perché la finestra (anche aperta al sole) attenua
# la radiazione, e perché la pianta indoor non vede mai un emisfero
# di cielo completo.

# DARK: vaso lontano dalle finestre o in stanza poco luminosa.
# Esempio: Pothos in un angolo del salotto. Riceve solo luce diffusa
# che riflette dalle pareti e dal soffitto. Valore medio annuale.
DARK_RADIATION_MJ_M2_DAY = 1.5

# INDIRECT_BRIGHT: vaso vicino a una finestra ma senza sole diretto.
# Esempio: basilico sul ripiano della cucina, lontano dalla finestra.
# Riceve principalmente luce diffusa dalla finestra e qualche raggio
# obliquo. Valore medio annuale.
INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY = 4.0

# DIRECT_SUN: vaso sul davanzale di una finestra esposta a sud o
# ovest, con qualche ora di sole diretto al giorno. Esempio:
# rosmarino sul davanzale del salotto. Valore medio annuale,
# significativamente inferiore alla radiazione outdoor perché la
# finestra trasmette solo una frazione della radiazione totale.
DIRECT_SUN_RADIATION_MJ_M2_DAY = 8.0


# =====================================================================
#  Modo continuo: frazioni della radiazione outdoor
# =====================================================================
#
# Tre frazioni che dicono "quanto della radiazione outdoor del giorno
# raggiunge il vaso indoor a quel livello di esposizione". I numeri
# sono adimensionali, in (0, 1].
#
# Le frazioni sono calibrate per produrre, in giornata estiva tipica
# milanese (radiazione outdoor 24 MJ/m²/d), valori indoor coerenti
# con i valori categoriali. Per esempio:
#   - DARK = 5% di 24 MJ/m²/d = 1.2 MJ/m²/d (≈ valore categoriale 1.5)
#   - INDIRECT_BRIGHT = 15% di 24 = 3.6 (≈ valore categoriale 4.0)
#   - DIRECT_SUN = 40% di 24 = 9.6 (≈ valore categoriale 8.0)
#
# La piccola discrepanza nei due modi è voluta: il modo continuo
# tende a stimare un po' più alto in estate e un po' più basso in
# inverno, riflettendo la stagionalità che il modo categoriale non
# cattura.

DARK_FRACTION_OF_OUTDOOR = 0.05
INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR = 0.15
DIRECT_SUN_FRACTION_OF_OUTDOOR = 0.40


# =====================================================================
#  Dalla globale alla netta (docs/proposta_radiazione_indoor.md, N2)
# =====================================================================
#
# I numeri qui sopra sono radiazione **globale** al vaso; Penman-Monteith
# vuole la **netta**. La parte riflessa si toglie sempre (FAO-56 eq. 38:
# R_ns = (1 − α) R_s, con α = 0,23 per la coltura di riferimento).
#
# L'onda lunga netta invece resta a zero: l'eq. 39 di FAO-56 è scritta
# per una superficie sotto il cielo, e in una stanza la chioma scambia
# con pareti, soffitto e vetri. Zero è l'ipotesi neutra — superfici alla
# temperatura della chioma — ed è una stima da tarare: ogni kelvin di
# differenza vale circa 0,48 MJ/m²/giorno (ε·4σT³ a 20 °C), col segno
# che dipende dalla stanza (un vetro freddo toglie, una chioma che
# traspira ed è più fresca delle pareti guadagna). Servirebbe la
# temperatura media radiante, che nessun sensore dà.
INDOOR_ALBEDO = 0.23


# =====================================================================
#  Funzioni di utility
# =====================================================================


def net_indoor_radiation(
    global_radiation_mj_m2_day: float, albedo: float = INDOOR_ALBEDO,
) -> float:
    """
    La radiazione netta al vaso in casa, in MJ/m²/giorno, dalla globale:
    la parte non riflessa (FAO-56 eq. 38), con l'onda lunga netta a
    zero. È quella che va a Penman-Monteith.
    """
    if global_radiation_mj_m2_day < 0:
        raise ValueError(
            f"global_radiation_mj_m2_day={global_radiation_mj_m2_day} non può "
            f"essere negativa."
        )
    if not 0.0 <= albedo < 1.0:
        raise ValueError(f"albedo={albedo} deve stare in [0, 1).")
    return (1.0 - albedo) * global_radiation_mj_m2_day


def light_fraction(exposure: LightExposure) -> float:
    """
    Che frazione della luce a cielo aperto arriva a un vaso in casa a
    quel livello di esposizione: le stesse tre frazioni del modo
    continuo. Serve al DLI al vaso (`science/light.dli_at_pot`).
    """
    return {
        LightExposure.DARK: DARK_FRACTION_OF_OUTDOOR,
        LightExposure.INDIRECT_BRIGHT: INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR,
        LightExposure.DIRECT_SUN: DIRECT_SUN_FRACTION_OF_OUTDOOR,
    }[exposure]


def categorical_indoor_radiation(
    exposure: LightExposure,
) -> float:
    """
    Restituisce la radiazione indoor categoriale in MJ/m²/giorno
    associata al livello di esposizione luminosa.

    È il fallback usato dal metodo `apply_balance_step_from_indoor`
    quando il chiamante non passa dati outdoor del giorno. Ignora
    la stagionalità ma è sempre disponibile.

    Parametri
    ---------
    exposure : LightExposure
        Livello di esposizione luminosa del vaso.

    Ritorna
    -------
    float
        Radiazione media giornaliera in MJ/m²/giorno.
    """
    mapping = {
        LightExposure.DARK: DARK_RADIATION_MJ_M2_DAY,
        LightExposure.INDIRECT_BRIGHT: INDIRECT_BRIGHT_RADIATION_MJ_M2_DAY,
        LightExposure.DIRECT_SUN: DIRECT_SUN_RADIATION_MJ_M2_DAY,
    }
    return mapping[exposure]


def continuous_indoor_radiation(
    exposure: LightExposure,
    outdoor_radiation_mj_m2_day: float,
) -> float:
    """
    Stima la radiazione indoor in MJ/m²/giorno come frazione della
    radiazione outdoor del giorno.

    È il modo continuo, più accurato del categoriale perché cattura
    la stagionalità e le variazioni giornaliere. Richiede che il
    chiamante abbia i dati di radiazione outdoor (tipicamente dal
    piranometro della stazione meteo Ecowitt sul balcone).

    Parametri
    ---------
    exposure : LightExposure
        Livello di esposizione luminosa del vaso.
    outdoor_radiation_mj_m2_day : float
        Radiazione globale outdoor del giorno in MJ/m²/giorno.
        Tipicamente la lettura del piranometro Ecowitt esterno.
        Deve essere non-negativa.

    Ritorna
    -------
    float
        Radiazione indoor stimata in MJ/m²/giorno.

    Solleva
    -------
    ValueError
        Se outdoor_radiation_mj_m2_day è negativa.
    """
    if outdoor_radiation_mj_m2_day < 0:
        raise ValueError(
            f"outdoor_radiation_mj_m2_day deve essere non-negativa "
            f"(ricevuto {outdoor_radiation_mj_m2_day})."
        )
    fractions = {
        LightExposure.DARK: DARK_FRACTION_OF_OUTDOOR,
        LightExposure.INDIRECT_BRIGHT: INDIRECT_BRIGHT_FRACTION_OF_OUTDOOR,
        LightExposure.DIRECT_SUN: DIRECT_SUN_FRACTION_OF_OUTDOOR,
    }
    return fractions[exposure] * outdoor_radiation_mj_m2_day


def estimate_indoor_radiation(
    exposure: LightExposure,
    outdoor_radiation_mj_m2_day: float | None = None,
) -> float:
    """
    Stima la radiazione indoor scegliendo automaticamente tra modo
    continuo e modo categoriale in base ai dati disponibili.

    È la funzione "best available" della radiazione indoor, simmetrica
    al selettore "best available" dell'evapotraspirazione introdotto
    dalla sotto-tappa B. Se il chiamante ha dati outdoor del giorno
    usa il modo continuo (più accurato); altrimenti ricade sul modo
    categoriale (sempre disponibile).

    Parametri
    ---------
    exposure : LightExposure
        Livello di esposizione luminosa del vaso.
    outdoor_radiation_mj_m2_day : float, opzionale
        Radiazione globale outdoor del giorno. Se None, si usa il
        modo categoriale.

    Ritorna
    -------
    float
        Radiazione indoor stimata in MJ/m²/giorno.
    """
    if outdoor_radiation_mj_m2_day is not None:
        return continuous_indoor_radiation(
            exposure=exposure,
            outdoor_radiation_mj_m2_day=outdoor_radiation_mj_m2_day,
        )
    return categorical_indoor_radiation(exposure=exposure)


def estimate_indoor_net_radiation(
    exposure: LightExposure,
    outdoor_radiation_mj_m2_day: float | None = None,
) -> float:
    """
    La radiazione **netta** al vaso in casa, pronta per Penman-Monteith:
    `estimate_indoor_radiation` (la globale, dal sole di fuori o dal
    numero fisso del livello) passata per `net_indoor_radiation`. È la
    funzione da chiamare per l'ET di una stanza; la globale resta quella
    da cui si calcola la luce utile alla pianta (`science/light`).
    """
    return net_indoor_radiation(
        estimate_indoor_radiation(
            exposure=exposure, outdoor_radiation_mj_m2_day=outdoor_radiation_mj_m2_day,
        )
    )


# =====================================================================
#  La cascata: dalla misura alla categoria (docs/proposta_luce_misurata.md)
# =====================================================================

class IndoorRadiationSource(Enum):
    """Da dove viene la radiazione al vaso di un giorno, dal più misurato al meno."""

    MEASURED_AT_POT = "measured_at_pot"
    """Misurata al vaso quel giorno (un sensore di luce, un piranometro)."""

    MEASURED_FRACTION = "measured_fraction"
    """La radiazione di fuori per la frazione di luce misurata del posto."""

    EXPOSURE_FRACTION = "exposure_fraction"
    """La radiazione di fuori per la frazione del livello di luce del vaso."""

    EXPOSURE_FIXED = "exposure_fixed"
    """Il numero fisso del livello di luce: uguale tutto l'anno."""


@dataclass(frozen=True)
class IndoorRadiation:
    """
    La radiazione **globale** al vaso di un giorno, in MJ/m², e da dove
    viene. Da questo numero solo si ricavano la netta per
    Penman-Monteith (`net_mj_m2_day`) e la luce utile alla pianta
    (`science/light.dli_from_shortwave`).
    """

    global_mj_m2_day: float
    source: IndoorRadiationSource

    @property
    def net_mj_m2_day(self) -> float:
        """La netta: la parte non riflessa, con l'onda lunga a zero."""
        return net_indoor_radiation(self.global_mj_m2_day)

    @property
    def follows_the_day(self) -> bool:
        """
        Se il numero è di quel giorno (misurato, o ricavato dalla
        radiazione di fuori) e non il fisso del livello: solo allora ha
        senso ricavarne la luce utile alla pianta.
        """
        return self.source is not IndoorRadiationSource.EXPOSURE_FIXED


def resolve_indoor_radiation(
    *,
    exposure: LightExposure | None = None,
    outdoor_radiation_mj_m2_day: float | None = None,
    global_radiation_at_pot_mj_m2_day: float | None = None,
    measured_light_fraction: float | None = None,
) -> IndoorRadiation:
    """
    La radiazione al vaso in casa, dal dato migliore che c'è. Quattro
    gradini, dal più misurato al meno:

      1. la radiazione globale **misurata al vaso** quel giorno;
      2. la radiazione di fuori per la **frazione misurata** del posto
         (per i giorni in cui il sensore manca);
      3. la radiazione di fuori per la frazione del livello di luce;
      4. il numero fisso del livello di luce.

    Coi primi due il livello di luce (`exposure`) non serve. Senza
    niente di usabile solleva ValueError.
    """
    if global_radiation_at_pot_mj_m2_day is not None:
        if global_radiation_at_pot_mj_m2_day < 0:
            raise ValueError(
                f"global_radiation_at_pot_mj_m2_day="
                f"{global_radiation_at_pot_mj_m2_day} non può essere negativa."
            )
        return IndoorRadiation(
            global_radiation_at_pot_mj_m2_day, IndoorRadiationSource.MEASURED_AT_POT,
        )
    if outdoor_radiation_mj_m2_day is not None and outdoor_radiation_mj_m2_day < 0:
        raise ValueError(
            f"outdoor_radiation_mj_m2_day deve essere non-negativa "
            f"(ricevuto {outdoor_radiation_mj_m2_day})."
        )
    if measured_light_fraction is not None:
        if not 0.0 <= measured_light_fraction <= 1.0:
            raise ValueError(
                f"measured_light_fraction={measured_light_fraction} deve stare fra 0 e 1."
            )
        if outdoor_radiation_mj_m2_day is not None:
            return IndoorRadiation(
                measured_light_fraction * outdoor_radiation_mj_m2_day,
                IndoorRadiationSource.MEASURED_FRACTION,
            )
    if exposure is None:
        raise ValueError(
            "Nessuna radiazione al vaso: serve una misura, una frazione "
            "misurata con la radiazione di fuori, o il livello di luce."
        )
    if outdoor_radiation_mj_m2_day is not None:
        return IndoorRadiation(
            continuous_indoor_radiation(exposure, outdoor_radiation_mj_m2_day),
            IndoorRadiationSource.EXPOSURE_FRACTION,
        )
    return IndoorRadiation(
        categorical_indoor_radiation(exposure), IndoorRadiationSource.EXPOSURE_FIXED,
    )
