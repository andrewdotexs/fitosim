"""
Il giorno fatto di blocchi (A7, 2026-09-29).

Il giorno resta l'unità della contabilità del modello — stadio
fenologico e Kc, gradi-giorno, cancello del freddo sui nutrienti,
istantanea di fine giornata, taratura di Kc dai cali giornalieri — e
dentro il giorno il vaso avanza a blocchi [h, h+Δt): un'ora con i
sensori, una o tre ore con la previsione. In ogni blocco il secchio
riceve l'ET₀ *di quel blocco*, l'acqua entrata *in quel blocco*, e
valuta Ks sullo stato del momento. Il cammino giornaliero
(`Pot.apply_balance_step`) è il caso di un solo blocco di 24 ore, e
lo resta: i due danno gli stessi numeri per costruzione.

Questo modulo tiene i tipi del passo a blocchi e il calcolo dell'ET₀
per blocco; i metodi che li usano stanno sul `Pot`
(`apply_balance_blocks`, `apply_step_blocks`, `apply_blocks_from_weather`).

Le decisioni prese il 29 settembre 2026, con la loro ragione:

  D1  Kc costante dentro il giorno: ET_c,b = Kc · ET₀,b. FAO-56 (cap.
      5–6) definisce Kc come rapporto mediato nel tempo, tabulato per
      stadi; un Kc orario non esiste nella pubblicazione. È la pratica
      delle applicazioni orarie di ASCE-EWRI. Il totale del giorno non
      cambia, se non per Ks.
  D2  Ks sullo stato del blocco (eq. 84 è una funzione di θ): il vaso
      è più secco alle 17 che alla media del giorno. Misurato: −1.4 %
      di ET_c a settimana, solo sotto la soglia.
  D3  D_e (dual-Kc) aggiornata a ogni blocco: lo stesso secchio di
      FAO-56 cap. 7, integrato più fine. Misurato indistinguibile dal
      passo giornaliero.
  D4  Il tasso capillare del sottovaso è «per giorno»: su un blocco di
      Δt ore diventa 1 − (1 − r)^(Δt/24). Applicare 0.4 a ogni ora
      svuoterebbe il piattino in due giorni invece di quattro.
  D5  Cancello del freddo sulla temperatura media del giorno e
      assorbimento sulla traspirazione del giorno: fisiologia, non
      meteo dell'ora.
  D6  Forma oraria FAO-56 eq. 53 (r_s 70 s/m), non ASCE-EWRI 2005
      (50/200): coerenza con la eq. 6 del cammino giornaliero. Misurato
      +1.9 % a settimana per ASCE.
  D7  I blocchi notturni con ET₀ negativa (rugiada) valgono zero: per
      il vaso non è acqua che entra nel substrato. Vale 0.5–0.6 mm a
      settimana, il 3 %. FAO-56 non lo prescrive: è una convenzione
      nostra, e sta qui.
  D8  Di notte G = 0.5 R_n (eq. 46) e R_s/R_so è quello del blocco che
      contiene l'istante (tramonto − 2.5 h), tenuto fino al giorno
      dopo, limitato a [0.3, 1] (FAO-56 cap. 4).
  D9  L'allerta ha un'ora: la fine del primo blocco sotto la soglia.
      La politica di notifica resta di chi usa la libreria.

Quando ai blocchi mancano umidità, vento o radiazione, Penman-Monteith
a blocchi non si può fare e Hargreaves-Samani non ha una forma oraria:
l'ET₀ del giorno (dal selettore di `science/et0.py`) viene ripartita
sui blocchi in proporzione alla R_a di ciascuno — il profilo del sole,
zero di notte. Non è un'ET₀ nuova: la somma è quella del giorno.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import TYPE_CHECKING

from fitosim.domain.weather import (
    WeatherBlock,
    validate_day_blocks,
    weather_day_from_blocks,
)
from fitosim.science.balance import BalanceStepResult
from fitosim.science.et0 import (
    EtMethod,
    actual_vapor_pressure,
    compute_et,
    compute_et0_penman_monteith,
    compute_et_penman_monteith_physical,
    distribute_daily_et0,
    soil_heat_flux_interval,
)
from fitosim.science.nutrients import NutrientAmounts
from fitosim.science.radiation import (
    RS_RSO_MIN_SUBDAILY,
    clear_sky_radiation,
    day_of_year,
    daylight_fraction,
    extraterrestrial_radiation,
    extraterrestrial_radiation_interval,
    net_radiation,
    net_radiation_interval,
    sunrise_sunset_hours,
)

if TYPE_CHECKING:  # solo per le annotazioni: pot.py importa questo modulo
    from fitosim.domain.pot import FertigationResult, NutrientStepResult

# Un blocco è «diurno» se il sole è sopra l'orizzonte per almeno metà
# della sua durata: decide G (eq. 45–46) e da dove viene R_s/R_so.
DAYTIME_MIN_FRACTION = 0.5

# Il rapporto R_s/R_so della notte è quello del blocco che contiene
# l'istante (tramonto − PRE_SUNSET_HOURS): «2–3 ore prima del
# tramonto», FAO-56 cap. 4.
PRE_SUNSET_HOURS = 2.5

# Sopra questa durata un blocco non è più «sub-giornaliero»: la forma
# oraria di FAO-56 (T alla quarta del blocco, G di giorno/notte) perde
# senso, e c'è il cammino giornaliero.
MAX_BLOCK_HOURS_FOR_ET0 = 12


# ---------------------------------------------------------------------
#  I tipi del passo a blocchi
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class BalanceBlock:
    """
    L'ingresso di un blocco al bilancio del vaso: la sua ET₀ (già
    azzerata sotto zero, D7) e l'acqua entrata come semplice input in
    mm (pioggia efficace o irrigazione senza chimica). Le irrigazioni
    con EC e pH passano da `BlockFertigation`, la pioggia da
    `Pot.apply_step_blocks(rainfall_l_by_hour=...)`.

    `start_hour` e `hours` sono in ore intere di tempo civile standard;
    i blocchi di un giorno devono coprirlo tutto, contigui, da 0 a 24
    (`validate_block_tiling`).
    """

    start_hour: int
    hours: int
    et_0_mm: float
    water_input_mm: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.start_hour < 24:
            raise ValueError(f"start_hour ({self.start_hour}) deve stare in [0, 24).")
        if self.hours < 1 or self.start_hour + self.hours > 24:
            raise ValueError(
                f"Il blocco [{self.start_hour}, {self.start_hour + self.hours}) "
                f"deve durare almeno un'ora e finire entro le 24."
            )
        if self.et_0_mm < 0:
            raise ValueError(
                f"et_0_mm ({self.et_0_mm}) deve essere ≥ 0: i blocchi notturni "
                f"negativi vanno azzerati prima (D7)."
            )
        if self.water_input_mm < 0:
            raise ValueError(f"water_input_mm ({self.water_input_mm}) deve essere ≥ 0.")

    @property
    def end_hour(self) -> int:
        return self.start_hour + self.hours


def validate_block_tiling(blocks: Sequence[BalanceBlock]) -> None:
    """I blocchi coprono il giorno intero, contigui, da 0 a 24: altrimenti ValueError."""
    if not blocks:
        raise ValueError("Il giorno a blocchi ha bisogno di almeno un blocco.")
    if blocks[0].start_hour != 0:
        raise ValueError(f"Il primo blocco deve iniziare a 0, non a {blocks[0].start_hour}.")
    for prev, nxt in pairwise(blocks):
        if nxt.start_hour != prev.end_hour:
            raise ValueError(
                f"Buco o sovrapposizione fra i blocchi: [{prev.start_hour}, "
                f"{prev.end_hour}) e [{nxt.start_hour}, {nxt.end_hour})."
            )
    if blocks[-1].end_hour != 24:
        raise ValueError(f"L'ultimo blocco deve finire a 24, non a {blocks[-1].end_hour}.")


@dataclass(frozen=True)
class BlockFertigation:
    """Un'irrigazione (o fertirrigazione) all'ora in cui è stata data."""

    start_hour: int
    volume_l: float
    ec_mscm: float = 0.0
    ph: float = 7.0
    nutrients_mg_per_l: NutrientAmounts | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.start_hour < 24:
            raise ValueError(f"start_hour ({self.start_hour}) deve stare in [0, 24).")
        if self.volume_l <= 0:
            raise ValueError(f"volume_l ({self.volume_l}) deve essere positivo.")


@dataclass(frozen=True)
class BlockTrace:
    """Che cosa è successo al vaso in un blocco: la traccia per le curve."""

    start_hour: int
    hours: int
    et_0_mm: float
    water_input_mm: float
    et_c_mm: float
    soil_evaporation_mm: float
    drainage_mm: float
    state_after_mm: float
    under_alert: bool
    # Lo stato del sottovaso dopo il blocco, se il vaso ne ha uno.
    saucer_state_after_mm: float | None = None

    @property
    def end_hour(self) -> int:
        return self.start_hour + self.hours


@dataclass(frozen=True)
class BlocksStepResult:
    """
    L'esito di un giorno a blocchi: la traccia blocco per blocco, il
    bilancio del giorno nella stessa forma del passo giornaliero, i
    totali, e l'ora dell'allerta (D9) — la fine del primo blocco in cui
    l'acqua è scesa sotto la soglia, 0 se il giorno è cominciato già
    sotto; None se non è successo.
    """

    event_date: date
    blocks: tuple[BlockTrace, ...]
    balance_result: BalanceStepResult
    et_c_mm: float
    soil_evaporation_mm: float
    transpiration_mm: float
    alert_hour: int | None
    nutrient_result: NutrientStepResult | None = None


@dataclass(frozen=True)
class FullBlocksStepResult:
    """
    Il fratello a blocchi di `FullStepResult`: il bilancio a blocchi più
    gli eventi applicati alla loro ora — possono essere più d'uno al
    giorno —, il metodo con cui è stata calcolata l'ET₀ quando viene
    dal meteo, e il rapporto R_s/R_so pre-tramonto da passare alla notte
    del giorno dopo.
    """

    event_date: date
    blocks_result: BlocksStepResult
    rainfall_results: tuple[FertigationResult, ...] = ()
    fertigation_results: tuple[FertigationResult, ...] = ()
    et_method: EtMethod | None = None
    rs_rso_pre_sunset: float | None = None

    @property
    def nutrient_result(self) -> NutrientStepResult | None:
        return self.blocks_result.nutrient_result


# ---------------------------------------------------------------------
#  L'ET₀ per blocco
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class BlockEt0:
    """
    L'evapotraspirazione di un blocco meteo, con i suoi ingredienti.

    `et_mm` è quella da dare al secchio: azzerata sotto zero (D7). È
    ET₀ (Hargreaves, Penman-Monteith standard) oppure ET della specie
    (Penman-Monteith fisico): lo dice il metodo che `et0_for_blocks`
    restituisce accanto, e il `Pot` la riporta a ET₀ equivalente come
    nel cammino giornaliero. `et_raw_mm` è il valore come esce dalla
    formula, negativo nelle notti umide.
    """

    start_hour: int
    hours: int
    et_mm: float
    et_raw_mm: float
    ra_mj: float
    rn_mj: float | None
    g_mj: float | None
    daytime: bool
    rs_rso: float | None


def _rs_rso(block: WeatherBlock, ra_mj: float, elevation_m: float) -> float | None:
    """R_s/R_so del blocco, limitato a [0.3, 1]; None se non c'è cielo sereno (notte)."""
    rso = clear_sky_radiation(ra_mj, elevation_m)
    if rso <= 0.0 or block.solar_radiation_mj_m2 is None:
        return None
    return min(max(block.solar_radiation_mj_m2 / rso, RS_RSO_MIN_SUBDAILY), 1.0)


def et0_for_blocks(
    blocks: Sequence[WeatherBlock],
    *,
    latitude_deg: float,
    longitude_deg: float,
    utc_offset_hours: float,
    elevation_m: float,
    wind_factor: float = 1.0,
    stomatal_resistance_s_m: float | None = None,
    crop_height_m: float | None = None,
    rs_rso_night_previous: float | None = None,
) -> tuple[list[BlockEt0], EtMethod, float | None]:
    """
    L'evapotraspirazione di ogni blocco di un giorno, il metodo usato,
    e il rapporto R_s/R_so pre-tramonto da passare al giorno dopo.

    Con umidità, vento e radiazione in tutti i blocchi: Penman-Monteith
    per blocco — la forma oraria di FAO-56 (eq. 53), cioè
    `compute_et0_penman_monteith(..., hours=Δt)`, con R_a del blocco
    (eq. 28), R_n del blocco (cap. 4), G di giorno e di notte (eq.
    45–46) e la regola del rapporto notturno (D8). Se la specie ha
    resistenza stomatica e altezza, la versione fisica: allora è ET,
    non ET₀, e il metodo restituito lo dice. La stessa gerarchia del
    selettore `compute_et`.

    Con qualche dato mancante: l'ET₀ del giorno dal selettore (Penman-
    Monteith giornaliera se il giorno aggregato è completo, altrimenti
    Hargreaves-Samani), ripartita sui blocchi in proporzione alla R_a
    di ciascuno.

    Parametri
    ---------
    blocks : Sequence[WeatherBlock]
        I blocchi di un giorno, contigui da 0 a 24, nessuno più lungo di
        12 ore.
    latitude_deg, longitude_deg, elevation_m : float
        Il sito. La longitudine è positiva a est.
    utc_offset_hours : float
        Il fuso orario standard del sito (1 per l'Italia), senza ora
        legale: le ore dei blocchi sono in quel tempo.
    wind_factor : float
        Il fattore di riparo del vaso (`shelter_wind_factor`) da
        applicare al vento prima di Penman-Monteith.
    stomatal_resistance_s_m, crop_height_m : float, opzionali
        I parametri della specie per la versione fisica; con uno solo
        dei due, o nessuno, si usa la standard.
    rs_rso_night_previous : float, opzionale
        Il rapporto pre-tramonto del giorno prima, per i blocchi
        notturni che precedono il pre-tramonto di oggi. Senza, si usa
        quello di oggi anche per loro.
    """
    validate_day_blocks(blocks)
    if any(b.hours > MAX_BLOCK_HOURS_FOR_ET0 for b in blocks):
        raise ValueError(
            f"I blocchi per l'ET₀ non possono durare più di "
            f"{MAX_BLOCK_HOURS_FOR_ET0} ore: per il giorno intero c'è il "
            f"cammino giornaliero."
        )
    j = day_of_year(blocks[0].date_)
    ra_blocks = [
        extraterrestrial_radiation_interval(
            latitude_deg, longitude_deg, j, b.start_hour, b.end_hour, utc_offset_hours,
        )
        for b in blocks
    ]

    if not all(b.has_full_weather for b in blocks):
        return _distributed_daily_et0(
            blocks, ra_blocks, latitude_deg=latitude_deg, elevation_m=elevation_m,
            wind_factor=wind_factor, stomatal_resistance_s_m=stomatal_resistance_s_m,
            crop_height_m=crop_height_m,
        )

    physical = stomatal_resistance_s_m is not None and crop_height_m is not None
    method = (
        EtMethod.PENMAN_MONTEITH_PHYSICAL if physical
        else EtMethod.PENMAN_MONTEITH_STANDARD
    )
    daytime = [
        daylight_fraction(
            latitude_deg, longitude_deg, j, b.start_hour, b.end_hour, utc_offset_hours,
        ) >= DAYTIME_MIN_FRACTION
        for b in blocks
    ]

    # Il blocco pre-tramonto (D8): quello che contiene tramonto − 2.5 h.
    # Il suo rapporto serve alle notti; se il tramonto cade fuori dal
    # giorno civile (latitudini estreme) si prende l'ultimo blocco
    # diurno.
    _sunrise, sunset = sunrise_sunset_hours(latitude_deg, longitude_deg, j, utc_offset_hours)
    t_pre = sunset - PRE_SUNSET_HOURS
    pre_index = next(
        (i for i, b in enumerate(blocks) if b.start_hour <= t_pre < b.end_hour), None,
    )
    if pre_index is None or not daytime[pre_index]:
        pre_index = max((i for i, d in enumerate(daytime) if d), default=None)
    rs_rso_pre_sunset = (
        _rs_rso(blocks[pre_index], ra_blocks[pre_index], elevation_m)
        if pre_index is not None else None
    )
    night_ratio = (
        rs_rso_night_previous if rs_rso_night_previous is not None
        else rs_rso_pre_sunset
    )

    results: list[BlockEt0] = []
    for i, b in enumerate(blocks):
        ra = ra_blocks[i]
        ea = actual_vapor_pressure(b.t_c, b.humidity_relative)
        rn = net_radiation_interval(
            b.solar_radiation_mj_m2, ra, b.t_c, ea, b.hours,
            daytime=daytime[i], rs_rso_night=night_ratio, elevation_m=elevation_m,
        )
        g = soil_heat_flux_interval(rn, daytime[i])
        u2 = max(b.wind_speed_m_s * wind_factor, 0.0)
        if u2 <= 0.0:
            # Il Penman-Monteith fisico vuole un vento positivo (r_a
            # finita): calma piatta = vento minimo convettivo.
            u2 = 0.5
        if physical:
            et_raw = compute_et_penman_monteith_physical(
                temperature_c=b.t_c, humidity_relative=b.humidity_relative,
                wind_speed_m_s=u2, net_radiation_mj_m2_day=rn,
                stomatal_resistance_s_m=stomatal_resistance_s_m,
                crop_height_m=crop_height_m, elevation_m=elevation_m,
                soil_heat_flux_mj_m2_day=g, hours=b.hours,
            )
        else:
            et_raw = compute_et0_penman_monteith(
                temperature_c=b.t_c, humidity_relative=b.humidity_relative,
                wind_speed_m_s=u2, net_radiation_mj_m2_day=rn,
                elevation_m=elevation_m, soil_heat_flux_mj_m2_day=g, hours=b.hours,
            )
        rs_rso = _rs_rso(b, ra, elevation_m) if daytime[i] else night_ratio
        results.append(BlockEt0(
            start_hour=b.start_hour, hours=b.hours,
            et_mm=max(et_raw, 0.0), et_raw_mm=et_raw,
            ra_mj=ra, rn_mj=rn, g_mj=g, daytime=daytime[i], rs_rso=rs_rso,
        ))
        if i == pre_index and rs_rso_pre_sunset is not None:
            night_ratio = rs_rso_pre_sunset
    return results, method, rs_rso_pre_sunset


def _distributed_daily_et0(
    blocks: Sequence[WeatherBlock],
    ra_blocks: list[float],
    *,
    latitude_deg: float,
    elevation_m: float,
    wind_factor: float,
    stomatal_resistance_s_m: float | None,
    crop_height_m: float | None,
) -> tuple[list[BlockEt0], EtMethod, float | None]:
    """
    L'ET₀ del giorno dal selettore, sui blocchi ∝ R_a. È il cammino di
    `Pot.apply_balance_step_from_weather` applicato al giorno aggregato
    dai blocchi, poi ripartito.
    """
    day = weather_day_from_blocks(blocks)
    j = day_of_year(day.date_)
    rn_day: float | None = None
    wind: float | None = None
    if day.has_full_weather:
        t_mean = (day.t_min + day.t_max) / 2.0
        ea = actual_vapor_pressure(t_mean, day.humidity_relative)
        rn_day = net_radiation(
            solar_radiation_mj=day.solar_radiation_mj_m2_day,
            extraterrestrial_radiation_mj=extraterrestrial_radiation(latitude_deg, j),
            t_max_c=day.t_max, t_min_c=day.t_min,
            actual_vapor_pressure_kpa=ea, elevation_m=elevation_m,
        )
    if day.wind_speed_m_s is not None:
        wind = day.wind_speed_m_s * wind_factor
    et_result = compute_et(
        t_min=day.t_min, t_max=day.t_max, latitude_deg=latitude_deg, j=j,
        humidity_relative=day.humidity_relative, wind_speed_m_s=wind,
        net_radiation_mj_m2_day=rn_day,
        stomatal_resistance_s_m=stomatal_resistance_s_m, crop_height_m=crop_height_m,
        elevation_m=elevation_m,
    )
    parts = distribute_daily_et0(max(et_result.value_mm, 0.0), ra_blocks)
    results = [
        BlockEt0(
            start_hour=b.start_hour, hours=b.hours, et_mm=part, et_raw_mm=part,
            ra_mj=ra, rn_mj=None, g_mj=None, daytime=ra > 0.0, rs_rso=None,
        )
        for b, ra, part in zip(blocks, ra_blocks, parts)
    ]
    return results, et_result.method, None
