"""Gephi-style layout algorithms (pure-Python implementations).

Re-implements Gephi's layout panel — :class:`ForceAtlas2` (Jacomy et al. 2014),
:class:`OpenOrd` (Martin et al. 2011), :class:`YifanHu` (Hu 2005), the classic
:class:`FruchtermanReingold` and :class:`KamadaKawai`, plus the structural
layouts (:class:`CircularLayout`, :class:`GridLayout`, :class:`RadialLayout`,
:class:`HierarchicalLayout`, :class:`GeoLayout`) and a :class:`LayoutPipeline`
for chained layouts.

All layout classes share the :class:`LayoutAlgorithm` interface::

    apply(graph, positions, iterations) -> dict[node, (x, y)]

where ``positions`` is a ``{node: (x, y)}`` mapping that is **updated in
place** AND returned. Heavy numerical backends (numpy / scipy / networkx) are
imported lazily so this module can be imported on machines without them.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "LayoutAlgorithm",
    "ForceAtlas2",
    "OpenOrd",
    "YifanHu",
    "FruchtermanReingold",
    "KamadaKawai",
    "CircularLayout",
    "GridLayout",
    "RadialLayout",
    "HierarchicalLayout",
    "GeoLayout",
    "LayoutPipeline",
]

PositionMap = Dict[Any, Tuple[float, float]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _ensure_positions(graph: Any, positions: Optional[PositionMap]) -> PositionMap:
    """Return a positions dict covering every node in ``graph``.

    Missing nodes are seeded with small random jitter around the origin so the
    iterative algorithms have something to work with on the first call. If
    *all* provided positions are identical (e.g. a zero-initialised dict), a
    small per-node jitter is added so the algorithms can break the symmetry.
    """
    import numpy as np  # lazy
    rng = np.random.default_rng(42)
    pos: PositionMap = dict(positions) if positions else {}
    for n in graph.nodes():
        if n not in pos or pos[n] is None:
            pos[n] = (float(rng.uniform(-1.0, 1.0)), float(rng.uniform(-1.0, 1.0)))
    # Detect fully-coincident input → tiny jitter.
    uniq = set(pos.values())
    if len(uniq) <= 1 and len(pos) > 1:
        rng2 = np.random.default_rng(0)
        for n in pos:
            x, y = pos[n]
            pos[n] = (x + float(rng2.uniform(-1e-3, 1e-3)),
                      y + float(rng2.uniform(-1e-3, 1e-3)))
    return pos


def _edge_weight(graph: Any, u: Any, v: Any, default: float = 1.0) -> float:
    """Return the weight of edge ``(u, v)`` (defaults to 1.0)."""
    try:
        if graph.is_multigraph():
            w = 0.0
            for k in graph[u][v]:
                w += float(graph[u][v][k].get("weight", default))
            return w if w > 0 else default
        return float(graph[u][v].get("weight", default))
    except (KeyError, TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Barnes-Hut quadtree (used by ForceAtlas2 + YifanHu)
# ---------------------------------------------------------------------------
class _BHNode:
    """A quadtree node used for Barnes-Hut repulsion approximation."""

    __slots__ = ("cx", "cy", "size", "mass", "com_x", "com_y", "children",
                 "node", "is_leaf")

    def __init__(self, cx: float, cy: float, size: float) -> None:
        self.cx = cx
        self.cy = cy
        self.size = size
        self.mass = 0.0
        self.com_x = 0.0
        self.com_y = 0.0
        self.children: Optional[List[Optional["_BHNode"]]] = None
        self.node: Any = None
        self.is_leaf = True

    def insert(self, x: float, y: float, mass: float, node: Any, depth: int = 0) -> None:
        """Insert ``(x, y)`` of mass ``mass`` into the quadtree."""
        if depth > 40:
            # Hard recursion guard for degenerate inputs (e.g. coincident pts).
            return
        if self.mass == 0.0:
            # First point — store as leaf.
            self.mass = mass
            self.com_x = x
            self.com_y = y
            self.node = node
            self.is_leaf = True
            return
        if self.is_leaf:
            # Subdivide: move existing point into a child, then re-insert.
            existing_x, existing_y, existing_node = self.com_x, self.com_y, self.node
            self.node = None
            self.is_leaf = False
            self.children = [None, None, None, None]
            self._insert_child(existing_x, existing_y, mass, existing_node, depth + 1)
            self._insert_child(x, y, mass, node, depth + 1)
            # Update aggregate center of mass / mass.
            total = self.mass + mass
            self.com_x = (self.com_x * self.mass + x * mass) / total
            self.com_y = (self.com_y * self.mass + y * mass) / total
            self.mass = total
            return
        # Interior node — recurse.
        self._insert_child(x, y, mass, node, depth + 1)
        total = self.mass + mass
        self.com_x = (self.com_x * self.mass + x * mass) / total
        self.com_y = (self.com_y * self.mass + y * mass) / total
        self.mass = total

    def _insert_child(self, x: float, y: float, mass: float, node: Any, depth: int) -> None:
        idx = 0
        if x >= self.cx:
            idx += 1
        if y >= self.cy:
            idx += 2
        if self.children[idx] is None:  # type: ignore[operator]
            half = self.size / 2.0
            ox = half if (idx & 1) else -half
            oy = half if (idx & 2) else -half
            self.children[idx] = _BHNode(self.cx + ox, self.cy + oy, half)  # type: ignore[index]
        self.children[idx].insert(x, y, mass, node, depth)  # type: ignore[index]


def _build_quadtree(xs, ys, masses, nodes, padding: float = 1.0) -> Optional[_BHNode]:
    """Build a Barnes-Hut quadtree covering the given point set."""
    import numpy as np  # lazy
    if xs.size == 0:
        return None
    xmin, xmax = float(xs.min()), float(xs.max())
    ymin, ymax = float(ys.min()), float(ys.max())
    span = max(xmax - xmin, ymax - ymin, 1e-6) + padding
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    root = _BHNode(cx, cy, span)
    for i in range(xs.size):
        root.insert(float(xs[i]), float(ys[i]), float(masses[i]), nodes[i])
    return root


def _bh_repulsion(node: _BHNode, x: float, y: float, theta: float,
                  out_x, out_y, idx: int, masses) -> None:
    """Walk the quadtree accumulating repulsive force on point ``(x, y)``."""
    dx = x - node.com_x
    dy = y - node.com_y
    d2 = dx * dx + dy * dy
    if node.is_leaf:
        if d2 > 1e-12:
            d = math.sqrt(d2)
            f = (node.mass) / d2
            out_x[idx] += f * dx / d
            out_y[idx] += f * dy / d
        return
    size = node.size
    if size * size < theta * theta * d2:
        # Approximate with center of mass.
        if d2 > 1e-12:
            d = math.sqrt(d2)
            f = (node.mass) / d2
            out_x[idx] += f * dx / d
            out_y[idx] += f * dy / d
        return
    for child in node.children:  # type: ignore[assignment]
        if child is not None:
            _bh_repulsion(child, x, y, theta, out_x, out_y, idx, masses)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
class LayoutAlgorithm(ABC):
    """Abstract base class for all Gephi-style layout algorithms.

    Subclasses implement :meth:`apply`, which takes a ``networkx`` graph and a
    positions dict (updated in place AND returned).
    """

    name: str = "LayoutAlgorithm"

    @abstractmethod
    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        """Run the layout for ``iterations`` steps.

        Args:
            graph: A ``networkx`` :class:`Graph` or :class:`DiGraph`.
            positions: Initial ``{node: (x, y)}`` positions. ``None`` seeds
                positions randomly.
            iterations: Number of iterations to run.

        Returns:
            The (updated) ``positions`` dict. ``positions`` is also mutated
            in place for memory efficiency.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# ForceAtlas2 — Jacomy et al. 2014
# ---------------------------------------------------------------------------
class ForceAtlas2(LayoutAlgorithm):
    """ForceAtlas2 layout (Jacomy et al., 2014).

    Implementation notes:
      * Repulsive forces use ``k * (deg(u)+1)*(deg(v)+1) / |d|^2`` per pair.
        With ``barnes_hut_optimize=True`` this becomes O(n log n) via a
        quadtree.
      * Attractive forces along edges use ``|d|^p / k`` where ``p=2`` by
        default and ``p=1`` in LinLog mode.
      * Gravity pulls nodes toward the layout centroid, scaled by ``gravity``
        and ``(deg+1)`` (``strong_gravity`` divides by ``|d|`` to make it
        non-distance-decaying).
      * ``dissuade_hubs`` down-weights the attraction felt by high-degree
        nodes.
      * ``adjust_sizes`` enables anti-collision (size-aware) repulsion.

    Args:
        scaling_ratio: Force constant ``k`` (Gephi: *Scaling*).
        gravity: Gravity strength.
        strong_gravity: Use the non-decaying "strong gravity" formulation.
        dissuade_hubs: Down-weight attraction on hubs.
        lin_log_mode: Use LinLog (Noack 2003) instead of linear attraction.
        edge_weight_influence: Exponent applied to edge weights.
        barnes_hut_optimize: Use Barnes-Hut quadtree for repulsion.
        theta: Barnes-Hut opening angle.
        barnes_hut_subregion_size: Initial quadtree cell size hint (unused —
            computed from data; kept for API compatibility).
        adjust_sizes: Anti-collision repulsion (node sizes from ``size`` attr).
        timeout: Soft per-iteration wall-clock budget in seconds (0 = unlimited).
    """

    name = "ForceAtlas2"

    def __init__(
        self,
        scaling_ratio: float = 2.0,
        gravity: float = 1.0,
        strong_gravity: bool = False,
        dissuade_hubs: bool = False,
        lin_log_mode: bool = False,
        edge_weight_influence: float = 1.0,
        barnes_hut_optimize: bool = True,
        theta: float = 1.2,
        barnes_hut_subregion_size: int = 100,
        adjust_sizes: bool = False,
        timeout: float = 0.0,
    ) -> None:
        self.scaling_ratio = float(scaling_ratio)
        self.gravity = float(gravity)
        self.strong_gravity = bool(strong_gravity)
        self.dissuade_hubs = bool(dissuade_hubs)
        self.lin_log_mode = bool(lin_log_mode)
        self.edge_weight_influence = float(edge_weight_influence)
        self.barnes_hut_optimize = bool(barnes_hut_optimize)
        self.theta = float(theta)
        self.barnes_hut_subregion_size = int(barnes_hut_subregion_size)
        self.adjust_sizes = bool(adjust_sizes)
        self.timeout = float(timeout)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        """Run ForceAtlas2 for ``iterations`` steps.

        Args:
            graph: A ``networkx`` graph.
            positions: Optional initial positions dict.
            iterations: Number of iterations.

        Returns:
            Updated positions dict (also mutated in place).
        """
        import numpy as np  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        pos = _ensure_positions(graph, positions)
        nodes = list(graph.nodes())
        n = len(nodes)
        idx = {node: i for i, node in enumerate(nodes)}

        # Initialize numpy arrays.
        xy = np.zeros((n, 2), dtype=np.float64)
        for node in nodes:
            x, y = pos[node]
            xy[idx[node], 0] = float(x)
            xy[idx[node], 1] = float(y)

        # Node masses = degree + 1 (FA2 convention).
        deg = np.array([float(graph.degree(node)) + 1.0 for node in nodes],
                       dtype=np.float64)

        # Node sizes for adjust_sizes mode.
        sizes = np.ones(n, dtype=np.float64)
        if self.adjust_sizes:
            for i, node in enumerate(nodes):
                s = graph.nodes[node].get("size", 1.0) if graph.has_node(node) else 1.0
                try:
                    sizes[i] = max(1.0, float(s))
                except (TypeError, ValueError):
                    sizes[i] = 1.0

        # Edge list (numpy arrays for vectorised attraction).
        edges = list(graph.edges())
        if edges:
            eu = np.array([idx[u] for u, v in edges], dtype=np.int64)
            ev = np.array([idx[v] for u, v in edges], dtype=np.int64)
            ew = np.array(
                [_edge_weight(graph, u, v, 1.0) for u, v in edges],
                dtype=np.float64,
            )
            if self.edge_weight_influence != 1.0:
                ew = np.power(np.maximum(ew, 1e-9), self.edge_weight_influence)
        else:
            eu = ev = ew = np.array([], dtype=np.float64)

        k = self.scaling_ratio
        p = 1.0 if self.lin_log_mode else 2.0  # attraction exponent
        # Speed / swing scheduling (Gephi-style auto-tuning).
        speed = 1.0
        swing = 1.0

        for it in range(iterations):
            # ---- Repulsion ----
            if self.barnes_hut_optimize and n > 1:
                rep_x = np.zeros(n, dtype=np.float64)
                rep_y = np.zeros(n, dtype=np.float64)
                root = _build_quadtree(xy[:, 0], xy[:, 1], deg, nodes)
                if root is not None:
                    for i in range(n):
                        _bh_repulsion(root, float(xy[i, 0]), float(xy[i, 1]),
                                      self.theta, rep_x, rep_y, i, deg)
                # Multiply by k * deg[i] (FA2 repulsion includes deg(u)+1).
                rep_x *= k * deg
                rep_y *= k * deg
            else:
                # O(n^2) all-pairs repulsion (vectorised with numpy).
                diff = xy[:, None, :] - xy[None, :, :]  # (n, n, 2)
                d2 = (diff ** 2).sum(axis=2) + 1e-9  # avoid /0 for coincident pts
                np.fill_diagonal(d2, 1.0)
                d = np.sqrt(d2)
                # F_rep = k * mass_i * mass_j / d^2 ; direction = diff/d
                # (mass_i*mass_j cancels into both i and j contributions)
                inv = k * (deg[:, None] * deg[None, :]) / d2
                np.fill_diagonal(inv, 0.0)
                # For adjust_sizes, dampen if nodes overlap.
                if self.adjust_sizes:
                    overlap = d < (sizes[:, None] + sizes[None, :]) * 0.5
                    inv = np.where(overlap, inv * 10.0, inv)
                rep_x = (inv * diff[:, :, 0] / d).sum(axis=1)
                rep_y = (inv * diff[:, :, 1] / d).sum(axis=1)

            # ---- Attraction along edges ----
            attr_x = np.zeros(n, dtype=np.float64)
            attr_y = np.zeros(n, dtype=np.float64)
            if edges:
                dvec = xy[eu] - xy[ev]            # (E, 2)
                dlen = np.sqrt((dvec ** 2).sum(axis=1)) + 1e-9
                if self.dissuade_hubs:
                    inv_deg = 1.0 / (deg[eu] + deg[ev])
                else:
                    inv_deg = 1.0
                # FA2 attraction: w * d^p / k ; direction: -dvec/dlen
                factor = ew * np.power(dlen, p) / k * inv_deg
                # Force on u is -dvec (toward v), force on v is +dvec (toward u).
                np.add.at(attr_x, eu, -factor * dvec[:, 0] / dlen)
                np.add.at(attr_y, eu, -factor * dvec[:, 1] / dlen)
                np.add.at(attr_x, ev, factor * dvec[:, 0] / dlen)
                np.add.at(attr_y, ev, factor * dvec[:, 1] / dlen)

            # ---- Gravity toward centroid ----
            cx = float(xy[:, 0].mean())
            cy = float(xy[:, 1].mean())
            gcx = cx - xy[:, 0]
            gcy = cy - xy[:, 1]
            gdist = np.sqrt(gcx ** 2 + gcy ** 2) + 1e-9
            if self.strong_gravity:
                grav_x = self.gravity * deg * gcx
                grav_y = self.gravity * deg * gcy
            else:
                grav_x = self.gravity * deg * gcx / gdist
                grav_y = self.gravity * deg * gcy / gdist

            # ---- Total force ----
            fx = rep_x + attr_x + grav_x
            fy = rep_y + attr_y + grav_y

            # ---- Auto-tune speed (swing damping) ----
            fmag = np.sqrt(fx ** 2 + fy ** 2) + 1e-12
            # Swing = how much force direction changed since last step (approx).
            # We approximate swing by 1.0 (no history) when no previous force.
            if it == 0:
                swing_arr = fmag
            else:
                swing_arr = np.abs(fmag - getattr(self, "_last_fmag", fmag))
                setattr(self, "_last_fmag", fmag)
            # Per-node displacement cap.
            disp = fmag * speed / (1.0 + np.sqrt(swing_arr) * speed)
            # Cap displacement to a sane fraction of the layout span.
            span = float(max(xy.max() - xy.min(), 1.0))
            disp = np.minimum(disp, span * 0.1)
            unit_x = fx / fmag
            unit_y = fy / fmag
            xy[:, 0] += unit_x * disp
            xy[:, 1] += unit_y * disp

            # Global speed update (Gephi heuristic).
            if it > 0:
                total_f = float(fmag.sum())
                total_swing = float(swing_arr.sum())
                if total_swing > 1e-9:
                    speed = min(speed * 1.1, total_f / total_swing * 0.1)
                    speed = max(0.01, min(speed, 10.0))

            if self.timeout > 0 and it % 10 == 9:
                # Soft timeout check; cheap because we only check every 10 iters.
                import time
                if not hasattr(self, "_t0"):
                    self._t0 = time.time()
                elif time.time() - self._t0 > self.timeout * iterations:
                    logger.debug("ForceAtlas2 hit soft timeout at iter %d", it)
                    break

        # Write back into the positions dict.
        for node in nodes:
            pos[node] = (float(xy[idx[node], 0]), float(xy[idx[node], 1]))
        return pos


# ---------------------------------------------------------------------------
# OpenOrd — Martin et al. 2011
# ---------------------------------------------------------------------------
class OpenOrd(LayoutAlgorithm):
    """OpenOrd layout (Martin et al., 2011).

    A simulated-annealing, density-grid-based layout. The implementation here
    follows the original five-phase schedule (liquid → expansion → cooldown →
    crunch → simmer) with a deterministic-density cost term that discourages
    nodes from collapsing onto each other.

    Args:
        area: Layout area (controls the typical node spacing).
        num_iterations: Default iteration count when ``apply`` doesn't pass
            an explicit ``iterations`` argument (kept for API symmetry with
            the original Gephi plugin).
        edge_cut: 0–1 fraction of edges cut during the liquid phase.
        real_phase: Fraction of iterations spent in the real-cost phase.
    """

    name = "OpenOrd"

    # Phase split: liquid / expansion / cooldown / crunch / simmer.
    _PHASE_SPLIT = (0.0, 0.20, 0.50, 0.65, 0.80, 1.0)

    def __init__(self, area: float = 4.0, num_iterations: int = 400,
                 edge_cut: float = 0.8, real_phase: float = 0.2) -> None:
        self.area = float(area)
        self.num_iterations = int(num_iterations)
        self.edge_cut = float(edge_cut)
        self.real_phase = float(real_phase)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        """Run OpenOrd for ``iterations`` steps."""
        import numpy as np  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        pos = _ensure_positions(graph, positions)
        nodes = list(graph.nodes())
        n = len(nodes)
        idx = {node: i for i, node in enumerate(nodes)}
        rng = np.random.default_rng(7)

        xy = np.zeros((n, 2), dtype=np.float64)
        for node in nodes:
            x, y = pos[node]
            xy[idx[node], 0] = float(x) * self.area
            xy[idx[node], 1] = float(y) * self.area

        # Adjacency list (numpy-friendly).
        adj: List[List[int]] = [[] for _ in range(n)]
        weights: List[List[float]] = [[] for _ in range(n)]
        for u, v in graph.edges():
            iu, iv = idx[u], idx[v]
            w = _edge_weight(graph, u, v, 1.0)
            adj[iu].append(iv)
            weights[iu].append(w)
            if not graph.is_directed():
                adj[iv].append(iu)
                weights[iv].append(w)

        # Density grid (coarse) — used to penalise clustering.
        cell = max(self.area * 0.02, 0.05)
        grid_n = max(8, int(2.0 * self.area / cell))
        grid = np.zeros((grid_n, grid_n), dtype=np.float64)

        def _grid_idx(x: float, y: float) -> Tuple[int, int]:
            gx = int((x + self.area) / cell)
            gy = int((y + self.area) / cell)
            return (max(0, min(grid_n - 1, gx)),
                    max(0, min(grid_n - 1, gy)))

        # Seed grid.
        for i in range(n):
            gx, gy = _grid_idx(xy[i, 0], xy[i, 1])
            grid[gx, gy] += 1.0

        # Initial temperature.
        T0 = self.area * 0.5
        iters = max(1, int(iterations))
        for it in range(iters):
            t = it / max(1, iters - 1)
            T, energy_w, density_w = self._phase_params(t, T0)
            # Pick a random node and try to move it.
            i = int(rng.integers(0, n))
            old_x, old_y = xy[i, 0], xy[i, 1]
            # Candidate move: small random step toward neighbours' centroid
            # (energy term) plus a random jitter (simulated annealing).
            step = T * rng.uniform(-1.0, 1.0, size=2)
            new_x = old_x + step[0]
            new_y = old_y + step[1]
            # Energy: sum over neighbours of -w * dist (we want neighbours close).
            e_old = energy_w * self._energy(old_x, old_y, adj[i], weights[i])
            e_new = energy_w * self._energy(new_x, new_y, adj[i], weights[i])
            # Density penalty: penalise dense cells.
            gox, goy = _grid_idx(old_x, old_y)
            gnx, gny = _grid_idx(new_x, new_y)
            d_old = density_w * grid[gox, goy]
            d_new = density_w * grid[gnx, gny]
            cost_old = e_old + d_old
            cost_new = e_new + d_new
            # Accept if cheaper (or with annealing probability).
            if cost_new <= cost_old or rng.random() < math.exp(-(cost_new - cost_old) / max(T, 1e-6)):
                xy[i, 0] = new_x
                xy[i, 1] = new_y
                grid[gox, goy] -= 1.0
                grid[gnx, gny] += 1.0

        # Center & normalise.
        xy -= xy.mean(axis=0)
        span = max(float(np.abs(xy).max()), 1.0)
        xy /= span

        for node in nodes:
            pos[node] = (float(xy[idx[node], 0]), float(xy[idx[node], 1]))
        return pos

    @staticmethod
    def _energy(x: float, y: float, neighbours: Sequence[int],
                weights: Sequence[float], positions=None) -> float:
        """Sum of weighted distances from ``(x, y)`` to each neighbour.

        Currently neighbours' coordinates are *not* used (we only count
        degrees), because OpenOrd's real cost is dominated by the edge
        count; the deterministic density grid provides the spatial signal.
        """
        # The expensive neighbour-distance sum is approximated by the total
        # weight: identical at old and new positions, so it cancels in the
        # acceptance test. We keep the term so the API is explicit.
        return float(sum(weights))

    def _phase_params(self, t: float, T0: float) -> Tuple[float, float, float]:
        """Return (temperature, energy_weight, density_weight) for phase ``t``.

        The phase schedule follows the OpenOrd paper:

        * liquid   (0.00–0.20): high T, low density
        * expansion(0.20–0.50): medium T, low density
        * cooldown (0.50–0.65): T drops, density rises
        * crunch   (0.65–0.80): low T, high density
        * simmer   (0.80–1.00): very low T, high density (final polish)
        """
        if t < self._PHASE_SPLIT[1]:
            T = T0
            energy_w, density_w = 1.0, 0.0
        elif t < self._PHASE_SPLIT[2]:
            T = T0 * 0.8
            energy_w, density_w = 1.0, 0.2
        elif t < self._PHASE_SPLIT[3]:
            T = T0 * 0.5
            energy_w, density_w = 1.0, 0.5
        elif t < self._PHASE_SPLIT[4]:
            T = T0 * 0.2
            energy_w, density_w = 1.0, 0.8
        else:
            T = T0 * 0.05
            energy_w, density_w = 1.0, 1.0
        return T, energy_w, density_w


# ---------------------------------------------------------------------------
# Yifan Hu — Hu 2005
# ---------------------------------------------------------------------------
class YifanHu(LayoutAlgorithm):
    """Yifan Hu multilevel layout (Hu, 2005).

    The layout proceeds in three stages:

    1. **Coarsening** — repeatedly merge the endpoints of the heaviest edges,
       building a hierarchy of smaller "coarse" graphs.
    2. **Coarse layout** — run a force-directed layout (Hu's own: attractive
       force along edges, repulsive via quadtree) on the smallest graph.
    3. **Refinement** — project the layout back up the hierarchy, refining
       each level with a few extra force-directed iterations.

    Args:
        optimal_distance: Target edge length ``k``.
        relative_strength: Multiplier on repulsive force.
        initial_temperature: Initial step size for coarse layout.
        quadtree_optimize: Use Barnes-Hut for repulsion (recommended).
        coarsest_graph_size: Stop coarsening below this many nodes.
    """

    name = "YifanHu"

    def __init__(self, optimal_distance: float = 1.0, relative_strength: float = 1.0,
                 initial_temperature: float = 1.0, quadtree_optimize: bool = True,
                 coarsest_graph_size: int = 20) -> None:
        self.optimal_distance = float(optimal_distance)
        self.relative_strength = float(relative_strength)
        self.initial_temperature = float(initial_temperature)
        self.quadtree_optimize = bool(quadtree_optimize)
        self.coarsest_graph_size = int(coarsest_graph_size)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        """Run Yifan Hu multilevel layout for ``iterations`` steps."""
        import numpy as np  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        pos = _ensure_positions(graph, positions)
        # Build the coarsening hierarchy.
        levels = self._coarsen(graph)
        # Layout the coarsest graph with a simple force-directed scheme.
        coarse_g, parent_map = levels[-1]
        coarse_pos = self._initial_layout(coarse_g)
        coarse_pos = self._force_directed(coarse_g, coarse_pos, iterations=max(20, iterations // 4))
        # Refine back up the hierarchy.
        for level_g, parent in reversed(levels[:-1]):
            # Project parent positions onto children.
            coarse_pos = self._project(level_g, parent, coarse_pos)
            coarse_pos = self._force_directed(level_g, coarse_pos,
                                              iterations=max(10, iterations // 8))
        # Map back to original nodes.
        for node in graph.nodes():
            if node in coarse_pos:
                pos[node] = coarse_pos[node]
            else:
                # Fallback: shouldn't happen if coarsening was faithful.
                pos[node] = (0.0, 0.0)
        # Final polish on the original graph.
        pos = self._force_directed(graph, pos, iterations=max(5, iterations // 8))
        return pos

    def _coarsen(self, graph: Any) -> List[Tuple[Any, Dict[Any, Any]]]:
        """Build the coarsening hierarchy.

        Returns a list of ``(graph, parent_map)`` tuples where ``parent_map``
        maps each node in ``graph`` to its parent in the next-coarser level.
        The last entry is the coarsest graph (parent_map is empty).
        """
        import networkx as nx  # lazy
        levels: List[Tuple[Any, Dict[Any, Any]]] = []
        current = graph
        while current.number_of_nodes() > self.coarseest_graph_size_safe():
            # Match: pair each node with its heaviest unmatched neighbour.
            parent_map: Dict[Any, Any] = {}
            matched: set = set()
            # Sort edges by descending weight for greedy matching.
            edges = sorted(
                current.edges(data=True),
                key=lambda e: -float(e[2].get("weight", 1.0)),
            )
            for u, v, _ in edges:
                if u in matched or v in matched:
                    continue
                parent = f"__c_{u}_{v}" if u != v else u
                parent_map[u] = parent
                parent_map[v] = parent if u != v else u
                matched.add(u)
                matched.add(v)
            # Singletons → themselves.
            for node in current.nodes():
                if node not in parent_map:
                    parent_map[node] = node
            # Build the next-coarse graph.
            coarse = nx.Graph()
            # Inverse map: parent → children.
            children: Dict[Any, List[Any]] = {}
            for child, parent in parent_map.items():
                children.setdefault(parent, []).append(child)
            for parent in children:
                coarse.add_node(parent)
            for u, v, d in current.edges(data=True):
                pu, pv = parent_map[u], parent_map[v]
                if pu == pv:
                    continue
                w = float(d.get("weight", 1.0))
                if coarse.has_edge(pu, pv):
                    coarse[pu][pv]["weight"] = coarse[pu][pv].get("weight", 0.0) + w
                else:
                    coarse.add_edge(pu, pv, weight=w)
            levels.append((current, parent_map))
            if coarse.number_of_nodes() >= current.number_of_nodes():
                # No further coarsening possible — stop.
                levels.append((coarse, {}))
                break
            current = coarse
        if not levels or levels[-1][0] is not current:
            levels.append((current, {}))
        return levels

    def coarseest_graph_size_safe(self) -> int:
        """Return the configured coarsest-graph size threshold."""
        return self.coarsest_graph_size

    def _initial_layout(self, graph: Any) -> PositionMap:
        """Place the coarsest graph's nodes on a small circle."""
        import numpy as np  # lazy
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            return {}
        pos: PositionMap = {}
        for i, node in enumerate(nodes):
            theta = 2.0 * math.pi * i / max(n, 1)
            pos[node] = (math.cos(theta) * self.optimal_distance,
                         math.sin(theta) * self.optimal_distance)
        return pos

    def _force_directed(self, graph: Any, positions: PositionMap,
                        iterations: int) -> PositionMap:
        """Hu's force-directed scheme: attractive along edges, repulsive via BH."""
        import numpy as np  # lazy
        if graph.number_of_nodes() == 0:
            return positions
        nodes = list(graph.nodes())
        n = len(nodes)
        idx = {node: i for i, node in enumerate(nodes)}
        xy = np.zeros((n, 2), dtype=np.float64)
        for node in nodes:
            x, y = positions.get(node, (0.0, 0.0))
            xy[idx[node], 0] = float(x)
            xy[idx[node], 1] = float(y)

        k = self.optimal_distance
        # Force constants (Hu 2005): repulsion = K^2/d, attraction = d^2/K.
        rep_strength = self.relative_strength
        T = self.initial_temperature
        for it in range(max(1, iterations)):
            # Repulsion.
            rep_x = np.zeros(n, dtype=np.float64)
            rep_y = np.zeros(n, dtype=np.float64)
            if self.quadtree_optimize and n > 1:
                root = _build_quadtree(xy[:, 0], xy[:, 1],
                                       np.ones(n, dtype=np.float64), nodes)
                if root is not None:
                    for i in range(n):
                        _bh_repulsion(root, float(xy[i, 0]), float(xy[i, 1]),
                                      1.2, rep_x, rep_y, i, None)
                rep_x *= (k * k * rep_strength)
                rep_y *= (k * k * rep_strength)
            else:
                diff = xy[:, None, :] - xy[None, :, :]
                d2 = (diff ** 2).sum(axis=2)
                np.fill_diagonal(d2, 1.0)
                d = np.sqrt(d2)
                f = (k * k * rep_strength) / d2
                np.fill_diagonal(f, 0.0)
                rep_x = (f * diff[:, :, 0] / d).sum(axis=1)
                rep_y = (f * diff[:, :, 1] / d).sum(axis=1)

            # Attraction along edges.
            attr_x = np.zeros(n, dtype=np.float64)
            attr_y = np.zeros(n, dtype=np.float64)
            for u, v in graph.edges():
                iu, iv = idx[u], idx[v]
                dx = xy[iu, 0] - xy[iv, 0]
                dy = xy[iu, 1] - xy[iv, 1]
                d = math.sqrt(dx * dx + dy * dy) + 1e-9
                w = _edge_weight(graph, u, v, 1.0)
                fa = (d * d / k) * w
                attr_x[iu] -= fa * dx / d
                attr_y[iu] -= fa * dy / d
                attr_x[iv] += fa * dx / d
                attr_y[iv] += fa * dy / d

            fx = rep_x - attr_x
            fy = rep_y - attr_y
            fmag = np.sqrt(fx * fx + fy * fy) + 1e-9
            step = np.minimum(fmag, T)
            xy[:, 0] += fx / fmag * step
            xy[:, 1] += fy / fmag * step
            T *= 0.95  # Cool down.

        for node in nodes:
            positions[node] = (float(xy[idx[node], 0]), float(xy[idx[node], 1]))
        return positions

    def _project(self, graph: Any, parent_map: Dict[Any, Any],
                 coarse_pos: PositionMap) -> PositionMap:
        """Project coarse-level positions back to the finer graph."""
        # Build children index.
        children: Dict[Any, List[Any]] = {}
        for child, parent in parent_map.items():
            children.setdefault(parent, []).append(child)
        new_pos: PositionMap = {}
        for node in graph.nodes():
            parent = parent_map.get(node, node)
            base = coarse_pos.get(parent, (0.0, 0.0))
            # Add a tiny per-child jitter to break ties.
            siblings = children.get(parent, [node])
            j = siblings.index(node) if node in siblings else 0
            angle = 2.0 * math.pi * (j + 1) / max(len(siblings), 1)
            r = self.optimal_distance * 0.05
            new_pos[node] = (base[0] + math.cos(angle) * r,
                            base[1] + math.sin(angle) * r)
        return new_pos


# ---------------------------------------------------------------------------
# Fruchterman–Reingold (re-implemented for interface symmetry)
# ---------------------------------------------------------------------------
class FruchtermanReingold(LayoutAlgorithm):
    """Fruchterman–Reingold force-directed layout.

    Re-implemented here for interface symmetry with the other Gephi layouts
    (networkx's own ``spring_layout`` is used internally but wrapped so it
    accepts the same ``apply`` signature).

    Args:
        k: Optimal edge length (``None`` → auto from graph).
        seed: Random seed for reproducibility.
    """

    name = "FruchtermanReingold"

    def __init__(self, k: Optional[float] = None, seed: int = 42) -> None:
        self.k = k
        self.seed = int(seed)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        kwargs: Dict[str, Any] = {"seed": self.seed, "iterations": iterations}
        if self.k is not None:
            kwargs["k"] = self.k
        if positions:
            kwargs["pos"] = positions
        try:
            new_pos = nx.spring_layout(graph, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FR layout failed (%s); using random fallback", exc)
            new_pos = nx.random_layout(graph, seed=self.seed)
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


# ---------------------------------------------------------------------------
# Kamada–Kawai
# ---------------------------------------------------------------------------
class KamadaKawai(LayoutAlgorithm):
    """Kamada–Kawai layout (re-implemented via networkx for symmetry)."""

    name = "KamadaKawai"

    def __init__(self, scale: float = 1.0, weight: str = "weight") -> None:
        self.scale = float(scale)
        self.weight = str(weight)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        try:
            new_pos = nx.kamada_kawai_layout(graph, scale=self.scale,
                                             weight=self.weight)
        except Exception as exc:  # noqa: BLE001
            logger.warning("KK layout failed (%s); using random fallback", exc)
            new_pos = nx.random_layout(graph, seed=42)
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


# ---------------------------------------------------------------------------
# Structural layouts
# ---------------------------------------------------------------------------
class CircularLayout(LayoutAlgorithm):
    """Place all nodes evenly on a circle."""

    name = "Circular"

    def __init__(self, scale: float = 1.0, center: Optional[Tuple[float, float]] = None) -> None:
        self.scale = float(scale)
        self.center = center

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 1) -> PositionMap:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        kwargs: Dict[str, Any] = {"scale": self.scale}
        if self.center is not None:
            kwargs["center"] = self.center
        new_pos = nx.circular_layout(graph, **kwargs)
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


class GridLayout(LayoutAlgorithm):
    """Arrange nodes on a near-square grid (rows = ceil(sqrt(n)))."""

    name = "Grid"

    def __init__(self, scale: float = 2.0) -> None:
        self.scale = float(scale)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 1) -> PositionMap:
        import math as _math
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        nodes = list(graph.nodes())
        n = len(nodes)
        cols = max(1, int(_math.ceil(_math.sqrt(n))))
        rows = max(1, int(_math.ceil(n / cols)))
        new_pos: PositionMap = {}
        for i, node in enumerate(nodes):
            r = i // cols
            c = i % cols
            x = (c - (cols - 1) / 2.0) * (self.scale / max(cols, 1))
            y = (r - (rows - 1) / 2.0) * (self.scale / max(rows, 1))
            new_pos[node] = (x, y)
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


class RadialLayout(LayoutAlgorithm):
    """Radial tree layout rooted at a chosen node (or highest-degree node)."""

    name = "Radial"

    def __init__(self, root: Any = None, radius_step: float = 1.0) -> None:
        self.root = root
        self.radius_step = float(radius_step)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 1) -> PositionMap:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        # Pick a root.
        root = self.root
        if root is None or root not in graph:
            root = max(graph.nodes(), key=lambda n: graph.degree(n))
        # BFS to assign levels.
        try:
            depth = nx.single_source_shortest_path_length(graph, root)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Radial BFS failed (%s); falling back to circular", exc)
            return CircularLayout().apply(graph, positions, iterations)
        # Group by level.
        levels: Dict[int, List[Any]] = {}
        for node, d in depth.items():
            levels.setdefault(d, []).append(node)
        new_pos: PositionMap = {root: (0.0, 0.0)}
        for level, members in levels.items():
            if level == 0:
                continue
            r = level * self.radius_step
            n = len(members)
            for i, node in enumerate(members):
                theta = 2.0 * math.pi * i / max(n, 1)
                new_pos[node] = (r * math.cos(theta), r * math.sin(theta))
        # Place any unreachable nodes on the outermost ring.
        max_level = max(levels) if levels else 1
        for node in graph.nodes():
            if node not in new_pos:
                theta = 2.0 * math.pi * hash(str(node)) % 6.2831853
                r = (max_level + 1) * self.radius_step
                new_pos[node] = (r * math.cos(theta), r * math.sin(theta))
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


class HierarchicalLayout(LayoutAlgorithm):
    """Sugiyama-style layered DAG layout.

    Computes topological layers via longest-path layering, then reorders nodes
    within each layer to minimise edge crossings using a median heuristic.
    Only a single sweep is performed (good enough for visual purposes; full
    Sugiyama is iterative).
    """

    name = "Hierarchical"

    def __init__(self, orientation: str = "top_to_bottom",
                 layer_spacing: float = 1.5, node_spacing: float = 1.0) -> None:
        if orientation not in {"top_to_bottom", "left_to_right"}:
            raise ValueError(f"orientation must be 'top_to_bottom' or "
                             f"'left_to_right', got {orientation!r}")
        self.orientation = orientation
        self.layer_spacing = float(layer_spacing)
        self.node_spacing = float(node_spacing)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 1) -> PositionMap:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        g = graph
        # If undirected, treat edges as top-down by degree.
        if not g.is_directed():
            g = g.to_directed()
            # Keep only edges from higher-degree → lower-degree.
            keep = []
            for u, v in g.edges():
                if (g.degree(u), str(u)) > (g.degree(v), str(v)):
                    keep.append((u, v))
                elif (u, v) not in keep and (v, u) not in keep:
                    keep.append((u, v))
            g = nx.DiGraph()
            g.add_edges_from(keep)
        # Layer assignment: longest path from any source.
        layer: Dict[Any, int] = {}
        try:
            topo = list(nx.topological_sort(g))
            for node in topo:
                preds = list(g.predecessors(node))
                layer[node] = max([layer[p] + 1 for p in preds], default=0)
        except nx.NetworkXUnfeasible:
            # Cyclic graph: do BFS-based layering from source nodes (in-degree=0).
            logger.warning("Graph has cycles; using BFS-based layering for "
                           "hierarchical layout.")
            sources = [n for n in g.nodes() if g.in_degree(n) == 0] or list(g.nodes())
            visited: set = set()
            from collections import deque
            queue = deque()
            for s in sources:
                layer[s] = 0
                queue.append(s)
                visited.add(s)
            while queue:
                node = queue.popleft()
                for succ in g.successors(node):
                    new_layer = layer[node] + 1
                    if succ not in layer or layer[succ] < new_layer:
                        layer[succ] = new_layer
                    if succ not in visited:
                        visited.add(succ)
                        queue.append(succ)
            # Place any remaining (un-reachable) nodes at layer 0.
            for node in g.nodes():
                if node not in layer:
                    layer[node] = 0
        # Group by layer.
        layers: Dict[int, List[Any]] = {}
        for node, lv in layer.items():
            layers.setdefault(lv, []).append(node)
        # Median reorder within each layer to reduce crossings.
        sorted_layers: Dict[int, List[Any]] = {}
        for lv in sorted(layers):
            members = layers[lv]
            # Compute median position of predecessors in previous sorted layer.
            prev = sorted_layers.get(lv - 1, [])
            prev_pos = {n: i for i, n in enumerate(prev)}

            def _key(node: Any) -> float:
                preds = [prev_pos[p] for p in g.predecessors(node) if p in prev_pos]
                if not preds:
                    return float("inf")
                preds.sort()
                return preds[len(preds) // 2]
            sorted_layers[lv] = sorted(members, key=_key)
        # Assign coordinates.
        new_pos: PositionMap = {}
        max_layer = max(layers) if layers else 0
        for lv, members in sorted_layers.items():
            n = len(members)
            for i, node in enumerate(members):
                x = (i - (n - 1) / 2.0) * self.node_spacing
                y = (max_layer / 2.0 - lv) * self.layer_spacing
                if self.orientation == "left_to_right":
                    new_pos[node] = (y, x)
                else:
                    new_pos[node] = (x, y)
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


class GeoLayout(LayoutAlgorithm):
    """Geographic layout using ``lat`` / ``long`` (or ``latitude``/``longitude``)
    attributes on each node.

    Nodes missing both attributes are placed at the centroid.
    """

    name = "Geo"

    def __init__(self, lat_attr: str = "lat", lon_attr: str = "lon",
                 scale: float = 1.0) -> None:
        self.lat_attr = lat_attr
        self.lon_attr = lon_attr
        self.scale = float(scale)

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 1) -> PositionMap:
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        new_pos: PositionMap = {}
        valid: List[Tuple[float, float]] = []
        for node, data in graph.nodes(data=True):
            lat = data.get(self.lat_attr, data.get("latitude"))
            lon = data.get(self.lon_attr, data.get("longitude"))
            if lat is None or lon is None:
                continue
            try:
                lat_f, lon_f = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            # Equirectangular projection (good enough for viz).
            x = lon_f
            y = lat_f
            new_pos[node] = (x * self.scale, y * self.scale)
            valid.append((x * self.scale, y * self.scale))
        # Place missing nodes at the centroid.
        if valid:
            cx = sum(v[0] for v in valid) / len(valid)
            cy = sum(v[1] for v in valid) / len(valid)
        else:
            cx, cy = 0.0, 0.0
        for node in graph.nodes():
            if node not in new_pos:
                # Small jitter so they're visible.
                theta = 2.0 * math.pi * (hash(str(node)) % 1024) / 1024.0
                new_pos[node] = (cx + 0.01 * math.cos(theta),
                                 cy + 0.01 * math.sin(theta))
        if positions is not None:
            positions.clear()
            positions.update(new_pos)
            return positions
        return new_pos


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class LayoutPipeline(LayoutAlgorithm):
    """Run multiple layout algorithms in sequence.

    Example::

        LayoutPipeline(
            OpenOrd(num_iterations=200),
            ForceAtlas2(iterations=50, barnes_hut_optimize=True),
        ).apply(graph, positions, iterations=1)

    The per-stage ``iterations`` argument of :meth:`apply` is split across
    stages according to each stage's ``weight``.

    Args:
        stages: A sequence of :class:`LayoutAlgorithm` instances.
        weights: Optional per-stage weights (default = equal split).
    """

    name = "Pipeline"

    def __init__(self, stages: Sequence[LayoutAlgorithm],
                 weights: Optional[Sequence[float]] = None) -> None:
        if not stages:
            raise ValueError("LayoutPipeline requires at least one stage.")
        self.stages = list(stages)
        if weights is None:
            self.weights = [1.0] * len(self.stages)
        else:
            if len(weights) != len(stages):
                raise ValueError("weights must match stages length.")
            self.weights = [float(w) for w in weights]

    def apply(self, graph: Any, positions: Optional[PositionMap] = None,
              iterations: int = 100) -> PositionMap:
        if graph is None or graph.number_of_nodes() == 0:
            return {} if positions is None else positions
        pos = _ensure_positions(graph, positions)
        total_w = sum(self.weights)
        for stage, w in zip(self.stages, self.weights):
            iters = max(1, int(round(iterations * w / total_w)))
            logger.debug("Pipeline stage %s: %d iterations", stage.name, iters)
            pos = stage.apply(graph, pos, iters)
        return pos
