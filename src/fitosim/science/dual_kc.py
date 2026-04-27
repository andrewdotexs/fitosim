"""
Modello dual-Kc di FAO-56 capitolo 7: separazione di traspirazione
fogliare ed evaporazione superficiale.

Il modello FAO-56 di base (`science/balance.py`, `domain/species.py`)
descrive l'evapotraspirazione della coltura come prodotto di un
singolo coefficiente Kc per ET₀: ETc = Kc × ET₀. Il valore di Kc
nelle tabelle FAO è il **risultato medio** di due fenomeni fisici
distinti:

  T (traspirazione): perdita d'acqua attraverso le stomate fogliari,
      determinata dalla biologia della pianta e dal microclima.

  E (evaporazione superficiale): perdita d'acqua direttamente dalla
      superficie del substrato, dipendente dall'umidità superficiale
      e quindi dal tempo trascorso dall'ultima irrigazione/pioggia.

Il single Kc media questi due effetti in un valore costante per
stadio fenologico, ma in realtà E oscilla violentemente nel tempo:
è massima subito dopo un evento di bagnatura (substrato superficiale
saturo), poi crolla rapidamente man mano che la superficie si asciuga.
T invece è quasi costante (varia poco con l'umidità superficiale).

Il modello dual-Kc di FAO-56 cap. 7 separa esplicitamente queste due
componenti:

    ETc = (Kcb + Ke) × ET₀

dove:
  Kcb = basal crop coefficient, rappresenta T, quasi costante per stadio
  Ke = soil evaporation coefficient, rappresenta E, dinamico nel tempo

Il vantaggio operativo per un vaso domestico è significativo: il
modello cattura correttamente il fatto che nelle 24-48 ore post-
irrigazione il consumo idrico è 15-25% maggiore di quanto il single
Kc preveda. Per pianificazioni settimanali questo significa accorgersi
di irrigazioni "anticipate" che il single Kc avrebbe sottostimato.

Modello a due fasi di asciugamento
-----------------------------------

Il calcolo di Ke ruota attorno alla variabile De (cumulative depletion
from the topsoil), che misura quanta acqua è già evaporata dallo strato
superficiale del substrato dall'ultimo evento di bagnatura. De evolve
giorno per giorno: cresce con E e si resetta (in tutto o in parte) a
ogni nuovo input idrico.

Il coefficiente di riduzione dell'evaporazione Kr (FAO-56 eq. 74)
modula Ke in funzione di De seguendo due fasi:

  Fase 1 (energy-limited): finché De < REW, il substrato superficiale
      ha acqua "facilmente disponibile" e Kr = 1. Ke è massimo, vicino
      a Kcmax.

  Fase 2 (falling-rate): quando De supera REW, Kr decresce linearmente
      verso zero secondo Kr = (TEW - De) / (TEW - REW). Quando De
      raggiunge TEW, Kr = 0 e l'evaporazione superficiale cessa.

REW (readily evaporable water) e TEW (total evaporable water) sono
proprietà del substrato in mm. Tipicamente:
  - Substrati ritentivi (torba): REW ~9 mm, TEW ~22 mm
  - Substrati drenanti (bonsai): REW ~6 mm, TEW ~14 mm

Calcolo di Ke
-------------

Una volta noto Kr, FAO-56 eq. 71 calcola Ke con un cap a Kcmax:

    Ke = min(Kr × (Kcmax - Kcb), few × Kcmax)

dove:
  Kcmax = limite superiore di Kc + Ke imposto dalla disponibilità
      energetica. FAO-56 eq. 72: Kcmax ≈ max(1.2 + correzioni meteo,
      Kcb + 0.05). Per i vasi domestici semplifichiamo a Kcmax = Kcb
      + 0.05 (l'effetto correzioni meteo è di seconda grandezza
      rispetto agli altri rumori del modello).

  few = fraction of soil that is both exposed and wetted. Per le
      colture di campo dipende dalla geometria delle file e degli
      irrigatori. Per i vasi domestici, dove tutta la superficie è
      omogenea ed esposta a ogni irrigazione, semplifichiamo few = 1.

Riferimenti
-----------
Allen R.G., Pereira L.S., Raes D., Smith M. (1998), "Crop
evapotranspiration: Guidelines for computing crop water requirements",
FAO Irrigation and Drainage Paper No. 56, capitolo 7.
"""

# Baseline climatico per Kcmax (FAO-56 eq. 72). Rappresenta il limite
# energetico superiore di evapotraspirazione totale dato dalla
# disponibilità di radiazione netta meno il flusso di calore al suolo.
# In pieno campo dipende da velocità del vento, umidità relativa e
# altezza della coltura; per condizioni temperate tipiche italiane
# (Milano, vasi domestici sotto 1 m di altezza) il valore di 1.20 è
# il punto centrale dell'intervallo FAO-56 (1.05-1.30) ed è un buon
# compromesso che evita di dover importare grandezze meteo aggiuntive.
KCMAX_DEFAULT = 1.20

# Margine minimo tra Kcb e Kcmax (FAO-56 eq. 72). Questo NON è il
# valore principale di Kcmax: è solo il pavimento che garantisce
# Kcmax > Kcb in casi limite, in modo che Ke possa essere positivo
# anche per piante a Kcb molto alto. Confondere questo margine con
# Kcmax stesso è un errore concettuale comune nella prima lettura
# di FAO-56 cap. 7.
KCMAX_FLOOR_MARGIN = 0.05

# Frazione di superficie esposta e bagnata. Per i vasi domestici
# (superficie omogenea) vale 1.0; lasciamo come costante esposta in
# caso futuri usi richiedano valori diversi (es. pacciamatura parziale).
DEFAULT_FEW = 1.0


def evaporation_reduction_coefficient(
    de_mm: float,
    rew_mm: float,
    tew_mm: float,
) -> float:
    """
    Coefficiente di riduzione dell'evaporazione Kr (FAO-56 eq. 74).

    Funzione a due fasi che modula la disponibilità di acqua dello
    strato superficiale del substrato in funzione della cumulative
    depletion De.

    Parametri
    ---------
    de_mm : float
        Cumulative depletion dello strato superficiale, in mm. È la
        quantità di acqua già evaporata dall'ultimo evento di
        bagnatura. Deve essere ≥ 0; oltre TEW viene saturato a TEW.
    rew_mm : float
        Readily evaporable water del substrato, in mm. È la "riserva
        di superficie" che evapora a tasso massimo. Tipicamente
        6-12 mm per substrati di vaso. Deve essere positivo.
    tew_mm : float
        Total evaporable water del substrato, in mm. È la quantità
        massima di acqua trasferibile per evaporazione superficiale
        (oltre la quale il substrato superficiale è "secco"). Deve
        essere maggiore di rew_mm.

    Ritorna
    -------
    float
        Kr ∈ [0, 1]. Vale 1 in fase 1 (De ≤ REW), decresce
        linearmente in fase 2 (REW < De < TEW), vale 0 a saturazione
        (De ≥ TEW).

    Esempi
    ------
    Substrato fresco di irrigazione, De=0:
        evaporation_reduction_coefficient(0.0, 9.0, 22.0)  # → 1.0

    Substrato a metà fase 2:
        evaporation_reduction_coefficient(15.5, 9.0, 22.0)  # → 0.5

    Substrato superficie completamente asciutta:
        evaporation_reduction_coefficient(25.0, 9.0, 22.0)  # → 0.0
    """
    if de_mm < 0:
        raise ValueError(
            f"de_mm deve essere ≥ 0 (ricevuto {de_mm})."
        )
    if rew_mm <= 0:
        raise ValueError(
            f"rew_mm deve essere positivo (ricevuto {rew_mm})."
        )
    if tew_mm <= rew_mm:
        raise ValueError(
            f"tew_mm ({tew_mm}) deve essere maggiore di "
            f"rew_mm ({rew_mm})."
        )

    if de_mm <= rew_mm:
        # Fase 1 energy-limited: l'acqua superficiale è facilmente
        # disponibile, l'evaporazione è limitata solo dalla domanda
        # atmosferica.
        return 1.0
    if de_mm >= tew_mm:
        # Oltre TEW: superficie completamente asciutta, niente più
        # acqua da evaporare.
        return 0.0
    # Fase 2 falling-rate: decrescita lineare tra REW e TEW.
    return (tew_mm - de_mm) / (tew_mm - rew_mm)


def kcmax(
    kcb: float,
    climate_baseline: float = KCMAX_DEFAULT,
    floor_margin: float = KCMAX_FLOOR_MARGIN,
) -> float:
    """
    Limite superiore di Kc + Ke imposto dall'energia disponibile in
    superficie (FAO-56 eq. 72).

    Implementa la formula:

        Kcmax = max(climate_baseline, Kcb + floor_margin)

    dove `climate_baseline` rappresenta il limite energetico globale
    (tipicamente 1.05-1.30, dipende da clima e altezza della coltura),
    e `floor_margin` è il pavimento che garantisce Kcmax > Kcb anche
    in casi degeneri.

    Per condizioni temperate italiane su vasi domestici, il default
    1.20 è una scelta robusta che evita di dover importare grandezze
    meteo aggiuntive. Il pavimento di 0.05 è quello FAO-56 standard
    e raramente è il termine dominante (entra in gioco solo per
    Kcb > 1.15, cioè colture di pieno sviluppo in stagione di punta).

    Parametri
    ---------
    kcb : float
        Basal crop coefficient della specie nello stadio corrente.
    climate_baseline : float, opzionale
        Baseline climatico per Kcmax. Default KCMAX_DEFAULT = 1.20.
    floor_margin : float, opzionale
        Margine minimo Kcmax - Kcb. Default KCMAX_FLOOR_MARGIN = 0.05.

    Ritorna
    -------
    float
        Kcmax = max(climate_baseline, kcb + floor_margin).

    Esempi
    ------
    Basilico in stadio iniziale (Kcb=0.35) in clima temperato:
        kcmax(0.35)  # → 1.20 (domina il baseline climatico)

    Coltura di pieno sviluppo (Kcb=1.30):
        kcmax(1.30)  # → 1.35 (domina il pavimento Kcb+0.05)
    """
    if kcb <= 0:
        raise ValueError(
            f"kcb deve essere positivo (ricevuto {kcb})."
        )
    if climate_baseline <= 0:
        raise ValueError(
            f"climate_baseline deve essere positivo "
            f"(ricevuto {climate_baseline})."
        )
    if floor_margin < 0:
        raise ValueError(
            f"floor_margin deve essere ≥ 0 (ricevuto {floor_margin})."
        )
    return max(climate_baseline, kcb + floor_margin)


def soil_evaporation_coefficient(
    kr: float,
    kcb: float,
    few: float = DEFAULT_FEW,
    climate_baseline: float = KCMAX_DEFAULT,
    floor_margin: float = KCMAX_FLOOR_MARGIN,
) -> float:
    """
    Coefficiente di evaporazione superficiale Ke (FAO-56 eq. 71).

    Combina il coefficiente di riduzione Kr (che esprime la
    disponibilità idrica della superficie) con il limite energetico
    Kcmax (che esprime la domanda atmosferica). Il risultato è
    sempre nell'intervallo [0, few × Kcmax].

    Parametri
    ---------
    kr : float
        Coefficiente di riduzione dell'evaporazione, in [0, 1].
    kcb : float
        Basal crop coefficient della specie nello stadio corrente.
    few : float, opzionale
        Frazione di superficie esposta e bagnata. Default 1.0 (vaso
        domestico con superficie omogenea).
    climate_baseline : float, opzionale
        Baseline climatico per Kcmax. Default KCMAX_DEFAULT = 1.20.
    floor_margin : float, opzionale
        Margine minimo Kcmax - Kcb. Default KCMAX_FLOOR_MARGIN = 0.05.

    Ritorna
    -------
    float
        Ke ≥ 0. Per substrato appena bagnato (Kr=1) e Kcb tipico di
        ortive da foglia (0.30-0.40), Ke vale 0.80-0.90; per Kcb
        alto di pieno sviluppo (1.0), Ke vale 0.20-0.25.
    """
    if not 0.0 <= kr <= 1.0:
        raise ValueError(
            f"kr deve essere in [0, 1] (ricevuto {kr})."
        )
    if not 0.0 < few <= 1.0:
        raise ValueError(
            f"few deve essere in (0, 1] (ricevuto {few})."
        )
    kcmax_value = kcmax(
        kcb,
        climate_baseline=climate_baseline,
        floor_margin=floor_margin,
    )
    # FAO-56 eq. 71: Ke = min(Kr × (Kcmax - Kcb), few × Kcmax).
    # Il primo termine è "quanta evaporazione vorrei oggi" data la
    # disponibilità idrica e il margine energetico residuo dopo
    # aver tolto la traspirazione. Il secondo è il cap energetico
    # globale dato dalla frazione di superficie wetted.
    return min(kr * (kcmax_value - kcb), few * kcmax_value)


def update_de(
    de_mm_previous: float,
    evaporation_mm: float,
    water_input_mm: float,
    tew_mm: float,
) -> float:
    """
    Aggiornamento giornaliero della cumulative depletion De.

    De evolve secondo il bilancio FAO-56 eq. 77 (semplificato per il
    caso del vaso domestico): cresce con l'evaporazione effettiva del
    giorno e si riduce con l'input idrico (irrigazione + pioggia
    efficace), saturato in [0, TEW].

    Parametri
    ---------
    de_mm_previous : float
        De alla fine del giorno precedente, in mm.
    evaporation_mm : float
        Evaporazione superficiale effettiva del giorno corrente, in
        mm. È la grandezza E_giornaliera = Ke × ET₀, calcolata
        all'inizio del giorno con il De entrante.
    water_input_mm : float
        Acqua entrata nello strato superficiale oggi (irrigazione +
        pioggia), in mm. Il modello assume che ogni input idrico
        ricarichi prima lo strato superficiale; è un'approssimazione
        ragionevole per vasi domestici.
    tew_mm : float
        Total evaporable water del substrato, in mm. Cap superiore
        di De.

    Ritorna
    -------
    float
        Nuovo De alla fine del giorno corrente, in [0, TEW].

    Note
    ----
    La formula completa di FAO-56 eq. 77 include anche il drenaggio
    verticale dello strato superficiale e la frazione di pioggia
    intercettata dalle foglie. Per i vasi domestici questi termini
    sono trascurabili (la profondità Ze è piccola e la chioma è
    poco interceptante in vaso); semplifichiamo accettando un
    errore < 5%.
    """
    if de_mm_previous < 0:
        raise ValueError(
            f"de_mm_previous deve essere ≥ 0 (ricevuto {de_mm_previous})."
        )
    if evaporation_mm < 0:
        raise ValueError(
            f"evaporation_mm deve essere ≥ 0 (ricevuto {evaporation_mm})."
        )
    if water_input_mm < 0:
        raise ValueError(
            f"water_input_mm deve essere ≥ 0 (ricevuto {water_input_mm})."
        )
    if tew_mm <= 0:
        raise ValueError(
            f"tew_mm deve essere positivo (ricevuto {tew_mm})."
        )
    # De cresce con E e si riduce con l'input. Saturato in [0, TEW].
    raw_new_de = de_mm_previous + evaporation_mm - water_input_mm
    return max(0.0, min(tew_mm, raw_new_de))
