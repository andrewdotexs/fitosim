"""
Sistema di allerte per il Garden.

Il modulo introduce nella sotto-tappa E della tappa 4 della fascia 2
il sistema di allerte: comunicazioni strutturate dal sistema al
giardiniere quando una condizione del giardino richiede (o richiederà)
la sua attenzione.

Filosofia
---------

Le allerte sono **derivate dallo stato**: non sono qualcosa che è
successo o che farò, sono qualcosa che il sistema deduce dallo stato
corrente o proiettato del giardino. Conseguenza importante: le
allerte **non si persistono**. Sono il risultato dell'applicazione
delle regole allo stato corrente del modello. Se ricalcoli le
allerte un'ora dopo aver fatto una fertirrigazione, l'allerta che
chiedeva la fertirrigazione sarà scomparsa.

Questo è coerente con la filosofia "Garden orchestratore puro" che
abbiamo seguito fin dalla sotto-tappa A: le allerte sono una vista,
non un dato. Niente tabella SQL, niente serializzazione JSON,
niente metodi di add/cancel. Il chiamante chiama
``Garden.current_alerts()`` o ``Garden.forecast_alerts(...)`` ogni
volta che vuole avere lo stato corrente del piano operativo.

Struttura del modulo
--------------------

Il modulo espone:

  * ``Alert``: dataclass frozen che rappresenta una singola allerta.
  * ``AlertSeverity``: enum con tre livelli di urgenza.
  * ``AlertCategory``: enum con le categorie semantiche delle allerte.
  * ``ALL_RULES``: tuple di tutte le regole, ognuna è una funzione
    pura ``Pot → Optional[Alert]`` o
    ``Pot, current_date → Optional[Alert]``.

Le regole sono **funzioni pure dichiarative**: prendono un Pot e
ritornano l'allerta se la condizione si verifica, altrimenti None.
Sono indipendenti tra loro e si possono applicare in qualsiasi
ordine.

Il modulo NON conosce il Garden — è un livello di astrazione
inferiore. Il Garden si appoggia a questo modulo per implementare
``current_alerts`` e ``forecast_alerts``.

Determinismo dell'alert_id
--------------------------

Ogni allerta ha un ``alert_id`` calcolato come hash deterministico
di ``(pot_label, category, triggered_date)``. Conseguenza pratica:
la stessa allerta scattata in due ricalcoli successivi nello stesso
giorno produce lo stesso ``alert_id``, e il dashboard può fare
deduplicazione del lato suo confrontando gli id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable, Optional, Tuple

from fitosim.domain.pot import Pot


# =======================================================================
#  Enum: severità e categorie
# =======================================================================

class AlertSeverity(Enum):
    """
    Livello di urgenza di un'allerta.

    INFO: informativa, niente urgenza. Esempio: "il vaso si sta
    avvicinando alla soglia di irrigazione, valuta nei prossimi giorni".

    WARNING: attenzione, intervento entro pochi giorni. Esempio:
    "EC oltre il limite ottimale, fai un lavaggio entro la settimana".

    CRITICAL: urgente, intervento oggi. Esempio: "vaso al PWP, la
    pianta è in stress idrico severo".
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(Enum):
    """
    Categoria semantica dell'allerta.

    Cinque categorie nella sotto-tappa E. La sesta categoria
    SENSOR_OFFLINE è prevista in roadmap ma rinviata a una sotto-tappa
    successiva quando avremo deciso dove tracciare il timestamp
    dell'ultima lettura di ogni sensore.
    """

    IRRIGATION_NEEDED = "irrigation_needed"
    FERTILIZATION_DUE = "fertilization_due"
    EC_TOO_HIGH = "ec_too_high"
    EC_TOO_LOW = "ec_too_low"
    PH_OUT_OF_RANGE = "ph_out_of_range"


# =======================================================================
#  Dataclass Alert
# =======================================================================

@dataclass(frozen=True)
class Alert:
    """
    Allerta strutturata dal sistema al giardiniere.

    Frozen e immutabile: per "modificare" un'allerta il chiamante
    crea una nuova istanza. L'equality è basata su tutti i campi,
    quindi due allerte con stesso contenuto sono uguali.

    Attributi
    ---------
    alert_id : str
        Identificatore deterministico calcolato da
        ``(pot_label, category, triggered_date)``. Stessa allerta
        ricalcolata nello stesso giorno produce lo stesso id.
    severity : AlertSeverity
        Livello di urgenza.
    pot_label : str
        Vaso a cui l'allerta si riferisce.
    category : AlertCategory
        Categoria semantica.
    message : str
        Testo descrittivo per il giardiniere. Italiano, leggibile.
    recommended_action : str
        Cosa fare concretamente per risolvere il problema.
    triggered_date : date
        Data di riferimento dell'allerta. Per le current_alerts è
        la data corrente; per le forecast_alerts è la data futura
        a cui l'allerta si riferisce.
    """

    alert_id: str
    severity: AlertSeverity
    pot_label: str
    category: AlertCategory
    message: str
    recommended_action: str
    triggered_date: date


def _make_alert_id(
    pot_label: str, category: AlertCategory, triggered_date: date,
) -> str:
    """
    Costruisce un alert_id deterministico.

    Hash sha256 troncato a 12 caratteri esadecimali del concatenato
    ``pot_label|category.value|triggered_date.isoformat()``. La
    troncatura a 12 caratteri offre 48 bit di entropia che è
    abbondante per evitare collisioni tra le poche decine di allerte
    che un giardino tipico produrrà al giorno.
    """
    raw = f"{pot_label}|{category.value}|{triggered_date.isoformat()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:12]


# =======================================================================
#  Regole: funzioni pure Pot → Optional[Alert]
# =======================================================================

def check_irrigation_needed(
    pot: Pot, current_date: date,
) -> Optional[Alert]:
    """
    Allerta se il vaso è asciutto e prossimo al PWP.

    Soglia: ``state_theta < theta_pwp + 0.05`` (5% di umidità
    volumetrica sopra il PWP). Severity warning se sopra alert_mm,
    critical se sotto (cioè se il vaso è al di sotto della soglia
    di emergenza idrica).
    """
    threshold_theta = pot.substrate.theta_pwp + 0.05
    if pot.state_theta >= threshold_theta:
        return None

    # Distinzione warning/critical: usiamo alert_mm del Pot come
    # soglia di criticità (è il "livello di emergenza idrica" del
    # modello).
    if pot.state_mm < pot.alert_mm:
        severity = AlertSeverity.CRITICAL
        message = (
            f"Il vaso '{pot.label}' è al di sotto della soglia di "
            f"emergenza idrica (state_mm={pot.state_mm:.1f}, "
            f"alert={pot.alert_mm:.1f}). La pianta è in stress idrico "
            f"severo, prossima al PWP."
        )
    else:
        severity = AlertSeverity.WARNING
        message = (
            f"Il vaso '{pot.label}' si sta avvicinando al PWP "
            f"(theta={pot.state_theta:.3f}, soglia="
            f"{threshold_theta:.3f}). Da annaffiare a breve."
        )

    return Alert(
        alert_id=_make_alert_id(
            pot.label, AlertCategory.IRRIGATION_NEEDED, current_date,
        ),
        severity=severity,
        pot_label=pot.label,
        category=AlertCategory.IRRIGATION_NEEDED,
        message=message,
        recommended_action=(
            f"Annaffia il vaso '{pot.label}' con acqua pulita fino a "
            f"saturazione del substrato (~{pot.pot_volume_l * 0.4:.2f} L)."
        ),
        triggered_date=current_date,
    )


def check_ec_too_high(
    pot: Pot, current_date: date,
) -> Optional[Alert]:
    """
    Allerta se l'EC è significativamente sopra il range ottimale.

    Soglia: ``ec > ec_optimal_max + 0.5``. Severity warning fino a
    +1.0 sopra il max, critical oltre +1.0.

    Solo per specie col modello chimico abilitato.
    """
    if not pot.species.supports_chemistry_model:
        return None
    if pot.species.ec_optimal_max_mscm is None:
        return None

    ec = pot.ec_substrate_mscm
    threshold = pot.species.ec_optimal_max_mscm + 0.5
    if ec <= threshold:
        return None

    excess = ec - pot.species.ec_optimal_max_mscm
    if excess > 1.5:
        severity = AlertSeverity.CRITICAL
        message = (
            f"EC del vaso '{pot.label}' criticamente alta "
            f"(EC={ec:.2f} mS/cm, range ottimale "
            f"{pot.species.ec_optimal_min_mscm}-"
            f"{pot.species.ec_optimal_max_mscm}). Stress osmotico "
            f"grave per la pianta."
        )
    else:
        severity = AlertSeverity.WARNING
        message = (
            f"EC del vaso '{pot.label}' sopra il range ottimale "
            f"(EC={ec:.2f} mS/cm, max="
            f"{pot.species.ec_optimal_max_mscm}). Da gestire entro "
            f"pochi giorni."
        )

    return Alert(
        alert_id=_make_alert_id(
            pot.label, AlertCategory.EC_TOO_HIGH, current_date,
        ),
        severity=severity,
        pot_label=pot.label,
        category=AlertCategory.EC_TOO_HIGH,
        message=message,
        recommended_action=(
            f"Effettua un lavaggio del vaso '{pot.label}' con acqua "
            f"pulita (~0.5 L per 2 L di vaso) per provocare "
            f"drenaggio significativo e portare via i sali."
        ),
        triggered_date=current_date,
    )


def check_ec_too_low(
    pot: Pot, current_date: date,
) -> Optional[Alert]:
    """
    Allerta se l'EC è significativamente sotto il range ottimale.

    Soglia: ``ec < ec_optimal_min * 0.7`` (cioè più del 30% sotto il
    minimo). Severity sempre warning (l'EC bassa è un problema
    nutrizionale ma raramente acuto).
    """
    if not pot.species.supports_chemistry_model:
        return None
    if pot.species.ec_optimal_min_mscm is None:
        return None

    ec = pot.ec_substrate_mscm
    threshold = pot.species.ec_optimal_min_mscm * 0.7
    if ec >= threshold:
        return None

    return Alert(
        alert_id=_make_alert_id(
            pot.label, AlertCategory.EC_TOO_LOW, current_date,
        ),
        severity=AlertSeverity.WARNING,
        pot_label=pot.label,
        category=AlertCategory.EC_TOO_LOW,
        message=(
            f"EC del vaso '{pot.label}' sotto il range ottimale "
            f"(EC={ec:.2f} mS/cm, min={pot.species.ec_optimal_min_mscm})."
            f" La pianta riceve pochi nutrienti."
        ),
        recommended_action=(
            f"Programma una fertirrigazione del vaso '{pot.label}' "
            f"con dosaggio standard (BioBizz Bio-Grow ~2 mS/cm)."
        ),
        triggered_date=current_date,
    )


def check_fertilization_due(
    pot: Pot, current_date: date,
) -> Optional[Alert]:
    """
    Allerta se l'EC è sotto il minimo del range ottimale (ma non
    critica come check_ec_too_low).

    Soglia: ``ec_optimal_min * 0.7 ≤ ec < ec_optimal_min``. Cioè il
    vaso è "scarico" ma non drammaticamente. Severity info.

    Le due regole ec_too_low e fertilization_due sono complementari:
    le soglie non si sovrappongono. Per ec sotto 0.7*min scatta
    ec_too_low (warning). Per ec tra 0.7*min e min scatta
    fertilization_due (info). Sopra min nessuna allerta.
    """
    if not pot.species.supports_chemistry_model:
        return None
    if pot.species.ec_optimal_min_mscm is None:
        return None

    ec = pot.ec_substrate_mscm
    lower = pot.species.ec_optimal_min_mscm * 0.7
    upper = pot.species.ec_optimal_min_mscm
    if ec < lower or ec >= upper:
        return None

    return Alert(
        alert_id=_make_alert_id(
            pot.label, AlertCategory.FERTILIZATION_DUE, current_date,
        ),
        severity=AlertSeverity.INFO,
        pot_label=pot.label,
        category=AlertCategory.FERTILIZATION_DUE,
        message=(
            f"EC del vaso '{pot.label}' al limite inferiore del range "
            f"ottimale (EC={ec:.2f} mS/cm, min="
            f"{pot.species.ec_optimal_min_mscm}). Una fertirrigazione "
            f"sarebbe utile a breve."
        ),
        recommended_action=(
            f"Pianifica una fertirrigazione del vaso '{pot.label}' "
            f"nei prossimi giorni."
        ),
        triggered_date=current_date,
    )


def check_ph_out_of_range(
    pot: Pot, current_date: date,
) -> Optional[Alert]:
    """
    Allerta se il pH è fuori dal range ottimale della specie.

    Soglie:
      - Tra range_min - 0.3 e range_max + 0.3: nessuna allerta
        (margine di tolleranza).
      - Fuori del margine ma entro 0.7: warning.
      - Oltre 0.7 fuori range: critical.

    Severity sempre warning o critical (mai info, perché un pH fuori
    range ha conseguenze chimiche misurabili sul Kn).
    """
    if not pot.species.supports_chemistry_model:
        return None
    if pot.species.ph_optimal_min is None:
        return None

    ph = pot.ph_substrate
    ph_min = pot.species.ph_optimal_min
    ph_max = pot.species.ph_optimal_max

    # Margine di tolleranza ±0.3.
    if (ph_min - 0.3) <= ph <= (ph_max + 0.3):
        return None

    # Calcola la distanza dal range più vicina.
    if ph < ph_min:
        distance = ph_min - ph
        direction = "acido"
        action = (
            f"Aggiungi un correttore basico (es. carbonato di calcio) "
            f"al vaso '{pot.label}' per alzare il pH."
        )
    else:
        distance = ph - ph_max
        direction = "alcalino"
        action = (
            f"Aggiungi un correttore acido (es. acqua di scolo o "
            f"acidificante) al vaso '{pot.label}' per abbassare il pH."
        )

    if distance > 0.7:
        severity = AlertSeverity.CRITICAL
        urgency = "criticamente"
    else:
        severity = AlertSeverity.WARNING
        urgency = "moderatamente"

    return Alert(
        alert_id=_make_alert_id(
            pot.label, AlertCategory.PH_OUT_OF_RANGE, current_date,
        ),
        severity=severity,
        pot_label=pot.label,
        category=AlertCategory.PH_OUT_OF_RANGE,
        message=(
            f"pH del vaso '{pot.label}' {urgency} "
            f"{direction} (pH={ph:.2f}, range ottimale "
            f"{ph_min:.1f}-{ph_max:.1f}). La disponibilità "
            f"nutrizionale è compromessa."
        ),
        recommended_action=action,
        triggered_date=current_date,
    )


# =======================================================================
#  Tuple di tutte le regole
# =======================================================================

# Ogni regola è una funzione pura (Pot, date) → Optional[Alert].
# Il Garden itera su questa tuple per applicare tutte le regole.
ALL_RULES: Tuple[Callable[[Pot, date], Optional[Alert]], ...] = (
    check_irrigation_needed,
    check_ec_too_high,
    check_ec_too_low,
    check_fertilization_due,
    check_ph_out_of_range,
)
