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

from typing import Optional

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
#  Funzioni di utility
# =====================================================================


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
    outdoor_radiation_mj_m2_day: Optional[float] = None,
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
