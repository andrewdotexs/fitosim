"""
Calibrazione empirica dei parametri del substrato dalle letture del
sensore WH51 (o di qualunque altro sensore di umidità volumetrica).

Il problema
-----------
I parametri θ_FC e θ_PWP dei substrati pre-configurati nel catalogo
provengono dalla letteratura agronomica vivaistica e sono valori medi
calcolati su molti vasi diversi. Il vaso specifico che il giardiniere
ha sul balcone ha invece la sua storia, la sua compattazione, il suo
perched water table, e in generale parametri "effettivi" che possono
differire di un 10-30% dai valori tabellati. Quando un sensore di
umidità è disponibile, questi parametri si possono ricavare
direttamente dai dati osservati, senza dover stimare.

Il segnale da cui partiamo è una serie temporale di letture θ del
sensore, tipicamente giornaliere (o aggregate a giornaliere se
provengono da un sensore orario come il WH51). La forma di questa
serie è caratteristica: una linea a "denti di sega" con picchi
post-irrigazione e valli pre-irrigazione. Ogni picco ci racconta la
capacità di campo effettiva del vaso; ogni valle ci racconta un
limite superiore (non il valore vero) del punto di appassimento.

L'asimmetria FC-PWP
-------------------
È fondamentale capire che le due stime hanno qualità diverse. La
stima di θ_FC è robusta: ogni irrigazione abbondante crea un picco
indipendente, e con sei mesi di dati abbiamo dozzine di osservazioni
che convergono su un valore stabile. La stima di θ_PWP è invece un
limite superiore: il giardiniere irriga prima che la pianta soffra,
quindi il sensore non vede mai il vero appassimento, ma solo "il
punto più asciutto a cui si è arrivati". Il modulo comunica questa
asimmetria esplicitamente attraverso il livello di confidenza
restituito.

Robustezza al rumore
--------------------
I sensori reali producono rumore di tipo termico ed elettronico
(tipicamente σ ~0.005-0.015 in θ per WH51). Per evitare che falsi
picchi rumorosi inquinino le stime usiamo tre tecniche standard:

  1. Distanza minima tra picchi consecutivi: due picchi devono essere
     separati di almeno N campioni (default 2 giorni). Filtra il
     rumore alla scala temporale dei singoli campioni.

  2. Prominenza minima: un picco deve emergere di almeno una soglia
     (default 0.02 in θ) sopra le valli circostanti. Filtra i picchi
     di ampiezza piccola che non corrispondono a eventi reali.

  3. Percentile robusto: anziché prendere il massimo (sensibile a un
     singolo outlier) prendiamo il 75° percentile dei picchi, che
     coglie il valore "tipico" senza farsi confondere dai casi
     anomali (irrigazione doppia, pioggia eccezionale).

Workflow tipico
---------------

    >>> readings = [...]  # serie giornaliera θ dal WH51
    >>> result = calibrate_substrate(
    ...     theta_series=readings,
    ...     name="vaso 1 calibrato 2026-04",
    ... )
    >>> print(result.theta_fc_estimate)  # es. 0.412
    >>> print(result.confidence_fc)      # es. "high"
    >>> # Iniettiamo il substrato calibrato nel sistema esistente.
    >>> from fitosim.science.substrate import Substrate
    >>> calibrated = Substrate(
    ...     name=result.name,
    ...     theta_fc=result.theta_fc_estimate,
    ...     theta_pwp=result.theta_pwp_estimate,
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from fitosim.science.balance import stress_coefficient_ks
from fitosim.science.substrate import (
    DEFAULT_DEPLETION_FRACTION,
    Substrate,
)


# Parametri di default per il rilevamento di picchi/valli su dati
# giornalieri. Possono essere sovrascritti dal chiamante in casi
# particolari (sensori a frequenza diversa, vasi con dinamiche
# inusuali).
DEFAULT_MIN_DISTANCE = 2          # giorni tra picchi/valli successivi
DEFAULT_MIN_PROMINENCE = 0.02     # soglia di emergenza in θ
DEFAULT_FC_PERCENTILE = 75        # percentile dei picchi per FC
DEFAULT_PWP_PERCENTILE = 10       # percentile delle valli per PWP

# Parametri di default per la calibrazione di Kc dalla pendenza
# (vedi la sezione "Calibrazione del consumo" più sotto).
DEFAULT_MIN_WINDOW_DAYS = 3       # durata minima di una finestra di asciugamento
DEFAULT_MIN_WINDOW_DEPLETION = 0.03   # calo minimo in θ perché il segnale
                                      # emerga dal rumore del sensore
DEFAULT_RISE_TOLERANCE = 0.01     # risalita in θ tollerata come rumore
                                  # (oltre questa soglia = apporto idrico)

# Limiti di plausibilità fisica per una stima di Kc. Fuori da questo
# intervallo la finestra è quasi certamente contaminata (irrigazione
# non registrata, glitch del sensore, substrato che drena ancora) e
# viene scartata anziché inquinare la mediana.
KC_MIN_PLAUSIBLE = 0.05
KC_MAX_PLAUSIBLE = 2.50

# Soglie di numerosità per i livelli di confidenza. Sono regole di
# pollice basate sull'osservazione che con meno di 5 cicli di
# bagnatura-asciugamento il segnale è troppo povero per produrre
# stime affidabili.
MIN_OBS_FOR_LOW_CONFIDENCE = 3
MIN_OBS_FOR_MEDIUM_CONFIDENCE = 5
MIN_OBS_FOR_HIGH_CONFIDENCE = 10


# =======================================================================
#  Risultato della calibrazione
# =======================================================================

@dataclass(frozen=True)
class CalibrationResult:
    """
    Risultato strutturato di una calibrazione empirica.

    Attributi
    ---------
    name : str
        Etichetta del substrato calibrato (per identificazione nei log
        e nei report).
    theta_fc_estimate : float
        Stima di θ_FC dai picchi della serie. Sempre presente se la
        calibrazione è andata a buon fine.
    theta_pwp_estimate : float | None
        Stima di θ_PWP dalle valli della serie. È `None` quando i dati
        non contengono informazione sufficiente (poche valli, o range
        troppo stretto). In questo caso il chiamante deve usare un
        valore di letteratura.
    n_peaks : int
        Numero di picchi trovati nella serie (numerosità su cui si
        basa la stima di FC).
    n_valleys : int
        Numero di valli trovate nella serie (numerosità su cui si
        basa la stima di PWP).
    confidence_fc : str
        Livello di confidenza per la stima di FC: "high", "medium",
        "low". Basato sulla numerosità dei picchi.
    confidence_pwp : str
        Livello di confidenza per la stima di PWP: "high", "medium",
        "low", "insufficient". È "low" anche con tanti dati perché
        per definizione il sensore non vede mai il PWP vero.
    notes : str
        Note esplicative sulla calibrazione, da mostrare al chiamante.
    """

    name: str
    theta_fc_estimate: float
    theta_pwp_estimate: float | None
    n_peaks: int
    n_valleys: int
    confidence_fc: str
    confidence_pwp: str
    notes: str


# =======================================================================
#  Rilevamento di picchi e valli
# =======================================================================

def find_peaks(
    values: list[float],
    min_distance: int = DEFAULT_MIN_DISTANCE,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
) -> list[int]:
    """
    Restituisce gli indici dei picchi (massimi locali) in una serie
    di valori, applicando filtri di robustezza standard.

    Un punto i è candidato picco se è strettamente maggiore dei suoi
    vicini immediati. Tra due picchi candidati che cadono entro
    `min_distance` campioni l'uno dall'altro teniamo solo il più
    alto. Infine scartiamo i picchi la cui prominenza (differenza
    rispetto alla valle più alta tra il picco e i picchi precedenti)
    è inferiore a `min_prominence`.

    Per i bordi della serie usiamo una convenzione conservativa: il
    primo e l'ultimo punto non possono essere picchi (manca il
    contesto su un lato). Per serie corte questa scelta può perdere
    informazione, ma è la più robusta in presenza di rumore.

    Parametri
    ---------
    values : list[float]
        Serie di valori (tipicamente θ giornaliero dal sensore).
    min_distance : int, opzionale
        Numero minimo di campioni tra due picchi successivi. Default 2.
    min_prominence : float, opzionale
        Differenza minima tra picco e valle precedente. Default 0.02.

    Ritorna
    -------
    list[int]
        Indici dei picchi in `values`, in ordine crescente.

    Esempi
    ------
    Serie con tre picchi netti:
        find_peaks([0.1, 0.4, 0.2, 0.1, 0.45, 0.2, 0.1, 0.5, 0.3])
        # → [1, 4, 7]
    """
    if min_distance < 1:
        raise ValueError(
            f"min_distance deve essere ≥ 1 (ricevuto {min_distance})."
        )
    if min_prominence < 0:
        raise ValueError(
            f"min_prominence deve essere ≥ 0 "
            f"(ricevuto {min_prominence})."
        )
    if len(values) < 3:
        # Senza almeno tre punti non si può definire un picco interno.
        return []

    # Passo 1: trova tutti i candidati picchi (massimi locali stretti).
    candidates: list[int] = []
    for i in range(1, len(values) - 1):
        if values[i] > values[i - 1] and values[i] > values[i + 1]:
            candidates.append(i)

    if not candidates:
        return []

    # Passo 2: applica il filtro di distanza minima. Se due candidati
    # sono troppo vicini, teniamo solo quello con valore più alto.
    # È un greedy che parte dal picco più alto e scarta i suoi vicini.
    accepted = set()
    sorted_by_height = sorted(
        candidates, key=lambda i: values[i], reverse=True,
    )
    for i in sorted_by_height:
        # Scarta i se ha un vicino accettato entro min_distance.
        if any(abs(i - j) < min_distance for j in accepted):
            continue
        accepted.add(i)

    # Passo 3: filtro di prominenza. Per ogni picco accettato, calcola
    # la differenza rispetto al minimo nella finestra precedente fino
    # al picco precedente (o all'inizio della serie). Scarta se sotto
    # soglia.
    final_peaks = sorted(accepted)
    if min_prominence > 0:
        prominent: list[int] = []
        prev_peak_idx = -1
        for peak_idx in final_peaks:
            # Finestra dalla fine del picco precedente fino a questo.
            window_start = prev_peak_idx + 1
            window_end = peak_idx
            local_min = min(values[window_start:window_end + 1])
            prominence = values[peak_idx] - local_min
            if prominence >= min_prominence:
                prominent.append(peak_idx)
                prev_peak_idx = peak_idx
        return prominent
    return final_peaks


def find_valleys(
    values: list[float],
    min_distance: int = DEFAULT_MIN_DISTANCE,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
) -> list[int]:
    """
    Restituisce gli indici delle valli (minimi locali) in una serie
    di valori, con la stessa logica e gli stessi filtri di `find_peaks`
    applicati alla serie negata.

    È implementato per chiarezza come `find_peaks` su `-values`: una
    valle nella serie originale corrisponde a un picco nella serie
    negata. La traduzione conserva tutti i filtri di robustezza.

    Parametri
    ---------
    values : list[float]
    min_distance : int, opzionale
    min_prominence : float, opzionale

    Ritorna
    -------
    list[int]
        Indici delle valli, in ordine crescente.
    """
    negated = [-v for v in values]
    return find_peaks(
        negated,
        min_distance=min_distance,
        min_prominence=min_prominence,
    )


# =======================================================================
#  Statistiche robuste
# =======================================================================

def _percentile(sorted_values: list[float], p: float) -> float:
    """
    Calcola il p-esimo percentile di una lista già ordinata, con
    interpolazione lineare. Implementazione stdlib-only equivalente
    a numpy.percentile con method='linear'.

    Per una lista di n valori ordinati v[0] ≤ v[1] ≤ ... ≤ v[n-1]:
      - p=0 ritorna v[0]
      - p=100 ritorna v[n-1]
      - per p intermedi usa interpolazione lineare tra i due valori
        adiacenti.
    """
    if not sorted_values:
        raise ValueError("Lista di valori vuota.")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"p deve essere in [0, 100] (ricevuto {p}).")
    if len(sorted_values) == 1:
        return sorted_values[0]
    # Posizione frazionaria nel range [0, n-1].
    pos = (p / 100.0) * (len(sorted_values) - 1)
    lower_idx = int(pos)
    upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
    frac = pos - lower_idx
    return (
        sorted_values[lower_idx] * (1 - frac)
        + sorted_values[upper_idx] * frac
    )


# =======================================================================
#  Stima dei parametri
# =======================================================================

def _confidence_level(n_obs: int) -> str:
    """Mappa la numerosità delle osservazioni al livello di confidenza."""
    if n_obs >= MIN_OBS_FOR_HIGH_CONFIDENCE:
        return "high"
    if n_obs >= MIN_OBS_FOR_MEDIUM_CONFIDENCE:
        return "medium"
    if n_obs >= MIN_OBS_FOR_LOW_CONFIDENCE:
        return "low"
    return "insufficient"


def estimate_theta_fc(
    theta_series: list[float],
    min_distance: int = DEFAULT_MIN_DISTANCE,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
    percentile: float = DEFAULT_FC_PERCENTILE,
) -> tuple[float | None, int, str]:
    """
    Stima θ_FC effettivo dai picchi della serie temporale.

    L'idea: ogni irrigazione abbondante crea un picco nella serie del
    sensore che, dopo il drenaggio, si attesta intorno alla capacità
    di campo effettiva del vaso. Trovati i picchi, prendiamo il loro
    75° percentile (default) come stima robusta di θ_FC. Il percentile
    alto privilegia i picchi maggiori (più vicini alla saturazione)
    rispetto ai picchi minori (irrigazioni parziali), ma evita gli
    outlier estremi.

    Parametri
    ---------
    theta_series : list[float]
        Serie di letture θ giornaliere (o aggregate a giornaliero).
    min_distance : int, opzionale
        Distanza minima tra picchi. Default 2 (giorni).
    min_prominence : float, opzionale
        Prominenza minima. Default 0.02.
    percentile : float, opzionale
        Percentile dei picchi da usare. Default 75.

    Ritorna
    -------
    tuple[float | None, int, str]
        (stima θ_FC, numero di picchi usati, livello di confidenza).
        La stima è `None` se non si trovano abbastanza picchi.
    """
    peaks_idx = find_peaks(
        theta_series,
        min_distance=min_distance,
        min_prominence=min_prominence,
    )
    n_peaks = len(peaks_idx)
    confidence = _confidence_level(n_peaks)

    if n_peaks < MIN_OBS_FOR_LOW_CONFIDENCE:
        return None, n_peaks, "insufficient"

    peak_values = sorted([theta_series[i] for i in peaks_idx])
    estimate = _percentile(peak_values, percentile)
    return estimate, n_peaks, confidence


def estimate_theta_pwp(
    theta_series: list[float],
    min_distance: int = DEFAULT_MIN_DISTANCE,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
    percentile: float = DEFAULT_PWP_PERCENTILE,
) -> tuple[float | None, int, str]:
    """
    Stima θ_PWP (limite superiore) dalle valli della serie temporale.

    ATTENZIONE: questa è una stima asimmetrica per ragioni intrinseche.
    Per definizione θ_PWP è il livello di appassimento della pianta;
    un giardiniere che cura il vaso irriga prima che la pianta soffra,
    quindi le valli del sensore corrispondono a "il punto più asciutto
    in cui la pianta è stata lasciata", che è tipicamente sopra al
    PWP vero. La stima ricavata è quindi un LIMITE SUPERIORE: il vero
    PWP è ≤ stima.

    Per questo motivo il livello di confidenza per PWP è limitato a
    "low" o "medium" anche con molte valli — non possiamo trasformare
    un limite superiore in una stima precisa. Il chiamante che vuole
    usare questo valore dovrebbe sapere che potrebbe sottostimare la
    riserva idrica disponibile per la pianta.

    Parametri
    ---------
    theta_series : list[float]
    min_distance : int, opzionale
    min_prominence : float, opzionale
    percentile : float, opzionale
        Percentile delle valli da usare. Default 10 (basso) per
        catturare il punto più asciutto tipico.

    Ritorna
    -------
    tuple[float | None, int, str]
        (stima θ_PWP, numero di valli, livello di confidenza).
        Confidenza limitata a "low"/"medium" per le ragioni discusse.
    """
    valleys_idx = find_valleys(
        theta_series,
        min_distance=min_distance,
        min_prominence=min_prominence,
    )
    n_valleys = len(valleys_idx)

    if n_valleys < MIN_OBS_FOR_LOW_CONFIDENCE:
        return None, n_valleys, "insufficient"

    # Per PWP, anche con tanti dati la confidenza è capata a "medium"
    # perché il sensore non vede mai il vero appassimento.
    raw_confidence = _confidence_level(n_valleys)
    capped_confidence = (
        "medium" if raw_confidence in ("high", "medium") else "low"
    )

    valley_values = sorted([theta_series[i] for i in valleys_idx])
    estimate = _percentile(valley_values, percentile)
    return estimate, n_valleys, capped_confidence


def calibrate_substrate(
    theta_series: list[float],
    name: str = "calibrated",
    min_distance: int = DEFAULT_MIN_DISTANCE,
    min_prominence: float = DEFAULT_MIN_PROMINENCE,
) -> CalibrationResult:
    """
    Pipeline completa di calibrazione di un substrato dai dati storici.

    Orchestra le due stime indipendenti di θ_FC e θ_PWP, raccoglie
    metadati di qualità (numerosità, confidenza), e produce un
    `CalibrationResult` strutturato che il chiamante può ispezionare
    prima di costruire il `Substrate` finale.

    Parametri
    ---------
    theta_series : list[float]
        Serie di letture θ giornaliere. Tipicamente 60+ giorni per
        ottenere stime affidabili (almeno 5-10 cicli di
        bagnatura-asciugamento).
    name : str, opzionale
        Etichetta del risultato. Default "calibrated".
    min_distance : int, opzionale
    min_prominence : float, opzionale

    Ritorna
    -------
    CalibrationResult
        Risultato strutturato con stime, numerosità, confidenze e note.

    Solleva
    -------
    ValueError
        Se la serie è troppo corta (< 10 punti) per qualsiasi
        analisi sensata, o se contiene valori fuori range fisico
        [0, 1].
    """
    if len(theta_series) < 10:
        raise ValueError(
            f"theta_series troppo corta per calibrare "
            f"({len(theta_series)} punti, minimo 10). Per stime "
            f"affidabili servono almeno 60 giorni di dati."
        )
    for i, v in enumerate(theta_series):
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"theta_series[{i}]={v} fuori range fisico [0, 1]. "
                f"Verifica le unità del sensore."
            )

    fc_estimate, n_peaks, fc_conf = estimate_theta_fc(
        theta_series,
        min_distance=min_distance,
        min_prominence=min_prominence,
    )
    pwp_estimate, n_valleys, pwp_conf = estimate_theta_pwp(
        theta_series,
        min_distance=min_distance,
        min_prominence=min_prominence,
    )

    # Costruzione delle note esplicative per il chiamante.
    notes_parts = []
    if fc_estimate is None:
        notes_parts.append(
            "Picchi insufficienti per stimare θ_FC. Il vaso forse non "
            "ha avuto cicli di bagnatura-asciugamento ben definiti, "
            "oppure il rumore è troppo alto. Considera di estendere "
            "il periodo di osservazione."
        )
    if pwp_estimate is None:
        notes_parts.append(
            "Valli insufficienti per stimare θ_PWP. Usa il valore di "
            "letteratura del substrato di riferimento."
        )
    elif pwp_conf in ("low", "medium"):
        notes_parts.append(
            "La stima di θ_PWP è un limite SUPERIORE: il vero PWP "
            "potrebbe essere più basso. Il sensore non vede il vero "
            "appassimento se il giardiniere irriga prima."
        )
    if not notes_parts:
        notes_parts.append("Calibrazione riuscita con dati sufficienti.")

    # Se FC non è stimabile, sollevi un valore "fallback" non-fisico
    # che il chiamante deve interpretare insieme alla confidenza.
    # Per semplicità ritorniamo NaN-equivalente come 0.0 con confidenza
    # "insufficient", e la note esplicita.
    final_fc = fc_estimate if fc_estimate is not None else 0.0

    return CalibrationResult(
        name=name,
        theta_fc_estimate=final_fc,
        theta_pwp_estimate=pwp_estimate,
        n_peaks=n_peaks,
        n_valleys=n_valleys,
        confidence_fc=fc_conf,
        confidence_pwp=pwp_conf,
        notes=" ".join(notes_parts),
    )


# =======================================================================
#  Calibrazione del consumo: Kc dalla pendenza di asciugamento
# =======================================================================
#
# Il secondo segnale del sensore
# ------------------------------
#
# Le funzioni sopra sfruttano le ANCORE della serie: i picchi
# raccontano θ_FC, le valli raccontano un limite superiore di θ_PWP.
# Dicono quanto è grande il serbatoio.
#
# Esiste però un secondo segnale, indipendente e altrettanto prezioso:
# la PENDENZA con cui la curva scende tra due irrigazioni. Se il
# modello prevede un consumo di 4 mm/giorno e il sensore ne mostra 6,
# il Kc di quel vaso è sottostimato del 50%. La pendenza dice quanto
# in fretta il serbatoio si svuota — ed è questa, non la sua capacità,
# a determinare *quando irrigare*.
#
# La relazione fisica invertita
# -----------------------------
#
# Il bilancio idrico giornaliero, in assenza di apporti, è:
#
#     deplezione_mm = Ks · Kp · Kc · ET₀
#
# Tutti i termini a destra sono noti o osservabili tranne Kc:
#   - la deplezione la misura il sensore (Δθ × profondità);
#   - ET₀ viene dal meteo;
#   - Kp è il coefficiente di vaso (materiale, colore, esposizione);
#   - Ks lo calcoliamo dal θ osservato, senza doverlo stimare — è il
#     vantaggio di avere il sensore: non ipotizziamo lo stress, lo
#     leggiamo.
#
# Invertendo su una finestra di N giorni:
#
#     Kc = Σ(deplezione_mm) / (Kp · Σ(Ks_i · ET₀_i))
#
# Il Kc così stimato è il Kc "bulk" del modello a singolo coefficiente:
# include traspirazione ed evaporazione insieme, esattamente come il
# Kc del catalogo che va a correggere.
#
# Cosa può andare storto (e come lo gestiamo)
# -------------------------------------------
#
#   1. Apporto idrico dentro la finestra (irrigazione o pioggia).
#      Invalida la stima. Lo rileviamo come risalita di θ oltre la
#      tolleranza di rumore, e spezziamo la finestra.
#
#   2. Irrigazione INVISIBILE. Se il campionamento è giornaliero e
#      l'utente irriga e il vaso drena tra due letture, la risalita
#      non si vede: osserviamo un calo più piccolo del reale e
#      sottostimiamo Kc. È il limite principale del metodo. Mitigazione:
#      il chiamante può passare `known_water_input_days` con i giorni
#      in cui il diario registra un apporto, e quelle transizioni
#      vengono escluse.
#
#   3. Rumore del sensore. Su finestre corte o con cali piccoli il
#      rumore domina il segnale. Imponiamo una durata minima e un calo
#      minimo perché la finestra sia considerata.
#
#   4. Stress idrico. Verso il fondo della curva Ks scende sotto 1 e
#      l'asciugamento rallenta: ignorarlo porterebbe a sottostimare Kc.
#      Calcolando Ks giorno per giorno dal θ osservato il problema è
#      gestito esattamente.
#
#   5. Drenaggio residuo. Nelle ore successive a un'irrigazione
#      abbondante il vaso perde acqua per gravità, non per ET: la
#      pendenza iniziale è più ripida del consumo reale. Il filtro di
#      plausibilità su Kc scarta i casi peggiori; per il resto la
#      mediana su più finestre assorbe l'effetto.
#
# Ordine consigliato: prima `calibrate_substrate` (ancore), poi
# `calibrate_kc` usando il Substrate calibrato — così la conversione
# θ→mm e il calcolo di Ks usano i parametri veri di quel vaso.


@dataclass(frozen=True)
class DryingWindow:
    """
    Un tratto di serie in cui il vaso si sta asciugando senza apporti.

    Gli indici si riferiscono alla serie θ passata in ingresso e sono
    inclusivi: la finestra copre le letture da `start_index` a
    `end_index`, cioè `n_days` transizioni giornaliere.

    Attributi
    ---------
    start_index, end_index : int
        Estremi inclusivi nella serie θ.
    n_days : int
        Numero di transizioni giornaliere coperte (end - start).
    theta_start, theta_end : float
        Umidità volumetrica agli estremi.
    total_depletion_theta : float
        Calo complessivo in θ (sempre ≥ 0 per costruzione).
    """

    start_index: int
    end_index: int
    n_days: int
    theta_start: float
    theta_end: float
    total_depletion_theta: float


@dataclass(frozen=True)
class KcCalibrationResult:
    """
    Risultato della calibrazione del coefficiente colturale.

    Attributi
    ---------
    kc_estimate : float | None
        Stima robusta (mediana) del Kc effettivo del vaso, o `None`
        se nessuna finestra utilizzabile è stata trovata.
    n_windows : int
        Numero di finestre di asciugamento che hanno prodotto una
        stima plausibile.
    confidence : str
        "high" / "medium" / "low" / "insufficient", con le stesse
        soglie di numerosità usate per la calibrazione del substrato.
    window_estimates : tuple[float, ...]
        Le stime delle singole finestre, in ordine cronologico. Utili
        per diagnostica: una dispersione ampia segnala dati rumorosi o
        apporti idrici non registrati.
    notes : str
        Spiegazione in linguaggio naturale, pensata per essere mostrata
        all'utente insieme alla stima.
    """

    kc_estimate: Optional[float]
    n_windows: int
    confidence: str
    window_estimates: tuple[float, ...]
    notes: str


def find_drying_windows(
    theta_series: list[float],
    *,
    min_days: int = DEFAULT_MIN_WINDOW_DAYS,
    min_depletion: float = DEFAULT_MIN_WINDOW_DEPLETION,
    rise_tolerance: float = DEFAULT_RISE_TOLERANCE,
    known_water_input_days: Optional[Iterable[int]] = None,
) -> list[DryingWindow]:
    """
    Individua i tratti di serie in cui il vaso si asciuga senza apporti.

    Una finestra è un tratto massimale in cui θ non risale mai oltre
    `rise_tolerance` da una lettura alla successiva. Le piccole
    oscillazioni (rumore del sensore) non spezzano la finestra; una
    risalita significativa sì, perché segnala un'irrigazione o una
    pioggia.

    Parametri
    ---------
    theta_series : list[float]
        Serie di umidità volumetrica, tipicamente giornaliera e in
        ordine cronologico crescente.
    min_days : int, opzionale
        Numero minimo di transizioni perché la finestra sia utile.
        Finestre più corte hanno troppo poco segnale.
    min_depletion : float, opzionale
        Calo minimo complessivo in θ. Sotto questa soglia il rumore
        del sensore è dello stesso ordine del segnale.
    rise_tolerance : float, opzionale
        Risalita di θ tollerata come rumore tra due letture.
    known_water_input_days : iterable[int], opzionale
        Indici in cui il diario registra un apporto idrico. La
        transizione che porta a quell'indice viene esclusa anche se
        il sensore non mostra risalita (irrigazione "invisibile").

    Ritorna
    -------
    list[DryingWindow]
        Finestre valide in ordine cronologico. Lista vuota se la serie
        non contiene tratti di asciugamento sufficientemente lunghi.
    """
    if len(theta_series) < 2:
        return []

    excluded = set(known_water_input_days or ())
    windows: list[DryingWindow] = []

    start = 0
    for i in range(1, len(theta_series)):
        # La transizione i-1 → i è contaminata se il sensore mostra una
        # risalita significativa oppure se il diario dichiara un apporto.
        rise = theta_series[i] - theta_series[i - 1]
        contaminated = (rise > rise_tolerance) or (i in excluded)

        if contaminated:
            _append_window_if_valid(
                windows, theta_series, start, i - 1,
                min_days, min_depletion,
            )
            start = i

    # Chiusura dell'ultima finestra aperta.
    _append_window_if_valid(
        windows, theta_series, start, len(theta_series) - 1,
        min_days, min_depletion,
    )
    return windows


def _append_window_if_valid(
    windows: list[DryingWindow],
    theta_series: list[float],
    start: int,
    end: int,
    min_days: int,
    min_depletion: float,
) -> None:
    """Aggiunge la finestra [start, end] se supera i filtri di validità."""
    n_days = end - start
    if n_days < min_days:
        return
    depletion = theta_series[start] - theta_series[end]
    if depletion < min_depletion:
        return
    windows.append(DryingWindow(
        start_index=start,
        end_index=end,
        n_days=n_days,
        theta_start=theta_series[start],
        theta_end=theta_series[end],
        total_depletion_theta=depletion,
    ))


def estimate_kc_from_window(
    window: DryingWindow,
    theta_series: list[float],
    et0_series: list[float],
    substrate: Substrate,
    substrate_depth_mm: float,
    *,
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION,
    kp: float = 1.0,
) -> Optional[float]:
    """
    Stima il Kc effettivo da una singola finestra di asciugamento.

    Applica l'inversione del bilancio idrico descritta in testa alla
    sezione, calcolando Ks giorno per giorno dal θ osservato all'inizio
    di ciascuna giornata.

    Convenzione sugli indici: `et0_series[i]` è l'ET₀ della giornata
    che ha portato alla lettura `theta_series[i]`. La deplezione tra
    `theta_series[i-1]` e `theta_series[i]` è quindi guidata da
    `et0_series[i]`.

    Parametri
    ---------
    window : DryingWindow
        La finestra da valutare.
    theta_series, et0_series : list[float]
        Serie allineate per indice.
    substrate : Substrate
        Preferibilmente quello CALIBRATO su questo vaso: θ_FC e θ_PWP
        entrano nel calcolo di Ks.
    substrate_depth_mm : float
        Profondità del substrato, per convertire θ in mm.
    depletion_fraction : float, opzionale
        Frazione p della specie, per la soglia di stress.
    kp : float, opzionale
        Coefficiente di vaso. Default 1.0 (vaso neutro).

    Ritorna
    -------
    float | None
        La stima di Kc, oppure `None` se la finestra non produce un
        valore fisicamente plausibile (domanda evapotraspirativa nulla,
        oppure Kc fuori dai limiti di plausibilità).
    """
    demand = 0.0
    for i in range(window.start_index + 1, window.end_index + 1):
        # Ks valutato sullo stato di INIZIO giornata.
        ks = stress_coefficient_ks(
            theta_series[i - 1], substrate,
            depletion_fraction=depletion_fraction,
        )
        demand += ks * et0_series[i]

    if demand <= 0.0 or kp <= 0.0:
        return None

    depletion_mm = window.total_depletion_theta * substrate_depth_mm
    kc = depletion_mm / (kp * demand)

    if not (KC_MIN_PLAUSIBLE <= kc <= KC_MAX_PLAUSIBLE):
        return None
    return kc


def calibrate_kc(
    theta_series: list[float],
    et0_series: list[float],
    substrate: Substrate,
    substrate_depth_mm: float,
    *,
    depletion_fraction: float = DEFAULT_DEPLETION_FRACTION,
    kp: float = 1.0,
    min_days: int = DEFAULT_MIN_WINDOW_DAYS,
    min_depletion: float = DEFAULT_MIN_WINDOW_DEPLETION,
    rise_tolerance: float = DEFAULT_RISE_TOLERANCE,
    known_water_input_days: Optional[Iterable[int]] = None,
) -> KcCalibrationResult:
    """
    Stima il coefficiente colturale effettivo di un vaso dalla velocità
    con cui si asciuga.

    Individua tutte le finestre di asciugamento della serie, stima Kc
    su ciascuna, e aggrega con la MEDIANA — robusta agli outlier
    prodotti da finestre contaminate sfuggite ai filtri.

    Il valore restituito è il Kc "bulk" (traspirazione + evaporazione)
    confrontabile direttamente con `kc_for_stage(species, stage)` del
    catalogo. Il rapporto tra i due è il fattore di correzione da
    applicare a quel vaso.

    Parametri
    ---------
    theta_series, et0_series : list[float]
        Serie allineate per indice e di pari lunghezza. `et0_series[i]`
        è l'ET₀ della giornata che ha portato a `theta_series[i]`; il
        primo elemento non viene mai usato ed è convenzionalmente 0.
    substrate : Substrate
        Preferibilmente calibrato (vedi `calibrate_substrate`).
    substrate_depth_mm : float
        Profondità del substrato nel vaso.
    depletion_fraction, kp : float, opzionali
        Parametri della specie e del vaso.
    min_days, min_depletion, rise_tolerance : opzionali
        Soglie di validità delle finestre.
    known_water_input_days : iterable[int], opzionale
        Giorni in cui il diario registra un apporto idrico.

    Ritorna
    -------
    KcCalibrationResult

    Solleva
    -------
    ValueError
        Se le due serie hanno lunghezze diverse.
    """
    if len(theta_series) != len(et0_series):
        raise ValueError(
            f"theta_series ({len(theta_series)}) e et0_series "
            f"({len(et0_series)}) devono avere la stessa lunghezza: "
            f"l'elemento i-esimo di et0_series è l'ET0 della giornata "
            f"che ha portato alla lettura i-esima di theta_series."
        )

    windows = find_drying_windows(
        theta_series,
        min_days=min_days,
        min_depletion=min_depletion,
        rise_tolerance=rise_tolerance,
        known_water_input_days=known_water_input_days,
    )

    estimates: list[float] = []
    for w in windows:
        kc = estimate_kc_from_window(
            w, theta_series, et0_series, substrate, substrate_depth_mm,
            depletion_fraction=depletion_fraction, kp=kp,
        )
        if kc is not None:
            estimates.append(kc)

    n = len(estimates)
    confidence = _confidence_level(n)

    if n == 0:
        notes = (
            "Nessuna finestra di asciugamento utilizzabile. Possibili "
            "cause: serie troppo corta, irrigazioni troppo frequenti "
            "per lasciare tratti di asciugamento continui, oppure cali "
            "troppo piccoli rispetto al rumore del sensore."
        )
        return KcCalibrationResult(
            kc_estimate=None, n_windows=0, confidence=confidence,
            window_estimates=(), notes=notes,
        )

    kc_estimate = _percentile(sorted(estimates), 50.0)

    notes_parts = [
        f"Stima da {n} finestra/e di asciugamento "
        f"({len(windows)} candidate)."
    ]
    if confidence == "insufficient":
        notes_parts.append(
            "Numerosita' troppo bassa per una stima affidabile: usare "
            "il Kc di catalogo e attendere altri cicli."
        )
    spread = max(estimates) - min(estimates)
    if n >= 2 and spread > 0.5 * kc_estimate:
        notes_parts.append(
            f"Dispersione ampia tra le finestre (min {min(estimates):.2f}, "
            f"max {max(estimates):.2f}): possibili apporti idrici non "
            f"registrati nel diario."
        )
    if not notes_parts[1:]:
        notes_parts.append("Dispersione contenuta, stima coerente.")

    return KcCalibrationResult(
        kc_estimate=kc_estimate,
        n_windows=n,
        confidence=confidence,
        window_estimates=tuple(estimates),
        notes=" ".join(notes_parts),
    )
