"""
Precedenza tra fonti di calibrazione.

Il problema
-----------

Alla fine della fase A lo stesso parametro può essere toccato da più
fonti. Il coefficiente colturale Kc, in particolare, ne ha tre:

  - il **lisimetro**, che misura il consumo di un vaso di riferimento
    in condizioni controllate — il valore di **catalogo** per il
    sim_group;
  - la **pendenza del sensore**, che misura direttamente quanto in
    fretta si asciuga **questo** vaso;
  - il **segnale comportamentale**, che deduce dal ritmo delle
    irrigazioni quanto **questo** vaso consuma, quando un sensore non
    c'è.

Quando il lisimetro dice 0.95 e la pendenza del sensore di quel vaso
dice 1.20, **non è per forza un conflitto**: il primo descrive il vaso
medio del gruppo, il secondo descrive quel vaso lì, che può
legittimamente consumare di più perché sta più al sole, o ha una
chioma più grande. La domanda giusta non è "quale fonte è più
accurata" ma "quale fonte parla dell'oggetto che sto simulando".

I due assi da non confondere
----------------------------

Ogni proposta si colloca su **due** assi indipendenti, e la trappola è
schiacciarli in uno solo:

  - lo **scope** — quanto è specifica al vaso: catalogo (tutto il
    gruppo) ⊂ cluster (clima × gruppo) ⊂ vaso (questo);
  - la **reliability** — quanto è affidabile la fonte in sé.

Il lisimetro è *ground truth* sull'asse della reliability, ma vive
sullo scope più largo (il catalogo). Per simulare **questo** vaso, una
misura diretta del vaso — anche meno raffinata — batte il valore di
catalogo, perché parla dell'oggetto giusto. Per il **default che un
vaso nuovo eredita**, invece, vince il lisimetro. Non c'è
contraddizione: le due risposte vivono a scope diversi, e questo
modulo le restituisce entrambe.

La regola
---------

1. **Lo scope più specifico che ha una proposta usabile decide il
   valore del vaso.** Lo scope batte la reliability *tra* scope
   diversi.
2. **Dentro uno stesso scope**, se più fonti competono, vince la più
   affidabile: prima la confidenza (numerosità), poi il tipo di fonte
   (una misura assoluta batte un fattore inferito), così una fonte
   solida non viene scavalcata da una fondata su pochi dati.
3. Il valore risolto a ogni livello viene restituito: quello di
   catalogo (per i vasi fratelli) e quello del vaso (per la sua
   simulazione) sono output distinti.

Assoluti e fattori: perché i fattori si ancorano al prior
---------------------------------------------------------

Le fonti non parlano tutte la stessa lingua. Lisimetro e sensore
producono un Kc **assoluto**; il comportamentale produce un
**fattore** moltiplicativo. Un fattore è definito rispetto a ciò che
il modello prevedeva **quando è stato misurato** — cioè il valore che
il modello usava allora, il `prior` passato qui. Perciò ogni proposta
viene prima convertita in un "assoluto implicito" ancorato al prior
(`assoluto = prior × fattore`), e solo dopo si risolve per scope.

La conseguenza pratica conta. Se un lisimetro abbassa il catalogo da
1.00 a 0.90 e un fattore comportamentale dice ×1.10, applicare il
fattore al catalogo darebbe 0.99 — trascinando il vaso verso la media
del gruppo. Ma il fattore diceva "questo vaso consuma il 10% più di
quanto il modello (1.00) prevedeva": la sua evidenza è ~1.10, ed è del
**vaso**, non del gruppo. Ancorando al prior il vaso resta a 1.10, e
il catalogo 0.90 viene restituito a parte per i fratelli.

Questo presume che `prior` sia il valore che il modello usa **adesso**
per questo vaso. È vero per costruzione: le proposte sono evidenza
*nuova*, non ancora incorporata. Se il vaso avesse già ereditato un
valore di cluster, quello sarebbe il prior, e il fattore vi si
ancorerebbe correttamente. Nel transitorio dopo un aggiornamento di
catalogo, un vecchio fattore e il nuovo catalogo possono discordare di
poco: la ricalibrazione successiva rimisura sul nuovo prior e il
sistema converge. È lo stesso carattere convergente già discusso per
il segnale comportamentale.

Cosa NON fa questo modulo
-------------------------

Non raccoglie evidenze, non conosce utenti né fingerprint, non aggrega
tra persone diverse: quella è la gerarchia di aggregazione, e vive in
The Pot. Qui c'è solo la **matematica della precedenza**: date alcune
proposte già formate, con scope e confidenza, produce un valore
risolto e la sua spiegazione. The Pot decide *quali* proposte
esistono; fitosim decide *come si compongono*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

# Nomi di parametro. Stringhe e non enum per lasciare aperta l'aggiunta
# di parametri futuri senza toccare questo modulo.
PARAM_KC = "kc"
PARAM_DEPLETION = "p"

# Oltre questa differenza relativa tra il valore del vaso e un valore di
# catalogo ad alta confidenza, la divergenza viene segnalata. Non è un
# errore — un vaso può essere un outlier — ma va resa visibile invece
# di essere inghiottita in silenzio.
DEFAULT_DIVERGENCE_TOLERANCE = 0.15


class CalibrationScope(Enum):
    """Quanto una proposta è specifica al singolo vaso."""

    CATALOG = "catalog"   # il prior del sim_group, valido per tutti
    CLUSTER = "cluster"   # clima × sim_group (riservato: lo emette The Pot)
    POT = "pot"           # questo vaso


class CalibrationSource(Enum):
    """Da dove viene una proposta. Determina la reliability entro lo scope."""

    EXPERT = "expert"             # correzione curata dal team (riservato)
    LYSIMETER = "lysimeter"       # pesata
    SENSOR_SLOPE = "sensor_slope"  # velocità di asciugamento
    DISMISSAL = "dismissal"       # giudizio del giardiniere sulle allerte
    BEHAVIORAL = "behavioral"     # scostamento delle irrigazioni


class ProposalKind(Enum):
    """La proposta è un valore assoluto o un fattore moltiplicativo?"""

    ABSOLUTE = "absolute"
    FACTOR = "factor"


# Ordine di specificità, dal più largo al più stretto. Lo scope più
# stretto con una proposta usabile decide il valore del vaso.
_SCOPE_ORDER: tuple[CalibrationScope, ...] = (
    CalibrationScope.CATALOG,
    CalibrationScope.CLUSTER,
    CalibrationScope.POT,
)

# Rango di confidenza: più basso è meglio. "insufficient" non compare —
# le proposte insufficienti vengono scartate prima di arrivare qui.
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

# Reliability della fonte, usata solo per rompere i pari DENTRO uno
# stesso scope. Più basso è più autorevole.
_RELIABILITY_RANK: dict[CalibrationSource, int] = {
    CalibrationSource.EXPERT: 0,
    CalibrationSource.LYSIMETER: 1,
    CalibrationSource.SENSOR_SLOPE: 1,
    CalibrationSource.DISMISSAL: 1,
    CalibrationSource.BEHAVIORAL: 2,
}

# A parità di confidenza e reliability, una misura assoluta batte un
# fattore: l'assoluto è una misura diretta, il fattore un aggiustamento
# relativo che sull'assoluto sarebbe un doppio conteggio.
_KIND_RANK: dict[ProposalKind, int] = {
    ProposalKind.ABSOLUTE: 0,
    ProposalKind.FACTOR: 1,
}

# Etichette brevi per la spiegazione, al posto delle note complete
# (che restano sulla proposta).
_SOURCE_LABEL: dict[CalibrationSource, str] = {
    CalibrationSource.EXPERT: "la correzione curata",
    CalibrationSource.LYSIMETER: "il lisimetro",
    CalibrationSource.SENSOR_SLOPE: "la pendenza del sensore",
    CalibrationSource.DISMISSAL: "il giudizio sulle allerte",
    CalibrationSource.BEHAVIORAL: "il segnale comportamentale",
}

_SCOPE_LABEL: dict[CalibrationScope, str] = {
    CalibrationScope.CATALOG: "catalogo",
    CalibrationScope.CLUSTER: "cluster",
    CalibrationScope.POT: "vaso",
}


@dataclass(frozen=True)
class CalibrationProposal:
    """
    Una proposta di correzione, normalizzata rispetto alla fonte.

    È la valuta comune del modulo: le fonti eterogenee vengono ridotte
    a questa forma dagli adapter più sotto, così il cuore della
    risoluzione non sa nulla dei tipi di risultato specifici.

    Attributi
    ---------
    parameter : str
        Quale parametro tocca (`PARAM_KC`, `PARAM_DEPLETION`, ...).
    source : CalibrationSource
        La fonte, che ne determina la reliability entro lo scope.
    scope : CalibrationScope
        Quanto è specifica al vaso.
    kind : ProposalKind
        Valore assoluto o fattore moltiplicativo.
    value : float
        Il valore assoluto, o il fattore se `kind` è FACTOR.
    confidence : str
        "high" / "medium" / "low". "insufficient" fa scartare la
        proposta.
    n_observations : int
        Da quante osservazioni nasce la proposta. Solo informativo.
    note : str
        Spiegazione della fonte, riportabile all'utente.
    """

    parameter: str
    source: CalibrationSource
    scope: CalibrationScope
    kind: ProposalKind
    value: float
    confidence: str
    n_observations: int = 0
    note: str = ""


@dataclass(frozen=True)
class Resolution:
    """
    Esito della risoluzione di un parametro.

    Attributi
    ---------
    parameter : str
        Il parametro risolto.
    resolved_value : float
        Il valore per **questo vaso**: lo scope più specifico che aveva
        una proposta usabile. È quello con cui simulare il vaso.
    baseline : float
        Il prior da cui si è partiti.
    catalog_value : float
        Il valore allo scope di **catalogo**: quello che un vaso nuovo
        del gruppo eredita. Coincide con `baseline` se nessuna fonte di
        catalogo (il lisimetro) era presente.
    values_by_scope : tuple[tuple[CalibrationScope, float], ...]
        Il valore risolto a ogni livello di scope, dal più largo al più
        stretto, con i livelli senza proposte che riportano il valore
        del livello precedente. `catalog_value` e `resolved_value` sono
        i due estremi.
    decisive : CalibrationProposal | None
        La proposta che ha fissato `resolved_value` (allo scope più
        stretto). `None` se nessuna proposta era usabile e il valore è
        rimasto il prior.
    applied : tuple[CalibrationProposal, ...]
        La proposta vincente a ciascuno scope che ne aveva, dal più
        largo al più stretto.
    ignored : tuple[tuple[CalibrationProposal, str], ...]
        Le proposte scartate, ciascuna con il motivo.
    catalog_divergence : bool
        True se un valore di catalogo ad alta confidenza differisce dal
        valore del vaso oltre la tolleranza. Non è un errore: segnala
        un vaso potenzialmente outlier, da guardare.
    explanation : str
        Spiegazione in italiano, pensata per essere mostrata così.
    """

    parameter: str
    resolved_value: float
    baseline: float
    catalog_value: float
    values_by_scope: tuple[tuple[CalibrationScope, float], ...]
    decisive: Optional[CalibrationProposal]
    applied: tuple[CalibrationProposal, ...]
    ignored: tuple[tuple[CalibrationProposal, str], ...]
    catalog_divergence: bool
    explanation: str

    @property
    def implied_factor(self) -> float:
        """
        Il rapporto `resolved_value / baseline`.

        È il modo di applicare la risoluzione a una `Species` riusando
        `behavioral_calibration.apply_kc_correction`, che scala tutti
        gli stadi del Kc: la risoluzione fissa il Kc effettivo *adesso*,
        e questo rapporto lo traduce nel fattore che porta il modello
        lì. Per un parametro assoluto come `p`, si usa direttamente
        `resolved_value`.
        """
        if self.baseline == 0.0:
            return 1.0
        return self.resolved_value / self.baseline


# =======================================================================
#  Adapter dalle fonti concrete
# =======================================================================
#
# Ogni adapter legge i pochi campi che gli servono per campo, senza
# vincolarsi al tipo esatto del risultato: così questo modulo non si
# rompe se un risultato guadagna campi, e resta testabile con proposte
# sintetiche. Restituiscono None quando la fonte non ha una stima
# (niente da proporre).


def proposal_from_lysimeter(
    result,
    *,
    scope: CalibrationScope = CalibrationScope.CATALOG,
) -> Optional[CalibrationProposal]:
    """
    Proposta di Kc dal lisimetro (assoluta, scope di catalogo).

    Il lisimetro misura il vaso di riferimento in condizioni
    controllate: per default è quindi una proposta di **catalogo**, non
    del singolo vaso.
    """
    if result.kc_estimate is None:
        return None
    return CalibrationProposal(
        parameter=PARAM_KC,
        source=CalibrationSource.LYSIMETER,
        scope=scope,
        kind=ProposalKind.ABSOLUTE,
        value=result.kc_estimate,
        confidence=result.confidence,
        n_observations=result.n_intervals,
        note=result.notes,
    )


def proposal_from_sensor_slope(
    result,
    *,
    scope: CalibrationScope = CalibrationScope.POT,
) -> Optional[CalibrationProposal]:
    """Proposta di Kc dalla pendenza del sensore (assoluta, scope vaso)."""
    if result.kc_estimate is None:
        return None
    return CalibrationProposal(
        parameter=PARAM_KC,
        source=CalibrationSource.SENSOR_SLOPE,
        scope=scope,
        kind=ProposalKind.ABSOLUTE,
        value=result.kc_estimate,
        confidence=result.confidence,
        n_observations=result.n_windows,
        note=result.notes,
    )


def proposal_from_behavioral_kc(
    result,
    *,
    scope: CalibrationScope = CalibrationScope.POT,
) -> Optional[CalibrationProposal]:
    """
    Proposta di Kc dal segnale comportamentale (fattore, scope vaso).

    È un fattore, non un assoluto: dice di quanto scostarsi da ciò che
    il modello prevedeva, non a che valore arrivare.
    """
    if result.kc_correction_factor is None:
        return None
    return CalibrationProposal(
        parameter=PARAM_KC,
        source=CalibrationSource.BEHAVIORAL,
        scope=scope,
        kind=ProposalKind.FACTOR,
        value=result.kc_correction_factor,
        confidence=result.confidence,
        n_observations=result.n_observations,
        note=result.notes if hasattr(result, "notes") else "",
    )


def proposal_from_dismissal(
    result,
    *,
    scope: CalibrationScope = CalibrationScope.POT,
) -> Optional[CalibrationProposal]:
    """Proposta di soglia p dal giudizio sulle allerte (assoluta, scope vaso)."""
    if result.depletion_fraction is None:
        return None
    return CalibrationProposal(
        parameter=PARAM_DEPLETION,
        source=CalibrationSource.DISMISSAL,
        scope=scope,
        kind=ProposalKind.ABSOLUTE,
        value=result.depletion_fraction,
        confidence=result.confidence,
        n_observations=result.n_healthy + result.n_stressed,
        note=result.notes,
    )


# =======================================================================
#  Il cuore: risoluzione
# =======================================================================


def _sort_key(proposal: CalibrationProposal) -> tuple[int, int, int]:
    """
    Chiave di preferenza DENTRO uno scope: prima la confidenza, poi la
    reliability della fonte, poi il tipo (assoluto prima del fattore).
    """
    return (
        _CONFIDENCE_RANK[proposal.confidence],
        _RELIABILITY_RANK[proposal.source],
        _KIND_RANK[proposal.kind],
    )


def _loser_reason(
    winner: CalibrationProposal, loser: CalibrationProposal,
) -> str:
    """Perché una proposta ha perso contro un'altra dello stesso scope."""
    if (
        winner.kind is ProposalKind.ABSOLUTE
        and loser.kind is ProposalKind.FACTOR
    ):
        return (
            f"allo stesso scope ({_SCOPE_LABEL[loser.scope]}) una misura "
            f"assoluta ({_SOURCE_LABEL[winner.source]}) ha la precedenza: "
            f"applicare anche il fattore sarebbe un doppio conteggio"
        )
    return (
        f"allo stesso scope ({_SCOPE_LABEL[loser.scope]}) ha vinto una "
        f"fonte a priorità superiore ({_SOURCE_LABEL[winner.source]}, "
        f"confidenza {winner.confidence})"
    )


def _implied_absolute(proposal: CalibrationProposal, prior: float) -> float:
    """Il valore assoluto implicito: i fattori si ancorano al prior."""
    if proposal.kind is ProposalKind.ABSOLUTE:
        return proposal.value
    return prior * proposal.value


def resolve(
    parameter: str,
    prior: float,
    proposals: Sequence[CalibrationProposal],
    *,
    divergence_tolerance: float = DEFAULT_DIVERGENCE_TOLERANCE,
) -> Resolution:
    """
    Risolve un parametro dato il prior e un insieme di proposte.

    Parametri
    ---------
    parameter : str
        Il parametro da risolvere. Le proposte per altri parametri
        vengono ignorate senza rumore.
    prior : float
        Il valore che il modello usa **adesso** per questo vaso, e
        l'ancora dei fattori.
    proposals : sequence[CalibrationProposal]
        Le proposte disponibili, di qualunque fonte e scope.
    divergence_tolerance : float, opzionale
        Soglia relativa oltre cui segnalare `catalog_divergence`.

    Ritorna
    -------
    Resolution
    """
    if not math.isfinite(prior):
        raise ValueError(f"Il prior deve essere finito, ricevuto {prior}.")

    relevant = [p for p in proposals if p.parameter == parameter]

    usable: list[CalibrationProposal] = []
    ignored: list[tuple[CalibrationProposal, str]] = []
    for p in relevant:
        if p.confidence in _CONFIDENCE_RANK:
            usable.append(p)
        else:
            ignored.append(
                (p, f"confidenza '{p.confidence}' non sufficiente per essere usata")
            )

    if prior <= 0.0 and any(p.kind is ProposalKind.FACTOR for p in usable):
        raise ValueError(
            "Con almeno un fattore tra le proposte il prior deve essere "
            f"positivo (serve ad ancorarlo), ricevuto {prior}."
        )

    running = prior
    values_by_scope: list[tuple[CalibrationScope, float]] = []
    applied: list[CalibrationProposal] = []

    for scope in _SCOPE_ORDER:
        candidates = [p for p in usable if p.scope is scope]
        if candidates:
            ordered = sorted(candidates, key=_sort_key)
            winner = ordered[0]
            running = _implied_absolute(winner, prior)
            applied.append(winner)
            for loser in ordered[1:]:
                ignored.append((loser, _loser_reason(winner, loser)))
        values_by_scope.append((scope, running))

    resolved = running
    catalog_value = values_by_scope[0][1]
    decisive = applied[-1] if applied else None

    # Divergenza: una fonte di scope più largo del decisivo, ad alta
    # confidenza, che si discosta dal valore del vaso oltre la
    # tolleranza. Segnala un possibile outlier, non un errore.
    catalog_divergence = False
    divergence_note = ""
    if decisive is not None:
        for broader in applied[:-1]:
            broader_value = _implied_absolute(broader, prior)
            denom = max(abs(broader_value), 1e-9)
            rel = abs(resolved - broader_value) / denom
            if broader.confidence == "high" and rel > divergence_tolerance:
                catalog_divergence = True
                verso = "in meno" if broader_value < resolved else "in più"
                divergence_note = (
                    f" Attenzione: {_SOURCE_LABEL[broader.source]} "
                    f"({_SCOPE_LABEL[broader.scope]}, confidenza alta) vale "
                    f"{broader_value:.2f}, il {rel:.0%} {verso} del valore "
                    f"risolto per il vaso ({resolved:.2f}): atteso se il vaso "
                    f"è un outlier, da verificare altrimenti."
                )
                break

    explanation = _build_explanation(
        parameter, prior, resolved, catalog_value,
        applied, ignored, divergence_note,
    )

    return Resolution(
        parameter=parameter,
        resolved_value=resolved,
        baseline=prior,
        catalog_value=catalog_value,
        values_by_scope=tuple(values_by_scope),
        decisive=decisive,
        applied=tuple(applied),
        ignored=tuple(ignored),
        catalog_divergence=catalog_divergence,
        explanation=explanation,
    )


def _fmt(proposal: CalibrationProposal, prior: float) -> str:
    """Una riga leggibile per una proposta applicata."""
    label = _SOURCE_LABEL[proposal.source]
    scope = _SCOPE_LABEL[proposal.scope]
    if proposal.kind is ProposalKind.ABSOLUTE:
        what = f"{proposal.value:.2f}"
    else:
        what = f"×{proposal.value:.2f} (→ {prior * proposal.value:.2f})"
    return (
        f"{label} ({scope}) propone {what}, confidenza "
        f"{proposal.confidence}, {proposal.n_observations} osservazioni"
    )


def _build_explanation(
    parameter: str,
    prior: float,
    resolved: float,
    catalog_value: float,
    applied: Sequence[CalibrationProposal],
    ignored: Sequence[tuple[CalibrationProposal, str]],
    divergence_note: str,
) -> str:
    """Compone la spiegazione in italiano dagli elementi della risoluzione."""
    if not applied:
        base = (
            f"Nessuna calibrazione usabile per '{parameter}': resta il "
            f"prior ({prior:.2f})."
        )
        if ignored:
            base += (
                f" {len(ignored)} proposta/e scartata/e per confidenza "
                f"insufficiente."
            )
        return base

    parts = [
        f"'{parameter}' risolto a {resolved:.2f} per questo vaso "
        f"(prior {prior:.2f})."
    ]

    for proposal in applied:
        parts.append(_fmt(proposal, prior) + ".")

    # Il valore di catalogo va detto solo se differisce dal vaso: è
    # l'informazione che serve a chi gestisce i vasi fratelli.
    if abs(catalog_value - resolved) > 1e-9:
        parts.append(
            f"Il valore di catalogo per i vasi fratelli resta "
            f"{catalog_value:.2f}."
        )

    if ignored:
        parts.append(
            "Ignorate: "
            + "; ".join(
                f"{_SOURCE_LABEL[p.source]} ({_SCOPE_LABEL[p.scope]}) — {reason}"
                for p, reason in ignored
            )
            + "."
        )

    return " ".join(parts) + divergence_note
