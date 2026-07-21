"""
Lisimetro: misura diretta dell'evapotraspirazione per pesata.

Il principio
------------

Tutte le altre fonti di calibrazione inferiscono l'evapotraspirazione
da qualcos'altro: il sensore la deduce dalla variazione di θ, il
comportamento del giardiniere la deduce dagli intervalli di
irrigazione. Il lisimetro la **misura**, e lo fa nel modo più
elementare possibile: mettendo il vaso su una bilancia.

L'acqua che se ne va pesa. Un vaso che perde 100 grammi in una
giornata ha perso 100 millilitri d'acqua, punto — non c'è modello di
mezzo, non ci sono parametri idraulici da conoscere, non serve sapere
θ_FC né la profondità del substrato. È per questo che il lisimetro è
il **ground truth** del layer di feedback: è l'unica fonte contro cui
si possono validare le altre.

Il bilancio di massa
--------------------

Su un intervallo tra due pesate:

    ET = (massa_iniziale − massa_finale) + acqua_aggiunta − drenaggio

Tutto in grammi, con la convenzione che un grammo d'acqua è un
millilitro (densità 1 g/cm³, vera entro lo 0.3% alle temperature
domestiche). La conversione in millimetri passa per la superficie del
vaso, perché i millimetri di FAO-56 sono un'altezza d'acqua:

    ET_mm = ET_g × 10 / superficie_cm²

Perché il protocollo vuole il vaso ben irrigato
-----------------------------------------------

Questo è il punto che decide come si usa lo strumento, e vale la pena
dirlo prima delle formule.

Il coefficiente colturale Kc è **definito** in condizioni idriche non
limitanti: è il rapporto tra il consumo di una coltura sana e ben
irrigata e quello della coltura di riferimento. Se si misura il
consumo di una pianta in stress, non si sta misurando Kc: si sta
misurando il prodotto Ks·Kc, e i due non sono separabili da una sola
pesata.

Quindi il protocollo corretto per stimare Kc tiene il vaso nella zona
di comfort, e in quel regime Ks vale 1 per definizione. Non è una
limitazione dello strumento, è la definizione della grandezza che si
vuole misurare. Chi ha ragioni per credere che Ks fosse inferiore a 1
durante l'intervallo può dichiararlo sull'intervallo stesso.

Cosa può falsare la pesata
--------------------------

La massa del sistema cambia anche per ragioni che non sono acqua
evaporata, e il protocollo deve tenerne conto:

  - **Potature e raccolta**: togliere foglie toglie massa, e sulla
    bilancia è indistinguibile da acqua evaporata. Gli intervalli che
    contengono una potatura vanno esclusi, non corretti.
  - **Pioggia** sui vasi all'aperto: aggiunge massa non contabilizzata.
    Il vaso lisimetrico va riparato, oppure la pioggia va misurata e
    dichiarata come acqua aggiunta.
  - **Crescita della pianta**: la biomassa accumulata è massa che
    resta. Su una giornata sono grammi contro decine o centinaia di
    grammi d'acqua, quindi trascurabile; su intervalli lunghi
    introduce una sottostima sistematica dell'ET.
  - **Concimazione solida**: aggiunge massa che non è acqua.

I limiti di plausibilità e la mediana su più intervalli assorbono gli
errori occasionali, ma non un vizio sistematico del protocollo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

# Densità dell'acqua assunta pari a 1 g/cm³. Alle temperature
# domestiche il valore vero sta tra 0.997 e 1.000: l'errore che
# introduciamo è inferiore al 0.3%, molto sotto la ripetibilità di una
# bilancia da cucina.
WATER_DENSITY_G_PER_CM3 = 1.0

# Soglie di numerosità. Coincidono con quelle della calibrazione da
# sensore, ma per una ragione diversa: qui la singola misura è più
# affidabile (nessuna catena di inferenza), però il conteggio serve a
# mediare la variabilità biologica giorno per giorno, che c'è
# comunque, per quanto buono sia lo strumento.
MIN_INTERVALS_FOR_LOW_CONFIDENCE = 3
MIN_INTERVALS_FOR_MEDIUM_CONFIDENCE = 5
MIN_INTERVALS_FOR_HIGH_CONFIDENCE = 10

# Limiti di plausibilità per un Kc misurato. Fuori da qui l'intervallo
# è quasi certamente contaminato: una potatura non dichiarata, una
# pioggia non contabilizzata, o una pesata sbagliata.
KC_MIN_PLAUSIBLE = 0.05
KC_MAX_PLAUSIBLE = 2.50


@dataclass(frozen=True)
class LysimeterInterval:
    """
    Un intervallo tra due pesate, con tutto ciò che serve a chiuderne
    il bilancio di massa.

    L'intervallo è autocontenuto: porta con sé anche la domanda
    atmosferica dello stesso periodo, così il confronto tra misura e
    modello non dipende da allineamenti fatti altrove.

    Attributi
    ---------
    start_date, end_date : date
        Estremi dell'intervallo. `end_date` deve essere successiva.
    mass_start_g, mass_end_g : float
        Massa dell'intero sistema (vaso + substrato + pianta + acqua)
        alle due pesate, in grammi.
    et0_mm : float
        Evapotraspirazione di riferimento **cumulata** sull'intervallo,
        in mm. Per un intervallo di più giorni è la somma, non la media.
    water_added_g : float, opzionale
        Acqua aggiunta durante l'intervallo (irrigazione, e pioggia
        se il vaso non è riparato), in grammi.
    drainage_g : float, opzionale
        Acqua uscita dal fondo e raccolta, in grammi.
    mean_ks : float, opzionale
        Coefficiente di stress medio sull'intervallo. Default 1.0, che
        corrisponde al protocollo corretto per misurare Kc: vaso nella
        zona di comfort. Va abbassato solo se si sa che la pianta era
        in stress, sapendo che in quel caso si sta stimando Ks·Kc.
    """

    start_date: date
    end_date: date
    mass_start_g: float
    mass_end_g: float
    et0_mm: float
    water_added_g: float = 0.0
    drainage_g: float = 0.0
    mean_ks: float = 1.0

    def __post_init__(self) -> None:
        if self.end_date <= self.start_date:
            raise ValueError(
                f"end_date ({self.end_date}) deve essere successiva a "
                f"start_date ({self.start_date})."
            )
        if self.mass_start_g <= 0.0 or self.mass_end_g <= 0.0:
            raise ValueError(
                f"Le masse devono essere positive, ricevute "
                f"{self.mass_start_g} e {self.mass_end_g} g."
            )
        if self.water_added_g < 0.0 or self.drainage_g < 0.0:
            raise ValueError(
                "Acqua aggiunta e drenaggio non possono essere negativi."
            )
        if not 0.0 <= self.mean_ks <= 1.0:
            raise ValueError(
                f"mean_ks deve stare in [0, 1], ricevuto {self.mean_ks}."
            )
        if self.et0_mm < 0.0:
            raise ValueError(
                f"et0_mm non può essere negativa, ricevuta {self.et0_mm}."
            )

    @property
    def duration_days(self) -> int:
        """Durata dell'intervallo in giorni."""
        return (self.end_date - self.start_date).days

    @property
    def water_lost_g(self) -> float:
        """
        Acqua evapotraspirata nell'intervallo, in grammi.

        È il bilancio di massa descritto in testa al modulo. Può
        risultare negativo se il vaso ha guadagnato più acqua di quanta
        ne abbia persa: succede con pioggia non contabilizzata, ed è il
        segnale che l'intervallo non è utilizzabile.
        """
        return (
            self.mass_start_g - self.mass_end_g
            + self.water_added_g - self.drainage_g
        )


@dataclass(frozen=True)
class LysimeterCalibrationResult:
    """
    Risultato della calibrazione da pesata.

    Attributi
    ---------
    kc_estimate : float | None
        Kc misurato (mediana sugli intervalli), o `None` se nessun
        intervallo è utilizzabile.
    n_intervals : int
        Intervalli che hanno prodotto una stima plausibile.
    n_discarded : int
        Intervalli scartati perché fuori dai limiti di plausibilità o
        con bilancio non fisico.
    confidence : str
        "high" / "medium" / "low" / "insufficient".
    interval_estimates : tuple[float, ...]
        Le stime dei singoli intervalli, per diagnostica: una
        dispersione ampia segnala un protocollo instabile.
    measured_et_mm : tuple[float, ...]
        Le ET misurate sui singoli intervalli, in mm. Sono il dato
        grezzo, utile anche indipendentemente dalla stima di Kc.
    notes : str
        Spiegazione in italiano.
    """

    kc_estimate: Optional[float]
    n_intervals: int
    n_discarded: int
    confidence: str
    interval_estimates: tuple[float, ...]
    measured_et_mm: tuple[float, ...]
    notes: str


def mass_to_mm(mass_g: float, surface_area_cm2: float) -> float:
    """
    Converte una massa d'acqua in altezza equivalente sul vaso.

    I millimetri di FAO-56 sono un'altezza d'acqua distribuita sulla
    superficie: la stessa massa su un vaso stretto fa più millimetri
    che su uno largo.

    La superficie si ricava dalla geometria del vaso; per i vasi
    circolari `science.substrate.circular_pot_surface_area_m2`
    restituisce il valore in m², da moltiplicare per 10 000.
    """
    if surface_area_cm2 <= 0.0:
        raise ValueError(
            f"La superficie deve essere positiva, ricevuta "
            f"{surface_area_cm2} cm²."
        )
    volume_cm3 = mass_g / WATER_DENSITY_G_PER_CM3
    # volume/superficie dà un'altezza in cm, ×10 per averla in mm.
    return volume_cm3 / surface_area_cm2 * 10.0


def measured_et_mm(
    interval: LysimeterInterval, surface_area_cm2: float,
) -> float:
    """
    Evapotraspirazione misurata sull'intervallo, in mm.

    È la grandezza che rende il lisimetro il riferimento del layer di
    feedback: nessun parametro del modello entra in questo calcolo,
    solo masse e geometria.
    """
    return mass_to_mm(interval.water_lost_g, surface_area_cm2)


def measured_et_mm_per_day(
    interval: LysimeterInterval, surface_area_cm2: float,
) -> float:
    """ET misurata normalizzata a mm/giorno."""
    return measured_et_mm(interval, surface_area_cm2) / interval.duration_days


def estimate_kc_from_interval(
    interval: LysimeterInterval,
    surface_area_cm2: float,
    *,
    kp: float = 1.0,
    kn: float = 1.0,
) -> Optional[float]:
    """
    Kc misurato su un singolo intervallo.

    Inverte la catena moltiplicativa del modello a partire dall'ET
    misurata:

        ET = Ks · Kp · Kc · Kn · ET₀   →   Kc = ET / (Ks · Kp · Kn · ET₀)

    Ritorna `None` quando l'intervallo non è utilizzabile: domanda
    atmosferica nulla, bilancio di massa negativo (il vaso ha
    guadagnato acqua, segno di pioggia non contabilizzata), o Kc fuori
    dai limiti di plausibilità.
    """
    if kp <= 0.0 or kn <= 0.0 or interval.mean_ks <= 0.0:
        return None
    if interval.et0_mm <= 0.0:
        return None

    et_measured = measured_et_mm(interval, surface_area_cm2)
    if et_measured <= 0.0:
        # Il vaso ha guadagnato acqua invece di perderne: il bilancio
        # non è chiuso, l'intervallo non dice nulla sul consumo.
        return None

    kc = et_measured / (interval.mean_ks * kp * kn * interval.et0_mm)
    if not (KC_MIN_PLAUSIBLE <= kc <= KC_MAX_PLAUSIBLE):
        return None
    return kc


def _median(values: Sequence[float]) -> float:
    """Mediana di una sequenza non vuota."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _confidence_level(n_obs: int) -> str:
    """Livello di confidenza dalla numerosità degli intervalli."""
    if n_obs >= MIN_INTERVALS_FOR_HIGH_CONFIDENCE:
        return "high"
    if n_obs >= MIN_INTERVALS_FOR_MEDIUM_CONFIDENCE:
        return "medium"
    if n_obs >= MIN_INTERVALS_FOR_LOW_CONFIDENCE:
        return "low"
    return "insufficient"


def calibrate_kc_from_lysimeter(
    intervals: Sequence[LysimeterInterval],
    surface_area_cm2: float,
    *,
    kp: float = 1.0,
    kn: float = 1.0,
) -> LysimeterCalibrationResult:
    """
    Stima il Kc di una specie dalle pesate di un vaso lisimetrico.

    A differenza delle calibrazioni da sensore e da comportamento, che
    correggono il singolo vaso, questa è pensata per **misurare il
    parametro di catalogo**: un vaso strumentato per gruppo di specie,
    in condizioni controllate, produce il valore di riferimento contro
    cui tutto il resto si confronta.

    Parametri
    ---------
    intervals : sequence[LysimeterInterval]
        Gli intervalli di pesata.
    surface_area_cm2 : float
        Superficie evaporante del vaso.
    kp : float, opzionale
        Coefficiente di vaso. Per un lisimetro si usa tipicamente un
        vaso neutro (plastica, colore medio), quindi 1.0.
    kn : float, opzionale
        Coefficiente nutrizionale. In un protocollo controllato la
        nutrizione è ottimale, quindi 1.0.

    Ritorna
    -------
    LysimeterCalibrationResult
    """
    estimates: list[float] = []
    ets: list[float] = []
    n_discarded = 0

    for interval in intervals:
        kc = estimate_kc_from_interval(
            interval, surface_area_cm2, kp=kp, kn=kn,
        )
        if kc is None:
            n_discarded += 1
            continue
        estimates.append(kc)
        ets.append(measured_et_mm(interval, surface_area_cm2))

    n = len(estimates)
    confidence = _confidence_level(n)

    if n == 0:
        return LysimeterCalibrationResult(
            kc_estimate=None, n_intervals=0, n_discarded=n_discarded,
            confidence=confidence, interval_estimates=(),
            measured_et_mm=(),
            notes=(
                "Nessun intervallo utilizzabile. Cause tipiche: domanda "
                "atmosferica nulla, bilancio di massa che non si chiude "
                "(pioggia o irrigazione non contabilizzate), oppure "
                "intervalli contaminati da potature."
            ),
        )

    kc_estimate = _median(estimates)

    notes_parts = [
        f"Stima da {n} intervallo/i di pesata"
        + (f" ({n_discarded} scartati)." if n_discarded else ".")
    ]
    if confidence == "insufficient":
        notes_parts.append(
            f"Numerosità troppo bassa per un valore di riferimento: "
            f"ne servono almeno {MIN_INTERVALS_FOR_LOW_CONFIDENCE}."
        )
    spread = max(estimates) - min(estimates)
    if n >= 2 and spread > 0.4 * kc_estimate:
        notes_parts.append(
            f"Dispersione ampia tra gli intervalli (min "
            f"{min(estimates):.2f}, max {max(estimates):.2f}): "
            f"verifica il protocollo di pesata e l'esclusione degli "
            f"intervalli con potature o pioggia."
        )
    else:
        notes_parts.append("Dispersione contenuta, misura coerente.")

    return LysimeterCalibrationResult(
        kc_estimate=kc_estimate, n_intervals=n, n_discarded=n_discarded,
        confidence=confidence,
        interval_estimates=tuple(estimates),
        measured_et_mm=tuple(ets),
        notes=" ".join(notes_parts),
    )
