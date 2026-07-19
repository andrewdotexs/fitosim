"""
Calibrazione dal comportamento del giardiniere.

Il segnale
----------

Gli altri moduli di calibrazione partono da misure: il sensore dice
quanta acqua c'è nel substrato, il lisimetro quanta ne è uscita. Qui
la sorgente è diversa e non richiede alcun hardware: è lo **scostamento
sistematico tra quando il modello suggerisce di irrigare e quando il
giardiniere irriga davvero**.

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
