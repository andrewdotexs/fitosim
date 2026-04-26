"""
Demo della stazione Ecowitt: snapshot + dashboard.

Scarica i dati in tempo reale dalla stazione Ecowitt dell'utente e
produce due output:

  1. Un report testuale strutturato che mostra outdoor, indoor (gateway
     base), WN31 CH1 (sensore indoor di precisione), pioggia, vento,
     pressione, e i sensori WH51 di umidità del substrato.

  2. Un grafico "dashboard" a quattro quadranti:
       - Outdoor: temperatura, umidità, dew point, vento, solare
       - Indoor microclimate: T e RH del WN31 CH1
       - Umidità del substrato: bar chart per canale, codificata per
         zona (rosso < 25%, arancione 25-40%, verde > 40%) — utile
         per identificare a colpo d'occhio quali vasi sono asciutti
       - Pioggia: cumuli a diverse scale temporali

Modalità di funzionamento
-------------------------
Il demo prova a leggere le credenziali dalle variabili d'ambiente
(`ECOWITT_APPLICATION_KEY`, `ECOWITT_API_KEY`, `ECOWITT_MAC`) e a
chiamare la stazione reale. Se le credenziali mancano o la rete non è
disponibile, ricade sul payload reale fornito dall'utente come fixture
di test, così che il demo sia sempre eseguibile.

Esegui con:
    # Con credenziali (uso reale):
    export ECOWITT_APPLICATION_KEY="..."
    export ECOWITT_API_KEY="..."
    export ECOWITT_MAC="88:13:BF:CB:5A:AF"
    python examples/ecowitt_dashboard.py

    # Senza credenziali (modalità offline con fixture):
    python examples/ecowitt_dashboard.py
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from fitosim.io.ecowitt import (
    EcowittObservation,
    credentials_from_env,
    fetch_real_time,
    parse_ecowitt_response,
)


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Path della fixture: il payload reale della stazione, riutilizzato
# anche nei test, è la nostra "rete di sicurezza" per le demo offline.
FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "tests" / "fixtures" / "ecowitt_real_sample.json"
)


# -----------------------------------------------------------------------
#  Acquisizione dati (con fallback a fixture)
# -----------------------------------------------------------------------

def acquire_observation() -> tuple[EcowittObservation, str]:
    """
    Restituisce (observation, source_label) dove source_label dichiara
    la provenienza dei dati per trasparenza nei grafici.
    """
    # Tentiamo prima il path reale: credenziali + rete.
    try:
        app_key, api_key, mac = credentials_from_env()
    except RuntimeError as exc:
        print(f"○ Credenziali Ecowitt non configurate: {exc}")
        print("   Demo eseguito con fixture del payload reale.\n")
        return _load_fixture(), "fixture (payload reale offline)"

    try:
        obs = fetch_real_time(
            application_key=app_key,
            api_key=api_key,
            mac=mac,
        )
        print(f"✓ Dati reali scaricati dalla stazione {mac}.\n")
        return obs, f"stazione live {mac}"
    except (OSError, ValueError) as exc:
        print(f"⚠️  Chiamata API Ecowitt fallita: {exc}")
        print("   Fallback alla fixture del payload reale.\n")
        return _load_fixture(), "fixture (fallback offline)"


def _load_fixture() -> EcowittObservation:
    """Carica e parse il payload reale catturato in fixture."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        return parse_ecowitt_response(json.load(fh))


# -----------------------------------------------------------------------
#  Report testuale
# -----------------------------------------------------------------------

def print_summary(obs: EcowittObservation, source: str) -> None:
    """Stampa una sintesi strutturata, in unità metriche."""
    print("=" * 70)
    print(f"Snapshot stazione Ecowitt — {obs.timestamp.isoformat()}")
    print(f"Fonte: {source}")
    print("=" * 70)

    print("\n☀️  OUTDOOR (stazione esterna)")
    if obs.outdoor_temp_c is not None:
        print(f"   Temperatura      {obs.outdoor_temp_c:>6.1f} °C")
    if obs.outdoor_humidity_pct is not None:
        print(f"   Umidità relativa {obs.outdoor_humidity_pct:>6.0f} %")
    if obs.outdoor_dew_point_c is not None:
        print(f"   Dew point        {obs.outdoor_dew_point_c:>6.1f} °C")
    if obs.solar_w_m2 is not None:
        print(f"   Radiazione       {obs.solar_w_m2:>6.1f} W/m²")
    if obs.uv_index is not None:
        print(f"   UV index         {obs.uv_index:>6.1f}")
    if obs.wind_speed_m_s is not None:
        print(f"   Vento            {obs.wind_speed_m_s:>6.2f} m/s "
              f"(raffica {obs.wind_gust_m_s:.2f} m/s)")
    if obs.pressure_relative_hpa is not None:
        print(f"   Pressione        {obs.pressure_relative_hpa:>6.1f} hPa")

    print("\n🏠 GATEWAY INDOOR")
    if obs.indoor_temp_c is not None:
        print(f"   Temperatura      {obs.indoor_temp_c:>6.1f} °C")
    if obs.indoor_humidity_pct is not None:
        print(f"   Umidità relativa {obs.indoor_humidity_pct:>6.0f} %")

    if obs.extra_temp_c:
        print("\n🌿 SENSORI WN31 (per piante indoor)")
        for ch in sorted(obs.extra_temp_c.keys()):
            t = obs.extra_temp_c[ch]
            h = obs.extra_humidity_pct.get(ch, None)
            h_str = f", umidità {h:.0f} %" if h is not None else ""
            print(f"   CH{ch}: temperatura {t:.1f} °C{h_str}")

    print("\n💧 PIOGGIA (cumuli)")
    if obs.rain_today_mm is not None:
        print(f"   Oggi             {obs.rain_today_mm:>6.2f} mm")
    if obs.rain_24h_mm is not None:
        print(f"   24 ore           {obs.rain_24h_mm:>6.2f} mm")
    if obs.rain_event_mm is not None:
        print(f"   Evento corrente  {obs.rain_event_mm:>6.2f} mm")

    if obs.soil_moisture_pct:
        print(f"\n🌱 UMIDITÀ SUBSTRATO ({len(obs.soil_moisture_pct)} sensori)")
        for ch in sorted(obs.soil_moisture_pct.keys()):
            m = obs.soil_moisture_pct[ch]
            # Marker visivo per colpo d'occhio.
            if m < 25:
                marker = "🔴 secco"
            elif m < 40:
                marker = "🟠 medio"
            else:
                marker = "🟢 umido"
            print(f"   CH{ch}: {m:>5.1f} %  {marker}")

    print("\n" + "=" * 70 + "\n")


# -----------------------------------------------------------------------
#  Dashboard plot — 4 quadranti
# -----------------------------------------------------------------------

def _draw_text_panel(
    ax,
    title: str,
    rows: list[tuple[str, str]],
    title_color: str = "tab:blue",
) -> None:
    """
    Disegna un pannello testuale "card" con titolo colorato e righe
    (etichetta, valore). È il blocco di base dei due quadranti
    superiori (outdoor e indoor).
    """
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Card di sfondo.
    box = FancyBboxPatch(
        (0.02, 0.02), 0.96, 0.96,
        boxstyle="round,pad=0.02,rounding_size=0.03",
        linewidth=1.2, edgecolor="lightgray",
        facecolor="white",
    )
    ax.add_patch(box)

    # Titolo.
    ax.text(0.5, 0.92, title, ha="center", va="center",
            fontsize=14, fontweight="bold", color=title_color)

    # Righe etichetta/valore. Le distribuiamo uniformemente
    # nello spazio rimanente.
    if not rows:
        ax.text(0.5, 0.5, "(nessun dato)", ha="center",
                va="center", fontsize=11, color="gray")
        return

    n = len(rows)
    top = 0.80
    bottom = 0.10
    spacing = (top - bottom) / max(1, n - 1) if n > 1 else 0
    for i, (label, value) in enumerate(rows):
        y = top - i * spacing if n > 1 else (top + bottom) / 2
        ax.text(0.10, y, label, ha="left", va="center",
                fontsize=11, color="dimgray")
        ax.text(0.92, y, value, ha="right", va="center",
                fontsize=12, fontweight="bold", color="black")


def _soil_color(moisture_pct: float) -> str:
    """Codifica colore tipo semaforo per l'umidità del substrato."""
    if moisture_pct < 25:
        return "tab:red"
    if moisture_pct < 40:
        return "tab:orange"
    return "tab:green"


def plot_dashboard(
    obs: EcowittObservation,
    source: str,
) -> Path:
    """Dashboard a 4 quadranti che riassume lo snapshot della stazione."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle(
        f"Stazione meteo Ecowitt — {obs.timestamp.strftime('%d/%m/%Y %H:%M UTC')}",
        fontsize=15, fontweight="bold", y=0.985,
    )

    # ---- Quadrante 1 (top-left): OUTDOOR ----
    outdoor_rows = []
    if obs.outdoor_temp_c is not None:
        outdoor_rows.append(("Temperatura",
                             f"{obs.outdoor_temp_c:.1f} °C"))
    if obs.outdoor_humidity_pct is not None:
        outdoor_rows.append(("Umidità relativa",
                             f"{obs.outdoor_humidity_pct:.0f} %"))
    if obs.outdoor_dew_point_c is not None:
        outdoor_rows.append(("Dew point",
                             f"{obs.outdoor_dew_point_c:.1f} °C"))
    if obs.wind_speed_m_s is not None:
        gust = (f" (raff. {obs.wind_gust_m_s:.1f})"
                if obs.wind_gust_m_s is not None else "")
        outdoor_rows.append(("Vento",
                             f"{obs.wind_speed_m_s:.1f} m/s{gust}"))
    if obs.solar_w_m2 is not None:
        outdoor_rows.append(("Radiazione solare",
                             f"{obs.solar_w_m2:.0f} W/m²"))
    if obs.pressure_relative_hpa is not None:
        outdoor_rows.append(("Pressione (rel.)",
                             f"{obs.pressure_relative_hpa:.1f} hPa"))
    _draw_text_panel(axes[0, 0], "Outdoor", outdoor_rows,
                     title_color="tab:blue")

    # ---- Quadrante 2 (top-right): INDOOR / WN31 ----
    indoor_rows = []
    # Preferiamo WN31 CH1 se presente — è il sensore "buono" per
    # le piante indoor — e mostriamo il gateway come secondario.
    if 1 in obs.extra_temp_c:
        indoor_rows.append(("WN31 CH1 — T",
                            f"{obs.extra_temp_c[1]:.1f} °C"))
    if 1 in obs.extra_humidity_pct:
        indoor_rows.append(("WN31 CH1 — RH",
                            f"{obs.extra_humidity_pct[1]:.0f} %"))
    if obs.indoor_temp_c is not None:
        indoor_rows.append(("Gateway — T",
                            f"{obs.indoor_temp_c:.1f} °C"))
    if obs.indoor_humidity_pct is not None:
        indoor_rows.append(("Gateway — RH",
                            f"{obs.indoor_humidity_pct:.0f} %"))
    _draw_text_panel(axes[0, 1], "Indoor", indoor_rows,
                     title_color="tab:purple")

    # ---- Quadrante 3 (bottom-left): SOIL MOISTURE ----
    ax_soil = axes[1, 0]
    if obs.soil_moisture_pct:
        channels = sorted(obs.soil_moisture_pct.keys())
        values = [obs.soil_moisture_pct[ch] for ch in channels]
        colors = [_soil_color(v) for v in values]
        labels = [f"CH{ch}" for ch in channels]

        bars = ax_soil.bar(
            labels, values, color=colors, alpha=0.85,
            edgecolor="black", linewidth=0.6,
        )
        # Etichetta numerica sopra ogni barra.
        for bar, v in zip(bars, values):
            ax_soil.text(
                bar.get_x() + bar.get_width() / 2,
                v + 1.5,
                f"{v:.0f}%",
                ha="center", fontsize=10, fontweight="bold",
            )
        # Linee orizzontali di riferimento per le soglie del semaforo.
        ax_soil.axhline(25, color="red", linestyle=":", alpha=0.5,
                        linewidth=1)
        ax_soil.axhline(40, color="orange", linestyle=":", alpha=0.5,
                        linewidth=1)
        ax_soil.set_ylim(0, 100)
        ax_soil.set_ylabel("Umidità substrato (%)")
        ax_soil.set_title(
            "Sensori WH51 — umidità del substrato per canale",
            fontsize=12, fontweight="bold", color="tab:green",
        )
        ax_soil.grid(True, alpha=0.3, axis="y")
        # Mini-legenda per le tre zone, in versione testuale per
        # compatibilità con qualunque font.
        ax_soil.text(
            0.02, 0.94,
            "Soglie:  rosso < 25% (secco)   |   "
            "arancio 25–40% (medio)   |   verde > 40% (umido)",
            transform=ax_soil.transAxes, fontsize=8.5,
            color="dimgray",
        )
    else:
        ax_soil.axis("off")
        ax_soil.text(0.5, 0.5, "Nessun sensore WH51 collegato",
                     ha="center", va="center",
                     fontsize=12, color="gray",
                     transform=ax_soil.transAxes)

    # ---- Quadrante 4 (bottom-right): RAINFALL ----
    ax_rain = axes[1, 1]
    rain_rows = []
    if obs.rain_event_mm is not None:
        rain_rows.append(("Evento", obs.rain_event_mm))
    if obs.rain_today_mm is not None:
        rain_rows.append(("Oggi", obs.rain_today_mm))
    if obs.rain_24h_mm is not None:
        rain_rows.append(("24 ore", obs.rain_24h_mm))

    if rain_rows:
        labels_r = [r[0] for r in rain_rows]
        values_r = [r[1] for r in rain_rows]
        bars_r = ax_rain.bar(
            labels_r, values_r, color="tab:cyan", alpha=0.8,
            edgecolor="black", linewidth=0.5,
        )
        # Etichetta sopra ogni barra (anche se zero, per chiarezza).
        for bar, v in zip(bars_r, values_r):
            ax_rain.text(
                bar.get_x() + bar.get_width() / 2,
                v + 0.05 + max(values_r) * 0.02,
                f"{v:.2f} mm",
                ha="center", fontsize=10, fontweight="bold",
            )
        ax_rain.set_ylabel("Pioggia (mm)")
        ax_rain.set_title(
            "Pioggia accumulata su finestre temporali",
            fontsize=12, fontweight="bold", color="tab:cyan",
        )
        ax_rain.grid(True, alpha=0.3, axis="y")
        # Margin verticale: se i valori sono tutti zero, fissiamo un
        # range minimo per non avere un grafico schiacciato.
        if max(values_r) == 0:
            ax_rain.set_ylim(0, 1)
        else:
            ax_rain.set_ylim(0, max(values_r) * 1.25)
    else:
        ax_rain.axis("off")

    # Footer con la fonte dei dati.
    fig.text(
        0.5, 0.005,
        f"Fonte: {source}",
        ha="center", fontsize=9, color="gray", style="italic",
    )

    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    path = OUTPUT_DIR / "ecowitt_dashboard.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------

def main() -> None:
    obs, source = acquire_observation()
    print_summary(obs, source)

    print("Generazione dashboard...")
    p = plot_dashboard(obs, source)
    print(f"  → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
