"""Show which nodes of a three-axis chiller map the irregular data supports.

The map's grid variables are the chilled water leaving temperature, the condenser water
entering temperature, and the compressor sequence number, built from the same irregular data
and transformations as ``translate_to_regular_map.py``. The condenser water entering
temperature axis is widened to start at 55 degrees Fahrenheit, below the 65 degree floor of the
data, so the map covers conditions the data never reached.

The fit report sorts every grid node into one of three extrapolation zones:

    * inside the convex hull of the data ......... interpolation between data points
    * inside the bounding box, outside the hull .. gap-filling between data points
    * outside the bounding box ................... pure extrapolation

The script prints the fit report's zone counts and axis coverage, and writes two figures of
the zones in ``images/``: a rotatable plotly page (``hull_versus_box.html``) and a still image
(``hull_versus_box.png``).

Run from the repository root:

    uv run --group examples python examples/chiller/hull_versus_box.py
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from koozie import fr_u, to_u  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402
from scipy.spatial import ConvexHull  # noqa: E402
from translate_to_regular_map import (  # noqa: E402
    CAPACITY,
    CHILLED_WATER_LEAVING_TEMPERATURE,
    CONDENSER_WATER_ENTERING_TEMPERATURE,
    CONDENSER_WATER_FLOW,
    IMAGE_DIRECTORY,
    INPUT_PATH,
    PERCENT_LOAD,
    POWER,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    column_values,
    compressor_sequence_number,
    flow_key,
    grid_variables,
    lookup_variables,
    minimum_load_by_flow,
)

from performance_mapper import (  # noqa: E402
    FitReport,
    GridVariableSpecification,
    PerformanceMap,
    PointTable,
)

HTML_PATH = IMAGE_DIRECTORY / "hull_versus_box.html"
IMAGE_PATH = IMAGE_DIRECTORY / "hull_versus_box.png"

# The widened condenser water entering temperature axis, in degrees Fahrenheit.
CONDENSER_AXIS_RANGE = (55.0, 85.0)
CONDENSER_AXIS_POINTS = 7

# The zones carry a state, so they use status colors, each paired with its own marker shape.
ZONES = (
    ("inside the convex hull", "#0ca30c", "circle", "o"),
    ("inside the bounding box only", "#fab219", "square", "s"),
    ("outside the bounding box", "#d03b3b", "x", "X"),
)
DATA_COLOR = TEXT_PRIMARY
HULL_COLOR = "#1baf7a"
BOX_COLOR = "#898781"
PAGE = "#f9f9f7"
GRID_LINE = "#e1e0d9"

AXIS_TITLES = (
    "chilled water leaving temperature (°F)",
    "condenser water entering temperature (°F)",
    "compressor sequence number",
)


def three_axis_grid_variables(minimum_loads: dict[float, float]) -> list[GridVariableSpecification]:
    """Chilled water leaving temperature, the widened condenser water entering temperature,
    and the compressor sequence number."""
    _, chilled_water_leaving, _, condenser_entering, sequence_number = grid_variables(minimum_loads)
    widened_condenser_entering = replace(
        condenser_entering, range=CONDENSER_AXIS_RANGE, number_of_points=CONDENSER_AXIS_POINTS
    )
    return [chilled_water_leaving, widened_condenser_entering, sequence_number]


def grid_nodes(performance_map: PerformanceMap) -> np.ndarray:
    """The grid nodes in row-major order, one row per node, with temperatures in degrees
    Fahrenheit."""
    axes = [np.array(grid_variable.values) for grid_variable in performance_map.grid_variables]
    axes[0] = to_u(axes[0], "degF")
    axes[1] = to_u(axes[1], "degF")
    meshes = np.meshgrid(*axes, indexing="ij")
    return np.column_stack([mesh.ravel(order="C") for mesh in meshes])


def zone_masks(report: FitReport, number_of_nodes: int) -> list[np.ndarray]:
    """Boolean masks over the grid nodes for the three zones, in the order of ``ZONES``."""
    outside_box = np.zeros(number_of_nodes, dtype=bool)
    outside_box[list(report.grid_points_outside_bounding_box)] = True
    outside_hull = np.zeros(number_of_nodes, dtype=bool)
    outside_hull[list(report.grid_points_outside_convex_hull)] = True
    return [~outside_box & ~outside_hull, outside_hull, outside_box]


def data_coordinates(points: PointTable, minimum_loads: dict[float, float]) -> np.ndarray:
    """The irregular data in the map's three grid variables, one row per point, with
    temperatures in degrees Fahrenheit."""
    sequence_numbers = [
        compressor_sequence_number(load / 100, minimum_loads[flow_key(flow)])
        for load, flow in zip(column_values(points, PERCENT_LOAD), column_values(points, CONDENSER_WATER_FLOW))
    ]
    return np.column_stack(
        [
            column_values(points, CHILLED_WATER_LEAVING_TEMPERATURE),
            column_values(points, CONDENSER_WATER_ENTERING_TEMPERATURE),
            sequence_numbers,
        ]
    )


def box_edges(coordinates: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """The twelve edges of the bounding box of ``coordinates``, as pairs of corner points."""
    low, high = coordinates.min(axis=0), coordinates.max(axis=0)
    corners = np.array([[(low, high)[(index >> axis) & 1][axis] for axis in range(3)] for index in range(8)])
    return [
        (corners[start], corners[start | 1 << axis]) for start in range(8) for axis in range(3) if not start & 1 << axis
    ]


def print_summary(performance_map: PerformanceMap, report: FitReport, masks: list[np.ndarray]) -> None:
    """Print the grid shape, the zone counts, the axis coverage, and the read-back fit."""
    total = int(np.prod(performance_map.grid_shape))
    print(f"three-axis map: {' x '.join(map(str, performance_map.grid_shape))} grid ({total} nodes)")
    for (name, *_), mask in zip(ZONES, masks):
        print(f"  {name}: {int(mask.sum())}")
    print(f"convex hull evaluated: {report.convex_hull_evaluated}")
    print("axis coverage (axis range | data range):")
    for coverage in report.grid_variable_coverage:
        print(
            f"  {coverage.name} ({coverage.units or 'dimensionless'}): "
            f"{coverage.axis_minimum:.6g} to {coverage.axis_maximum:.6g} | "
            f"{coverage.data_minimum:.6g} to {coverage.data_maximum:.6g}"
        )
    print(f"irregular data points outside the grid's range: {len(report.points_outside_grid)}")
    print(f"read-back R^2: {report.r_squared:.4f}")


def plot_interactive(
    nodes: np.ndarray, masks: list[np.ndarray], data: np.ndarray, points: PointTable, path: Path
) -> None:
    """Write a rotatable page of the zones, the convex hull surface, the bounding box, and the
    irregular data."""
    figure = go.Figure()
    hull = ConvexHull(data)
    figure.add_trace(
        go.Mesh3d(
            x=data[:, 0],
            y=data[:, 1],
            z=data[:, 2],
            i=hull.simplices[:, 0],
            j=hull.simplices[:, 1],
            k=hull.simplices[:, 2],
            color=HULL_COLOR,
            opacity=0.18,
            flatshading=True,
            name="convex hull of the data",
            showlegend=True,
            hoverinfo="skip",
        )
    )
    box_x: list[float | None] = []
    box_y: list[float | None] = []
    box_z: list[float | None] = []
    for start, end in box_edges(data):
        box_x += [start[0], end[0], None]
        box_y += [start[1], end[1], None]
        box_z += [start[2], end[2], None]
    figure.add_trace(
        go.Scatter3d(
            x=box_x,
            y=box_y,
            z=box_z,
            mode="lines",
            line={"color": BOX_COLOR, "width": 3, "dash": "dot"},
            name="bounding box of the data",
            hoverinfo="skip",
        )
    )
    for (name, color, symbol, _), mask in zip(ZONES, masks):
        figure.add_trace(
            go.Scatter3d(
                x=nodes[mask, 0],
                y=nodes[mask, 1],
                z=nodes[mask, 2],
                mode="markers",
                name=f"grid nodes {name} ({int(mask.sum())})",
                marker={
                    "size": 6,
                    "color": color,
                    "symbol": symbol,
                    "line": {"width": 1, "color": "rgba(11,11,11,0.55)"},
                },
                hovertemplate=(
                    "chilled water leaving %{x:.1f} °F<br>condenser water entering %{y:.1f} °F<br>"
                    "sequence %{z:.0f}<br>" + name + "<extra></extra>"
                ),
            )
        )
    figure.add_trace(
        go.Scatter3d(
            x=data[:, 0],
            y=data[:, 1],
            z=data[:, 2],
            mode="markers",
            name=f"irregular data ({len(data)})",
            marker={"size": 4, "color": DATA_COLOR, "symbol": "diamond"},
            customdata=np.column_stack(
                [
                    fr_u(column_values(points, CAPACITY), "ton_ref") / 1000.0,
                    column_values(points, POWER),
                ]
            ),
            hovertemplate=(
                "chilled water leaving %{x:.1f} °F<br>condenser water entering %{y:.1f} °F<br>"
                "sequence %{z:.2f}<br>net evaporator capacity %{customdata[0]:.0f} kW<br>"
                "input power %{customdata[1]:.0f} kW<extra>irregular data</extra>"
            ),
        )
    )
    axis_style = {
        "backgroundcolor": SURFACE,
        "gridcolor": GRID_LINE,
        "zerolinecolor": GRID_LINE,
        "color": TEXT_SECONDARY,
    }
    figure.update_layout(
        title={"text": "Which grid nodes the irregular data supports", "font": {"color": TEXT_PRIMARY}},
        paper_bgcolor=PAGE,
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "color": TEXT_SECONDARY},
        legend={"bgcolor": SURFACE, "bordercolor": GRID_LINE, "borderwidth": 1, "font": {"color": TEXT_PRIMARY}},
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        scene={
            "xaxis": {"title": AXIS_TITLES[0], **axis_style},
            "yaxis": {"title": AXIS_TITLES[1], **axis_style},
            "zaxis": {"title": AXIS_TITLES[2], "dtick": 1, **axis_style},
            "camera": {"eye": {"x": 1.7, "y": -1.5, "z": 0.9}},
            "aspectmode": "cube",
        },
    )
    figure.write_html(path, include_plotlyjs="cdn")


def plot_still(nodes: np.ndarray, masks: list[np.ndarray], data: np.ndarray, path: Path) -> None:
    """Draw the zones, the convex hull surface, the bounding box, and the irregular data as a
    still image."""
    figure = plt.figure(figsize=(8, 6.5), facecolor=SURFACE)
    axes = figure.add_subplot(projection="3d", facecolor=SURFACE)
    hull = ConvexHull(data)
    axes.add_collection3d(
        Poly3DCollection(data[hull.simplices], facecolor=HULL_COLOR, alpha=0.12, edgecolor=HULL_COLOR, linewidth=0.3)
    )
    for start, end in box_edges(data):
        axes.plot(*zip(start, end), color=BOX_COLOR, linestyle=":", linewidth=1.5)
    for (name, color, _, marker), mask in zip(ZONES, masks):
        axes.scatter(
            *nodes[mask].T,
            color=color,
            marker=marker,
            s=48,
            edgecolors=TEXT_PRIMARY,
            linewidths=0.5,
            depthshade=False,
            label=f"grid nodes {name} ({int(mask.sum())})",
        )
    axes.scatter(*data.T, color=DATA_COLOR, marker="D", s=12, depthshade=False, label=f"irregular data ({len(data)})")
    for setter, title in zip((axes.set_xlabel, axes.set_ylabel, axes.set_zlabel), AXIS_TITLES):
        setter(title, color=TEXT_SECONDARY)
    axes.set_xticks(np.unique(nodes[:, 0]))
    axes.set_yticks(np.unique(nodes[:, 1]))
    axes.set_zticks(np.unique(nodes[:, 2]))
    axes.tick_params(colors=TEXT_SECONDARY)
    for axis in (axes.xaxis, axes.yaxis, axes.zaxis):
        axis.pane.set_facecolor(SURFACE)
        axis.pane.set_edgecolor(GRID_LINE)
    axes.view_init(elev=22, azim=-60)
    axes.set_title("Which grid nodes the irregular data supports", loc="left", color=TEXT_PRIMARY, fontsize=12)
    axes.legend(frameon=False, labelcolor=TEXT_SECONDARY, loc="upper left", bbox_to_anchor=(0.0, 0.0), ncol=2)
    figure.tight_layout()
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    points = PointTable.from_csv(INPUT_PATH)
    minimum_loads = minimum_load_by_flow(points)
    performance_map, report = points.to_performance_map(
        three_axis_grid_variables(minimum_loads), lookup_variables(), fit_report=True
    )
    nodes = grid_nodes(performance_map)
    masks = zone_masks(report, len(nodes))
    print_summary(performance_map, report, masks)

    data = data_coordinates(points, minimum_loads)
    IMAGE_DIRECTORY.mkdir(exist_ok=True)
    plot_interactive(nodes, masks, data, points, HTML_PATH)
    plot_still(nodes, masks, data, IMAGE_PATH)
    print(f"wrote {HTML_PATH.name} and {IMAGE_PATH.name} to {IMAGE_DIRECTORY.relative_to(INPUT_PATH.parents[2])}")


if __name__ == "__main__":
    main()
