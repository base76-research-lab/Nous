"""
generate_brain_template.py -- one-time offline asset generation for the
"Living Tractograph" brain visualization (Nous, 2026-08-25).

Voxelizes the real anatomical GLB brain model, flood-fills its interior,
and tags each candidate point with the nearest of the 11 named anatomical
regions already used by brain_view.js (REGIONS dict). Writes a compact
JSON asset of candidate positions + region ids that the frontend samples
from when placing the graph's real concept nodes.

Coordinate frame: matches EXACTLY the transform brain_view.js applies to
the GLB at render time (loadAnatomicalBrainModel(): center at origin,
uniform scale to contain-fit a 220x187x264 envelope) -- so template points
line up with the already-displayed mesh without any frontend-side
re-alignment.

Usage:
    uv run --extra brain_template python scripts/generate_brain_template.py

Regenerate only if the GLB model changes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parent.parent
GLB_PATH = REPO_ROOT / "src/nouse/web/static/models/human_brain.glb"
OUT_PATH = REPO_ROOT / "src/nouse/web/static/models/brain_template.json"

# Must match brain_view.js's sphereEnvelope exactly (the fallback sphere's
# own dimensions, used as the contain-fit target for the anatomical model).
ENVELOPE = np.array([220.0, 187.0, 264.0])

# Same 11 regions + positions as brain_view.js's REGIONS dict (render-space
# coordinates, i.e. already in the post-transform frame).
REGION_ANCHORS = {
    "prefrontal":      (0, 25, 105),
    "frontal":         (0, 0, 85),
    "parietal":        (0, 65, 40),
    "temporal_left":   (-85, 0, 0),
    "temporal_right":  (85, 0, 0),
    "occipital":       (0, 0, -85),
    "hippocampus":     (0, -40, 10),
    "amygdala":        (32, -52, 12),
    "cerebellum":      (0, -82, -55),
    "brainstem":       (0, -105, 0),
    "corpus_callosum": (0, 0, 0),
}

# Target candidate pool size (before radial-bias subsampling). Ox Alpha's
# estimate: 150k-400k raw voxels from flood-fill; pitch is tuned to land
# in that range for this specific mesh (checked empirically below).
TARGET_RAW_VOXELS = (120_000, 350_000)

# Per-region final pool size, AFTER region assignment. A pure global
# radial-bias subsample (favor points far from centroid, for the cortex
# look) starves small/central real structures like the brainstem almost
# to zero -- fine for anatomical realism, useless as a graph-node target
# when a high-traffic domain happens to map there. Apply the radial bias
# *within* each region instead, with a floor so every region can host a
# few thousand graph nodes without visual collapse onto a handful of
# points.
MIN_POINTS_PER_REGION = 3000
MAX_POINTS_PER_REGION = 9000


def load_combined_mesh() -> trimesh.Trimesh:
    scene = trimesh.load(GLB_PATH)
    mesh = scene.to_geometry() if hasattr(scene, "to_geometry") else scene
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"expected a single Trimesh after combining, got {type(mesh)}")
    return mesh


def render_space_transform(mesh: trimesh.Trimesh) -> tuple[np.ndarray, float]:
    bounds = mesh.bounds  # [[minx,miny,minz],[maxx,maxy,maxz]]
    center = bounds.mean(axis=0)
    size = bounds[1] - bounds[0]
    scale = float(np.min(ENVELOPE / np.where(size > 0, size, 1.0)))
    return center, scale


def voxelize_interior(mesh: trimesh.Trimesh) -> np.ndarray:
    """Returns raw-space (pre-transform) interior point coordinates."""
    size = mesh.bounds[1] - mesh.bounds[0]
    approx_volume = float(np.prod(size))

    # Binary-search-ish pitch tuning: start from a volume-based estimate,
    # adjust once if the first attempt lands far outside the target range.
    pitch = (approx_volume / 200_000) ** (1 / 3)

    for attempt in range(3):
        vox = mesh.voxelized(pitch=pitch)
        filled = vox.fill()
        points = filled.points
        n = len(points)
        print(f"  attempt {attempt}: pitch={pitch:.5f} -> {n} voxels")
        if TARGET_RAW_VOXELS[0] <= n <= TARGET_RAW_VOXELS[1]:
            return points
        # too few points -> smaller pitch (finer); too many -> coarser
        target_mid = sum(TARGET_RAW_VOXELS) / 2
        ratio = (target_mid / max(n, 1)) ** (1 / 3)
        pitch = pitch / ratio

    print(f"  WARNING: pitch tuning did not converge into target range, using last result ({n} points)")
    return points


def main() -> None:
    print(f"Loading {GLB_PATH} ...")
    mesh = load_combined_mesh()
    print(f"  {len(mesh.vertices)} vertices, {len(mesh.faces)} faces, watertight={mesh.is_watertight}")

    center, scale = render_space_transform(mesh)
    print(f"  render-space transform: center={center}, scale={scale:.4f}")

    if not mesh.is_watertight:
        print("  mesh is not watertight -- attempting hole-fill repair before voxelizing")
        mesh = mesh.copy()
        trimesh.repair.fill_holes(mesh)
        print(f"  after repair: watertight={mesh.is_watertight}")

    print("Voxelizing + flood-filling interior ...")
    raw_points = voxelize_interior(mesh)

    fallback_used = False
    if len(raw_points) < TARGET_RAW_VOXELS[0] // 4:
        # Flood-fill leaked badly (near-empty result) -- fall back to the
        # mesh's convex hull as a coarse-but-honest container instead of a
        # hand-tuned parametric blob, since we at least still have a real
        # scan's outer envelope.
        print("  flood-fill produced too few points -- falling back to convex hull volume")
        hull = mesh.convex_hull
        pitch = ((hull.bounds[1] - hull.bounds[0]).prod() / 200_000) ** (1 / 3)
        vox = hull.voxelized(pitch=pitch).fill()
        raw_points = vox.points
        fallback_used = True
        print(f"  convex-hull fallback: {len(raw_points)} points")

    render_points = (raw_points - center) * scale
    centroid = render_points.mean(axis=0)

    print(f"Assigning all {len(render_points)} raw points to nearest of {len(REGION_ANCHORS)} regions ...")
    anchor_names = list(REGION_ANCHORS.keys())
    anchor_coords = np.array([REGION_ANCHORS[n] for n in anchor_names], dtype=float)
    tree = cKDTree(anchor_coords)
    _, nearest_idx = tree.query(render_points, k=1)

    rng = np.random.default_rng(seed=42)  # deterministic across regenerations
    pool_points_list: list[np.ndarray] = []
    pool_region_ids: list[str] = []

    print("  per-region raw counts -> final pool size:")
    for region_i, name in enumerate(anchor_names):
        mask = nearest_idx == region_i
        region_points = render_points[mask]
        raw_count = len(region_points)
        if raw_count == 0:
            print(f"    {name:16s} {raw_count:6d} -> 0 (no raw voxels landed here)")
            continue

        target = int(np.clip(raw_count, MIN_POINTS_PER_REGION, MAX_POINTS_PER_REGION))
        if raw_count <= target:
            # Small region: keep everything it has, no subsampling needed.
            chosen = region_points
        else:
            # Radial bias WITHIN this region (relative to the global
            # centroid, so "outer" means the same thing everywhere), then
            # subsample down to target.
            radial_dist = np.linalg.norm(region_points - centroid, axis=1)
            weights = radial_dist ** 1.5
            weights = weights / weights.sum()
            idx = rng.choice(raw_count, size=target, replace=False, p=weights)
            chosen = region_points[idx]

        print(f"    {name:16s} {raw_count:6d} -> {len(chosen):6d}")
        pool_points_list.append(chosen)
        pool_region_ids.extend([name] * len(chosen))

    pool_points = np.concatenate(pool_points_list, axis=0)
    region_ids = pool_region_ids

    asset = {
        "version": 1,
        "generated_from": "src/nouse/web/static/models/human_brain.glb",
        "point_count": len(pool_points),
        "watertight_repair_applied": True,
        "convex_hull_fallback_used": fallback_used,
        "radial_bias": "distance_from_centroid ** 1.5 (approximation, not a true surface distance transform)",
        "points": [[round(float(x), 2), round(float(y), 2), round(float(z), 2)] for x, y, z in pool_points],
        "region_ids": region_ids,
    }
    OUT_PATH.write_text(json.dumps(asset))
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB, {len(pool_points)} points)")


if __name__ == "__main__":
    main()
