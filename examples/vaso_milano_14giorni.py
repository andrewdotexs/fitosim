"""
Esempio: simulazione a 14 giorni di un vaso a Milano, in doppia unità.

Questo esempio è la prima vera integrazione end-to-end del motore
scientifico di fitosim. Simula l'evoluzione dello stato idrico di un
vaso da 5 litri con terriccio universale nella seconda metà di luglio
a Milano, usando:
  - il modulo `radiation` per la geometria astronomica;
  - il modulo `et0` per l'evapotraspirazione di riferimento;
  - il modulo `substrate` per le proprietà idrauliche del terriccio;
  - il modulo `balance` per l'aggiornamento giornaliero dello stato.

Lo scopo pedagogico è duplice. Primo, dimostra che i quattro moduli si
compongono armoniosamente: ciascuno risponde a una domanda specifica e
i risultati si concatenano naturalmente. Secondo, esegue la stessa
simulazione *in parallelo* nelle due unità (θ e mm), mostrando che le
due rappresentazioni convergono sugli stessi eventi fisici. Se vedessi
divergenze significative tra le due colonne, sapresti che c'è un bug.

Ipotesi adottate
----------------
  - Localizzazione: Milano (45.47° N).
  - Periodo: 14 giorni a partire dal 15 luglio.
  - Meteo: temperature climatologiche tipiche di luglio a Milano, con
    piccole oscillazioni casuali deterministiche. Nessuna pioggia.
  - Vaso: 5 L, diametro 20 cm (area ≈ 0.0314 m²).
  - Substrato: terriccio universale (θ_FC=0.40, θ_PWP=0.15).
  - Stato iniziale: appena irrigato → θ = θ_FC.
  - Coltura: coefficiente Kc = 1.0 (trattiamo la pianta come prato di
    riferimento; il vero Kc per il basilico in estate sarebbe ≈ 1.10
    e accorcerebbe i tempi di allerta, ma lasciamo ai moduli di
    dominio — prossima fase — il compito di gestire specie reali).

Esegui con:
    python examples/vaso_milano_14giorni.py
"""

from datetime import date, timedelta

from fitosim.science.balance import (
    water_balance_step_mm,
    water_balance_step_theta,
)
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import (
    UNIVERSAL_POTTING_SOIL,
    circular_pot_surface_area_m2,
    mm_to_theta,
    pot_substrate_depth_mm,
    theta_to_mm,
)


# -----------------------------------------------------------------------
#  Parametri dello scenario
# -----------------------------------------------------------------------
LATITUDE_DEG = 45.47
START_DATE = date(2025, 7, 15)
N_DAYS = 14
POT_VOLUME_L = 5.0
POT_DIAMETER_CM = 20.0
SUBSTRATE = UNIVERSAL_POTTING_SOIL
KC = 1.0  # coefficiente colturale semplificato per questo esempio


# Temperature sintetiche per 14 giorni a Milano a metà luglio. Oscillano
# leggermente attorno a una climatologia tipica (T_min ~19°C, T_max ~31°C).
# Il pattern è deterministico così che l'esempio sia riproducibile, e
# include qualche giorno più fresco per mostrare come ET₀ fluttua.
DAILY_TEMPERATURES = [
    # (T_min, T_max) in °C, in ordine cronologico
    (19.0, 31.0),  # giorno 1
    (20.0, 32.0),
    (21.0, 33.0),
    (20.0, 31.0),
    (18.0, 28.0),  # onda fresca
    (17.0, 26.0),
    (18.0, 28.0),
    (20.0, 30.0),  # giorno 8
    (21.0, 32.0),
    (22.0, 33.0),
    (22.0, 34.0),
    (21.0, 32.0),
    (19.0, 29.0),
    (19.0, 28.0),  # giorno 14
]


def main() -> None:
    # -------------------------------------------------------------------
    #  Preparazione della geometria del vaso
    # -------------------------------------------------------------------
    surface_area = circular_pot_surface_area_m2(POT_DIAMETER_CM)
    depth_mm = pot_substrate_depth_mm(POT_VOLUME_L, surface_area)

    print("Simulazione bilancio idrico — Vaso a Milano, 14 giorni da "
          f"{START_DATE.isoformat()}")
    print(f"Vaso: {POT_VOLUME_L} L, diametro {POT_DIAMETER_CM} cm, "
          f"area {surface_area:.4f} m², profondità effettiva "
          f"{depth_mm:.1f} mm")
    print(f"Substrato: {SUBSTRATE.name} "
          f"(θ_FC={SUBSTRATE.theta_fc}, θ_PWP={SUBSTRATE.theta_pwp})")
    print(f"Coefficiente colturale Kc = {KC}")
    print()

    # -------------------------------------------------------------------
    #  Stato iniziale: appena irrigato, θ = θ_FC
    # -------------------------------------------------------------------
    state_theta = SUBSTRATE.theta_fc
    state_mm = theta_to_mm(state_theta, depth_mm)

    # Intestazione della tabella. Stampiamo l'evoluzione giorno per
    # giorno, con le due rappresentazioni affiancate per confronto
    # visivo immediato.
    header = (
        f"{'Giorno':>6} {'Data':>10} "
        f"{'T_min':>5} {'T_max':>5} "
        f"{'ET₀':>5} {'ET_c':>5} "
        f"{'θ':>6} {'mm':>6} "
        f"{'θ→mm':>6} {'Alert':>6}"
    )
    print(header)
    print("-" * len(header))

    for day_index in range(N_DAYS):
        current_date = START_DATE + timedelta(days=day_index)
        j = day_of_year(current_date)
        t_min, t_max = DAILY_TEMPERATURES[day_index]

        # ET₀ giornaliera via Hargreaves-Samani.
        et0_mm = et0_hargreaves_samani(
            t_min=t_min, t_max=t_max,
            latitude_deg=LATITUDE_DEG, j=j,
        )
        et_c_mm = KC * et0_mm
        et_c_theta = mm_to_theta(et_c_mm, depth_mm)

        # Aggiornamento del bilancio nelle due unità in parallelo.
        # Nota: nessuna pioggia in questo scenario → water_input = 0.
        result_theta = water_balance_step_theta(
            current_theta=state_theta,
            water_input_theta=0.0,
            et_c_theta=et_c_theta,
            substrate=SUBSTRATE,
        )
        result_mm = water_balance_step_mm(
            current_mm=state_mm,
            water_input_mm=0.0,
            et_c_mm=et_c_mm,
            substrate=SUBSTRATE,
            substrate_depth_mm=depth_mm,
        )

        # Per il confronto cross-unit nella tabella, convertiamo lo
        # stato θ in mm: la colonna "θ→mm" deve coincidere con "mm".
        theta_converted_to_mm = theta_to_mm(result_theta.new_state, depth_mm)
        alert_marker = "⚠️" if result_mm.under_alert else ""

        print(
            f"{day_index + 1:>6} {current_date.isoformat():>10} "
            f"{t_min:>5.1f} {t_max:>5.1f} "
            f"{et0_mm:>5.2f} {et_c_mm:>5.2f} "
            f"{result_theta.new_state:>6.3f} {result_mm.new_state:>6.1f} "
            f"{theta_converted_to_mm:>6.1f} {alert_marker:>6}"
        )

        # Aggiornamento dello stato per il ciclo successivo.
        state_theta = result_theta.new_state
        state_mm = result_mm.new_state

    print()
    print("Colonne:")
    print("  ET₀    = evapotraspirazione di riferimento in mm/giorno")
    print("  ET_c   = evapotraspirazione della coltura = Kc × ET₀, mm/giorno")
    print("  θ      = contenuto idrico volumetrico (adimensionale)")
    print("  mm     = colonna d'acqua nel substrato (stessa quantità "
          "in unità FAO)")
    print("  θ→mm   = θ convertito in mm: deve coincidere con 'mm'")
    print("  Alert  = ⚠️ se sotto soglia RAW, irrigazione raccomandata")


if __name__ == "__main__":
    main()
