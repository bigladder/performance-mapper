"""Interactive 3-D view of the "which grid nodes can we trust?" question, for both datasets.

The trustworthy performance map for the synthetic chiller uses three independent axes --
``evaporator_liquid_leaving_temperature``, ``condenser_liquid_entering_temperature``, and
``compressor_sequence_number`` (see ``compare_grids.py`` for why those three). Regridding the
operating points onto that tensor grid raises the question every performance map faces:
which grid nodes are supported by data, and which are guesses?

    * inside the convex hull ...... interpolation between operating points (safe)
    * inside the box, outside hull . combinations never simulated ("gap fill", medium risk --
                                      interpolated but unsupported)
    * outside the bounding box ..... true extrapolation (high risk)

The radio control switches between the two generated datasets, which fill
``condenser_liquid_entering_temperature`` differently (design setpoint vs. actual simulated
value). Switching between them shows the difference the choice makes: the design conditions
give a small, mostly-supported grid; the actual conditions scatter the condenser axis into
many values, giving a four-times-larger grid with a much larger share of gap-fill nodes. The
zone logic mirrors
``performance_mapper._engine._Regridding._extrapolation_zones``, and both datasets are
cross-checked against the package's own fit report at startup, so the picture can never
disagree with the numbers.

The three zones carry a state (safe / gap-fill / extrapolation), so they use the status
palette -- green / amber / red -- and each zone additionally gets its own marker shape and
its own labelled legend entry, so the meaning never rests on color alone.

Run:
    uv run --package performance-mapper-examples python examples/hull_vs_box_dashboard.py
then open the printed http://127.0.0.1:8050/ URL in a browser. Pass --check to verify the
figures and their zone counts without starting the server.
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from _chiller_common import (
    ACTUAL_DATA_PATH,
    COMPRESSOR_SEQUENCE,
    CONDENSER_ENTERING_TEMPERATURE,
    DESIGN_DATA_PATH,
    EVAPORATOR_LEAVING_TEMPERATURE,
    INPUT_POWER,
    NET_EVAPORATOR_CAPACITY,
    load_points,
    lookup_variables,
    reduced_grid_variables,
)
from dash import Dash, Input, Output, dcc, html
from scipy.spatial import ConvexHull, Delaunay

# --- palette (dataviz skill) -------------------------------------------------------------
# The three zones carry STATE, so they use the status palette (good / warning / critical),
# never a categorical series color. Color never carries meaning alone: each zone also gets a
# distinct marker symbol and its own labelled legend trace.
COLOR_HULL = "#0ca30c"  # good      -- inside convex hull (interpolation)
COLOR_GAP = "#fab219"  # warning   -- inside box, outside hull (gap fill)
COLOR_OUT = "#d03b3b"  # critical  -- outside bounding box (extrapolation)
COLOR_DATA = "#0b0b0b"  # primary ink -- operating points
COLOR_HULL_FILL = "#1baf7a"  # hull surface, drawn at low opacity

SURFACE = "#fcfcfb"  # light chart surface
PAGE = "#f9f9f7"  # page plane
INK = "#0b0b0b"  # primary ink
INK_2 = "#52514e"  # secondary ink
MUTED = "#898781"  # axis / muted
GRID = "#e1e0d9"  # hairline gridline

AXIS_TITLES = (
    f"{EVAPORATOR_LEAVING_TEMPERATURE} (K)",
    f"{CONDENSER_ENTERING_TEMPERATURE} (K)",
    COMPRESSOR_SEQUENCE,
)
DATASETS = {"design conditions": DESIGN_DATA_PATH, "actual conditions": ACTUAL_DATA_PATH}


def load_data(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[np.ndarray]]:
    """Return ``(points, capacity, power, axes)`` for a dataset.

    ``points`` is an (N, 3) array of (evaporator leaving temperature, condenser entering
    temperature, compressor sequence number); ``capacity`` / ``power`` are per-point lookups
    for the hover text; ``axes`` is the list of the three sorted-unique grid-axis value arrays.
    """
    columns = {column.name: np.array(column.values) for column in load_points(path).columns}
    evaporator = columns[EVAPORATOR_LEAVING_TEMPERATURE]
    condenser = columns[CONDENSER_ENTERING_TEMPERATURE]
    sequence = columns[COMPRESSOR_SEQUENCE]
    points = np.column_stack([evaporator, condenser, sequence])
    axes = [np.unique(evaporator), np.unique(condenser), np.unique(sequence)]
    return points, columns[NET_EVAPORATOR_CAPACITY], columns[INPUT_POWER], axes


def build_grid(axes: list[np.ndarray]) -> np.ndarray:
    """Tensor-product grid nodes: ``np.meshgrid(indexing='ij')`` then ravel."""
    meshes = np.meshgrid(*axes, indexing="ij")
    return np.column_stack([mesh.ravel(order="C") for mesh in meshes])


def classify(points: np.ndarray, nodes: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(inside_hull, gap_only, outside_box)`` boolean masks over the grid nodes.

    Mirrors ``performance_mapper._engine._Regridding._extrapolation_zones``:
      * outside box: any coordinate below the per-axis data minimum or above its maximum;
      * inside hull: ``Delaunay(find_simplex) >= 0`` on per-axis min-max normalized
        coordinates (an affine map, so hull membership is identical in real coordinates);
      * gap only: inside the box but outside the hull -- the interior gaps.
    """
    data_minimum = points.min(axis=0)
    data_maximum = points.max(axis=0)
    outside_box = ((nodes < data_minimum) | (nodes > data_maximum)).any(axis=1)

    span = data_maximum - data_minimum
    span[span == 0.0] = 1.0

    def normalize(array: np.ndarray) -> np.ndarray:
        return (array - data_minimum) / span

    triangulation = Delaunay(normalize(points))
    inside_hull = triangulation.find_simplex(normalize(nodes)) >= 0
    gap_only = ~inside_hull & ~outside_box
    return inside_hull, gap_only, outside_box


def package_zone_counts(path: Path) -> tuple[int, int]:
    """Ground truth from the package itself: build the three-axis map for a dataset with a fit
    report and return ``(outside_bounding_box, outside_convex_hull)`` node counts.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the actual dataset averages duplicate coordinates
        _, report = load_points(path).to_performance_map(
            grid_variables=reduced_grid_variables(), lookup_variables=lookup_variables(), fit_report=True
        )
    return len(report.grid_points_outside_bounding_box), len(report.grid_points_outside_convex_hull)


def _box_edges(points: np.ndarray) -> tuple[list, list, list]:
    """The 12 edges of the per-axis min/max bounding box as line segments (None-separated)."""
    low = points.min(axis=0)
    high = points.max(axis=0)
    corners = np.array(
        [
            [low[0], low[1], low[2]],
            [high[0], low[1], low[2]],
            [high[0], high[1], low[2]],
            [low[0], high[1], low[2]],
            [low[0], low[1], high[2]],
            [high[0], low[1], high[2]],
            [high[0], high[1], high[2]],
            [low[0], high[1], high[2]],
        ]
    )
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),  # bottom face
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),  # top face
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),  # verticals
    ]
    xs: list = []
    ys: list = []
    zs: list = []
    for start, end in edges:
        xs += [corners[start, 0], corners[end, 0], None]
        ys += [corners[start, 1], corners[end, 1], None]
        zs += [corners[start, 2], corners[end, 2], None]
    return xs, ys, zs


def _zone_trace(nodes: np.ndarray, mask: np.ndarray, name: str, color: str, symbol: str) -> go.Scatter3d:
    return go.Scatter3d(
        x=nodes[mask, 0],
        y=nodes[mask, 1],
        z=nodes[mask, 2],
        mode="markers",
        name=f"{name} ({int(mask.sum())})",
        marker=dict(
            size=6,
            color=color,
            symbol=symbol,
            opacity=0.95,
            line=dict(width=1, color="rgba(11,11,11,0.55)"),  # surface ring for contrast
        ),
        hovertemplate=(
            "evaporator leaving %{x:.2f} K<br>condenser entering %{y:.2f} K<br>"
            "sequence %{z:.0f}<br>" + name + "<extra></extra>"
        ),
    )


def build_figure(points: np.ndarray, capacity: np.ndarray, power: np.ndarray, axes: list[np.ndarray]) -> tuple:
    """Assemble one rotatable 3-D figure for a dataset. Returns ``(figure, counts)``."""
    nodes = build_grid(axes)
    inside_hull, gap_only, outside_box = classify(points, nodes)
    counts = dict(
        inside_hull=int(inside_hull.sum()),
        gap_only=int(gap_only.sum()),
        outside_box=int(outside_box.sum()),
        total=len(nodes),
    )

    figure = go.Figure()

    # Convex-hull surface: ConvexHull on real coordinates; its simplices become mesh triangles.
    hull = ConvexHull(points)
    figure.add_trace(
        go.Mesh3d(
            x=points[:, 0],
            y=points[:, 1],
            z=points[:, 2],
            i=hull.simplices[:, 0],
            j=hull.simplices[:, 1],
            k=hull.simplices[:, 2],
            color=COLOR_HULL_FILL,
            opacity=0.18,
            flatshading=True,
            name="convex hull",
            showlegend=True,
            hoverinfo="skip",
        )
    )

    # Bounding-box wireframe (12 edges).
    box_x, box_y, box_z = _box_edges(points)
    figure.add_trace(
        go.Scatter3d(
            x=box_x,
            y=box_y,
            z=box_z,
            mode="lines",
            line=dict(color=MUTED, width=3, dash="dot"),
            name="bounding box",
            hoverinfo="skip",
        )
    )

    # Grid nodes colored by zone (each its own toggleable legend trace, each a distinct shape).
    figure.add_trace(_zone_trace(nodes, inside_hull, "inside hull", COLOR_HULL, "circle"))
    figure.add_trace(_zone_trace(nodes, gap_only, "inside box only", COLOR_GAP, "square"))
    figure.add_trace(_zone_trace(nodes, outside_box, "outside box", COLOR_OUT, "x"))

    # Operating points (black diamonds) with rich hover (capacities/powers shown in kW).
    customdata = np.column_stack([capacity / 1000.0, power / 1000.0])
    figure.add_trace(
        go.Scatter3d(
            x=points[:, 0],
            y=points[:, 1],
            z=points[:, 2],
            mode="markers",
            name=f"operating points ({len(points)})",
            marker=dict(size=5, color=COLOR_DATA, symbol="diamond", opacity=1.0),
            customdata=customdata,
            hovertemplate=(
                "evaporator leaving %{x:.2f} K<br>condenser entering %{y:.2f} K<br>"
                "sequence %{z:.0f}<br>net evaporator capacity %{customdata[0]:.1f} kW<br>"
                "input power %{customdata[1]:.1f} kW<extra>operating point</extra>"
            ),
        )
    )

    figure.update_layout(
        paper_bgcolor=PAGE,
        plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK_2),
        legend=dict(
            bgcolor=SURFACE,
            bordercolor=GRID,
            borderwidth=1,
            itemsizing="constant",
            font=dict(color=INK),
        ),
        margin=dict(l=0, r=0, t=10, b=0),
        scene=dict(
            xaxis=dict(title=AXIS_TITLES[0], backgroundcolor=SURFACE, gridcolor=GRID, zerolinecolor=GRID, color=INK_2),
            yaxis=dict(title=AXIS_TITLES[1], backgroundcolor=SURFACE, gridcolor=GRID, zerolinecolor=GRID, color=INK_2),
            zaxis=dict(title=AXIS_TITLES[2], backgroundcolor=SURFACE, gridcolor=GRID, zerolinecolor=GRID, color=INK_2),
            camera=dict(eye=dict(x=1.7, y=1.5, z=1.0)),
            aspectmode="cube",
        ),
    )
    return figure, counts


def _legend_panel(dataset_name: str, counts: dict[str, int]) -> html.Div:
    """On-page panel: which dataset is shown, live zone counts, and what each zone means."""

    def row(color: str, label: str, count: int, meaning: str) -> html.Div:
        swatch = html.Span(
            style={
                "display": "inline-block",
                "width": "14px",
                "height": "14px",
                "borderRadius": "3px",
                "backgroundColor": color,
                "border": "1px solid rgba(11,11,11,0.25)",
                "marginRight": "8px",
                "verticalAlign": "middle",
            }
        )
        return html.Div(
            [
                swatch,
                html.Span(
                    f"{count}",
                    style={
                        "fontWeight": 700,
                        "color": INK,
                        "fontVariantNumeric": "tabular-nums",
                        "minWidth": "34px",
                        "display": "inline-block",
                    },
                ),
                html.Span(f" {label} ", style={"fontWeight": 600, "color": INK}),
                html.Span(f"-- {meaning}", style={"color": INK_2}),
            ],
            style={"margin": "4px 0", "fontSize": "14px"},
        )

    return html.Div(
        [
            html.Div(
                f"{dataset_name}: coverage of {counts['total']} grid nodes "
                "(evaporator leaving x condenser entering x sequence)",
                style={"fontWeight": 700, "color": INK, "marginBottom": "6px", "fontSize": "15px"},
            ),
            row(COLOR_HULL, "inside convex hull", counts["inside_hull"], "safe interpolation between operating points"),
            row(
                COLOR_GAP,
                "inside box only",
                counts["gap_only"],
                "combinations never simulated -- gap-fill, MEDIUM risk (interpolated but unsupported)",
            ),
            row(
                COLOR_OUT,
                "outside bounding box",
                counts["outside_box"],
                "true extrapolation, HIGH risk -- bounded by the data in both datasets",
            ),
        ],
        style={
            "maxWidth": "900px",
            "margin": "10px auto",
            "padding": "12px 16px",
            "backgroundColor": SURFACE,
            "border": "1px solid %s" % GRID,
            "borderRadius": "8px",
            "fontFamily": 'system-ui, -apple-system, "Segoe UI", sans-serif',
        },
    )


def _build_all() -> dict[str, dict]:
    """Load every dataset, build its figure, and cross-check its zones against the package."""
    built: dict[str, dict] = {}
    for name, path in DATASETS.items():
        points, capacity, power, axes = load_data(path)
        figure, counts = build_figure(points, capacity, power, axes)
        package_outside_box, package_outside_hull = package_zone_counts(path)
        package_inside_hull = counts["total"] - package_outside_box - package_outside_hull
        assert counts["outside_box"] == package_outside_box, (name, counts, package_outside_box)
        assert counts["gap_only"] == package_outside_hull, (name, counts, package_outside_hull)
        assert counts["inside_hull"] == package_inside_hull, (name, counts, package_inside_hull)
        built[name] = {"figure": figure, "counts": counts}
    return built


def build_app() -> tuple[Dash, dict[str, dict]]:
    """Build the figures for both datasets and wire the radio control that switches between them."""
    built = _build_all()
    default = next(iter(DATASETS))

    app = Dash(__name__)
    app.title = "Synthetic chiller map: convex hull vs. bounding box"
    app.layout = html.Div(
        [
            html.Div(
                [
                    html.Span(
                        "condenser_liquid_entering_temperature filled with: ",
                        style={"fontWeight": 600, "color": INK, "marginRight": "8px"},
                    ),
                    dcc.RadioItems(
                        id="dataset",
                        options=list(DATASETS),
                        value=default,
                        inline=True,
                        labelStyle={"marginRight": "16px", "color": INK},
                    ),
                ],
                style={
                    "maxWidth": "900px",
                    "margin": "10px auto 0",
                    "fontSize": "14px",
                    "fontFamily": 'system-ui, -apple-system, "Segoe UI", sans-serif',
                },
            ),
            html.Div(id="legend"),
            dcc.Graph(id="scene", style={"height": "72vh"}, config={"displaylogo": False}),
        ],
        style={"backgroundColor": PAGE, "minHeight": "100vh", "padding": "8px"},
    )

    @app.callback(Output("scene", "figure"), Output("legend", "children"), Input("dataset", "value"))
    def _update(dataset_name: str) -> tuple:
        entry = built[dataset_name]
        return entry["figure"], _legend_panel(dataset_name, entry["counts"])

    return app, built


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="build the figures and verify zone counts, then exit without serving"
    )
    arguments = parser.parse_args()

    app, built = build_app()
    for name, entry in built.items():
        counts = entry["counts"]
        print(
            f"{name}: {counts['inside_hull']} inside hull, {counts['gap_only']} gap-fill, "
            f"{counts['outside_box']} outside box (of {counts['total']}) -- cross-check passed"
        )

    if arguments.check:
        return
    print("Starting Dash on http://127.0.0.1:8050/ ...")
    app.run(debug=True)


if __name__ == "__main__":
    main()
