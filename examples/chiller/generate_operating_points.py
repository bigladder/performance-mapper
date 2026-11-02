"""Generate the synthetic chiller operating points used by ``translate_to_regular_map.py``.

The points describe a water-cooled chiller of about 150 tons with two compressors, in the
form chiller selection software reports: one run per pair of design temperatures, and one row
per load step within the run. The script writes ``chiller_operating_points.csv`` in
inch-pound units.

Each run fixes a chilled water leaving temperature setpoint and a nominal condenser water
entering temperature. Both water flows are sized from the run's full-load capacity for a
10 degF temperature difference and stay constant as the chiller unloads. The condenser
water entering temperature falls with load (condenser relief), down to a 65 degF floor.

Capacity and power come from a model defined here: full-load capacity and power are
quadratic in the two water temperatures, and part-load power follows a convex curve for
each compressor, with the second compressor starting above 50 % load.

Run from the repository root:

    uv run --group examples python examples/chiller/generate_operating_points.py
"""

from __future__ import annotations

import csv
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "chiller_operating_points.csv"

HEADER = [
    "chilled water flow (gpm)",
    "chilled water leaving temperature (degF)",
    "chilled water entering temperature (degF)",
    "condenser water flow (gpm)",
    "condenser water entering temperature (degF)",
    "condenser water leaving temperature (degF)",
    "percent load (%)",
    "power (kW)",
    "capacity (ton_ref)",
]

# Design conditions of each run: chilled water leaving temperature setpoints (degF), each with
# the nominal condenser water entering temperatures (degF) run at that setpoint. The coldest
# condenser water is not run at the higher setpoints.
RUNS = {
    42.0: (65.0, 75.0, 85.0),
    47.0: (65.0, 75.0, 85.0),
    52.0: (75.0, 85.0),
    57.0: (75.0, 85.0),
    62.0: (75.0, 85.0),
}

# Load steps (%) from full load down to each run's minimum load.
FULL_LOAD = 100
LOAD_STEP = 10
MINIMUM_LOAD = 20
MINIMUM_LOAD_AT_HIGH_SETPOINTS = 30
HIGH_SETPOINT = 57.0  # degF; setpoints at or above this stop at the higher minimum load
SKIPPED_LOAD = 90  # not run when the nominal condenser temperature is at the relief floor

DESIGN_TEMPERATURE_DIFFERENCE = 10.0  # degF, both water loops at full load
CONDENSER_RELIEF_FLOOR = 65.0  # degF
CONDENSER_RELIEF_END_LOAD = 0.4  # load fraction at which relief reaches the floor

# Full-load model, about a reference point of 44 degF chilled water and 85 degF condenser water.
REFERENCE_CHILLED_WATER_TEMPERATURE = 44.0  # degF
REFERENCE_CONDENSER_WATER_TEMPERATURE = 85.0  # degF
REFERENCE_CAPACITY = 150.0  # ton_ref
REFERENCE_POWER = 105.0  # kW

# Part-load power of one compressor as a fraction of its full-load power, as a quadratic in its
# own load fraction (constant, linear, and quadratic coefficients).
COMPRESSOR_PART_LOAD_COEFFICIENTS = (0.45, 0.05, 0.5)
ONE_COMPRESSOR_LIMIT = 0.5  # fraction of full capacity one compressor carries

KW_PER_TON = 3.51685
BTU_PER_HOUR_PER_KW = 3412.14
BTU_PER_HOUR_PER_GPM_DEGF = 500.0  # water: 8.33 lb/gal x 60 min/h x 1 Btu/(lb degF)
GPM_PER_TON_PER_DEGF = 24.0  # 12000 Btu/h per ton / 500


def full_load_capacity(chilled_water_temperature: float, condenser_water_temperature: float) -> float:
    """Full-load capacity (ton_ref), rising about 2 % per degF of chilled water temperature and
    falling about 6 % per 10 degF of condenser water temperature."""
    chilled = chilled_water_temperature - REFERENCE_CHILLED_WATER_TEMPERATURE
    condenser = condenser_water_temperature - REFERENCE_CONDENSER_WATER_TEMPERATURE
    return REFERENCE_CAPACITY * (
        1.0 + 0.019 * chilled + 0.0001 * chilled**2 - 0.006 * condenser - 0.00002 * condenser**2
    )


def full_load_power(chilled_water_temperature: float, condenser_water_temperature: float) -> float:
    """Full-load power (kW), rising about 12 % per 10 degF of condenser water temperature and
    gently with chilled water temperature."""
    chilled = chilled_water_temperature - REFERENCE_CHILLED_WATER_TEMPERATURE
    condenser = condenser_water_temperature - REFERENCE_CONDENSER_WATER_TEMPERATURE
    return REFERENCE_POWER * (1.0 + 0.005 * chilled + 0.012 * condenser + 0.0001 * condenser**2)


def part_load_power_fraction(capacity_fraction: float) -> float:
    """Power as a fraction of full-load power at the same water temperatures. One compressor
    carries loads up to half of full capacity; above that, two compressors share the load."""
    constant, linear, quadratic = COMPRESSOR_PART_LOAD_COEFFICIENTS
    if capacity_fraction <= ONE_COMPRESSOR_LIMIT:
        compressor_load = capacity_fraction / ONE_COMPRESSOR_LIMIT
        compressor_share = ONE_COMPRESSOR_LIMIT
    else:
        compressor_load = capacity_fraction
        compressor_share = 1.0
    return compressor_share * (constant + linear * compressor_load + quadratic * compressor_load**2)


def relieved_condenser_temperature(nominal_temperature: float, load_fraction: float) -> float:
    """Condenser water entering temperature (degF), falling linearly from its nominal value at
    full load to the relief floor, and never below the floor."""
    span = (load_fraction - CONDENSER_RELIEF_END_LOAD) / (1.0 - CONDENSER_RELIEF_END_LOAD)
    return max(CONDENSER_RELIEF_FLOOR, CONDENSER_RELIEF_FLOOR + (nominal_temperature - CONDENSER_RELIEF_FLOOR) * span)


def load_steps(setpoint: float, nominal_condenser_temperature: float) -> list[int]:
    """The percent loads run at one pair of design conditions, from full load down."""
    minimum = MINIMUM_LOAD_AT_HIGH_SETPOINTS if setpoint >= HIGH_SETPOINT else MINIMUM_LOAD
    skipped = SKIPPED_LOAD if nominal_condenser_temperature == CONDENSER_RELIEF_FLOOR else None
    return [load for load in range(FULL_LOAD, minimum - 1, -LOAD_STEP) if load != skipped]


def run_rows(setpoint: float, nominal_condenser_temperature: float) -> list[list[float]]:
    """The operating points of one run, one row per load step, in the order of ``HEADER``."""
    design_capacity = full_load_capacity(setpoint, nominal_condenser_temperature)
    design_rejected_heat = design_capacity * KW_PER_TON + full_load_power(setpoint, nominal_condenser_temperature)
    chilled_water_flow = design_capacity * GPM_PER_TON_PER_DEGF / DESIGN_TEMPERATURE_DIFFERENCE
    condenser_water_flow = (
        design_rejected_heat * BTU_PER_HOUR_PER_KW / (BTU_PER_HOUR_PER_GPM_DEGF * DESIGN_TEMPERATURE_DIFFERENCE)
    )

    rows = []
    for percent_load in load_steps(setpoint, nominal_condenser_temperature):
        load_fraction = percent_load / FULL_LOAD
        condenser_temperature = relieved_condenser_temperature(nominal_condenser_temperature, load_fraction)
        capacity = load_fraction * design_capacity
        capacity_fraction = capacity / full_load_capacity(setpoint, condenser_temperature)
        power = full_load_power(setpoint, condenser_temperature) * part_load_power_fraction(capacity_fraction)
        rejected_heat = (capacity * KW_PER_TON + power) * BTU_PER_HOUR_PER_KW
        rows.append(
            [
                round(chilled_water_flow, 1),
                round(setpoint, 1),
                round(setpoint + capacity * GPM_PER_TON_PER_DEGF / chilled_water_flow, 1),
                round(condenser_water_flow, 1),
                round(condenser_temperature, 1),
                round(condenser_temperature + rejected_heat / (BTU_PER_HOUR_PER_GPM_DEGF * condenser_water_flow), 1),
                percent_load,
                round(power, 1),
                round(capacity, 1),
            ]
        )
    return rows


def main() -> None:
    rows = [row for setpoint, nominals in RUNS.items() for nominal in nominals for row in run_rows(setpoint, nominal)]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"wrote {len(rows)} operating points to {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
