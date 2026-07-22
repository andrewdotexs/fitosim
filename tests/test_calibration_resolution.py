"""
Test per fitosim.science.calibration_resolution.

La precedenza non calcola una misura nuova: decide quale, tra evidenze
già formate, vince per un dato parametro. I test coprono i due assi
che la regola tiene separati — lo scope (specificità al vaso) e la
reliability (affidabilità della fonte) — e soprattutto il punto dove
un'implementazione ingenua sbaglierebbe senza accorgersene: un fattore
deve ancorarsi al prior, non al valore di catalogo migliorato da
un'altra fonte.

Copertura:

  1. Gli adapter dalle fonti concrete.
  2. Casi a fonte singola (assoluto di catalogo, assoluto di vaso,
     fattore di vaso).
  3. Composizione tra scope: catalogo + vaso, e l'ancoraggio del
     fattore al prior.
  4. Competizione dentro lo stesso scope: assoluto batte fattore,
     confidenza batte reliability, niente doppio conteggio.
  5. Gate di confidenza, divergenza di catalogo, spiegazione,
     filtro per parametro.
"""

import unittest

from fitosim.science.calibration_resolution import (
    DEFAULT_DIVERGENCE_TOLERANCE,
    PARAM_DEPLETION,
    PARAM_KC,
    CalibrationProposal,
    CalibrationScope,
    CalibrationSource,
    ProposalKind,
    proposal_from_behavioral_kc,
    proposal_from_dismissal,
    proposal_from_lysimeter,
    proposal_from_sensor_slope,
    resolve,
)


def _abs(value, *, scope, source, confidence="high", n=10, parameter=PARAM_KC):
    return CalibrationProposal(
        parameter=parameter, source=source, scope=scope,
        kind=ProposalKind.ABSOLUTE, value=value, confidence=confidence,
        n_observations=n,
    )


def _factor(value, *, scope, source, confidence="high", n=10):
    return CalibrationProposal(
        parameter=PARAM_KC, source=source, scope=scope,
        kind=ProposalKind.FACTOR, value=value, confidence=confidence,
        n_observations=n,
    )


def _lysimeter(value, *, scope=CalibrationScope.CATALOG, confidence="high"):
    return _abs(
        value, scope=scope, source=CalibrationSource.LYSIMETER,
        confidence=confidence,
    )


def _sensor(value, *, confidence="high"):
    return _abs(
        value, scope=CalibrationScope.POT,
        source=CalibrationSource.SENSOR_SLOPE, confidence=confidence,
    )


def _behavioral(value, *, confidence="high"):
    return _factor(
        value, scope=CalibrationScope.POT,
        source=CalibrationSource.BEHAVIORAL, confidence=confidence,
    )


# =======================================================================
#  1. Adapter
# =======================================================================

class _FakeLysimeter:
    def __init__(self, kc, conf="high", n=6):
        self.kc_estimate = kc
        self.confidence = conf
        self.n_intervals = n
        self.notes = "nota lisimetro"


class _FakeSensor:
    def __init__(self, kc, conf="high", n=5):
        self.kc_estimate = kc
        self.confidence = conf
        self.n_windows = n
        self.notes = "nota sensore"


class _FakeBehavioral:
    def __init__(self, factor, conf="high", n=12):
        self.kc_correction_factor = factor
        self.confidence = conf
        self.n_observations = n
        self.notes = "nota comportamentale"


class _FakeDismissal:
    def __init__(self, p, conf="high", healthy=4, stressed=3):
        self.depletion_fraction = p
        self.confidence = conf
        self.n_healthy = healthy
        self.n_stressed = stressed
        self.notes = "nota dismissal"


class TestAdapters(unittest.TestCase):

    def test_lysimeter_is_absolute_catalog_kc(self):
        p = proposal_from_lysimeter(_FakeLysimeter(0.90))
        self.assertEqual(p.parameter, PARAM_KC)
        self.assertEqual(p.source, CalibrationSource.LYSIMETER)
        self.assertEqual(p.scope, CalibrationScope.CATALOG)
        self.assertEqual(p.kind, ProposalKind.ABSOLUTE)
        self.assertAlmostEqual(p.value, 0.90)
        self.assertEqual(p.n_observations, 6)

    def test_sensor_slope_is_absolute_pot_kc(self):
        p = proposal_from_sensor_slope(_FakeSensor(1.15))
        self.assertEqual(p.scope, CalibrationScope.POT)
        self.assertEqual(p.kind, ProposalKind.ABSOLUTE)
        self.assertAlmostEqual(p.value, 1.15)

    def test_behavioral_is_a_factor_at_pot_scope(self):
        p = proposal_from_behavioral_kc(_FakeBehavioral(1.10))
        self.assertEqual(p.scope, CalibrationScope.POT)
        self.assertEqual(p.kind, ProposalKind.FACTOR)
        self.assertAlmostEqual(p.value, 1.10)

    def test_dismissal_is_absolute_depletion(self):
        p = proposal_from_dismissal(_FakeDismissal(0.55))
        self.assertEqual(p.parameter, PARAM_DEPLETION)
        self.assertEqual(p.kind, ProposalKind.ABSOLUTE)
        self.assertAlmostEqual(p.value, 0.55)
        self.assertEqual(p.n_observations, 7)

    def test_adapters_return_none_when_the_source_has_no_estimate(self):
        self.assertIsNone(proposal_from_lysimeter(_FakeLysimeter(None)))
        self.assertIsNone(proposal_from_sensor_slope(_FakeSensor(None)))
        self.assertIsNone(proposal_from_behavioral_kc(_FakeBehavioral(None)))
        self.assertIsNone(proposal_from_dismissal(_FakeDismissal(None)))


# =======================================================================
#  2. Fonte singola
# =======================================================================

class TestSingleSource(unittest.TestCase):

    def test_no_proposals_keeps_the_prior(self):
        r = resolve(PARAM_KC, 1.00, [])
        self.assertAlmostEqual(r.resolved_value, 1.00)
        self.assertAlmostEqual(r.catalog_value, 1.00)
        self.assertIsNone(r.decisive)
        self.assertIn("prior", r.explanation)

    def test_catalog_absolute_sets_both_pot_and_catalog(self):
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90)])
        self.assertAlmostEqual(r.resolved_value, 0.90)
        self.assertAlmostEqual(r.catalog_value, 0.90)
        self.assertEqual(r.decisive.source, CalibrationSource.LYSIMETER)

    def test_pot_absolute_leaves_catalog_at_prior(self):
        # Un sensore parla del vaso, non del gruppo: il catalogo che i
        # fratelli ereditano resta il prior.
        r = resolve(PARAM_KC, 1.00, [_sensor(1.15)])
        self.assertAlmostEqual(r.resolved_value, 1.15)
        self.assertAlmostEqual(r.catalog_value, 1.00)

    def test_pot_factor_scales_the_prior(self):
        r = resolve(PARAM_KC, 1.00, [_behavioral(1.10)])
        self.assertAlmostEqual(r.resolved_value, 1.10)
        self.assertAlmostEqual(r.catalog_value, 1.00)
        self.assertAlmostEqual(r.implied_factor, 1.10)


# =======================================================================
#  3. Composizione tra scope
# =======================================================================

class TestScopeComposition(unittest.TestCase):

    def test_pot_absolute_wins_over_catalog_for_the_pot(self):
        # Il caso principe: lisimetro 0.90 (catalogo), sensore 1.15
        # (vaso). Il vaso simula a 1.15, i fratelli ereditano 0.90.
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90), _sensor(1.15)])
        self.assertAlmostEqual(r.resolved_value, 1.15)
        self.assertAlmostEqual(r.catalog_value, 0.90)
        self.assertEqual(r.decisive.source, CalibrationSource.SENSOR_SLOPE)
        # Entrambe hanno contribuito, a scope diversi.
        self.assertEqual(len(r.applied), 2)

    def test_factor_anchors_to_the_prior_not_to_the_catalog(self):
        # IL test che conta. Lisimetro abbassa il catalogo a 0.90, il
        # comportamentale dice ×1.10. Ingenuamente: 0.90×1.10 = 0.99,
        # che trascina il vaso verso la media. Corretto: il fattore era
        # relativo al modello di allora (prior 1.00), quindi il vaso
        # vale 1.10, e il catalogo resta 0.90 a parte.
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90), _behavioral(1.10)])
        self.assertAlmostEqual(r.resolved_value, 1.10)
        self.assertNotAlmostEqual(r.resolved_value, 0.99)
        self.assertAlmostEqual(r.catalog_value, 0.90)

    def test_values_by_scope_carries_forward_empty_levels(self):
        # Nessuna proposta di cluster: il livello cluster riporta il
        # valore di catalogo, non salta.
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90), _sensor(1.15)])
        by_scope = dict(r.values_by_scope)
        self.assertAlmostEqual(by_scope[CalibrationScope.CATALOG], 0.90)
        self.assertAlmostEqual(by_scope[CalibrationScope.CLUSTER], 0.90)
        self.assertAlmostEqual(by_scope[CalibrationScope.POT], 1.15)


# =======================================================================
#  4. Competizione dentro lo stesso scope
# =======================================================================

class TestSameScopeCompetition(unittest.TestCase):

    def test_absolute_beats_factor_and_prevents_double_counting(self):
        # Sensore (assoluto) e comportamentale (fattore) sullo stesso
        # vaso, stessa confidenza: vince il sensore, e il fattore NON
        # viene applicato sopra (sarebbe 1.15×1.10).
        r = resolve(PARAM_KC, 1.00, [_sensor(1.15), _behavioral(1.10)])
        self.assertAlmostEqual(r.resolved_value, 1.15)
        self.assertEqual(r.decisive.source, CalibrationSource.SENSOR_SLOPE)
        ignored_sources = [p.source for p, _ in r.ignored]
        self.assertIn(CalibrationSource.BEHAVIORAL, ignored_sources)

    def test_confidence_beats_reliability_within_scope(self):
        # Sensore rumoroso (low, poche finestre) contro comportamentale
        # solido (high): non vogliamo che 3 finestre rumorose battano
        # un segnale robusto solo perché "assoluto". Vince la
        # confidenza, quindi il fattore.
        r = resolve(
            PARAM_KC, 1.00,
            [_sensor(1.40, confidence="low"), _behavioral(1.05, confidence="high")],
        )
        self.assertAlmostEqual(r.resolved_value, 1.05)
        self.assertEqual(r.decisive.source, CalibrationSource.BEHAVIORAL)

    def test_reliability_breaks_ties_at_equal_confidence(self):
        # Stessa confidenza: l'assoluto diretto (sensore) batte il
        # fattore inferito (comportamentale).
        r = resolve(
            PARAM_KC, 1.00,
            [_sensor(1.15, confidence="medium"),
             _behavioral(1.30, confidence="medium")],
        )
        self.assertEqual(r.decisive.source, CalibrationSource.SENSOR_SLOPE)
        self.assertAlmostEqual(r.resolved_value, 1.15)


# =======================================================================
#  5. Gate, divergenza, spiegazione, filtro
# =======================================================================

class TestGatesAndReporting(unittest.TestCase):

    def test_insufficient_confidence_is_dropped_and_recorded(self):
        r = resolve(
            PARAM_KC, 1.00,
            [_sensor(1.15, confidence="insufficient")],
        )
        self.assertAlmostEqual(r.resolved_value, 1.00)
        self.assertEqual(len(r.ignored), 1)
        self.assertIn("non sufficiente", r.ignored[0][1])

    def test_catalog_divergence_flagged_when_pot_departs_far(self):
        # Catalogo ad alta confidenza 0.90, vaso a 1.20: oltre il 15%.
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90), _sensor(1.20)])
        self.assertTrue(r.catalog_divergence)
        self.assertIn("outlier", r.explanation)

    def test_no_divergence_when_pot_is_close_to_catalog(self):
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90), _sensor(0.95)])
        self.assertFalse(r.catalog_divergence)

    def test_no_divergence_when_broader_source_is_not_high_confidence(self):
        # Un catalogo a media confidenza non fa scattare l'allarme: non
        # è abbastanza autorevole da mettere in dubbio il vaso.
        r = resolve(
            PARAM_KC, 1.00,
            [_lysimeter(0.90, confidence="medium"), _sensor(1.20)],
        )
        self.assertFalse(r.catalog_divergence)

    def test_explanation_mentions_the_winner_and_the_catalog(self):
        r = resolve(PARAM_KC, 1.00, [_lysimeter(0.90), _sensor(1.15)])
        self.assertIn("pendenza del sensore", r.explanation)
        self.assertIn("catalogo", r.explanation)

    def test_resolve_filters_by_parameter(self):
        # Una proposta di p non deve influenzare la risoluzione di Kc.
        p_proposal = _abs(
            0.55, scope=CalibrationScope.POT,
            source=CalibrationSource.DISMISSAL, parameter=PARAM_DEPLETION,
        )
        r = resolve(PARAM_KC, 1.00, [p_proposal, _sensor(1.15)])
        self.assertAlmostEqual(r.resolved_value, 1.15)
        self.assertEqual(len(r.applied), 1)

    def test_depletion_resolves_like_any_absolute(self):
        p_proposal = _abs(
            0.55, scope=CalibrationScope.POT,
            source=CalibrationSource.DISMISSAL, parameter=PARAM_DEPLETION,
        )
        r = resolve(PARAM_DEPLETION, 0.40, [p_proposal])
        self.assertAlmostEqual(r.resolved_value, 0.55)

    def test_factor_with_nonpositive_prior_is_an_error(self):
        with self.assertRaises(ValueError):
            resolve(PARAM_KC, 0.0, [_behavioral(1.10)])

    def test_nonfinite_prior_is_an_error(self):
        with self.assertRaises(ValueError):
            resolve(PARAM_KC, float("nan"), [])


if __name__ == "__main__":
    unittest.main()
