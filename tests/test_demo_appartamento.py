"""
Test della demo end-to-end dell'appartamento (sotto-tappa E tappa 5).

Diversamente dai test della libreria che validano il codice di prodotto,
questi test validano la DEMO STESSA: che giri pulita end-to-end, produca
i grafici attesi, i numeri finali siano in range plausibili, e il
round-trip persistenza funzioni correttamente.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path


# Path alla directory examples del progetto.
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
DEMO_SCRIPT = EXAMPLES_DIR / "tappa5_E_appartamento_demo.py"
PROJECT_ROOT = EXAMPLES_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"


def _run_demo_script() -> subprocess.CompletedProcess:
    """
    Esegue lo script di demo come subprocess. Importante: parte
    dall'ambiente di sistema esistente (os.environ.copy) e ci aggiunge
    solo PYTHONPATH e MPLBACKEND. NON sostituisce l'ambiente, perché
    su Windows questo butterebbe via SYSTEMROOT, TEMP, e altre
    variabili che le DLL di Python e matplotlib si aspettano.

    Per portabilità Linux/Windows usiamo MPLBACKEND=Agg, in modo che
    matplotlib non tenti di aprire una finestra grafica nei contesti
    di test (CI, pytest senza display).
    """
    env = os.environ.copy()
    # Aggiungiamo src/ in testa al PYTHONPATH, preservando eventuali
    # path esistenti. os.pathsep è ":" su Linux e ";" su Windows.
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = str(SRC_DIR)
    # Backend non interattivo per matplotlib.
    env["MPLBACKEND"] = "Agg"
    # Forziamo UTF-8 sullo stdout/stderr del subprocess Python.
    # Su Windows il default e' cp1252 che non supporta caratteri come
    # delta greco o segni di spunta. Senza questo, lo script potrebbe
    # esplodere con UnicodeEncodeError appena prova a stampare un
    # carattere fuori dal range ASCII.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    return subprocess.run(
        [sys.executable, str(DEMO_SCRIPT)],
        capture_output=True, text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )


class TestDemoAppartamentoExecution(unittest.TestCase):
    """
    Test end-to-end dell'esecuzione dello script di demo. Lo script
    deve girare pulito e produrre i quattro grafici attesi.
    """

    def test_script_runs_end_to_end_without_errors(self):
        result = _run_demo_script()
        self.assertEqual(
            result.returncode, 0,
            msg=f"Demo fallita.\n"
                f"STDOUT (ultimi 500 char): {result.stdout[-500:]}\n"
                f"STDERR (ultimi 500 char): {result.stderr[-500:]}",
        )

    def test_script_produces_expected_png_files(self):
        result = _run_demo_script()
        self.assertEqual(
            result.returncode, 0,
            msg=f"Demo fallita prima di produrre i PNG.\n"
                f"STDERR: {result.stderr[-500:]}",
        )

        expected_pngs = [
            "tappa5_E_andamento_idrico.png",
            "tappa5_E_metodi_et.png",
            "tappa5_E_bilancio_per_ambiente.png",
            "tappa5_E_heatmap_et.png",
        ]
        for png_name in expected_pngs:
            png_path = EXAMPLES_DIR / png_name
            with self.subTest(png=png_name):
                self.assertTrue(
                    png_path.exists(),
                    msg=f"PNG atteso non trovato: {png_path}",
                )
                self.assertGreater(
                    png_path.stat().st_size, 1000,
                    msg=f"PNG sospetto vuoto: {png_path}",
                )

    def test_script_output_contains_expected_sections(self):
        result = _run_demo_script()
        self.assertEqual(
            result.returncode, 0,
            msg=f"Demo fallita.\nSTDERR: {result.stderr[-500:]}",
        )

        sezioni_attese = [
            "Parte 1: setup",
            "Parte 2: simulazione",
            "Parte 3: irrigazioni",
            "Parte 4: analisi diagnostica",
            "Parte 5: persistenza",
            "Parte 6: conclusioni",
        ]
        for sezione in sezioni_attese:
            with self.subTest(sezione=sezione):
                self.assertIn(sezione, result.stdout)

    def test_script_demonstrates_method_selection(self):
        result = _run_demo_script()
        self.assertEqual(
            result.returncode, 0,
            msg=f"Demo fallita.\nSTDERR: {result.stderr[-500:]}",
        )
        self.assertIn("hargreaves_samani", result.stdout)
        self.assertIn("penman_monteith_physical", result.stdout)

    def test_script_demonstrates_persistence_round_trip(self):
        result = _run_demo_script()
        self.assertEqual(
            result.returncode, 0,
            msg=f"Demo fallita.\nSTDERR: {result.stderr[-500:]}",
        )
        self.assertIn("Tutti gli stati dei vasi preservati", result.stdout)


class TestDemoAdHocSpecies(unittest.TestCase):
    """
    Test delle due specie ad-hoc costruite dalla demo (orchidea e
    sansevieria), che illustrano la differenziazione fisiologica
    estendendo il catalogo della libreria.
    """

    def test_orchid_and_sansevieria_have_distinct_physiology(self):
        from fitosim.domain.species import BASIL, ROSEMARY
        self.assertEqual(BASIL.stomatal_resistance_s_m, 100.0)
        self.assertEqual(ROSEMARY.stomatal_resistance_s_m, 200.0)


if __name__ == "__main__":
    unittest.main()
