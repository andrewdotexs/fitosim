"""
Test per fitosim.domain.scheduler.

Le quattro famiglie di test coprono:
  1. Validazione di IrrigationEvent.
  2. Metodi di convenienza di IrrigationPlan.
  3. Algoritmo plan_irrigations sui casi canonici.
  4. Garanzia di purezza: lo scheduler NON modifica i vasi.

L'ultima famiglia è cruciale dal punto di vista architetturale. Il
pianificatore è progettato per essere stateless e puro: invocarlo non
deve avere alcun effetto collaterale visibile sull'inventario. Se un
domani questa proprietà venisse violata da una refactoring distratta,
l'intero sistema diventerebbe difficile da usare in modo sicuro.
"""

import unittest
from datetime import date, timedelta

from fitosim.domain.pot import Location, Pot
from fitosim.domain.scheduler import (
    IrrigationEvent,
    IrrigationPlan,
    IrrigationReason,
    plan_irrigations,
)
from fitosim.domain.species import BASIL, ROSEMARY, TOMATO
from fitosim.io.openmeteo import DailyWeather
from fitosim.science.substrate import (
    CACTUS_MIX,
    UNIVERSAL_POTTING_SOIL,
)


MILAN_LAT = 45.47


def _hot_dry_forecast(start: date, n_days: int) -> list[DailyWeather]:
    """
    Previsione di una settimana calda e secca a Milano. Ogni giorno
    ha T_min=20, T_max=32, niente pioggia. Volutamente uniforme così
    che i test siano riproducibili e facili da ragionare a mente.
    """
    return [
        DailyWeather(
            day=start + timedelta(days=i),
            t_min=20.0, t_max=32.0,
            precipitation_mm=0.0,
        )
        for i in range(n_days)
    ]


def _rainy_forecast(start: date, n_days: int) -> list[DailyWeather]:
    """
    Previsione bagnata: 15 mm di pioggia ogni giorno. Volume
    sufficiente a tenere praticamente qualunque vaso in capacità di
    campo per tutto il periodo.
    """
    return [
        DailyWeather(
            day=start + timedelta(days=i),
            t_min=18.0, t_max=24.0,
            precipitation_mm=15.0,
        )
        for i in range(n_days)
    ]


def _basil_pot_full(planting_date: date) -> Pot:
    """Vaso di basilico standard, appena irrigato (stato a FC)."""
    return Pot(
        label="basilico-test",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=4.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=planting_date,
    )


class TestIrrigationEventValidation(unittest.TestCase):
    """Verifica della dataclass IrrigationEvent."""

    def test_valid_event(self):
        e = IrrigationEvent(
            event_date=date(2025, 7, 15),
            pot_label="test",
            dose_liters=1.5,
            reason=IrrigationReason.PREDICTED_ALERT,
        )
        self.assertEqual(e.dose_liters, 1.5)
        self.assertEqual(e.reason, IrrigationReason.PREDICTED_ALERT)

    def test_zero_dose_rejected(self):
        # Un evento con dose zero non avrebbe senso operativo.
        with self.assertRaises(ValueError):
            IrrigationEvent(
                event_date=date(2025, 7, 15),
                pot_label="test",
                dose_liters=0.0,
                reason=IrrigationReason.PREDICTED_ALERT,
            )

    def test_negative_dose_rejected(self):
        with self.assertRaises(ValueError):
            IrrigationEvent(
                event_date=date(2025, 7, 15),
                pot_label="test",
                dose_liters=-0.5,
                reason=IrrigationReason.PREDICTED_ALERT,
            )

    def test_immutability(self):
        e = IrrigationEvent(
            event_date=date(2025, 7, 15),
            pot_label="test",
            dose_liters=1.0,
            reason=IrrigationReason.PREDICTED_ALERT,
        )
        with self.assertRaises(Exception):
            e.dose_liters = 2.0  # type: ignore[misc]


class TestIrrigationPlanHelpers(unittest.TestCase):
    """Verifica dei metodi di IrrigationPlan."""

    def setUp(self):
        d0 = date(2025, 7, 15)
        self.plan = IrrigationPlan(
            events=[
                IrrigationEvent(
                    event_date=d0,
                    pot_label="A", dose_liters=1.0,
                    reason=IrrigationReason.CURRENTLY_IN_ALERT,
                ),
                IrrigationEvent(
                    event_date=d0,
                    pot_label="B", dose_liters=2.0,
                    reason=IrrigationReason.CURRENTLY_IN_ALERT,
                ),
                IrrigationEvent(
                    event_date=d0 + timedelta(days=3),
                    pot_label="A", dose_liters=1.5,
                    reason=IrrigationReason.PREDICTED_ALERT,
                ),
            ],
            horizon_days=7,
            generated_at=d0,
        )

    def test_total_water_liters(self):
        self.assertAlmostEqual(self.plan.total_water_liters(), 4.5)

    def test_pots_with_events(self):
        self.assertEqual(self.plan.pots_with_events(), {"A", "B"})

    def test_events_for_specific_date(self):
        events_today = self.plan.events_for_date(date(2025, 7, 15))
        self.assertEqual(len(events_today), 2)
        events_day3 = self.plan.events_for_date(date(2025, 7, 18))
        self.assertEqual(len(events_day3), 1)
        self.assertEqual(events_day3[0].pot_label, "A")

    def test_events_for_date_with_no_events(self):
        events = self.plan.events_for_date(date(2025, 7, 20))
        self.assertEqual(events, [])

    def test_is_empty_false_with_events(self):
        self.assertFalse(self.plan.is_empty())

    def test_is_empty_true_without_events(self):
        empty = IrrigationPlan(
            events=[], horizon_days=7, generated_at=date(2025, 7, 15)
        )
        self.assertTrue(empty.is_empty())

    def test_events_for_pot_filters_correctly(self):
        # Il vaso "A" ha due eventi (oggi e tra tre giorni); "B" uno solo.
        events_a = self.plan.events_for_pot("A")
        events_b = self.plan.events_for_pot("B")
        self.assertEqual(len(events_a), 2)
        self.assertEqual(len(events_b), 1)
        # Tutti gli eventi restituiti devono effettivamente riguardare il vaso.
        for e in events_a:
            self.assertEqual(e.pot_label, "A")

    def test_events_for_pot_unknown_label_returns_empty(self):
        # Vaso non presente nel piano: lista vuota, niente eccezione.
        events = self.plan.events_for_pot("Z-non-esiste")
        self.assertEqual(events, [])

    def test_days_with_events_sorted_and_unique(self):
        # Due eventi cadono nello stesso giorno (A e B il 15/7), il
        # terzo è il 18/7. La lista distinta deve avere 2 elementi
        # ordinati cronologicamente.
        days = self.plan.days_with_events()
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0], date(2025, 7, 15))
        self.assertEqual(days[1], date(2025, 7, 18))

    def test_total_liters_on_date(self):
        # Il 15/7 abbiamo eventi A (1.0L) + B (2.0L) = 3.0L totali.
        liters_today = self.plan.total_liters_on_date(date(2025, 7, 15))
        self.assertAlmostEqual(liters_today, 3.0)
        # Il 18/7 c'è solo l'evento A (1.5L).
        liters_day3 = self.plan.total_liters_on_date(date(2025, 7, 18))
        self.assertAlmostEqual(liters_day3, 1.5)
        # Un giorno senza eventi deve dare 0.
        liters_quiet = self.plan.total_liters_on_date(date(2025, 7, 20))
        self.assertEqual(liters_quiet, 0.0)


class TestPlanIrrigationsScenarios(unittest.TestCase):
    """Scenari principali del pianificatore."""

    def test_empty_inventory_produces_empty_plan(self):
        plan = plan_irrigations(
            inventory=[],
            forecast=_hot_dry_forecast(date(2025, 7, 15), 7),
            latitude_deg=MILAN_LAT,
            today=date(2025, 7, 15),
        )
        self.assertTrue(plan.is_empty())

    def test_pot_currently_in_alert_scheduled_for_today(self):
        # Vaso a stato BEN sotto soglia di allerta (impostato a metà
        # tra PWP e alert): deve scattare un evento per oggi con motivo
        # CURRENTLY_IN_ALERT.
        today = date(2025, 7, 15)
        pot = _basil_pot_full(planting_date=today - timedelta(days=40))
        # Forziamo stato corrente in piena zona di stress.
        pot.state_mm = (pot.alert_mm + pot.pwp_mm) / 2

        plan = plan_irrigations(
            inventory=[pot],
            forecast=_hot_dry_forecast(today, 5),
            latitude_deg=MILAN_LAT,
            today=today,
        )

        # Dobbiamo trovare almeno un evento, e il primo deve essere
        # quello di "currently_in_alert" per oggi.
        self.assertGreaterEqual(len(plan.events), 1)
        first = plan.events[0]
        self.assertEqual(first.event_date, today)
        self.assertEqual(first.reason, IrrigationReason.CURRENTLY_IN_ALERT)
        self.assertEqual(first.pot_label, pot.label)
        self.assertGreater(first.dose_liters, 0.0)

    def test_pot_predicted_alert_in_dry_week(self):
        # Vaso al 100% di FC e una settimana calda+secca: si prevede
        # un evento PREDICTED_ALERT in un giorno futuro.
        today = date(2025, 7, 15)
        pot = _basil_pot_full(planting_date=today - timedelta(days=40))
        # Stato a FC esplicitamente.
        pot.state_mm = pot.fc_mm

        plan = plan_irrigations(
            inventory=[pot],
            forecast=_hot_dry_forecast(today, 7),
            latitude_deg=MILAN_LAT,
            today=today,
        )

        # Almeno un evento, di tipo predicted_alert, in un giorno
        # successivo a oggi.
        self.assertGreater(len(plan.events), 0)
        first_event = plan.events[0]
        self.assertEqual(first_event.reason, IrrigationReason.PREDICTED_ALERT)
        self.assertGreater(first_event.event_date, today)

    def test_pot_saved_by_rain_yields_no_events(self):
        # Vaso a FC e settimana piovosa: la pioggia mantiene il vaso
        # sopra soglia per tutto l'orizzonte → nessun evento.
        today = date(2025, 7, 15)
        pot = _basil_pot_full(planting_date=today - timedelta(days=40))
        pot.state_mm = pot.fc_mm

        plan = plan_irrigations(
            inventory=[pot],
            forecast=_rainy_forecast(today, 7),
            latitude_deg=MILAN_LAT,
            today=today,
        )

        self.assertTrue(plan.is_empty())

    def test_horizon_clipping(self):
        # Orizzonte richiesto maggiore della previsione disponibile:
        # deve essere clippato senza errori.
        today = date(2025, 7, 15)
        pot = _basil_pot_full(planting_date=today - timedelta(days=40))
        pot.state_mm = pot.fc_mm

        forecast = _hot_dry_forecast(today, 3)  # solo 3 giorni
        plan = plan_irrigations(
            inventory=[pot],
            forecast=forecast,
            latitude_deg=MILAN_LAT,
            today=today,
            horizon_days=14,  # chiediamo 14
        )
        self.assertEqual(plan.horizon_days, 3)  # clippato a 3

    def test_multiple_pots_yield_combined_plan(self):
        # Tre vasi, di cui uno (rosmarino in cactus mix piccolo) molto
        # esposto e uno (pomodoro in vaso grande) più resiliente.
        # Aspettativa: almeno il rosmarino richiede irrigazione, il
        # plan ha almeno un evento per quel vaso.
        today = date(2025, 7, 15)
        basil = _basil_pot_full(planting_date=today - timedelta(days=40))
        rosemary = Pot(
            label="rosmarino", species=ROSEMARY, substrate=CACTUS_MIX,
            pot_volume_l=2.5, pot_diameter_cm=14.0,
            location=Location.OUTDOOR,
            planting_date=today - timedelta(days=200),
        )
        tomato_big = Pot(
            label="pomodoro", species=TOMATO,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=20.0, pot_diameter_cm=35.0,
            location=Location.OUTDOOR,
            planting_date=today - timedelta(days=70),
        )

        plan = plan_irrigations(
            inventory=[basil, rosemary, tomato_big],
            forecast=_hot_dry_forecast(today, 7),
            latitude_deg=MILAN_LAT,
            today=today,
        )

        # Il pomodoro nel vaso grande, in 7 giorni di calura senza
        # pioggia, è probabile che richieda intervento — ma il punto
        # del test è solo verificare che il piano contenga eventi.
        self.assertGreater(len(plan.events), 0)
        # Il piano deve essere ordinato cronologicamente.
        for i in range(len(plan.events) - 1):
            self.assertLessEqual(
                plan.events[i].event_date,
                plan.events[i + 1].event_date,
            )


class TestPurityOfPlanner(unittest.TestCase):
    """
    Garanzia architetturale: il pianificatore NON modifica lo stato
    dei vasi che riceve in ingresso. Senza questa proprietà non
    sarebbe sicuro chiamarlo più volte sulla stessa istanza, né
    integrarlo in flussi paralleli.
    """

    def test_pot_state_unchanged_after_planning(self):
        today = date(2025, 7, 15)
        pot = _basil_pot_full(planting_date=today - timedelta(days=40))
        pot.state_mm = pot.fc_mm * 0.7  # arbitrario, lontano da bordi

        state_before = pot.state_mm
        plan_irrigations(
            inventory=[pot],
            forecast=_hot_dry_forecast(today, 5),
            latitude_deg=MILAN_LAT,
            today=today,
        )
        state_after = pot.state_mm

        # Se il pianificatore avesse modificato lo stato, lo
        # avremmo trovato cambiato dopo la chiamata.
        self.assertEqual(state_before, state_after)

    def test_repeated_planning_yields_identical_results(self):
        # Ripetere lo stesso piano due volte deve dare gli stessi
        # eventi: nessun "memoria" residua tra invocazioni.
        today = date(2025, 7, 15)
        pot = _basil_pot_full(planting_date=today - timedelta(days=40))
        pot.state_mm = pot.fc_mm
        forecast = _hot_dry_forecast(today, 7)

        plan1 = plan_irrigations(
            [pot], forecast, MILAN_LAT, today,
        )
        plan2 = plan_irrigations(
            [pot], forecast, MILAN_LAT, today,
        )

        self.assertEqual(len(plan1.events), len(plan2.events))
        for e1, e2 in zip(plan1.events, plan2.events):
            self.assertEqual(e1.event_date, e2.event_date)
            self.assertEqual(e1.pot_label, e2.pot_label)
            self.assertEqual(e1.reason, e2.reason)
            self.assertAlmostEqual(e1.dose_liters, e2.dose_liters, places=6)


if __name__ == "__main__":
    unittest.main()
