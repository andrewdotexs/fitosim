"""
Pianificatore di irrigazione: dal motore descrittivo a quello prescrittivo.

Questo modulo è il "cervello agronomico" del livello `domain/`. Riceve
in ingresso un inventario di vasi e una previsione meteorologica, e
produce in uscita un piano di irrigazione: una lista di interventi
raccomandati con data, vaso e dose suggerita.

Algoritmo: forward planner per simulazione
------------------------------------------

La logica fondamentale è la "simulazione forward con interventi
incorporati". Per ciascun vaso:

  1. Si parte dallo stato corrente del vaso.
  2. Si simula giorno per giorno l'evoluzione dello stato applicando
     ET_c e pioggia previste, esattamente come farebbe il motore
     descrittivo del bilancio idrico — ma SENZA mutare lo stato reale
     del vaso (proiezione).
  3. Quando la simulazione produce un giorno in cui lo stato scende
     sotto la soglia di allerta, si programma un evento di irrigazione
     per quel giorno.
  4. Lo stato proiettato viene "riempito virtualmente" a capacità di
     campo, simulando l'effetto dell'evento programmato, e la
     simulazione continua.
  5. Si ripete fino al termine dell'orizzonte di pianificazione.

Questa semplice logica gestisce uniformemente sia i vasi già in stato
di allerta (per cui scatta un evento per la data odierna) sia i vasi
sani (per cui eventualmente scatta un evento futuro). Soprattutto, il
"rinvio per pioggia" emerge naturalmente: se la previsione include una
pioggia che riempie il vaso, il bilancio non scende sotto soglia e
nessun evento viene programmato — senza bisogno di euristiche manuali.

Caratteristiche di progetto
---------------------------

- **Stateless e puro**: lo scheduler non muta i vasi dell'inventario.
  Lo stato `state_mm` di ciascun Pot rimane invariato dopo la chiamata
  a `plan_irrigations`. Il piano è una raccomandazione, non un fatto.

- **Deterministico**: stesso inventario + stessa previsione → stesso
  piano. Nessuna sorgente di entropia, nessuna decisione casuale.

- **Componibile**: il piano restituito può essere ispezionato,
  filtrato per data, sommato in litri totali, o passato a un livello
  superiore (UI, sistema di notifiche) senza alcuna trasformazione.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from fitosim.domain.pot import Pot
from fitosim.domain.species import actual_et_c
from fitosim.io.openmeteo import DailyWeather
from fitosim.science.balance import water_balance_step_mm
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import mm_to_theta


class IrrigationReason(Enum):
    """
    Motivazione di un evento di irrigazione raccomandato.

    Distinguere il motivo è importante per due ragioni operative:
    primo, l'utente che riceve la raccomandazione può capire perché il
    sistema gli sta proponendo quell'intervento; secondo, eventuali
    livelli superiori (UI, notifiche) possono adattare l'urgenza
    visiva del messaggio.

    CURRENTLY_IN_ALERT
        Il vaso è già sotto la propria soglia di allerta al momento
        della pianificazione. È il caso più urgente: la pianta sta
        già subendo stress idrico anche se non lo si vede a occhio.

    PREDICTED_ALERT
        Il vaso scenderà sotto la soglia di allerta in un giorno
        futuro dell'orizzonte di pianificazione, sulla base della
        previsione meteorologica. È un'allerta anticipata, non
        ancora un'emergenza.
    """

    CURRENTLY_IN_ALERT = "currently_in_alert"
    PREDICTED_ALERT = "predicted_alert"


@dataclass(frozen=True)
class IrrigationEvent:
    """
    Singolo evento di irrigazione raccomandato dal pianificatore.

    Attributi
    ---------
    event_date : date
        Giorno suggerito per l'irrigazione.
    pot_label : str
        Etichetta identificativa del vaso (corrisponde a `Pot.label`).
    dose_liters : float
        Volume d'acqua raccomandato in litri, calcolato come
        l'acqua necessaria a riportare il vaso a capacità di campo
        partendo dallo stato proiettato per quel giorno.
    reason : IrrigationReason
        Motivo agronomico dell'evento (vedere `IrrigationReason`).

    Vincoli
    -------
    - dose_liters deve essere positivo: un evento con dose zero non
      avrebbe senso operativo (non c'è nulla da fare).
    """

    event_date: date
    pot_label: str
    dose_liters: float
    reason: IrrigationReason

    def __post_init__(self) -> None:
        if self.dose_liters <= 0:
            raise ValueError(
                f"IrrigationEvent per '{self.pot_label}' il "
                f"{self.event_date}: dose_liters deve essere positiva "
                f"(ricevuto {self.dose_liters})."
            )


@dataclass(frozen=True)
class IrrigationPlan:
    """
    Piano completo di irrigazione su un orizzonte temporale.

    Attributi
    ---------
    events : list[IrrigationEvent]
        Lista degli interventi raccomandati, ordinata per data
        crescente. Vasi diversi nello stesso giorno appaiono come
        eventi separati ma con la stessa `event_date`, e possono
        essere raggruppati visivamente come "sessione di irrigazione".
    horizon_days : int
        Numero di giorni di pianificazione coperti.
    generated_at : date
        Giorno di generazione del piano. Tipicamente coincide con il
        primo giorno della previsione meteorologica utilizzata.
    """

    events: list[IrrigationEvent]
    horizon_days: int
    generated_at: date

    def events_for_date(self, target: date) -> list[IrrigationEvent]:
        """Eventi raccomandati per una specifica data."""
        return [e for e in self.events if e.event_date == target]

    def events_for_pot(self, pot_label: str) -> list[IrrigationEvent]:
        """
        Tutti gli eventi raccomandati per uno specifico vaso, ordinati
        per data (l'ordine è preservato dall'ordinamento globale del
        piano).

        Utile per visualizzare la traiettoria di uno specifico vaso
        con markers nei suoi giorni di irrigazione.
        """
        return [e for e in self.events if e.pot_label == pot_label]

    def days_with_events(self) -> list[date]:
        """
        Date distinte in cui c'è almeno un evento, ordinate
        cronologicamente. Utile per disegnare un calendario
        condensato che mostri solo i "giorni operativi".
        """
        return sorted({e.event_date for e in self.events})

    def total_liters_on_date(self, target: date) -> float:
        """
        Litri totali da somministrare in una specifica data, sommando
        tutti gli eventi schedulati per quel giorno. È il numero che
        risponde alla domanda "che capacità di innaffiatoio mi serve
        oggi?".
        """
        return sum(e.dose_liters for e in self.events_for_date(target))

    def total_water_liters(self) -> float:
        """Volume totale di acqua del piano, in litri."""
        return sum(e.dose_liters for e in self.events)

    def pots_with_events(self) -> set[str]:
        """Insieme delle etichette dei vasi che richiedono almeno un intervento."""
        return {e.pot_label for e in self.events}

    def is_empty(self) -> bool:
        """True se il piano non contiene alcun evento (tutti i vasi
        attraversano l'orizzonte senza richiedere intervento)."""
        return not self.events


def plan_irrigations(
    inventory: list[Pot],
    forecast: list[DailyWeather],
    latitude_deg: float,
    today: date,
    *,
    horizon_days: int = -1,
) -> IrrigationPlan:
    """
    Genera un piano di irrigazione per un inventario di vasi su un
    orizzonte temporale specificato.

    Parametri
    ---------
    inventory : list[Pot]
        Vasi da pianificare. La funzione NON modifica il loro stato
        idrico — la simulazione interna lavora su variabili locali.
    forecast : list[DailyWeather]
        Previsione meteorologica giornaliera. Il primo elemento si
        riferisce a `today`, il secondo a `today + 1 giorno`, ecc.
    latitude_deg : float
        Latitudine del sito, necessaria per ricalcolare ET₀ con
        Hargreaves-Samani su ogni giorno della previsione.
    today : date
        Giorno di partenza della pianificazione. Gli eventi
        "CURRENTLY_IN_ALERT" hanno questa data.
    horizon_days : int, opzionale
        Numero di giorni da pianificare. Default: -1, che significa
        "usa tutta la lunghezza della previsione". Se specificato e
        maggiore della lunghezza della previsione, viene clippato.

    Ritorna
    -------
    IrrigationPlan
        Piano completo, eventi ordinati per data crescente.

    Algoritmo
    ---------
    Per ogni vaso si esegue una simulazione forward dello stato idrico
    proiettato, intercalata da eventi di irrigazione virtuali quando
    la simulazione attraversa la soglia di allerta. Vedi la docstring
    del modulo per la motivazione di questo design.
    """
    if horizon_days < 0 or horizon_days > len(forecast):
        horizon_days = len(forecast)

    events: list[IrrigationEvent] = []

    for pot in inventory:
        # Stato proiettato locale: NON tocchiamo pot.state_mm.
        # Il pianificatore deve essere puro, lo stato vero del vaso
        # rimane riservato al motore descrittivo.
        proj_state = pot.state_mm

        # Caso speciale: vaso GIÀ in allerta al tempo zero.
        # Lo trattiamo prima della simulazione meteo, schedulando
        # l'intervento per oggi e ripristinando lo stato a FC.
        if proj_state < pot.alert_mm:
            deficit_mm = pot.fc_mm - proj_state
            dose_liters = deficit_mm * pot.surface_area_m2
            events.append(IrrigationEvent(
                event_date=today,
                pot_label=pot.label,
                dose_liters=dose_liters,
                reason=IrrigationReason.CURRENTLY_IN_ALERT,
            ))
            proj_state = pot.fc_mm

        # Simulazione forward giorno per giorno.
        for i in range(horizon_days):
            weather = forecast[i]
            day = today + timedelta(days=i)

            # ET₀ calcolata col nostro Hargreaves-Samani sulla previsione.
            # Useremmo `weather.et0_mm` (Penman-Monteith di Open-Meteo)
            # se volessimo essere "fedeli alla fonte", ma manteniamo HS
            # per coerenza interna del motore — ricorda che HS ha
            # ~5% di bias medio rispetto a PM, già documentato nelle
            # validazioni precedenti.
            et0 = et0_hargreaves_samani(
                t_min=weather.t_min,
                t_max=weather.t_max,
                latitude_deg=latitude_deg,
                j=day_of_year(day),
            )

            # ET_c con Ks calcolato sullo stato proiettato (non quello
            # reale del vaso): la riduzione per stress dipende dalla
            # traiettoria che stiamo proiettando.
            theta_proj = mm_to_theta(proj_state, pot.substrate_depth_mm)
            et_c = actual_et_c(
                species=pot.species,
                stage=pot.current_stage(day),
                et_0=et0,
                current_theta=theta_proj,
                substrate=pot.substrate,
            )

            # Passo del bilancio idrico, con la pioggia prevista come
            # input idrico naturale.
            result = water_balance_step_mm(
                current_mm=proj_state,
                water_input_mm=weather.precipitation_mm,
                et_c_mm=et_c,
                substrate=pot.substrate,
                substrate_depth_mm=pot.substrate_depth_mm,
                depletion_fraction=pot.species.depletion_fraction,
            )

            if result.under_alert:
                # Lo stato proiettato è sceso sotto la soglia in questo
                # giorno: programmiamo l'irrigazione per `day`. La dose
                # è quella necessaria a riportare il vaso a FC partendo
                # dallo stato post-bilancio (che incorpora già pioggia
                # ed evapotraspirazione del giorno).
                deficit_mm = pot.fc_mm - result.new_state
                dose_liters = deficit_mm * pot.surface_area_m2
                events.append(IrrigationEvent(
                    event_date=day,
                    pot_label=pot.label,
                    dose_liters=dose_liters,
                    reason=IrrigationReason.PREDICTED_ALERT,
                ))
                # Lo stato proiettato dopo l'intervento virtuale si
                # riempie a FC: la simulazione continua da qui.
                proj_state = pot.fc_mm
            else:
                # Nessun intervento: aggiorniamo lo stato proiettato
                # all'esito del bilancio (che può comunque essere
                # variato per ET e pioggia).
                proj_state = result.new_state

    # Eventi ordinati cronologicamente, per stabilità del piano e
    # per facilità di lettura nel report.
    events.sort(key=lambda e: (e.event_date, e.pot_label))

    return IrrigationPlan(
        events=events,
        horizon_days=horizon_days,
        generated_at=today,
    )
