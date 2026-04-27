"""
Sottovaso e risalita capillare: secondo serbatoio idrico accoppiato.

Il modulo FAO-56 di base, che abbiamo implementato in `science/balance.py`,
descrive un singolo serbatoio (il substrato del vaso) che riceve input
meteo e perde acqua per evapotraspirazione. Il drenaggio in eccesso —
quando l'irrigazione o la pioggia superano la capacità di campo — viene
considerato "perso definitivamente". Per i vasi domestici dotati di
sottovaso, però, questa schematizzazione introduce un bias sistematico
non trascurabile.

Il sottovaso è un piattino posto sotto al vaso che raccoglie l'acqua di
drenaggio. Quel volume non è perso: rimane in contatto con il substrato
attraverso i fori di drenaggio del fondo, e nei giorni successivi viene
gradualmente riassorbito per **risalita capillare**. La quantità di
acqua trasferita dipende dal gradiente di potenziale matricco tra il
piattino (saturo) e il substrato (variabile): più il substrato è
asciutto, più "tira" l'acqua dal piattino.

L'effetto operativo per il giardiniere è ben noto: una pianta con
sottovaso richiede irrigazioni meno frequenti di una identica senza
sottovoto, perché ogni irrigazione abbondante crea una piccola riserva
nel piattino che prolunga l'autonomia di uno o più giorni. Stimare
quantitativamente questo effetto per un caso domestico tipico in
assenza del sottovaso si tradurrebbe in una sovrastima del fabbisogno
idrico del 10-20% nella stagione di crescita.

Modello fisico semplificato
----------------------------

Il modello che adottiamo non risolve esplicitamente l'equazione di
Richards per il flusso capillare (sarebbe sproporzionato per il dominio
del giardinaggio domestico). Adottiamo invece due funzioni pure che
descrivono i due flussi giornalieri rilevanti:

1. **Risalita capillare** dal sottovoto al substrato. Quantità
   trasferita in un giorno proporzionale al **deficit** del substrato
   rispetto a capacità di campo, fino al massimo dell'acqua disponibile
   nel piattino. Formalmente:

       transfer = min(saucer_water, rate × (FC − state))

   dove `rate` è una frazione adimensionale (tipicamente 0.3–0.5) che
   esprime la rapidità del riequilibrio. Se il substrato è già a FC,
   non ci sono forze capillari nette e il trasferimento è zero.

2. **Evaporazione del piattino**, perché l'acqua del sottovoto è
   esposta all'aria e si comporta come un piccolo specchio d'acqua.
   Modellata come una frazione di ET₀:

       evap = min(saucer_water, coef × et_0)

   dove `coef` è tipicamente 0.3–0.5 (più piccolo del coefficiente di
   un grande lago perché il sottovaso è poco profondo e di area
   limitata).

Le due funzioni sono pure, indipendenti dalla geometria specifica del
vaso, e composte ortogonalmente: il modulo di dominio le chiama in
sequenza nel passo giornaliero del bilancio.
"""

# Valori di default tarati per condizioni domestiche tipiche.
DEFAULT_CAPILLARY_RATE = 0.4
"""
Frazione del deficit colmata in un giorno se il sottovoto ha acqua a
sufficienza. Un valore di 0.4 dice "se il substrato è molto sotto FC,
oggi il sottovoto colma il 40% del divario". Sensibile al substrato:
substrati molto capillari (cocco, torba fine) hanno valori più alti
(0.5-0.6); substrati grossolani (mix con perlite) hanno valori più
bassi (0.2-0.3).
"""

DEFAULT_SAUCER_EVAP_COEF = 0.4
"""
Coefficiente di evaporazione del piattino: frazione di ET₀ a cui il
sottovoto evapora. Più piccolo del coefficiente di un grande lago
(che è ~0.7-0.8) perché il sottovoto è poco profondo e di area
limitata. Sensibile alla copertura: un sottovoto sotto il vaso è in
ombra parziale (la chioma della pianta lo copre), un sottovoto vuoto
e direttamente al sole evapora di più.
"""


def capillary_transfer(
    saucer_water_mm: float,
    deficit_mm: float,
    rate: float = DEFAULT_CAPILLARY_RATE,
) -> float:
    """
    Quantità d'acqua trasferita in un giorno dal sottovaso al substrato
    per risalita capillare, in mm.

    Il flusso è proporzionale al deficit (FC − state) del substrato e
    limitato dall'acqua effettivamente disponibile nel piattino. Quando
    il substrato è a capacità di campo (deficit = 0), nessun
    trasferimento avviene perché non c'è gradiente capillare netto.

    Parametri
    ---------
    saucer_water_mm : float
        Acqua attualmente nel sottovoto, in mm-equivalenti sull'area
        del vaso. Deve essere ≥ 0.
    deficit_mm : float
        Differenza FC − state corrente del substrato del vaso, in mm.
        Se ≤ 0 (substrato a FC o sopra), il ritorno è 0.
    rate : float, opzionale
        Frazione del deficit colmata in un giorno se il piattino ha
        acqua a sufficienza. Default: DEFAULT_CAPILLARY_RATE.

    Ritorna
    -------
    float
        Trasferimento in mm (≥ 0). Non eccede mai saucer_water_mm.

    Esempi
    ------
    Substrato a FC, sottovoto pieno: nessun trasferimento.
        capillary_transfer(10.0, 0.0)  # → 0.0

    Substrato 20 mm sotto FC, sottovoto con 5 mm: il modello vorrebbe
    trasferire 8 mm (40% di 20), ma il sottovoto ne ha solo 5.
        capillary_transfer(5.0, 20.0)  # → 5.0

    Substrato 10 mm sotto FC, sottovoto con 100 mm: trasferisce 4 mm.
        capillary_transfer(100.0, 10.0)  # → 4.0
    """
    if saucer_water_mm < 0:
        raise ValueError(
            f"saucer_water_mm deve essere ≥ 0 (ricevuto {saucer_water_mm})."
        )
    if rate <= 0:
        raise ValueError(
            f"rate deve essere positivo (ricevuto {rate})."
        )
    if deficit_mm <= 0:
        # Substrato già saturo o sovraccarico: niente forza capillare.
        return 0.0
    desired = rate * deficit_mm
    return min(saucer_water_mm, desired)


def saucer_evaporation(
    saucer_water_mm: float,
    et_0_mm: float,
    coef: float = DEFAULT_SAUCER_EVAP_COEF,
) -> float:
    """
    Evaporazione giornaliera dell'acqua presente nel sottovaso, in mm.

    Modellata come frazione di ET₀, limitata dall'acqua disponibile
    (un sottovoto vuoto evapora zero, qualunque sia la domanda
    atmosferica).

    Parametri
    ---------
    saucer_water_mm : float
        Acqua attualmente nel sottovoto, in mm. Deve essere ≥ 0.
    et_0_mm : float
        Evapotraspirazione di riferimento del giorno, in mm.
    coef : float, opzionale
        Coefficiente di evaporazione del piattino. Default:
        DEFAULT_SAUCER_EVAP_COEF.

    Ritorna
    -------
    float
        Evaporazione in mm (≥ 0). Non eccede mai saucer_water_mm.
    """
    if saucer_water_mm < 0:
        raise ValueError(
            f"saucer_water_mm deve essere ≥ 0 (ricevuto {saucer_water_mm})."
        )
    if et_0_mm < 0:
        raise ValueError(
            f"et_0_mm deve essere ≥ 0 (ricevuto {et_0_mm})."
        )
    if coef < 0:
        raise ValueError(
            f"coef deve essere ≥ 0 (ricevuto {coef})."
        )
    desired = coef * et_0_mm
    return min(saucer_water_mm, desired)
