"""
Esempio: confronto idrico dei substrati del catalogo fitosim.

Produce una tabella che mostra, per un vaso standard da 5 litri, come i
cinque substrati del catalogo differiscano nelle grandezze idriche
operative: acqua a capacità di campo, acqua totale disponibile, acqua
facilmente disponibile (con frazione di deplezione di default p=0.5).

Questo è il primo esempio che permette di "vedere" quanto la scelta del
substrato impatta la quantità d'acqua effettivamente utile alla pianta
in un vaso di dimensioni fissate. I valori di RAW mostrati sono il
"serbatoio operativo" che il bilancio idrico (prossimo modulo) userà
per decidere quando triggerare un'irrigazione.

Esegui dalla radice del progetto con:
    python examples/substrate_comparison.py
"""

from fitosim.science.substrate import (
    ALL_SUBSTRATES,
    DEFAULT_DEPLETION_FRACTION,
    readily_available_water,
    total_available_water,
    water_volume_at_field_capacity,
    water_volume_available,
    water_volume_readily_available,
)


POT_VOLUME_L = 5.0  # Vaso di riferimento in litri: taglia molto comune.


def main() -> None:
    print(f"Confronto idrico dei substrati — vaso da {POT_VOLUME_L:.0f} L")
    print(f"Frazione di deplezione (p) = {DEFAULT_DEPLETION_FRACTION}")
    print()

    # Intestazione. I campi sono: nome, θ_FC, θ_PWP, TAW%, Vol a FC,
    # Vol. TAW, Vol. RAW. Tutti i volumi sono in litri; le frazioni
    # volumetriche sono adimensionali.
    header = (
        f"{'Substrato':<30} {'θ_FC':>6} {'θ_PWP':>6} {'TAW%':>6} "
        f"{'Vol.FC':>7} {'Vol.TAW':>8} {'Vol.RAW':>8}"
    )
    print(header)
    print("-" * len(header))

    for s in ALL_SUBSTRATES:
        taw = total_available_water(s)
        vol_fc = water_volume_at_field_capacity(s, POT_VOLUME_L)
        vol_taw = water_volume_available(s, POT_VOLUME_L)
        vol_raw = water_volume_readily_available(s, POT_VOLUME_L)
        print(
            f"{s.name:<30} {s.theta_fc:>6.2f} {s.theta_pwp:>6.2f} "
            f"{taw * 100:>5.1f}% {vol_fc:>6.2f}L {vol_taw:>7.2f}L "
            f"{vol_raw:>7.3f}L"
        )

    print()
    print("Legenda:")
    print("  Vol.FC  = acqua trattenuta a capacità di campo")
    print("  Vol.TAW = acqua totale disponibile alla pianta")
    print("  Vol.RAW = acqua facilmente disponibile "
          "(soglia di allerta irrigazione)")

    # Piccolo confronto "estremi": il rapporto tra il più ritentivo e il
    # più drenante. Serve a far uscire un numero memorabile sul "quanto"
    # cambia il serbatoio idrico a parità di vaso.
    peat_raw = water_volume_readily_available(ALL_SUBSTRATES[0], POT_VOLUME_L)
    cactus_raw = water_volume_readily_available(
        ALL_SUBSTRATES[-1], POT_VOLUME_L
    )
    ratio = peat_raw / cactus_raw
    print()
    print(
        f"Il substrato più ritentivo (torba) offre {ratio:.1f}x "
        f"più acqua operativa del più drenante (cactacee), "
        f"a parità di vaso."
    )


if __name__ == "__main__":
    main()
