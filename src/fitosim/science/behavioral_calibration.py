"""
Calibrazione dal comportamento e dal giudizio del giardiniere.

Gli altri moduli di calibrazione partono da misure: il sensore dice
quanta acqua c'è nel substrato, il lisimetro quanta ne è uscita. Qui
le sorgenti sono diverse e non richiedono alcun hardware — vengono
gratis da chi non ha sensori, che è la maggioranza.

Il modulo copre due segnali distinti, che calibrano due parametri
diversi e sono complementari:

  1. **Scostamento delle irrigazioni** → coefficiente colturale Kc.
     Quando il giardiniere irriga sistematicamente più tardi (o più
     presto) di quanto suggerito.

  2. **Giudizio sulle allerte** → frazione di deplezione p.
     Quando il giardiniere dice "l'allerta era sbagliata, la pianta
     sta benissimo", oppure segnala sofferenza quando nessuna allerta
     era scattata.

La complementarità non è casuale. Il primo segnale, da solo, non sa
distinguere un Kc sbagliato da una soglia p sbagliata: entrambi
producono "irriga più tardi del previsto". Il secondo interroga
direttamente la soglia, perché chiede al giardiniere di giudicare lo
*stato della pianta*, non il momento dell'irrigazione.

Il segnale delle irrigazioni
----------------------------

È lo **scostamento sistematico tra quando il modello suggerisce di
irrigare e quando il giardiniere irriga davvero**.

Se fitosim dice "irriga giovedì" e l'utente irriga regolarmente il
sabato, sta dicendo qualcosa di preciso: il vaso si asciuga più
lentamente di quanto il modello creda. Non è una lamentela, è una
misura indiretta — e viene gratis da chi non ha sensori, che è la
maggioranza.

È la "calibrazione passiva" descritta nella visione di The Pot
(cap. 5, "L'autoapprendimento di fitosim") e la terza fonte della
fase A del layer di feedback.

La matematica
-------------

Il modello prevede che dalla capacità di campo si arrivi alla soglia
di allerta in N giorni:

    N ≈ p · TAW / (Kc · Kp · ET₀)

Se il giardiniere aspetta N' giorni invece di N, e attribuiamo tutto
lo scarto al coefficiente colturale:

    N'/N = Kc/Kc'    →    Kc' = Kc · (N / N')

Quindi il **fattore di correzione è il rapporto tra intervallo
previsto e intervallo effettivo**. Se il modello dice 4 giorni e
l'utente ne aspetta 6, il fattore è 0.67: il modello sovrastimava il
consumo del 50%.

Nota importante: conta il *rapporto*, non lo scarto in giorni. Due
giorni di ritardo su un intervallo previsto di 4 sono un errore
grosso; due giorni su un intervallo di 20 sono rumore. Per questo la
funzione vuole gli intervalli e non i soli scostamenti.

Cosa non possiamo distinguere (e perché lo diciamo)
---------------------------------------------------

Dal solo comportamento non è possibile separare tre cause diverse:

  1. il Kc è sbagliato (il vaso consuma meno del previsto);
  2. la soglia p è sbagliata (il vaso consuma come previsto, ma il
     giardiniere tollera più deplezione di quanta ne ammetta p);
  3. il giardiniere irriga quando gli è comodo, non quando serve.

Sono osservazionalmente equivalenti: tutte e tre producono "irriga più
tardi di quanto suggerito". Il fattore che questo modulo restituisce è
quindi un **equivalente-Kc**, che assorbe qualunque sia la causa vera.
Va bene per lo scopo — allineare i suggerimenti futuri alla pratica
reale — ma va detto, perché il numero non è una misura di Kc.

Per separare le cause serve il sensore: la pendenza di asciugamento
(vedi `science/calibration.py`) misura il consumo direttamente, e il
confronto tra i due segnali dice quale delle tre ipotesi regge.

Il rischio da non ignorare
--------------------------

Se il giardiniere sotto-irriga cronicamente e la pianta soffre,
calibrare sul suo comportamento **codifica l'errore nel modello**: da
lì in poi fitosim suggerirebbe di irrigare poco, con l'autorità di un
modello agronomico. È il motivo per cui questo modulo:

  - non applica nulla da solo, ma restituisce una proposta;
  - misura la *coerenza* dello scostamento, non solo la sua entità;
  - limita l'ampiezza della correzione;
  - richiede più osservazioni degli altri metodi (il comportamento è
    più rumoroso di una misura).

La decisione finale resta al giardiniere, che deve poterla vedere
spiegata e annullare — trasparenza e reversibilità sono principi
fissati nella visione di The Pot.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from fitosim.domain.species import Species


# Soglie di numerosità. Sono più alte di quelle della calibrazione da
# sensore (3/5/10) perché il comportamento è più rumoroso di una
# misura: la visione di The Pot parla di "10-15 spostamenti su un
# singolo vaso" prima di proporre una ritaratura.
MIN_OBS_FOR_LOW_CONFIDENCE = 5
MIN_OBS_FOR_MEDIUM_CONFIDENCE = 10
MIN_OBS_FOR_HIGH_CONFIDENCE = 15

# Limiti del fattore di correzione complessivo. Un fattore fuori da
# questo intervallo non è credibile a partire dal solo comportamento:
# più probabilmente l'accoppiamento suggerimento-irrigazione è
# sbagliato, o il giardiniere ha cambiato radicalmente abitudini.
CORRECTION_MIN = 0.5
CORRECTION_MAX = 2.0

# Limiti di plausibilità della singola osservazione. Servono a
# scartare i casi che non parlano del vaso ma della vita del
# giardiniere: due settimane di vacanza, o un'irrigazione registrata
# in ritardo.
OBSERVATION_RATIO_MIN = 0.25
OBSERVATION_RATIO_MAX = 4.0

# Frazione minima di osservazioni concordi perché lo scostamento sia
# considerato sistematico e non rumore. Con meno di due terzi
# d'accordo, un utente che a volte anticipa e a volte posticipa
# produrrebbe una mediana spostata senza che ci sia un vero bias.
MIN_CONSISTENCY = 0.67

# Estremi entro cui mantenere i Kc corretti, per restare dentro il
# range di validità di Species (0 < Kc < 2).
KC_FLOOR = 0.05
KC_CEILING = 1.95


@dataclass(frozen=True)
class IrrigationDeviation:
    """
    Una singola osservazione: cosa suggeriva il modello, cosa ha fatto
    il giardiniere.

    Tutti e tre gli istanti sono ancorati alla stessa irrigazione
    precedente, così i due intervalli sono confrontabili. È la forma
    in cui il dato esiste naturalmente nel diario di The Pot: ogni
    irrigazione registrata "consuma" un suggerimento, e conosce quella
    che l'ha preceduta.

    Attributi
    ---------
    previous_irrigation : date
        L'irrigazione da cui parte il ciclo osservato.
    suggested_date : date
        Quando il modello suggeriva la successiva.
    actual_date : date
        Quando il giardiniere l'ha effettivamente fatta.
    """

    previous_irrigation: date
    suggested_date: date
    actual_date: date

    def __post_init__(self) -> None:
        if self.suggested_date <= self.previous_irrigation:
            raise ValueError(
                f"suggested_date ({self.suggested_date}) deve essere "
                f"successiva a previous_irrigation "
                f"({self.previous_irrigation})."
            )
        if self.actual_date <= self.previous_irrigation:
            raise ValueError(
                f"actual_date ({self.actual_date}) deve essere "
                f"successiva a previous_irrigation "
                f"({self.previous_irrigation})."
            )

    @property
    def predicted_interval_days(self) -> int:
        """Giorni che il modello diceva di aspettare."""
        return (self.suggested_date - self.previous_irrigation).days

    @property
    def actual_interval_days(self) -> int:
        """Giorni che il giardiniere ha aspettato davvero."""
        return (self.actual_date - self.previous_irrigation).days

    @property
    def shift_days(self) -> int:
        """
        Scarto in giorni: positivo se l'utente ha posticipato.

        Utile per spiegare la correzione a parole ("posticipi in media
        di un giorno e mezzo"), ma NON è la grandezza su cui si calcola
        la correzione: per quella serve il rapporto tra intervalli.
        """
        return (self.actual_date - self.suggested_date).days

    @property
    def ratio(self) -> float:
        """Rapporto intervallo effettivo / intervallo previsto."""
        return self.actual_interval_days / self.predicted_interval_days


@dataclass(frozen=True)
class BehavioralCalibrationResult:
    """
    Proposta di correzione derivata dal comportamento.

    Attributi
    ---------
    kc_correction_factor : float | None
        Moltiplicatore da applicare ai Kc della specie per quel vaso.
        `None` quando non c'è motivo di correggere: osservazioni
        insufficienti, scostamento non sistematico, o scostamento
        trascurabile.
    n_observations : int
        Osservazioni utilizzabili (dopo lo scarto delle implausibili).
    n_discarded : int
        Osservazioni scartate perché fuori dai limiti di plausibilità.
    confidence : str
        "high" / "medium" / "low" / "insufficient".
    consistency : float
        Frazione di osservazioni che punta nella stessa direzione della
        mediana, in [0, 1]. È la misura di quanto lo scostamento sia
        sistematico: 1.0 significa che il giardiniere devia sempre
        nello stesso verso.
    median_shift_days : float
        Scarto mediano in giorni. Serve a spiegare la proposta
        all'utente, non a calcolarla.
    ratios : tuple[float, ...]
        I rapporti delle singole osservazioni, per diagnostica.
    notes : str
        Spiegazione in italiano, pensata per essere mostrata così com'è.
    """

    kc_correction_factor: Optional[float]
    n_observations: int
    n_discarded: int
    confidence: str
    consistency: float
    median_shift_days: float
    ratios: tuple[float, ...]
    notes: str

    @property
    def suggests_correction(self) -> bool:
        """True se c'è una proposta concreta da sottoporre all'utente."""
        return self.kc_correction_factor is not None


def _median(values: Sequence[float]) -> float:
    """Mediana di una sequenza non vuota."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _confidence_level(n_obs: int) -> str:
    """Livello di confidenza dalla numerosità delle osservazioni."""
    if n_obs >= MIN_OBS_FOR_HIGH_CONFIDENCE:
        return "high"
    if n_obs >= MIN_OBS_FOR_MEDIUM_CONFIDENCE:
        return "medium"
    if n_obs >= MIN_OBS_FOR_LOW_CONFIDENCE:
        return "low"
    return "insufficient"


def calibrate_kc_from_behavior(
    deviations: Sequence[IrrigationDeviation],
    *,
    min_consistency: float = MIN_CONSISTENCY,
    negligible_band: float = 0.10,
) -> BehavioralCalibrationResult:
    """
    Propone una correzione del Kc dallo scostamento sistematico tra
    suggerimenti e irrigazioni reali.

    Non applica nulla: restituisce una proposta con la sua confidenza
    e una spiegazione, che il chiamante deve sottoporre al giardiniere.

    Parametri
    ---------
    deviations : sequence[IrrigationDeviation]
        Le osservazioni, tipicamente tutte relative allo stesso vaso.
    min_consistency : float, opzionale
        Frazione minima di osservazioni concordi perché lo scostamento
        sia considerato sistematico.
    negligible_band : float, opzionale
        Ampiezza della banda attorno a 1.0 entro cui la correzione è
        considerata trascurabile e non vale la pena disturbare
        l'utente. Default 0.10, cioè ±10%.

    Ritorna
    -------
    BehavioralCalibrationResult
    """
    usable = []
    n_discarded = 0
    for dev in deviations:
        r = dev.ratio
        if OBSERVATION_RATIO_MIN <= r <= OBSERVATION_RATIO_MAX:
            usable.append(dev)
        else:
            n_discarded += 1

    n = len(usable)
    confidence = _confidence_level(n)
    ratios = tuple(d.ratio for d in usable)

    if n == 0:
        return BehavioralCalibrationResult(
            kc_correction_factor=None, n_observations=0,
            n_discarded=n_discarded, confidence=confidence,
            consistency=0.0, median_shift_days=0.0, ratios=(),
            notes=(
                "Nessuna osservazione utilizzabile. Servono irrigazioni "
                "registrate a fronte di un suggerimento del modello."
            ),
        )

    median_ratio = _median(ratios)
    median_shift = _median([float(d.shift_days) for d in usable])

    # Coerenza: quante osservazioni deviano nello stesso verso della
    # mediana. Un utente che a volte anticipa e a volte posticipa non
    # sta dicendo che il modello sbaglia, sta dicendo che la sua vita
    # è irregolare.
    above = sum(1 for r in ratios if r > 1.0)
    below = sum(1 for r in ratios if r < 1.0)
    on_target = n - above - below
    if median_ratio > 1.0:
        concordant = above
    elif median_ratio < 1.0:
        concordant = below
    else:
        # Mediana esattamente 1.0: non c'è una direzione. Prendiamo la
        # tendenza più forte, che è la misura onesta in questo caso.
        # Un utente sempre puntuale ha on_target = n e quindi coerenza
        # piena; uno che metà anticipa e metà posticipa si ferma al
        # 50%, ed è giusto così: non sta dicendo che il modello
        # sbaglia, sta dicendo che le sue abitudini sono irregolari.
        concordant = max(above, below, on_target)
    consistency = concordant / n

    # Il fattore inverte il rapporto: se l'utente aspetta di più, il
    # modello sovrastimava il consumo e il Kc va abbassato.
    factor = 1.0 / median_ratio
    factor = max(CORRECTION_MIN, min(CORRECTION_MAX, factor))

    notes_parts = [
        f"{n} osservazione/i utilizzabile/i"
        + (f" ({n_discarded} scartate come implausibili)."
           if n_discarded else ".")
    ]
    direction = "posticipa" if median_shift > 0 else "anticipa"

    if confidence == "insufficient":
        notes_parts.append(
            f"Troppo poche per proporre una ritaratura: ne servono "
            f"almeno {MIN_OBS_FOR_LOW_CONFIDENCE}."
        )
        return BehavioralCalibrationResult(
            kc_correction_factor=None, n_observations=n,
            n_discarded=n_discarded, confidence=confidence,
            consistency=consistency, median_shift_days=median_shift,
            ratios=ratios, notes=" ".join(notes_parts),
        )

    if consistency < min_consistency:
        notes_parts.append(
            f"Scostamento non sistematico: solo il "
            f"{consistency:.0%} delle osservazioni va nella stessa "
            f"direzione. Sembra variabilità delle abitudini, non un "
            f"errore del modello."
        )
        return BehavioralCalibrationResult(
            kc_correction_factor=None, n_observations=n,
            n_discarded=n_discarded, confidence=confidence,
            consistency=consistency, median_shift_days=median_shift,
            ratios=ratios, notes=" ".join(notes_parts),
        )

    if abs(factor - 1.0) <= negligible_band:
        notes_parts.append(
            f"Il modello è già allineato alla tua pratica "
            f"(scarto entro il {negligible_band:.0%}): nessuna "
            f"ritaratura necessaria."
        )
        return BehavioralCalibrationResult(
            kc_correction_factor=None, n_observations=n,
            n_discarded=n_discarded, confidence=confidence,
            consistency=consistency, median_shift_days=median_shift,
            ratios=ratios, notes=" ".join(notes_parts),
        )

    verso = "abbassare" if factor < 1.0 else "alzare"
    notes_parts.append(
        f"{direction.capitalize()} l'irrigazione mediamente di "
        f"{abs(median_shift):.1f} giorni rispetto al suggerimento, in "
        f"modo coerente ({consistency:.0%} delle volte). Proposta: "
        f"{verso} il consumo stimato del "
        f"{abs(1.0 - factor):.0%} per questo vaso."
    )

    return BehavioralCalibrationResult(
        kc_correction_factor=factor, n_observations=n,
        n_discarded=n_discarded, confidence=confidence,
        consistency=consistency, median_shift_days=median_shift,
        ratios=ratios, notes=" ".join(notes_parts),
    )


def apply_kc_correction(
    species: Species,
    factor: float,
    *,
    name_suffix: str = " (calibrato)",
) -> Species:
    """
    Restituisce una copia della specie con i Kc scalati dal fattore.

    È il modo concreto in cui l'override resta **locale**: la specie
    corretta va assegnata al singolo vaso, mentre il catalogo globale
    resta intatto. Nessun altro vaso, e nessun altro utente, vede la
    correzione.

    I Kcb del dual-Kc, se presenti, vengono scalati dello stesso
    fattore: la correzione riguarda il consumo della pianta, che nel
    dual-Kc vive nella componente basale.

    I valori risultanti sono limitati per restare nel range di
    validità di `Species`. La relazione Kcb ≤ Kc è preservata perché
    entrambi scalano nello stesso modo.
    """
    if factor <= 0.0:
        raise ValueError(
            f"Il fattore di correzione deve essere positivo, "
            f"ricevuto {factor}."
        )

    def _scale(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return max(KC_FLOOR, min(KC_CEILING, value * factor))

    return dataclasses.replace(
        species,
        common_name=f"{species.common_name}{name_suffix}",
        kc_initial=_scale(species.kc_initial),
        kc_mid=_scale(species.kc_mid),
        kc_late=_scale(species.kc_late),
        kcb_initial=_scale(species.kcb_initial),
        kcb_mid=_scale(species.kcb_mid),
        kcb_late=_scale(species.kcb_late),
    )


# =======================================================================
#  Il giudizio sulle allerte: calibrazione della soglia p
# =======================================================================
#
# Il segnale
# ----------
# L'allerta di irrigazione scatta quando la deplezione supera p, cioè
# quando il vaso ha consumato la frazione p della sua acqua
# disponibile. Se il giardiniere guarda la pianta e dice "sta
# benissimo, l'allerta era prematura", sta dicendo una cosa precisa e
# quantificabile: **a quel livello di deplezione la pianta non
# soffriva**, quindi la soglia vera è più in là.
#
# Vale anche il segnale opposto, ed è quello agronomicamente più
# prezioso: se il giardiniere segnala una pianta che soffre a un
# livello di deplezione a cui il modello la dava tranquilla, la soglia
# è troppo permissiva e va abbassata. Un'allerta mancata costa di più
# di una prematura.
#
# Il metodo: delimitare, non mediare
# ----------------------------------
# Ogni osservazione è un vincolo su dove può stare p:
#
#   pianta sana a deplezione d      →  p sta SOPRA d
#   pianta sofferente a deplezione d →  p sta SOTTO (o a) d
#
# Non ha senso mediare i due gruppi: sono vincoli di verso opposto che
# delimitano un intervallo. La stima è il punto di mezzo tra il
# "sicuramente sana fin qui" e il "già sofferente da qui".
#
# Per robustezza non usiamo il massimo delle sane e il minimo delle
# sofferenti — un singolo giudizio distratto sposterebbe tutto — ma il
# 75° percentile delle sane e il 25° delle sofferenti, con la stessa
# filosofia della calibrazione da sensore.
#
# Osservazioni contraddittorie
# ----------------------------
# Può capitare che la pianta risulti sana a una deplezione più alta di
# quella a cui è risultata sofferente. Non è necessariamente un errore
# dell'utente: la tolleranza reale cambia con la stagione, con lo
# stadio e con la domanda atmosferica. In quel caso proponiamo comunque
# il punto di mezzo, ma lo dichiariamo e limitiamo la confidenza: è
# un'informazione da mostrare al giardiniere, non da applicare in
# silenzio.

# Soglie di numerosità per il giudizio sulle allerte. Stanno in mezzo
# tra il sensore (3/5/10) e lo scostamento delle irrigazioni (5/10/15):
# ogni giudizio è esplicito e quindi più informativo di un orario di
# irrigazione, ma resta soggettivo e quindi meno affidabile di una
# misura.
MIN_JUDGMENTS_FOR_LOW_CONFIDENCE = 3
MIN_JUDGMENTS_FOR_MEDIUM_CONFIDENCE = 6
MIN_JUDGMENTS_FOR_HIGH_CONFIDENCE = 10

# Limiti agronomici entro cui mantenere la p proposta. Sotto 0.15 il
# vaso verrebbe irrigato di continuo; sopra 0.85 si arriverebbe quasi
# al punto di appassimento prima di dire qualcosa.
DEPLETION_MIN = 0.15
DEPLETION_MAX = 0.85

# Margine con cui superare il vincolo quando abbiamo un solo verso di
# osservazioni. Con sole piante sane sappiamo che p sta più in là, ma
# non quanto: ci spostiamo del minimo difendibile.
ONE_SIDED_MARGIN = 0.05


def depletion_fraction(
    state_mm: float, fc_mm: float, taw_mm: float,
) -> float:
    """
    Frazione di acqua disponibile già consumata dal vaso.

    È la grandezza con cui si esprime un giudizio sull'allerta: 0.0
    significa substrato alla capacità di campo, 1.0 significa acqua
    disponibile esaurita. Si confronta direttamente con la
    `depletion_fraction` della specie, che è la soglia di allerta.

    I valori sono limitati a [0, 1]: un vaso appena irrigato può
    trovarsi sopra la capacità di campo per qualche ora, e non ha senso
    riportare una deplezione negativa.
    """
    if taw_mm <= 0.0:
        raise ValueError(
            f"taw_mm deve essere positivo, ricevuto {taw_mm}."
        )
    return max(0.0, min(1.0, (fc_mm - state_mm) / taw_mm))


@dataclass(frozen=True)
class AlertJudgment:
    """
    Il giudizio del giardiniere sullo stato della pianta, a un livello
    di deplezione noto.

    Nasce tipicamente da due gesti nell'app: il rifiuto di un'allerta
    ("la pianta sta bene") e la segnalazione spontanea di sofferenza.
    In entrambi i casi quello che serve al modello è la coppia
    *deplezione osservata* + *giudizio*.

    Attributi
    ---------
    observed_at : date
        Quando il giardiniere ha espresso il giudizio.
    depletion : float
        Frazione di acqua disponibile consumata in quel momento,
        in [0, 1]. Si ricava con `depletion_fraction()`.
    plant_stressed : bool
        True se la pianta mostrava sofferenza, False se stava bene.
        Il rifiuto di un'allerta di irrigazione è un `False`.
    """

    observed_at: date
    depletion: float
    plant_stressed: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.depletion <= 1.0:
            raise ValueError(
                f"depletion deve stare in [0, 1], ricevuto "
                f"{self.depletion}. Usa depletion_fraction() per "
                f"calcolarla dallo stato del vaso."
            )


@dataclass(frozen=True)
class DepletionCalibrationResult:
    """
    Proposta di correzione della soglia di deplezione p.

    Attributi
    ---------
    depletion_fraction : float | None
        La p proposta per quel vaso, o `None` quando non c'è motivo di
        correggere: giudizi insufficienti, oppure proposta troppo
        vicina al valore corrente.
    n_healthy, n_stressed : int
        Giudizi nei due versi.
    confidence : str
        "high" / "medium" / "low" / "insufficient".
    healthy_up_to : float | None
        Deplezione fino alla quale la pianta è risultata sana
        (75° percentile dei giudizi positivi).
    stressed_from : float | None
        Deplezione da cui la pianta è risultata sofferente
        (25° percentile dei giudizi negativi).
    contradictory : bool
        True se i due gruppi si sovrappongono, cioè la pianta è
        risultata sana a una deplezione superiore a quella a cui è
        risultata sofferente.
    notes : str
        Spiegazione in italiano, pensata per essere mostrata così com'è.
    """

    depletion_fraction: Optional[float]
    n_healthy: int
    n_stressed: int
    confidence: str
    healthy_up_to: Optional[float]
    stressed_from: Optional[float]
    contradictory: bool
    notes: str

    @property
    def suggests_correction(self) -> bool:
        """True se c'è una proposta concreta da sottoporre all'utente."""
        return self.depletion_fraction is not None


def _percentile(values: Sequence[float], p: float) -> float:
    """Percentile con interpolazione lineare su una sequenza non vuota."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (p / 100.0) * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    frac = pos - lower
    return ordered[lower] * (1.0 - frac) + ordered[upper] * frac


def _judgment_confidence(n_obs: int) -> str:
    """Livello di confidenza dalla numerosità dei giudizi."""
    if n_obs >= MIN_JUDGMENTS_FOR_HIGH_CONFIDENCE:
        return "high"
    if n_obs >= MIN_JUDGMENTS_FOR_MEDIUM_CONFIDENCE:
        return "medium"
    if n_obs >= MIN_JUDGMENTS_FOR_LOW_CONFIDENCE:
        return "low"
    return "insufficient"


def calibrate_depletion_from_judgments(
    judgments: Sequence[AlertJudgment],
    current_depletion_fraction: float,
    *,
    negligible_band: float = 0.05,
) -> DepletionCalibrationResult:
    """
    Propone una soglia di deplezione a partire dai giudizi del
    giardiniere sullo stato della pianta.

    Come per lo scostamento delle irrigazioni, non applica nulla:
    restituisce una proposta con la sua confidenza e una spiegazione.

    Parametri
    ---------
    judgments : sequence[AlertJudgment]
        I giudizi raccolti, tipicamente per un singolo vaso.
    current_depletion_fraction : float
        La p attualmente in uso, per decidere se lo scostamento vale
        la pena di essere proposto.
    negligible_band : float, opzionale
        Scostamento sotto il quale non vale la pena disturbare
        l'utente. Default 0.05 in unità di p.

    Ritorna
    -------
    DepletionCalibrationResult
    """
    healthy = [j.depletion for j in judgments if not j.plant_stressed]
    stressed = [j.depletion for j in judgments if j.plant_stressed]
    n_total = len(healthy) + len(stressed)
    confidence = _judgment_confidence(n_total)

    if n_total == 0:
        return DepletionCalibrationResult(
            depletion_fraction=None, n_healthy=0, n_stressed=0,
            confidence=confidence, healthy_up_to=None,
            stressed_from=None, contradictory=False,
            notes=(
                "Nessun giudizio raccolto. Servono allerte rifiutate "
                "('la pianta sta bene') o segnalazioni di sofferenza."
            ),
        )

    # Percentili robusti invece di massimo e minimo: un singolo
    # giudizio distratto non deve spostare la soglia.
    healthy_up_to = _percentile(healthy, 75.0) if healthy else None
    stressed_from = _percentile(stressed, 25.0) if stressed else None

    contradictory = (
        healthy_up_to is not None
        and stressed_from is not None
        and healthy_up_to >= stressed_from
    )

    notes_parts = [
        f"{len(healthy)} giudizio/i di pianta sana e "
        f"{len(stressed)} di sofferenza."
    ]

    if confidence == "insufficient":
        notes_parts.append(
            f"Troppo pochi per proporre una ritaratura: ne servono "
            f"almeno {MIN_JUDGMENTS_FOR_LOW_CONFIDENCE}."
        )
        return DepletionCalibrationResult(
            depletion_fraction=None, n_healthy=len(healthy),
            n_stressed=len(stressed), confidence=confidence,
            healthy_up_to=healthy_up_to, stressed_from=stressed_from,
            contradictory=contradictory,
            notes=" ".join(notes_parts),
        )

    # La stima vera e propria: delimitare l'intervallo ammissibile.
    if healthy_up_to is not None and stressed_from is not None:
        proposed = (healthy_up_to + stressed_from) / 2.0
    elif healthy_up_to is not None:
        # Solo piante sane: sappiamo che la soglia sta più in là, ma
        # non quanto. Ci spostiamo del minimo difendibile.
        proposed = max(current_depletion_fraction,
                       healthy_up_to + ONE_SIDED_MARGIN)
    else:
        # Solo sofferenza: la soglia va abbassata sotto il livello a
        # cui la pianta stava già male.
        proposed = min(current_depletion_fraction,
                       stressed_from - ONE_SIDED_MARGIN)

    proposed = max(DEPLETION_MIN, min(DEPLETION_MAX, proposed))

    if contradictory:
        notes_parts.append(
            f"Giudizi in parte contraddittori: la pianta è risultata "
            f"sana fino a una deplezione del {healthy_up_to:.0%} ma "
            f"sofferente già dal {stressed_from:.0%}. Può dipendere "
            f"dalla stagione o dallo stadio, non necessariamente da un "
            f"errore: valuta la proposta con prudenza."
        )
        # La contraddizione non invalida il dato ma abbassa la fiducia.
        if confidence in ("high", "medium"):
            confidence = "low"

    if abs(proposed - current_depletion_fraction) <= negligible_band:
        notes_parts.append(
            f"La soglia attuale ({current_depletion_fraction:.2f}) è "
            f"già coerente con i tuoi giudizi: nessuna ritaratura "
            f"necessaria."
        )
        return DepletionCalibrationResult(
            depletion_fraction=None, n_healthy=len(healthy),
            n_stressed=len(stressed), confidence=confidence,
            healthy_up_to=healthy_up_to, stressed_from=stressed_from,
            contradictory=contradictory,
            notes=" ".join(notes_parts),
        )

    if proposed > current_depletion_fraction:
        notes_parts.append(
            f"Le allerte scattano prima del necessario: la pianta "
            f"risulta ancora sana a livelli di asciutto che il modello "
            f"considera critici. Proposta: alzare la soglia da "
            f"{current_depletion_fraction:.2f} a {proposed:.2f}, così "
            f"le allerte arrivano più tardi."
        )
    else:
        notes_parts.append(
            f"Le allerte arrivano tardi: la pianta mostra sofferenza "
            f"prima che il modello se ne accorga. Proposta: abbassare "
            f"la soglia da {current_depletion_fraction:.2f} a "
            f"{proposed:.2f}, così le allerte anticipano."
        )

    return DepletionCalibrationResult(
        depletion_fraction=proposed, n_healthy=len(healthy),
        n_stressed=len(stressed), confidence=confidence,
        healthy_up_to=healthy_up_to, stressed_from=stressed_from,
        contradictory=contradictory,
        notes=" ".join(notes_parts),
    )


def apply_depletion_correction(
    species: Species,
    new_depletion_fraction: float,
    *,
    name_suffix: str = " (calibrato)",
) -> Species:
    """
    Restituisce una copia della specie con la nuova soglia p.

    Come `apply_kc_correction`, è il modo in cui l'override resta
    locale al vaso: il catalogo globale non viene toccato.

    A differenza del Kc, qui non c'è una scalatura ma una sostituzione:
    la soglia è una proprietà della tolleranza della pianta, e il
    giudizio del giardiniere la stima direttamente.
    """
    if not 0.0 < new_depletion_fraction <= 1.0:
        raise ValueError(
            f"La frazione di deplezione deve stare in (0, 1], "
            f"ricevuto {new_depletion_fraction}."
        )
    return dataclasses.replace(
        species,
        common_name=f"{species.common_name}{name_suffix}",
        depletion_fraction=new_depletion_fraction,
    )
