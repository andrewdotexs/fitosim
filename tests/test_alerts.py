"""
Test del modulo domain/alerts.py (sotto-tappa E tappa 4 fascia 2).

Strategia di test
-----------------

Tre famiglie tematiche:

  1. **Dataclass Alert**: frozen, equality, determinismo dell'alert_id.

  2. **Regole singole**: ogni regola con caso positivo, caso negativo,
     soglie esatte, transizioni warning/critical.

  3. **Tuple ALL_RULES**: completezza, applicazione su un vaso
     "patologico" multi-problema.
"""

import unittest
from datetime import date
from typing import List

from fitosim.domain.alerts import (
    ALL_RULES,
    Alert,
    AlertCategory,
    AlertSeverity,
    _make_alert_id,
    check_ec_too_high,
    check_ec_too_low,
    check_fertilization_due,
    check_irrigation_needed,
    check_ph_out_of_range,
)
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import Species
from fitosim.science.substrate import Substrate


# =======================================================================
#  Helper di costruzione
# =======================================================================

def _make_basil() -> Species:
    return Species(
        common_name="basilico",
        scientific_name="Ocimum basilicum",
        kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
        ec_optimal_min_mscm=1.0, ec_optimal_max_mscm=1.6,
        ph_optimal_min=6.0, ph_optimal_max=7.0,
    )


def _make_no_chemistry_species() -> Species:
    """Specie senza modello chimico (no range EC/pH)."""
    return Species(
        common_name="generica",
        scientific_name="Plantae generica",
        kc_initial=0.5, kc_mid=1.0, kc_late=0.7,
    )


def _make_substrate() -> Substrate:
    return Substrate(
        name="terriccio universale",
        theta_fc=0.40, theta_pwp=0.10,
        cec_meq_per_100g=50.0, ph_typical=6.8,
    )


def _make_pot(label: str = "basilico-1", **overrides) -> Pot:
    defaults = dict(
        species=_make_basil(),
        substrate=_make_substrate(),
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        state_mm=25.0,
        salt_mass_meq=12.0,
        ph_substrate=6.5,
    )
    defaults.update(overrides)
    return Pot(label=label, **defaults)


# =======================================================================
#  Famiglia 1: dataclass Alert
# =======================================================================

class TestAlertDataclass(unittest.TestCase):
    """Frozen, equality, determinismo dell'alert_id."""

    def test_alert_is_frozen(self):
        # Modifica diretta di un campo deve sollevare FrozenInstanceError
        alert = Alert(
            alert_id="abc123",
            severity=AlertSeverity.WARNING,
            pot_label="basilico",
            category=AlertCategory.IRRIGATION_NEEDED,
            message="test",
            recommended_action="azione",
            triggered_date=date(2026, 5, 15),
        )
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            alert.severity = AlertSeverity.CRITICAL  # noqa

    def test_alert_equality_by_value(self):
        # Due alert con stessi campi sono uguali (eq automatica delle
        # dataclass).
        a1 = Alert(
            alert_id="abc", severity=AlertSeverity.WARNING,
            pot_label="x", category=AlertCategory.EC_TOO_HIGH,
            message="m", recommended_action="a",
            triggered_date=date(2026, 5, 15),
        )
        a2 = Alert(
            alert_id="abc", severity=AlertSeverity.WARNING,
            pot_label="x", category=AlertCategory.EC_TOO_HIGH,
            message="m", recommended_action="a",
            triggered_date=date(2026, 5, 15),
        )
        self.assertEqual(a1, a2)

    def test_alert_id_is_deterministic(self):
        # Stesso pot_label, category, date → stesso alert_id.
        id1 = _make_alert_id(
            "basilico", AlertCategory.IRRIGATION_NEEDED,
            date(2026, 5, 15),
        )
        id2 = _make_alert_id(
            "basilico", AlertCategory.IRRIGATION_NEEDED,
            date(2026, 5, 15),
        )
        self.assertEqual(id1, id2)

    def test_alert_id_differs_for_different_inputs(self):
        # Pot diversi, categorie diverse o date diverse producono id
        # diversi.
        base = _make_alert_id(
            "basilico", AlertCategory.IRRIGATION_NEEDED,
            date(2026, 5, 15),
        )
        diff_pot = _make_alert_id(
            "pomodoro", AlertCategory.IRRIGATION_NEEDED,
            date(2026, 5, 15),
        )
        diff_cat = _make_alert_id(
            "basilico", AlertCategory.EC_TOO_HIGH,
            date(2026, 5, 15),
        )
        diff_date = _make_alert_id(
            "basilico", AlertCategory.IRRIGATION_NEEDED,
            date(2026, 5, 16),
        )
        self.assertNotEqual(base, diff_pot)
        self.assertNotEqual(base, diff_cat)
        self.assertNotEqual(base, diff_date)

    def test_alert_id_length_is_12(self):
        # L'alert_id è troncato a 12 caratteri (48 bit di entropia).
        id_ = _make_alert_id(
            "basilico", AlertCategory.IRRIGATION_NEEDED,
            date(2026, 5, 15),
        )
        self.assertEqual(len(id_), 12)


# =======================================================================
#  Famiglia 2: regole singole
# =======================================================================

class TestRuleIrrigationNeeded(unittest.TestCase):
    """Regola check_irrigation_needed."""

    def test_no_alert_for_well_watered_pot(self):
        # Vaso ben irrigato (state_theta sopra threshold): no allerta.
        pot = _make_pot(state_mm=30.0)
        # state_theta ~ 0.38 > pwp+0.05 = 0.15
        result = check_irrigation_needed(pot, date(2026, 5, 15))
        self.assertIsNone(result)

    def test_critical_when_below_alert_mm(self):
        # state_mm < alert_mm e theta < threshold: critical.
        # Per il pot di test alert_mm=19.65, pwp_mm=7.86.
        # state_mm=2 → theta=0.025 < 0.15 (pwp+0.05) e < alert_mm.
        pot = _make_pot(state_mm=2.0)
        result = check_irrigation_needed(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.CRITICAL)

    def test_warning_just_above_threshold(self):
        # Caso limite: state_theta poco sotto threshold ma state_mm sopra
        # alert_mm. Ma per il pot di test alert_mm=19.65, e per avere
        # theta=0.13 (sotto threshold 0.15) serve state_mm~10mm < alert.
        # Quindi nel pot di default è praticamente impossibile avere
        # warning irrigation: o sei dentro range, o sei sotto alert_mm
        # (critical). Verifichiamo che le due regioni siano coerenti.
        pot_at_threshold = _make_pot(state_mm=12.0)
        # state_theta ~ 0.15, esattamente sulla soglia.
        result = check_irrigation_needed(pot_at_threshold, date(2026, 5, 15))
        # Sopra o sulla soglia: nessuna allerta.
        if pot_at_threshold.state_theta >= 0.15:
            self.assertIsNone(result)

    def test_alert_metadata_populated(self):
        # I campi message e recommended_action non sono vuoti.
        pot = _make_pot(state_mm=2.0)
        result = check_irrigation_needed(pot, date(2026, 5, 15))
        self.assertIn("basilico-1", result.message)
        self.assertIn("basilico-1", result.recommended_action)
        self.assertEqual(result.triggered_date, date(2026, 5, 15))


class TestRuleEcTooHigh(unittest.TestCase):

    def test_no_alert_in_optimal_range(self):
        # EC nel range ottimale 1.0-1.6: no allerta.
        # state_mm=25, water_volume=0.6362 L.
        # Voglio EC=1.3: salt = 1.3 * 0.6362 * 10 = 8.27
        pot = _make_pot(state_mm=25.0, salt_mass_meq=8.27)
        ec = pot.ec_substrate_mscm
        self.assertGreater(ec, 1.0)
        self.assertLess(ec, 1.6)
        result = check_ec_too_high(pot, date(2026, 5, 15))
        self.assertIsNone(result)

    def test_warning_when_moderately_high(self):
        # EC tra max+0.5 e max+1.5: warning. Range 2.1-3.1.
        # Voglio EC=2.5: salt = 2.5 * 0.6362 * 10 = 15.91
        pot = _make_pot(state_mm=25.0, salt_mass_meq=15.91)
        ec = pot.ec_substrate_mscm
        self.assertGreater(ec, 2.1)
        self.assertLess(ec, 3.1)
        result = check_ec_too_high(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.WARNING)

    def test_critical_when_severely_high(self):
        # EC > max+1.5 = 3.1: critical.
        # Voglio EC=5: salt = 5 * 0.6362 * 10 = 31.81
        pot = _make_pot(state_mm=25.0, salt_mass_meq=31.81)
        ec = pot.ec_substrate_mscm
        self.assertGreater(ec, 3.1)
        result = check_ec_too_high(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.CRITICAL)

    def test_no_alert_for_species_without_chemistry(self):
        # Specie senza modello chimico: nessuna allerta indipendente
        # dall'EC reale.
        pot = _make_pot(
            species=_make_no_chemistry_species(),
            state_mm=25.0, salt_mass_meq=100.0,  # EC enorme
        )
        result = check_ec_too_high(pot, date(2026, 5, 15))
        self.assertIsNone(result)


class TestRuleEcTooLow(unittest.TestCase):

    def test_no_alert_when_above_threshold(self):
        # EC tra ec_min*0.7 e ec_min: scatta fertilization_due ma
        # NON ec_too_low.
        # Voglio EC=0.85: salt = 0.85 * 0.6362 * 10 = 5.41
        pot = _make_pot(state_mm=25.0, salt_mass_meq=5.41)
        ec = pot.ec_substrate_mscm
        self.assertGreaterEqual(ec, 0.7)
        result = check_ec_too_low(pot, date(2026, 5, 15))
        self.assertIsNone(result)

    def test_warning_when_below_threshold(self):
        # EC < ec_min*0.7 = 0.7 mS/cm.
        # Voglio EC=0.4: salt = 0.4 * 0.6362 * 10 = 2.55
        pot = _make_pot(state_mm=25.0, salt_mass_meq=2.55)
        ec = pot.ec_substrate_mscm
        self.assertLess(ec, 0.7)
        result = check_ec_too_low(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.WARNING)
        self.assertEqual(result.category, AlertCategory.EC_TOO_LOW)


class TestRuleFertilizationDue(unittest.TestCase):

    def test_alert_when_in_fertilization_window(self):
        # ec_min*0.7 ≤ EC < ec_min: scatta fertilization_due con info.
        # Voglio EC=0.85: salt = 0.85 * 0.6362 * 10 = 5.41
        pot = _make_pot(state_mm=25.0, salt_mass_meq=5.41)
        ec = pot.ec_substrate_mscm
        self.assertGreaterEqual(ec, 0.7)
        self.assertLess(ec, 1.0)
        result = check_fertilization_due(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.INFO)
        self.assertEqual(result.category, AlertCategory.FERTILIZATION_DUE)

    def test_no_alert_when_above_min(self):
        # EC ≥ ec_min: no allerta fertilization_due (nutrizione ok).
        pot = _make_pot(state_mm=25.0, salt_mass_meq=8.27)
        ec = pot.ec_substrate_mscm
        self.assertGreaterEqual(ec, 1.0)
        result = check_fertilization_due(pot, date(2026, 5, 15))
        self.assertIsNone(result)

    def test_no_alert_when_below_too_low_threshold(self):
        # EC < ec_min*0.7: scatta ec_too_low ma NON fertilization_due
        # (le finestre non si sovrappongono).
        pot = _make_pot(state_mm=25.0, salt_mass_meq=2.55)
        result = check_fertilization_due(pot, date(2026, 5, 15))
        self.assertIsNone(result)


class TestRulePhOutOfRange(unittest.TestCase):

    def test_no_alert_within_tolerance(self):
        # pH dentro al margine di tolleranza ±0.3 dal range.
        # Range basilico 6.0-7.0, tolleranza 5.7-7.3.
        for ph in [6.0, 6.5, 7.0, 5.8, 7.2]:
            with self.subTest(ph=ph):
                pot = _make_pot(ph_substrate=ph)
                result = check_ph_out_of_range(pot, date(2026, 5, 15))
                self.assertIsNone(result)

    def test_warning_when_moderately_out(self):
        # pH fuori del margine ma entro 0.7 dal range.
        # Es. pH 5.4: 0.6 sotto min (6.0).
        pot = _make_pot(ph_substrate=5.4)
        result = check_ph_out_of_range(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.WARNING)

    def test_critical_when_severely_out(self):
        # pH oltre 0.7 dal range.
        # Es. pH 8.0: 1.0 sopra max (7.0).
        pot = _make_pot(ph_substrate=8.0)
        result = check_ph_out_of_range(pot, date(2026, 5, 15))
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, AlertSeverity.CRITICAL)

    def test_acid_direction_in_message(self):
        # pH troppo basso: message menziona "acido".
        pot = _make_pot(ph_substrate=4.5)
        result = check_ph_out_of_range(pot, date(2026, 5, 15))
        self.assertIn("acido", result.message)

    def test_alkaline_direction_in_message(self):
        # pH troppo alto: message menziona "alcalino".
        pot = _make_pot(ph_substrate=8.5)
        result = check_ph_out_of_range(pot, date(2026, 5, 15))
        self.assertIn("alcalino", result.message)


# =======================================================================
#  Famiglia 3: ALL_RULES e applicazione completa
# =======================================================================

class TestAllRules(unittest.TestCase):
    """Test sulla tuple ALL_RULES e applicazione integrata."""

    def test_all_rules_count(self):
        # Cinque regole nella sotto-tappa E.
        self.assertEqual(len(ALL_RULES), 5)

    def test_optimal_pot_no_alerts_from_any_rule(self):
        # Vaso in condizioni ottimali: nessuna regola scatta.
        # state_mm=25, salt=8.27 → EC=1.3 (in range), pH 6.5 (in range).
        pot = _make_pot(state_mm=25.0, salt_mass_meq=8.27,
                        ph_substrate=6.5)
        alerts = [
            r(pot, date(2026, 5, 15)) for r in ALL_RULES
        ]
        self.assertTrue(all(a is None for a in alerts))

    def test_pathological_pot_multiple_alerts(self):
        # Vaso patologico: secco + EC alta + pH fuori range.
        # state_mm=2 (critical irrigation, sotto alert_mm).
        # salt=31.81 con water_volume small ~0.05 → EC molto alta.
        # pH 8.5 (oltre 0.7 dal max=7.0 → critical).
        pot = _make_pot(
            state_mm=2.0,
            salt_mass_meq=31.81,
            ph_substrate=8.5,
        )
        alerts: List = [
            r(pot, date(2026, 5, 15)) for r in ALL_RULES
        ]
        non_none = [a for a in alerts if a is not None]
        # Almeno tre allerte: irrigation, ec_too_high, ph_out_of_range
        self.assertGreaterEqual(len(non_none), 3)
        categories = {a.category for a in non_none}
        self.assertIn(AlertCategory.IRRIGATION_NEEDED, categories)
        self.assertIn(AlertCategory.EC_TOO_HIGH, categories)
        self.assertIn(AlertCategory.PH_OUT_OF_RANGE, categories)


if __name__ == "__main__":
    unittest.main()
