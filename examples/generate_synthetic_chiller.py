"""Synthesize a toy water-cooled chiller dataset and write it as two ASHRAE 205 tables.

The data is fabricated from a small, deliberately simple physics model -- it contains no
private information -- but it reproduces the one structural feature that makes a real
chiller dataset instructive: the condenser entering temperature that a control holds by
*design* is a clean independent axis, while the *actual* temperature the machine runs at
diverges from it at part load and makes a poor axis.

Column names and units follow the ``PerformanceMapCoolingLiquid`` section of the ASHRAE 205
RS0001 (Chiller) schema exactly -- every column is a schema Data Element name, and every
value is in that element's SI unit (temperatures in K, flows in m^3/s, powers and
capacities in W, the compressor sequence number dimensionless):

    grid variables  : evaporator_liquid_volumetric_flow_rate, evaporator_liquid_leaving_temperature,
                      condenser_liquid_volumetric_flow_rate, condenser_liquid_entering_temperature,
                      compressor_sequence_number
    lookup variables: input_power, net_evaporator_capacity, net_condenser_capacity

Two datasets, differing in one column only
------------------------------------------
The schema has a single condenser grid variable, ``condenser_liquid_entering_temperature``.
It cannot hold both the design value and the simulated value, so we emit two tables built
from the *same* physical operating points -- identical evaporator conditions, flows,
sequence numbers, powers, and capacities -- that differ only in what fills that one column:

  * ``chiller_design_conditions.csv`` -- the condenser entering temperature is the *design*
    setpoint, constant for a design case across every load step.
  * ``chiller_actual_conditions.csv`` -- the condenser entering temperature is the *actual*
    simulated value, pulled toward a common minimum-condensing-temperature floor as the
    machine unloads::

        condenser_liquid_entering_temperature = FLOOR + (design_value - FLOOR) * load_fraction

At full load the actual value equals the design value; at minimum load every design case
sits at the same floor, so distinct design cases collapse onto one coordinate. Feeding each
table to the same three-axis map (see ``design_vs_actual_axis.py`` and the dashboard) shows
the difference the choice of value makes -- the whole point of the examples.

Run it with the examples workspace member so the output lands next to the scripts::

    uv run --package performance-mapper-examples python examples/generate_synthetic_chiller.py
"""

from __future__ import annotations

import csv
from pathlib import Path

# --- fluid and design constants (SI) -----------------------------------------------------
# Volumetric heat capacity of water: heat [W] = VOLUMETRIC_HEAT_CAPACITY * flow [m^3/s] *
# temperature difference [K], with VOLUMETRIC_HEAT_CAPACITY ~= density * specific heat.
VOLUMETRIC_HEAT_CAPACITY = 4.174e6  # J/(m^3*K)
DESIGN_DELTA_T_EVAPORATOR = 5.0  # evaporator design temperature difference (K)
DESIGN_DELTA_T_CONDENSER = 5.0  # condenser design temperature difference (K)

# --- design space (kelvin; Celsius equivalents in comments) ------------------------------
# A coarse sweep on purpose: three chilled-liquid setpoints, four condenser design points,
# and load in five steps. That keeps the three-axis grid small enough -- 3 x 4 x 5 = 60
# nodes -- to read clearly in the 3-D coverage view.
EVAPORATOR_LEAVING_SETPOINTS = [277.15, 280.15, 283.15]  # 4, 7, 10 C
NOMINAL_CONDENSER_ENTERING = [291.15, 297.15, 303.15, 309.15]  # 18, 24, 30, 36 C
CONDENSER_FLOOR = 294.15  # minimum-condensing-temperature control floor, 21 C
LOAD_STEPS_PERCENT = [100, 80, 60, 40, 20]  # part-load sweep

# Not every design case is simulated, and some stop before minimum load -- so the regular
# grid has interior gaps (combinations that were never run). This is what separates
# "gap-fill" grid nodes from true extrapolation in the coverage analysis.
SKIPPED_CASES = {(277.15, 309.15), (280.15, 309.15)}  # extreme lift at low leaving temp
EARLY_STOP_NOMINAL = 309.15  # the warmest-condenser case runs only down to 40 % load
EARLY_STOP_MINIMUM_PERCENT = 40

DATA_DIRECTORY = Path(__file__).parent / "data"
DESIGN_OUTPUT_PATH = DATA_DIRECTORY / "chiller_design_conditions.csv"
ACTUAL_OUTPUT_PATH = DATA_DIRECTORY / "chiller_actual_conditions.csv"

# Header labels are "Data Element name (koozie SI units)"; a dimensionless element is a bare
# name. ``condenser_liquid_entering_temperature`` is filled per dataset, so it is listed once
# and both tables share this column order.
COLUMNS = [
    ("evaporator_liquid_volumetric_flow_rate", "m**3/s"),
    ("evaporator_liquid_leaving_temperature", "K"),
    ("condenser_liquid_volumetric_flow_rate", "m**3/s"),
    ("condenser_liquid_entering_temperature", "K"),
    ("compressor_sequence_number", ""),
    ("input_power", "W"),
    ("net_evaporator_capacity", "W"),
    ("net_condenser_capacity", "W"),
]


def compressor_sequence_number(percent_load: float) -> int:
    """Sequence number, lowest capacity first: 20 % -> 1, then +1 per 20 % step, 100 % -> 5.

    Matches the RS0001 ``compressor_sequence_number`` definition (integer, starting at 1).
    """
    return round((percent_load - 20.0) / 20.0) + 1


def design_capacity(evaporator_leaving: float, nominal_condenser: float) -> float:
    """Full-load net evaporator capacity of a design case (W).

    Rises gently with a warmer chilled-liquid setpoint (easier duty) and falls with a warmer
    condenser design point (more lift). Centered on 350 kW at 280.15 K / 297.15 K.
    """
    setpoint_factor = 1.0 + 0.02 * (evaporator_leaving - 280.15)
    lift_factor = 1.0 - 0.01 * (nominal_condenser - 297.15)
    return 350_000.0 * setpoint_factor * lift_factor


def actual_condenser_entering(nominal_condenser: float, percent_load: float) -> float:
    """Simulated condenser entering temperature, pulled toward the floor as load drops."""
    load_fraction = (percent_load - min(LOAD_STEPS_PERCENT)) / (max(LOAD_STEPS_PERCENT) - min(LOAD_STEPS_PERCENT))
    return CONDENSER_FLOOR + (nominal_condenser - CONDENSER_FLOOR) * load_fraction


def coefficient_of_performance(lift: float, percent_load: float) -> float:
    """Cooling coefficient of performance: worse with lift, best at moderate part load.

    ``lift`` is the condenser-minus-evaporator liquid-temperature span (K). The part-load
    factor gives the characteristic mid-load efficiency bump of a good chiller.
    """
    full_load = 5.5 - 0.03 * (lift - 20.0)
    unloaded = 1.0 - percent_load / 100.0
    part_load_factor = 1.0 + 0.35 * unloaded - 0.5 * unloaded**2
    return max(0.5, full_load * part_load_factor)


def generate_datasets() -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    """Build the design-conditions and actual-conditions rows from one set of operating points.

    Both lists hold the same physical points -- the only difference is the value written for
    ``condenser_liquid_entering_temperature`` (nominal design value vs. actual simulated one).
    """
    design_rows: list[dict[str, float]] = []
    actual_rows: list[dict[str, float]] = []

    for evaporator_leaving in EVAPORATOR_LEAVING_SETPOINTS:
        for nominal_condenser in NOMINAL_CONDENSER_ENTERING:
            if (evaporator_leaving, nominal_condenser) in SKIPPED_CASES:
                continue

            full_load_capacity = design_capacity(evaporator_leaving, nominal_condenser)

            # Design-rule flows (constant for the whole case): the flow giving the design
            # temperature difference at full load. heat = VOLUMETRIC_HEAT_CAPACITY * flow * dT.
            evaporator_flow = full_load_capacity / (VOLUMETRIC_HEAT_CAPACITY * DESIGN_DELTA_T_EVAPORATOR)
            full_load_lift = nominal_condenser - evaporator_leaving
            full_load_power = full_load_capacity / coefficient_of_performance(full_load_lift, 100.0)
            design_condenser_heat = full_load_capacity + full_load_power
            condenser_flow = design_condenser_heat / (VOLUMETRIC_HEAT_CAPACITY * DESIGN_DELTA_T_CONDENSER)

            for percent_load in LOAD_STEPS_PERCENT:
                if nominal_condenser == EARLY_STOP_NOMINAL and percent_load < EARLY_STOP_MINIMUM_PERCENT:
                    continue

                capacity = full_load_capacity * percent_load / 100.0
                actual_condenser = actual_condenser_entering(nominal_condenser, percent_load)
                lift = actual_condenser - evaporator_leaving
                power = capacity / coefficient_of_performance(lift, percent_load)
                condenser_capacity = capacity + power  # steady-state energy balance
                sequence = compressor_sequence_number(percent_load)

                shared = {
                    "evaporator_liquid_volumetric_flow_rate": evaporator_flow,
                    "evaporator_liquid_leaving_temperature": evaporator_leaving,
                    "condenser_liquid_volumetric_flow_rate": condenser_flow,
                    "compressor_sequence_number": sequence,
                    "input_power": power,
                    "net_evaporator_capacity": capacity,
                    "net_condenser_capacity": condenser_capacity,
                }
                design_rows.append({**shared, "condenser_liquid_entering_temperature": nominal_condenser})
                actual_rows.append({**shared, "condenser_liquid_entering_temperature": actual_condenser})

    return design_rows, actual_rows


def _write(path: Path, rows: list[dict[str, float]]) -> None:
    header = [f"{name} ({units})" if units else name for name, units in COLUMNS]
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for row in rows:
            writer.writerow(
                # The sequence number is an integer element; the rest are SI floats.
                str(int(row[name])) if name == "compressor_sequence_number" else f"{row[name]:.6g}"
                for name, _ in COLUMNS
            )


def main() -> None:
    design_rows, actual_rows = generate_datasets()
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    _write(DESIGN_OUTPUT_PATH, design_rows)
    _write(ACTUAL_OUTPUT_PATH, actual_rows)
    print(f"wrote {len(design_rows)} points to {DESIGN_OUTPUT_PATH.name} and {ACTUAL_OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
