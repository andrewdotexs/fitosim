"""
Bilancio idrico giornaliero di un vaso.

Il modulo implementa l'equazione di aggiornamento discreta dello stato
idrico del substrato, che è l'anima del motore di allerta irrigazione:

    stato(t+1) = clip( stato(t) + input(t) − ET_c(t),  min,  max )

dove l'eccesso oltre il massimo (capacità di campo) si disperde come
drenaggio, e il minimo (punto di appassimento) rappresenta la condizione
limite sotto la quale, per convenzione, lo stato non scende nella
simulazione. Una soglia intermedia — di solito capacità di campo meno
l'acqua facilmente disponibile RAW — definisce il livello sotto al quale
l'algoritmo considera di dover raccomandare un'irrigazione.

Unità di misura
---------------
L'equazione di aggiornamento è *lineare* nelle sue grandezze, il che
significa che funziona identicamente in qualunque sistema di unità,
purché tutti i termini (stato, input, output, soglie) siano espressi
nella stessa unità. Sfruttiamo questa proprietà per organizzare il
modulo in tre livelli:

  1. `water_balance_step`  — funzione core, agnostica rispetto alle
     unità. La matematica del bilancio vive qui, una volta sola.

  2. `water_balance_step_theta` — wrapper che lavora in frazione
     volumetrica θ (adimensionale). Prende un Substrate come riferimento
     e ne ricava automaticamente i limiti superiore/inferiore (θ_FC,
     θ_PWP) e la soglia di allerta (θ_FC − RAW).

  3. `water_balance_step_mm` — wrapper che lavora in colonna d'acqua
     equivalente espressa in mm. Le soglie si ricavano da θ moltiplicato
     per la profondità effettiva del substrato (vedi
     `pot_substrate_depth_mm` in substrate.py). È l'unità "nativa"
     della letteratura FAO-56 ed è particolarmente comoda quando gli
     input meteorologici arrivano già in mm (pioggia, ET₀).

Il risultato di ogni passo è una `BalanceStepResult`, una dataclass
immutabile che contiene il nuovo stato, l'eventuale drenaggio, e
informazioni sullo stato di allerta.
"""

from dataclasses import dataclass

from fitosim.science.substrate import (
    DEFAULT_DEPLETION_FRACTION,
    Substrate,
    readily_available_water,
)


@dataclass(frozen=True)
class BalanceStepResult:
    """
    Esito di un passo (giornaliero) del bilancio idrico.

    Attributi
    ---------
    new_state : float
        Stato idrico aggiornato, nell'unità usata in input (θ, mm, o
        altro sistema coerente). Garantito dentro l'intervallo
        [lower_bound, upper_bound].
    drainage : float
        Eccesso d'acqua disperso come drenaggio, ovvero la quantità di
        input che avrebbe portato lo stato sopra upper_bound ed è stata
        "persa". Non negativo.
    under_alert : bool
        True se new_state è sceso sotto la soglia di allerta operativa,
        cioè se è il momento di irrigare.
    deficit : float
        Quanto, in unità di input, lo stato è sotto la soglia di allerta.
        Zero se under_alert è False. Utile come indicatore di "urgenza"
        quando l'allerta è già scattata.
    """

    new_state: float
    drainage: float
    under_alert: bool
    deficit: float


def water_balance_step(
    current_state: float,
    water_input: float,
    et_c: float,
    upper_bound: float,
    lower_bound: float,
    alert_threshold: float,
) -> BalanceStepResult:
    """
    Funzione core del bilancio idrico, agnostica rispetto alle unità.

    Esegue un singolo passo temporale (tipicamente giornaliero)
    dell'equazione di aggiornamento:

        stato_nuovo = clip(stato + input − et_c,  lower,  upper)

    Parametri
    ---------
    current_state : float
        Stato idrico attuale del substrato, in unità coerenti con tutti
        gli altri parametri.
    water_input : float
        Ingresso netto d'acqua nel giorno (irrigazione + pioggia
        efficace). Deve essere ≥ 0.
    et_c : float
        Evapotraspirazione effettiva della coltura nel giorno. Deve
        essere ≥ 0.
    upper_bound : float
        Limite superiore dello stato (capacità di campo). L'eccesso
        viene conteggiato come drenaggio.
    lower_bound : float
        Limite inferiore dello stato (punto di appassimento). Lo stato
        viene comunque clippato a questo valore; nella realtà agronomica
        la pianta muore prima di arrivarci, ma nella simulazione puntuale
        evitiamo di produrre stati fisicamente impossibili.
    alert_threshold : float
        Valore dello stato sotto al quale scatta l'allerta operativa.
        Deve stare fra lower_bound e upper_bound.

    Ritorna
    -------
    BalanceStepResult
        Struttura immutabile con stato aggiornato, drenaggio, flag e
        deficit.

    Solleva
    -------
    ValueError
        Se water_input o et_c sono negativi, o se le soglie non sono
        in relazione coerente (lower ≤ alert ≤ upper).
    """
    # Validazione parametri: evitiamo di propagare silenziosamente
    # condizioni fisicamente impossibili.
    if water_input < 0:
        raise ValueError(
            f"water_input non può essere negativo (ricevuto {water_input})."
        )
    if et_c < 0:
        raise ValueError(
            f"et_c non può essere negativo (ricevuto {et_c})."
        )
    if not (lower_bound <= alert_threshold <= upper_bound):
        raise ValueError(
            f"Le soglie devono soddisfare "
            f"lower_bound ({lower_bound}) ≤ "
            f"alert_threshold ({alert_threshold}) ≤ "
            f"upper_bound ({upper_bound})."
        )

    # Aggiornamento pre-clipping: è lo stato che si avrebbe se non ci
    # fossero né saturazione (drenaggio) né soglia minima (punto
    # d'appassimento).
    raw_new = current_state + water_input - et_c

    # Clipping superiore: l'acqua in eccesso rispetto alla capacità di
    # campo non resta nel vaso, si disperde attraverso i fori di
    # drenaggio. Contabilizziamo quanta ne è stata persa, perché è
    # un'informazione utile (ad esempio segnala irrigazione eccessiva).
    if raw_new > upper_bound:
        drainage = raw_new - upper_bound
        new_state = upper_bound
    else:
        drainage = 0.0
        new_state = raw_new

    # Clipping inferiore: sotto PWP lo stato perde significato fisico
    # (la pianta sarebbe già morta). Clippiamo per sicurezza numerica e
    # per permettere simulazioni lunghe senza stati aberranti.
    if new_state < lower_bound:
        new_state = lower_bound

    # Valutazione della soglia operativa di allerta.
    under_alert = new_state < alert_threshold
    deficit = max(0.0, alert_threshold - new_state)

    return BalanceStepResult(
        new_state=new_state,
        drainage=drainage,
        under_alert=under_alert,
        deficit=deficit,
    )


def water_balance_step_theta(
    current_theta: float,
    water_input_theta: float,
    et_c_theta: float,
    substrate: Substrate,
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION,
) -> BalanceStepResult:
    """
    Bilancio idrico in unità di frazione volumetrica θ (adimensionale).

    Le soglie (capacità di campo, punto di appassimento, livello di
    allerta) vengono derivate automaticamente dal Substrate:
      - upper_bound  = substrate.theta_fc
      - lower_bound  = substrate.theta_pwp
      - alert_threshold = substrate.theta_fc − RAW_fraction

    dove RAW_fraction = depletion_fraction × (θ_FC − θ_PWP). Questo
    significa che l'allerta scatta quando la frazione volumetrica è
    scesa di RAW unità sotto la capacità di campo — il tipico criterio
    operativo raccomandato da FAO-56.

    I parametri water_input_theta e et_c_theta devono essere anch'essi
    espressi come "θ equivalenti", cioè come frazione del volume del
    substrato. Se hai input in mm o in litri, converti a monte con le
    utilità geometriche disponibili in substrate.py.
    """
    raw = readily_available_water(substrate, depletion_fraction)
    return water_balance_step(
        current_state=current_theta,
        water_input=water_input_theta,
        et_c=et_c_theta,
        upper_bound=substrate.theta_fc,
        lower_bound=substrate.theta_pwp,
        alert_threshold=substrate.theta_fc - raw,
    )


def water_balance_step_mm(
    current_mm: float,
    water_input_mm: float,
    et_c_mm: float,
    substrate: Substrate,
    substrate_depth_mm: float,
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION,
) -> BalanceStepResult:
    """
    Bilancio idrico in unità di colonna d'acqua equivalente (mm).

    Versione "FAO-56 native" del bilancio: lavora in mm, che è l'unità
    in cui sono espressi la maggior parte dei dati meteorologici
    (pioggia, irrigazione, ET₀). Le soglie vengono derivate dal
    Substrate moltiplicandone θ_FC e θ_PWP per la profondità effettiva
    del substrato, che per un vaso si calcola come volume/area (vedi
    pot_substrate_depth_mm in substrate.py).

    Questa versione è preferibile quando:
      - gli input arrivano direttamente in mm da stazione meteo;
      - si vogliono confrontare diversi vasi di profondità variabile
        mantenendo un'unità di misura omogenea;
      - si vuole parlare il linguaggio standard della letteratura
        agronomica internazionale.
    """
    if substrate_depth_mm <= 0:
        raise ValueError(
            f"substrate_depth_mm deve essere positiva "
            f"(ricevuto {substrate_depth_mm})."
        )

    # Le soglie in mm sono θ × depth_mm. Questo riesce perché la
    # conversione θ ↔ mm è lineare attraverso lo stesso fattore di scala
    # per tutti i livelli di stato del sistema.
    upper_mm = substrate.theta_fc * substrate_depth_mm
    lower_mm = substrate.theta_pwp * substrate_depth_mm
    raw_fraction = readily_available_water(substrate, depletion_fraction)
    alert_mm = (substrate.theta_fc - raw_fraction) * substrate_depth_mm

    return water_balance_step(
        current_state=current_mm,
        water_input=water_input_mm,
        et_c=et_c_mm,
        upper_bound=upper_mm,
        lower_bound=lower_mm,
        alert_threshold=alert_mm,
    )
