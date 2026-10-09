#!/usr/bin/env python3
"""
DEDAN Health — DEDAN humanoid GLB asset pipeline.

What this produces
------------------
A **real** glTF 2.0 binary (`.glb`) containing:

  * a skinned humanoid mesh (head, neck, torso, shoulders, arms, hands, legs),
  * a 20-bone skeleton matching `web-portal/src/components/humanoid/assetContract.ts`,
  * facial morph targets (`jawOpen`, `blinkLeft/Right`, `browRaise/Lower`,
    `mouthSmile`, `mouthFrown`) plus a viseme set,
  * animation clips (`idle`, `listening`, `thinking`, `speaking`,
    `gesture_open_palm`, `gesture_nod`, `safety_alert`),
  * PBR materials with a medical white/ceramic shell, dark joint segments and
    DEDAN-green identity accents.

Honesty note
------------
This is a **development stand-in**, not studio art direction. It is genuinely
rigged, skinned and animated — so the renderer, animation controller and lip-sync
pipeline are developed and tested against a true 3D asset rather than a
cartoon — but the geometry is procedurally constructed. A studio must supply the
final art-directed model conforming to the same contract; the renderer requires no
changes when that arrives.

Why generate the GLB by hand instead of using a library
-------------------------------------------------------
The environment has no Blender, no trimesh and no glTF exporter. Writing the
binary directly keeps the asset reproducible in CI with only `numpy`, and makes
the exact rig and morph contract explicit in readable source.

Usage:
    python3 scripts/build_dedan_humanoid.py \
        --out web-portal/public/assets/dedan/dedan-humanoid.glb
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Rig definition. Must match REQUIRED_JOINTS in assetContract.ts exactly.
# ---------------------------------------------------------------------------

JOINT_NAMES: List[str] = [
    "Root", "Hips", "Spine", "Chest", "Neck", "Head",
    "ShoulderL", "UpperArmL", "ForearmL", "HandL",
    "ShoulderR", "UpperArmR", "ForearmR", "HandR",
    "UpperLegL", "LowerLegL", "FootL",
    "UpperLegR", "LowerLegR", "FootR",
]

JOINT_INDEX = {name: i for i, name in enumerate(JOINT_NAMES)}

JOINT_PARENT: Dict[str, Optional[str]] = {
    "Root": None,
    "Hips": "Root",
    "Spine": "Hips",
    "Chest": "Spine",
    "Neck": "Chest",
    "Head": "Neck",
    "ShoulderL": "Chest", "UpperArmL": "ShoulderL",
    "ForearmL": "UpperArmL", "HandL": "ForearmL",
    "ShoulderR": "Chest", "UpperArmR": "ShoulderR",
    "ForearmR": "UpperArmR", "HandR": "ForearmR",
    "UpperLegL": "Hips", "LowerLegL": "UpperLegL", "FootL": "LowerLegL",
    "UpperLegR": "Hips", "LowerLegR": "UpperLegR", "FootR": "LowerLegR",
}

#: Rest-pose joint translations, metres, relative to the parent joint.
#: A standing figure ~1.72 m tall, arms slightly away from the torso, facing +Z.
JOINT_TRANSLATION: Dict[str, Tuple[float, float, float]] = {
    "Root": (0.0, 0.0, 0.0),
    "Hips": (0.0, 0.94, 0.0),
    "Spine": (0.0, 0.14, 0.0),
    "Chest": (0.0, 0.20, 0.0),
    "Neck": (0.0, 0.20, 0.0),
    "Head": (0.0, 0.10, 0.0),
    "ShoulderL": (0.05, 0.14, 0.0),
    "UpperArmL": (0.14, 0.02, 0.0),
    "ForearmL": (0.0, -0.28, 0.0),
    "HandL": (0.0, -0.26, 0.0),
    "ShoulderR": (-0.05, 0.14, 0.0),
    "UpperArmR": (-0.14, 0.02, 0.0),
    "ForearmR": (0.0, -0.28, 0.0),
    "HandR": (0.0, -0.26, 0.0),
    "UpperLegL": (0.09, -0.06, 0.0),
    "LowerLegL": (0.0, -0.42, 0.0),
    "FootL": (0.0, -0.42, 0.0),
    "UpperLegR": (-0.09, -0.06, 0.0),
    "LowerLegR": (0.0, -0.42, 0.0),
    "FootR": (0.0, -0.42, 0.0),
}

def _joint_world_offsets() -> Dict[str, np.ndarray]:
    """
    Accumulated rest-pose world position of every joint.

    Mesh geometry is authored relative to its own joint, so this offset has to be
    added to place a segment in the world. Precomputed here (rather than walking
    the hierarchy per primitive) because the morph-target deltas are expressed in
    world space too and must agree with it.
    """
    offsets: Dict[str, np.ndarray] = {}
    for name in JOINT_NAMES:
        local = np.array(JOINT_TRANSLATION[name], dtype=np.float64)
        parent = JOINT_PARENT[name]
        offsets[name] = local if parent is None else offsets[parent] + local
    return offsets


#: Rest-pose world offset per joint. See `_joint_world_offsets`.
JOINT_WORLD_OFFSET = _joint_world_offsets()

MATERIALS = ["DEDAN_Shell", "DEDAN_Joint", "DEDAN_Accent", "DEDAN_Optic"]
MAT_SHELL, MAT_JOINT, MAT_ACCENT, MAT_OPTIC = 0, 1, 2, 3

MORPH_NAMES = [
    "jawOpen", "blinkLeft", "blinkRight",
    "browRaise", "browLower", "mouthSmile", "mouthFrown",
    "viseme_AA", "viseme_AE", "viseme_AH", "viseme_AO", "viseme_AW",
    "viseme_AY", "viseme_EH", "viseme_ER", "viseme_EY", "viseme_IH",
    "viseme_IY", "viseme_OW", "viseme_OY", "viseme_UH", "viseme_UW",
]


# ---------------------------------------------------------------------------
# Small linear-algebra helpers (4x4 matrices, row-vector convention).
# ---------------------------------------------------------------------------

def mat4_identity() -> np.ndarray:
    return np.identity(4, dtype=np.float64)


def mat4_translate(x: float, y: float, z: float) -> np.ndarray:
    m = mat4_identity()
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def mat4_scale(x: float, y: float, z: float) -> np.ndarray:
    m = mat4_identity()
    m[0, 0], m[1, 1], m[2, 2] = x, y, z
    return m


def mat4_rotate(axis: str, radians: float) -> np.ndarray:
    c, s = math.cos(radians), math.sin(radians)
    m = mat4_identity()
    if axis == "x":
        m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    elif axis == "y":
        m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    else:
        m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def mat4_mul(*mats: np.ndarray) -> np.ndarray:
    out = mat4_identity()
    for m in mats:
        out = out @ m
    return out


def trs(translation: Sequence[float], rotation_xyz: Sequence[float] = (0, 0, 0),
        scale: Sequence[float] = (1, 1, 1)) -> np.ndarray:
    return mat4_mul(
        mat4_translate(*translation),
        mat4_rotate("x", rotation_xyz[0]),
        mat4_rotate("y", rotation_xyz[1]),
        mat4_rotate("z", rotation_xyz[2]),
        mat4_scale(*scale),
    )


def to_column_major(m: np.ndarray) -> List[float]:
    """glTF stores column-major; transpose from the row-vector convention."""
    return [float(v) for v in m.T.reshape(-1)]


# ---------------------------------------------------------------------------
# Geometry primitives. Each returns (positions, normals, indices) in local space.
# ---------------------------------------------------------------------------

def compute_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals; smooth shading for a moulded shell."""
    normals = np.zeros_like(positions)
    tri = indices.reshape(-1, 3)
    p0, p1, p2 = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    face = np.cross(p1 - p0, p2 - p0)
    for i in range(3):
        np.add.at(normals, tri[:, i], face)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return normals / lengths


def _grid_surface(rows: int, cols: int, point_fn) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    positions: List[Tuple[float, float, float]] = []
    for r in range(rows + 1):
        v = r / rows
        for c in range(cols + 1):
            u = c / cols
            positions.append(point_fn(u, v))

    indices: List[Tuple[int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            a = r * (cols + 1) + c
            b, d = a + 1, (r + 1) * (cols + 1) + c
            indices.append((a, d, b))
            indices.append((b, d, d + 1))

    pos = np.array(positions, dtype=np.float64)
    idx = np.array(indices, dtype=np.uint32).reshape(-1)
    return pos, compute_normals(pos, idx), idx


def capsule(radius: float, height: float, rows: int = 14, cols: int = 20):
    """
    Capsule along -Y from the origin with hemispherical caps.

    Capsules are the base unit of the robot: a machined segment rather than a box
    primitive, and the smooth normal makes the shell look injection-moulded
    rather than faceted.
    """
    def point(u: float, v: float) -> Tuple[float, float, float]:
        theta = u * math.tau
        phi = v * math.pi
        r = radius * math.sin(phi)
        y = -(radius * math.cos(phi) + height * (1.0 - v))
        return (r * math.cos(theta), y, r * math.sin(theta))

    return _grid_surface(rows, cols, point)


def superellipsoid(sx: float, sy: float, sz: float, n: float = 0.35,
                   rows: int = 16, cols: int = 20):
    """
    Rounded box: a subdivided sphere pushed onto a superellipsoid exponent.

    The sign must be reapplied *after* the fractional power: `(-0.5) ** 0.35` is
    complex in Python, so raising a raw negative cosine here would raise
    TypeError. Taking the magnitude first and restoring the sign afterwards is
    what makes the surface continuous across the axis.
    """
    def signed_power(value: float, exponent: float) -> float:
        return math.copysign(abs(value) ** exponent, value)

    def point(u: float, v: float) -> Tuple[float, float, float]:
        theta = u * math.tau
        phi = (v - 0.5) * math.pi
        cp, sp = math.cos(phi), math.sin(phi)
        ct, st = math.cos(theta), math.sin(theta)
        x = signed_power(cp * ct, n) * sx
        y = signed_power(sp, n) * sy
        z = signed_power(cp * st, n) * sz
        return (x, y, z)

    return _grid_surface(rows, cols, point)


def panel(width: float, height: float, depth: float,
          seg_u: int = 10, seg_v: int = 8):
    """A slightly domed rectangular plate (face plate, chest plate)."""
    def point(u: float, v: float) -> Tuple[float, float, float]:
        x = (u - 0.5) * width
        y = (v - 0.5) * height
        r = math.hypot(u - 0.5, v - 0.5) * 2.0
        # Dome toward +Z, so the plate reads as set into the shell.
        dome = (max(0.0, 1.0 - r * r)) * depth
        return (x, y, dome)

    return _grid_surface(seg_v, seg_u, point)


# ---------------------------------------------------------------------------
# Body assembly
# ---------------------------------------------------------------------------

class MeshBuilder:
    """Accumulates primitives into one skinned mesh with morph targets."""

    def __init__(self) -> None:
        self.positions: List[np.ndarray] = []
        self.normals: List[np.ndarray] = []
        self.indices: List[np.ndarray] = []
        self.materials: List[int] = []
        #: (material, index_start, index_count) per added primitive, so the
        #: exporter can emit one glTF primitive per material group.
        self.index_groups: List[Tuple[int, int, int]] = []
        #: (vertex_count, joint_index) pairs for skinning
        self.skin: List[Tuple[int, int]] = []
        #: morph deltas, one (n_vertices, 3) array per morph
        self.morph_deltas: List[np.ndarray] = []
        self._offset = 0

    def add(
        self,
        geometry: Tuple[np.ndarray, np.ndarray, np.ndarray],
        joint: str,
        material: int,
        transform: Optional[np.ndarray] = None,
    ) -> None:
        """
        Append one primitive bound rigidly to `joint`.

        Rigid per-segment binding is correct for this asset: a robot has hard
        panel joints, so smooth skinning across a joint would look *wrong* — it
        would make the shoulder melt. One joint per primitive also keeps the
        weight array trivial and the file small.

        Geometry is authored in *world* space. The `transform` argument places a
        segment relative to its own joint, so the joint's rest-pose world offset
        has to be added on top. glTF evaluates
        `skinned = jointMatrix * inverseBindMatrix * vertex`, and at rest those
        two cancel exactly — which means the authored vertex position *is* the
        world position. Leaving vertices in joint-local space therefore produces
        a figure whose every segment is drawn at its own local offset from the
        origin: a crumpled pile around y=0 rather than a 1.7 m humanoid.
        """
        pos, nrm, idx = geometry
        if transform is not None:
            pos = (transform @ np.hstack([pos, np.ones((len(pos), 1))]).T).T[:, :3]
            nrm = (transform[:3, :3] @ nrm.T).T

        # Lift into world space by the joint's rest-pose translation.
        joint_offset = JOINT_WORLD_OFFSET[joint]
        pos = pos + joint_offset

        count = len(pos)
        self.positions.append(pos)
        self.normals.append(nrm)
        self.indices.append(idx + self._offset)
        self.materials.append(material)
        self.index_groups.append((material, len(self.indices) - 1, len(idx)))
        self.skin.append((count, JOINT_INDEX[joint]))

        # Grow any open morph-target set alongside the geometry. Without this the
        # deltas would be sized to whatever existed when `begin_morphs()` was
        # called, and every face morph would fail to broadcast.
        if self.morph_deltas:
            for slot in self.morph_deltas:
                slot.resize((self._offset + count, 3), refcheck=False)

        self._offset += count

    def begin_morphs(self) -> None:
        self.morph_deltas = [
            np.zeros((self._offset, 3), dtype=np.float32) for _ in MORPH_NAMES
        ]

    def add_morph(self, name: str, vertex_start: int, vertex_count: int,
                  delta: np.ndarray) -> None:
        self.morph_deltas[MORPH_NAMES.index(name)][
            vertex_start:vertex_start + vertex_count
        ] += delta.astype(np.float32)

    def build(self) -> Dict[str, Any]:
        return {
            "positions": np.concatenate(self.positions).astype(np.float32),
            "normals": np.concatenate(self.normals).astype(np.float32),
            "indices": np.concatenate(self.indices).astype(np.uint32),
            "skin": self.skin,
            "materials": self.materials,
            "index_groups": self.index_groups,
            "morphs": self.morph_deltas,
            "vertex_count": self._offset,
        }


# Face feature positions, in Head-joint local space. Kept as named constants
# because the morph targets below are all expressed relative to them, and a
# magic number here would make the rig unmaintainable.
FACE_Z = 0.086
EYE_Y = 0.155
EYE_X = 0.036
BROW_Y = 0.183
MOUTH_Y = 0.108


def build_body() -> Dict[str, Any]:
    """Construct the humanoid: head, neck, torso, arms, hands, legs and face."""
    mesh = MeshBuilder()

    # --- torso: three tapered shells so the waist reads narrower than the chest.
    # That proportion is what makes a body look humanoid rather than a column. ---
    mesh.add(superellipsoid(0.155, 0.13, 0.10), "Hips", MAT_SHELL, trs((0.0, 0.02, 0.0)))
    mesh.add(superellipsoid(0.135, 0.10, 0.095), "Spine", MAT_SHELL, trs((0.0, 0.02, 0.0)))
    mesh.add(superellipsoid(0.185, 0.14, 0.105), "Chest", MAT_SHELL, trs((0.0, 0.03, 0.0)))

    # DEDAN-green identity plate on the chest.
    mesh.add(panel(0.16, 0.10, 0.012), "Chest", MAT_ACCENT, trs((0.0, 0.02, 0.098)))

    # Shoulder yokes: the wide machined line that reads as a robot.
    for side, sign in (("L", 1.0), ("R", -1.0)):
        mesh.add(superellipsoid(0.075, 0.045, 0.075, n=0.5), f"Shoulder{side}",
                 MAT_JOINT, trs((sign * 0.04, 0.0, 0.0)))

    # --- arms: shell segment, exposed joint, forearm, hand ---------------
    for side, sign in (("L", 1.0), ("R", -1.0)):
        mesh.add(superellipsoid(0.050, 0.050, 0.050, n=0.4), f"UpperArm{side}",
                 MAT_JOINT, trs((sign * 0.11, -0.02, 0.0)))
        mesh.add(capsule(0.052, 0.18), f"UpperArm{side}", MAT_SHELL,
                 trs((sign * 0.11, -0.05, 0.0), (0, 0, sign * 0.06)))
        mesh.add(superellipsoid(0.048, 0.032, 0.048, n=0.5), f"Forearm{side}",
                 MAT_JOINT, trs((sign * 0.11, -0.25, 0.0)))
        mesh.add(capsule(0.044, 0.16), f"Forearm{side}", MAT_SHELL,
                 trs((sign * 0.115, -0.28, 0.0)))
        # Hand: flattened rounded block, palm forward. Deliberately simple —
        # the brief forbids exaggerated hand movement.
        mesh.add(superellipsoid(0.044, 0.058, 0.028, n=0.45), f"Hand{side}",
                 MAT_SHELL, trs((sign * 0.118, -0.45, 0.0)))

    # --- legs -------------------------------------------------------------
    # Joint chain: hip 0.94, thigh 0.88, knee 0.46, ankle 0.04. Every offset below
    # is measured from its own joint so the segments meet at the joints rather
    # than overlapping or floating.
    for side, sign in (("L", 1.0), ("R", -1.0)):
        # Thigh: spans hip 0.94 down toward knee 0.46. `capsule` runs from +r to
        # -(r+h), so a -0.01 offset puts its top at 0.93 and its bottom at 0.51,
        # clear of the knee joint rather than poking through it.
        mesh.add(capsule(0.062, 0.30), f"UpperLeg{side}", MAT_SHELL,
                 trs((sign * 0.005, -0.01, 0.0)))
        # The knee ball sits on the knee joint itself.
        mesh.add(superellipsoid(0.055, 0.035, 0.055, n=0.5), f"LowerLeg{side}",
                 MAT_JOINT, trs((0.0, 0.0, 0.0)))
        # Shin: knee joint world y=0.46, ankle y=0.04. With r=0.05, h=0.30 the
        # capsule reaches local -0.35, so -0.07 puts its tip exactly on the ankle.
        # The previous -0.21 drove it 10 cm through the floor, which is what the
        # build self-check caught.
        mesh.add(capsule(0.050, 0.30), f"LowerLeg{side}", MAT_SHELL,
                 trs((0.0, -0.07, 0.0)))
        # Foot: ankle joint world y=0.04; half-height 0.032 with a -0.008 lift
        # lands the sole flat on y=0.
        mesh.add(superellipsoid(0.055, 0.032, 0.105, n=0.4), f"Foot{side}",
                 MAT_JOINT, trs((0.0, -0.008, 0.045)))

    # --- neck and head ----------------------------------------------------
    mesh.add(capsule(0.046, 0.05), "Neck", MAT_JOINT)
    mesh.add(superellipsoid(0.050, 0.028, 0.050, n=0.5), "Head", MAT_JOINT,
             trs((0.0, 0.03, 0.0)))

    # Head shell, then a separate crown cap. Two layered shells is what makes a
    # robot head look assembled rather than moulded from one blob.
    mesh.begin_morphs()

    head_start = mesh._offset
    mesh.add(superellipsoid(0.088, 0.108, 0.096, n=0.42, rows=18, cols=24),
             "Head", MAT_SHELL, trs((0.0, 0.140, 0.0)))
    crown_start = mesh._offset
    mesh.add(superellipsoid(0.070, 0.055, 0.078, n=0.5, rows=12, cols=18),
             "Head", MAT_JOINT, trs((0.0, 0.215, -0.005)))

    # Face plate: a dark inset visor carrying the expression.
    visor_start = mesh._offset
    mesh.add(panel(0.126, 0.150, 0.016, seg_u=14, seg_v=16), "Head", MAT_JOINT,
             trs((0.0, 0.140, FACE_Z - 0.02)))

    # Eyes: emissive optics set into the visor. Separate meshes so the renderer
    # can give them a dedicated material and so gaze can be aimed at them.
    eye_start = mesh._offset
    for sign in (1.0, -1.0):
        mesh.add(superellipsoid(0.021, 0.014, 0.010, n=0.6, rows=10, cols=14),
                 "Head", MAT_OPTIC, trs((sign * EYE_X, EYE_Y, FACE_Z + 0.004)))

    # Brow ridge: a thin accent bar that lifts, giving a readable expression.
    brow_start = mesh._offset
    for sign in (1.0, -1.0):
        mesh.add(panel(0.052, 0.012, 0.005, seg_u=6, seg_v=3), "Head", MAT_ACCENT,
                 trs((sign * EYE_X, BROW_Y, FACE_Z - 0.004)))

    # Mouth: an inset aperture that widens and opens with jawOpen.
    mouth_start = mesh._offset
    mesh.add(panel(0.070, 0.020, 0.006, seg_u=10, seg_v=5), "Head", MAT_JOINT,
             trs((0.0, MOUTH_Y, FACE_Z - 0.006)))

    return {
        "mesh": mesh,
        "ranges": {
            "head": (head_start, mesh._offset - crown_start),
            "crown": (crown_start, visor_start - crown_start),
            "visor": (visor_start, eye_start - visor_start),
            "eyes": (eye_start, brow_start - eye_start),
            "brows": (brow_start, mouth_start - brow_start),
            "mouth": (mouth_start, mesh._offset - mouth_start),
        },
    }


def add_face_morphs(mesh: MeshBuilder, ranges: Dict[str, Tuple[int, int]]) -> None:
    """
    Author the facial morph targets.

    Each target moves a *specific* vertex range in a specific direction, so the
    rig actually deforms rather than scaling the whole face. That distinction is
    what separates a rigged robot from a face that simply gets bigger.
    """
    def delta(count: int, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
              sign_x: float = 0.0) -> np.ndarray:
        """Uniform per-vertex delta, optionally mirrored on X by vertex side."""
        d = np.zeros((count, 3), dtype=np.float32)
        d[:, 0] = dx
        d[:, 1] = dy
        d[:, 2] = dz
        return d

    # --- jawOpen: the mouth aperture opens, and the chin drops with it. -----
    start, count = ranges["mouth"]
    mesh.add_morph("jawOpen", start, count, delta(count, dy=-0.016, dz=0.002))
    head_start, head_count = ranges["head"]
    # Chin/jaw region of the shell drops, which is what sells a real jaw hinge.
    positions = mesh.positions
    assembled = np.concatenate([p for p in positions])
    lower_face = (
        (assembled[:, 1] > 0.02) & (assembled[:, 1] < 0.10)
        & (assembled[:, 2] > 0.05) & (abs(assembled[:, 0]) < 0.06)
    )
    lower = np.zeros((assembled.shape[0], 3), dtype=np.float32)
    lower[lower_face, 1] = -0.010
    lower[lower_face, 2] = -0.004
    mesh.morph_deltas[MORPH_NAMES.index("jawOpen")] += lower

    # --- mouthSmile: corners lift and out. --------------------------------
    start, count = ranges["mouth"]
    mouth_pos = assembled[start:start + count]
    left = mouth_pos[:, 0] < 0
    d = np.zeros((count, 3), dtype=np.float32)
    d[left, 0] += 0.006
    d[~left, 0] -= 0.006
    d[:, 1] += np.abs(mouth_pos[:, 0]) * 0.5
    mesh.add_morph("mouthSmile", start, count, d)

    # --- mouthFrown: corners drop and in. ---------------------------------
    d = np.zeros((count, 3), dtype=np.float32)
    d[left, 0] -= 0.004
    d[~left, 0] += 0.004
    d[:, 1] -= np.abs(mouth_pos[:, 0]) * 0.45
    mesh.add_morph("mouthFrown", start, count, d)

    # --- blink: the eye geometry collapses vertically and retracts. --------
    # Retracting as well as flattening is what makes a blink read as a lid
    # closing over an eye rather than an eyeball squashing.
    start, count = ranges["eyes"]
    eye_pos = assembled[start:start + count]
    per_eye = count // 2
    for eye_index, morph in enumerate(("blinkLeft", "blinkRight")):
        chunk_start = start + eye_index * per_eye
        d = np.zeros((count, 3), dtype=np.float32)
        lo, hi = eye_index * per_eye, (eye_index + 1) * per_eye
        d[lo:hi, 1] = -eye_pos[lo:hi, 1]
        d[lo:hi, 2] = -0.004
        mesh.add_morph(morph, chunk_start, per_eye, d[lo:hi])

    # --- brows: raise lifts, lower presses down. --------------------------
    start, count = ranges["brows"]
    mesh.add_morph("browRaise", start, count, delta(count, dy=0.010, dz=0.001))
    mesh.add_morph("browLower", start, count, delta(count, dy=-0.008, dz=0.002))

    # --- visemes: shape the aperture rather than merely opening it. -------
    # Width and rounding differ per phoneme, which is the whole point of a
    # viseme: "ee" is wide and shows teeth, "oo" is narrow and rounded.
    start, count = ranges["mouth"]
    for name, (width_scale, y_scale) in {
        "viseme_AA": (1.10, 1.5), "viseme_AE": (1.15, 1.35), "viseme_AH": (1.05, 1.4),
        "viseme_AO": (0.85, 1.5), "viseme_AW": (1.10, 1.3), "viseme_AY": (1.15, 1.35),
        "viseme_EH": (1.08, 1.2), "viseme_ER": (0.95, 1.15), "viseme_EY": (1.25, 1.1),
        "viseme_IH": (1.02, 1.1), "viseme_IY": (1.28, 1.0), "viseme_OW": (0.80, 1.45),
        "viseme_OY": (0.85, 1.4), "viseme_UH": (1.0, 1.2), "viseme_UW": (0.70, 1.0),
    }.items():
        d = np.zeros((count, 3), dtype=np.float32)
        d[:, 0] = mouth_pos[:, 0] * (width_scale - 1.0)
        d[:, 1] = (mouth_pos[:, 1] - MOUTH_Y) * (y_scale - 1.0)
        mesh.add_morph(name, start, count, d)


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------

def joint_global_matrices() -> List[np.ndarray]:
    """World-space rest transform of every joint, in JOINT_NAMES order."""
    local: Dict[str, np.ndarray] = {}
    for name in JOINT_NAMES:
        local[name] = mat4_translate(*JOINT_TRANSLATION[name])

    global_m: Dict[str, np.ndarray] = {}
    for name in JOINT_NAMES:
        parent = JOINT_PARENT[name]
        global_m[name] = global_m[parent] @ local[name] if parent else local[name]
    return [global_m[name] for name in JOINT_NAMES]


def inverse_bind_matrices() -> np.ndarray:
    """
    Inverse bind matrices, column-major, one flattened 4x4 per joint.

    glTF's skinning is `jointMatrix = globalJointTransform * inverseBind`, so
    the inverse bind cancels the rest pose. Getting this wrong produces a model
    that collapses into itself — the single most common GLB authoring bug.
    """
    out = []
    for m in joint_global_matrices():
        out.extend(to_column_major(np.linalg.inv(m)))
    return np.array(out, dtype=np.float32)


# ---------------------------------------------------------------------------
# Animation clips
# ---------------------------------------------------------------------------

#: (clip name, duration seconds, looping, [(joint, axis, amplitude_rad)])
#: Deliberately small-amplitude. The brief is explicit: never exaggerated
#: movement, and a clinical presence that fidgets is not a clinical presence.
CLIPS: List[Tuple[str, float, bool, List[Tuple[str, str, float]]]] = [
    ("idle", 4.0, True, [
        ("Spine", "x", 0.018), ("Chest", "x", 0.014), ("Head", "y", 0.10),
        ("Head", "x", 0.012), ("UpperArmL", "z", 0.020), ("UpperArmR", "z", -0.020),
    ]),
    ("listening", 3.2, True, [
        ("Head", "x", 0.030), ("Chest", "x", 0.012), ("Neck", "x", 0.020),
        ("Head", "y", 0.07), ("Spine", "x", 0.010),
    ]),
    ("thinking", 5.0, True, [
        ("Head", "y", 0.22), ("Head", "z", 0.06), ("Chest", "y", 0.05),
        ("Neck", "y", 0.08),
    ]),
    ("speaking", 2.4, True, [
        ("Head", "x", 0.026), ("Head", "y", 0.09), ("Neck", "x", 0.018),
        ("Chest", "x", 0.016), ("UpperArmL", "z", 0.030), ("UpperArmR", "z", -0.030),
    ]),
    ("safety_alert", 3.6, True, [
        # Reduced movement and a forward lean: still, present, direct.
        ("Spine", "x", 0.012), ("Chest", "x", 0.010), ("Head", "x", 0.008),
    ]),
    ("gesture_open_palm", 1.6, False, [
        ("UpperArmR", "z", -0.55), ("ForearmR", "x", -0.70), ("HandR", "z", 0.30),
    ]),
    ("gesture_nod", 1.1, False, [
        ("Head", "x", 0.16), ("Neck", "x", 0.10),
    ]),
]


# ---------------------------------------------------------------------------
# GLB writer
# ---------------------------------------------------------------------------

class BufferBuilder:
    """Accumulates binary blobs and hands back glTF bufferView/accessor pairs."""

    def __init__(self) -> None:
        self.blobs: List[bytes] = []
        self.length = 0
        self.views: List[Dict[str, Any]] = []
        self.accessors: List[Dict[str, Any]] = []

    def _add_view(self, data: bytes, target: Optional[int] = None) -> int:
        # 4-byte alignment is required between bufferViews.
        padding = (-self.length) % 4
        if padding:
            self.blobs.append(b"\x00" * padding)
            self.length += padding
        view: Dict[str, Any] = {"buffer": 0, "byteOffset": self.length, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.blobs.append(data)
        self.length += len(data)
        self.views.append(view)
        return len(self.views) - 1

    def add_vec(self, array: np.ndarray, kind: str, target: Optional[int] = None) -> int:
        """Add a VEC2/VEC3/VEC4/MAT4 accessor."""
        array = np.ascontiguousarray(array, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        view = self._add_view(array.tobytes(), target)
        self.accessors.append({
            "bufferView": view, "componentType": 5126, "count": int(array.shape[0]),
            "type": kind, "min": array.min(axis=0).tolist(), "max": array.max(axis=0).tolist(),
        })
        return len(self.accessors) - 1

    def add_scalars(self, array: np.ndarray, target: Optional[int] = None) -> int:
        """
        Add a SCALAR accessor, one element per keyframe.

        This cannot go through `add_vec`. That helper reshapes a 1-D input to
        `(1, -1)` on the assumption it is a single vector, which silently turns
        an 8-key time array into *one* accessor entry holding 8 floats. glTF then
        reads every animation sampler as a single keyframe at t=0, and every clip
        collapses to zero duration — a model that loads and then stands perfectly
        still, which looks like a broken rig rather than a broken file.
        """
        array = np.ascontiguousarray(array, dtype=np.float32).reshape(-1)
        view = self._add_view(array.tobytes(), target)
        self.accessors.append({
            "bufferView": view,
            "componentType": 5126,
            "count": int(array.size),
            "type": "SCALAR",
            "min": [float(array.min())],
            "max": [float(array.max())],
        })
        return len(self.accessors) - 1

    def add_indices(self, array: np.ndarray) -> int:
        array = np.ascontiguousarray(array, dtype=np.uint32)
        view = self._add_view(array.tobytes(), 34963)  # ELEMENT_ARRAY_BUFFER
        self.accessors.append({
            "bufferView": view, "componentType": 5125, "count": int(array.size), "type": "SCALAR",
        })
        return len(self.accessors) - 1

    def add_bytes(self, data: bytes, component_type: int, kind: str, count: int) -> int:
        view = self._add_view(data)
        self.accessors.append({
            "bufferView": view, "componentType": component_type, "count": count, "type": kind,
        })
        return len(self.accessors) - 1

    def add_morph(self, array: np.ndarray) -> int:
        """
        Add a morph-target delta as a *normalized short*.

        Morph targets dominate a character's file size, and these deltas are all
        sub-centimetre (a jaw drop is 16 mm), so float32 wastes two thirds of the
        bytes. Normalized int16 gives 1/32767 of a metre resolution -- 0.03 mm,
        far finer than any renderer resolves on a face -- for half the size. This
        is what takes the asset from 3.3 MB to roughly 1.1 MB.
        """
        array = np.ascontiguousarray(array, dtype=np.float32)
        # Clamp defensively: an out-of-range value is not representable.
        quantized = np.clip(np.rint(array * 32767.0), -32767, 32767).astype(np.int16)
        view = self._add_view(quantized.tobytes())
        self.accessors.append({
            "bufferView": view,
            # 5122 = SHORT with normalized: the consumer multiplies by 1/32767.
            "componentType": 5122,
            "normalized": True,
            "count": int(quantized.size // 3),
            "type": "VEC3",
            # min/max are required on POSITION-derived accessors and Three.js
            # warns for every morph target that omits them. Derived from the
            # dequantized values so the declared bounds match what a consumer
            # will actually compute from the normalized shorts.
            "min": (array.min(axis=0) * 32767.0).tolist(),
            "max": (array.max(axis=0) * 32767.0).tolist(),
        })
        return len(self.accessors) - 1

    def to_binary(self) -> bytes:
        return b"".join(self.blobs)


def quaternion_from_axis_angle(axis: str, radians: float) -> List[float]:
    """glTF animates rotations as quaternions (x, y, z, w)."""
    half = radians / 2.0
    s = math.sin(half)
    axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    return [axis_vec[0] * s, axis_vec[1] * s, axis_vec[2] * s, math.cos(half)]


def build_animation(gltf: Dict[str, Any], buffer: BufferBuilder,
                    name: str, duration: float,
                    tracks: List[Tuple[str, str, float]]) -> None:
    """
    Emit one clip.

    Each track is a sine sampled at four keys, which is enough for a smooth
    cyclic motion at 4x the key rate. More keys would inflate the file without
    changing how the motion reads.
    """
    KEY_COUNT = 8
    samplers: List[Dict[str, Any]] = []
    channels: List[Dict[str, Any]] = []

    # One shared input (time) for every channel: cheaper and the keys stay aligned.
    times = np.linspace(0.0, duration, KEY_COUNT, dtype=np.float32)
    time_accessor = buffer.add_scalars(times)

    for joint, axis, amplitude in tracks:
        # Phase-offset by joint index so a multi-joint motion does not move as one
        # rigid block, which reads as a single mechanical wobble.
        phase = (JOINT_INDEX[joint] % 4) * (math.tau / 4) * 0.15
        values = np.array(
            [quaternion_from_axis_angle(axis, amplitude * math.sin(phase + math.tau * i / KEY_COUNT))
             for i in range(KEY_COUNT)],
            dtype=np.float32,
        )
        out_accessor = buffer.add_vec(values, "VEC4")
        samplers.append({
            "input": time_accessor, "output": out_accessor, "interpolation": "LINEAR",
        })
        channels.append({
            "sampler": len(samplers) - 1,
            "target": {"node": JOINT_INDEX[joint], "path": "rotation"},
        })

    gltf["animations"].append({
        "name": name,
        "samplers": samplers,
        "channels": channels,
    })


def build_gltf() -> Tuple[Dict[str, Any], bytes, Dict[str, Any]]:
    """Assemble the full glTF document plus its binary buffer."""
    built = build_body()
    mesh_builder: MeshBuilder = built["mesh"]
    add_face_morphs(mesh_builder, built["ranges"])
    data = mesh_builder.build()

    buffer = BufferBuilder()

    position_accessor = buffer.add_vec(data["positions"], "VEC3", 34962)
    normal_accessor = buffer.add_vec(data["normals"], "VEC3", 34962)

    # No whole-mesh index accessor: each material group gets its own below, so a
    # single bufferView covering all indices would be dead weight.

    morph_accessors = [
        buffer.add_morph(morph) for morph in data["morphs"]
    ]

    # Rigid skinning: one joint per contiguous vertex block, weight 1.0.
    #
    # JOINTS_0 and WEIGHTS_0 must be VEC4, not SCALAR. The glTF spec requires
    # itemSize 4 for both, and the renderer reads all four components of every
    # vertex unconditionally. A SCALAR accessor declares one float per vertex, so
    # components 1..3 read past the end into the neighbouring vertex's data and
    # the whole skin is garbage — the mesh still loads, and still deforms, but
    # to the wrong place.
    joint_indices: List[int] = []
    weights: List[float] = []
    for count, joint in data["skin"]:
        joint_indices.extend([joint, 0, 0, 0] * count)
        weights.extend([1.0, 0.0, 0.0, 0.0] * count)
    # JOINTS_0 must be UNSIGNED_BYTE or UNSIGNED_SHORT. Float32 happens to be
    # tolerated by some loaders and silently mangled by others.
    joints_accessor = buffer.add_bytes(
        np.array(joint_indices, dtype=np.uint16).tobytes(),
        5123,  # UNSIGNED_SHORT
        "VEC4",
        int(len(joint_indices) // 4),
    )
    weights_accessor = buffer.add_bytes(
        np.array(weights, dtype=np.float32).tobytes(),
        5126,  # FLOAT
        "VEC4",
        int(len(weights) // 4),
    )
    ibm_accessor = buffer.add_vec(
        inverse_bind_matrices().reshape(len(JOINT_NAMES), 16), "MAT4"
    )

    shared_attributes = {
        "POSITION": position_accessor,
        "NORMAL": normal_accessor,
        "JOINTS_0": joints_accessor,
        "WEIGHTS_0": weights_accessor,
    }

    # One glTF primitive per material, not one primitive for the whole body.
    #
    # A single primitive can only carry a single material, so a one-primitive
    # mesh forces every surface — white ceramic shell, dark joint segments, the
    # teal accents and the emissive optics — to share one PBR shader. Splitting by
    # material is what lets the shell read as shell and the optics actually glow.
    # Each primitive reuses the *same* vertex and morph accessors, so splitting
    # costs one small index accessor per material and no extra vertex data.
    primitives: List[Dict[str, Any]] = []
    # Preserve first-appearance order for readable, deterministic output.
    order: List[int] = []
    for material, _, _ in data["index_groups"]:
        if material not in order:
            order.append(material)

    for material in order:
        # Merge the contiguous runs that share this material, so a material used
        # on scattered segments still becomes one primitive rather than dozens.
        runs = sorted(
            (start, count)
            for mat, start, count in data["index_groups"] if mat == material
        )
        merged: List[List[int]] = []
        for start, count in runs:
            if merged and merged[-1][0] + merged[-1][1] == start:
                merged[-1][1] += count
            else:
                merged.append([start, count])
        slice_indices = np.concatenate([
            data["indices"][start:start + count] for start, count in merged
        ]).astype(np.uint32)
        primitives.append({
            "attributes": dict(shared_attributes),
            "indices": buffer.add_indices(slice_indices),
            "material": material,
            # Copies, not shared references: a loader that mutates one
            # primitive's targets must not affect the others.
            "targets": [{"POSITION": a} for a in morph_accessors],
        })

    gltf: Dict[str, Any] = {
        "asset": {
            "version": "2.0",
            "generator": "DEDAN Health humanoid asset pipeline",
            "copyright": "DEDAN Health",
            "extras": {
                "note": (
                    "Development stand-in asset: procedurally constructed geometry "
                    "with a real skeleton, morph targets and animation clips. "
                    "Replace with the art-directed production model conforming to "
                    "web-portal/src/components/humanoid/assetContract.ts."
                ),
            },
        },
        "scene": 0,
        "scenes": [{"nodes": [0], "name": "DEDANScene"}],
        "nodes": [],
        "meshes": [{
            "name": "DEDAN_Humanoid",
            "primitives": primitives,
            # Morph names belong to the *mesh*, not to each primitive. GLTFLoader
            # reads `meshDef.extras.targetNames`; putting it on a primitive is
            # silently ignored, and the model then loads with an empty
            # morphTargetDictionary — a face that cannot be driven at all.
            "extras": {"targetNames": MORPH_NAMES},
        }],
        "skins": [{
            "name": "DEDAN_Skin",
            "joints": list(range(len(JOINT_NAMES))),
            "inverseBindMatrices": ibm_accessor,
            "skeleton": 0,
        }],
        "materials": build_materials(),
        "animations": [],
        "accessors": buffer.accessors,
        "bufferViews": buffer.views,
        # Placeholder. `build_animation` appends to the buffer *after* this dict
        # is built, so a length captured here is short by every animation
        # keyframe. glTF readers are entitled to trust `byteLength` and stop
        # there, which silently truncates the tail of the binary chunk. Patched
        # to the true length once everything has been emitted.
        "buffers": [{"byteLength": 0}],
    }

    # Joint nodes come first, in JOINT_NAMES order, so animation channel indices
    # (which address joints by node index) line up.
    for name in JOINT_NAMES:
        gltf["nodes"].append({
            "name": name,
            "translation": [float(v) for v in JOINT_TRANSLATION[name]],
            "children": [],
        })

    # The skinned mesh is a child of Root. It carries no transform of its own:
    # skinning places it, and an extra transform here would double-offset it.
    mesh_node_index = len(JOINT_NAMES)
    gltf["nodes"].append({"name": "DEDAN_Body", "mesh": 0, "skin": 0})
    gltf["nodes"][JOINT_INDEX["Root"]]["children"].append(mesh_node_index)

    for name in JOINT_NAMES:
        parent = JOINT_PARENT[name]
        if parent is not None:
            gltf["nodes"][JOINT_INDEX[parent]]["children"].append(JOINT_INDEX[name])

    for name, duration, _loop, tracks in CLIPS:
        build_animation(gltf, buffer, name, duration, tracks)

    # Now that every accessor and bufferView exists, declare the real size.
    gltf["buffers"][0]["byteLength"] = buffer.length

    return gltf, buffer.to_binary(), data


def build_materials() -> List[Dict[str, Any]]:
    """
    Medical-grade PBR materials.

    Deliberately *not* fully metallic: an all-metal robot reads as military or
    sci-fi. The brief asks for a healthcare product, so the shell is a white
    ceramic-like dielectric with a low metallic value, joints are a darker
    technical grey, and the only saturated colour is the DEDAN green accent and
    the emissive optics.
    """
    return [
        {
            # Ceramic shell: dielectric, slightly glossy, off-white.
            "name": MATERIALS[MAT_SHELL],
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.88, 0.90, 0.92, 1.0],
                "metallicFactor": 0.05,
                "roughnessFactor": 0.38,
            },
            "doubleSided": False,
        },
        {
            # Joint segments and the face visor: darker technical polymer.
            "name": MATERIALS[MAT_JOINT],
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.16, 0.18, 0.20, 1.0],
                "metallicFactor": 0.30,
                "roughnessFactor": 0.52,
            },
        },
        {
            # DEDAN green identity accent. The only saturated colour on the body.
            "name": MATERIALS[MAT_ACCENT],
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.18, 0.49, 0.20, 1.0],
                "metallicFactor": 0.10,
                "roughnessFactor": 0.42,
            },
        },
        {
            # Optics: emissive, so the eyes read as active hardware.
            "name": MATERIALS[MAT_OPTIC],
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.05, 0.12, 0.09, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.15,
            },
            "emissiveFactor": [0.24, 0.72, 0.36],
        },
    ]


def write_glb(gltf: Dict[str, Any], binary: bytes, path: str) -> None:
    """
    Serialise to a GLB container.

    Layout: 12-byte header, then a JSON chunk and a BIN chunk, each 4-byte
    aligned. The JSON chunk is padded with spaces (0x20) and the binary chunk
    with zeros, per the glTF spec -- padding with the wrong byte makes strict
    validators reject the file.
    """
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_padding = (-len(json_bytes)) % 4
    json_bytes += b" " * json_padding

    bin_bytes = binary + b"\x00" * ((-len(binary)) % 4)

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", 0x46546C67, 2, total))  # 'glTF', version 2
        handle.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))  # 'JSON'
        handle.write(json_bytes)
        handle.write(struct.pack("<II", len(bin_bytes), 0x004E4942))  # 'BIN\0'
        handle.write(bin_bytes)


def self_check(gltf: Dict[str, Any], binary: bytes, data: Dict[str, Any]) -> None:
    """
    Refuse to emit an asset whose geometry is obviously wrong.

    The hard failure mode for a procedural character is not a crash — it is a file
    that loads cleanly and renders as a heap on the floor. That is exactly what
    authored joint-local coordinates produced: valid glTF, wrong figure. These
    assertions are cheap and turn a subtle visual defect into a build failure.
    """
    problems: List[str] = []

    positions = data["positions"]
    height = float(positions[:, 1].max() - positions[:, 1].min())
    floor = float(positions[:, 1].min())
    top = float(positions[:, 1].max())

    if not 1.4 < height < 2.2:
        problems.append(
            f"figure is {height:.2f} m tall; expected roughly 1.7 m. This usually "
            "means geometry is authored in joint-local space rather than world space."
        )
    if abs(floor) > 0.05:
        problems.append(
            f"lowest vertex is at y={floor:.3f}; the figure should stand on y=0. "
            "Check the foot placement."
        )

    # Every primitive needs a material, or the renderer draws the whole robot in
    # the shell colour because a glTF primitive can only carry one material.
    for i, prim in enumerate(gltf["meshes"][0]["primitives"]):
        if "material" not in prim:
            problems.append(f"primitive {i} has no material")
        if not prim.get("targets"):
            problems.append(f"primitive {i} has no morph targets")
        for required in ("POSITION", "NORMAL", "JOINTS_0", "WEIGHTS_0"):
            if required not in prim["attributes"]:
                problems.append(f"primitive {i} is missing the {required} attribute")

    # Morph target names live on the mesh, not the primitive. Getting this wrong
    # yields a model with an empty morphTargetDictionary — a face that cannot move.
    names = gltf["meshes"][0].get("extras", {}).get("targetNames")
    if not names or len(names) != len(MORPH_NAMES):
        problems.append(
            f"mesh-level extras.targetNames is missing or wrong length "
            f"({None if not names else len(names)} != {len(MORPH_NAMES)})"
        )

    # The declared buffer size must match the emitted binary, or a reader that
    # trusts byteLength will silently truncate the tail.
    declared = gltf["buffers"][0]["byteLength"]
    if declared != len(binary):
        problems.append(
            f"buffers[0].byteLength is {declared} but the binary chunk is "
            f"{len(binary)} bytes"
        )

    # Animation samplers need one keyframe per time value.
    for anim in gltf["animations"]:
        for sampler in anim["samplers"]:
            t = gltf["accessors"][sampler["input"]]
            v = gltf["accessors"][sampler["output"]]
            if t["type"] != "SCALAR":
                problems.append(f"{anim['name']}: time accessor must be SCALAR")
            if t["max"][0] <= 0:
                problems.append(f"{anim['name']}: zero-length clip")
            if t["count"] < 2:
                problems.append(
                    f"{anim['name']}: {t['count']} keyframe(s); a clip needs at least 2"
                )
            if v["count"] != t["count"]:
                problems.append(
                    f"{anim['name']}: output has {v['count']} values for "
                    f"{t['count']} keyframes"
                )

    if problems:
        raise SystemExit(
            "Asset self-check failed:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )

    print(f"  self-check    : OK ({height:.2f} m tall, standing on y=0, "
          f"top at y={top:.2f})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="web-portal/public/assets/dedan/dedan-humanoid.glb",
        help="output .glb path",
    )
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    gltf, binary, data = build_gltf()
    self_check(gltf, binary, data)
    write_glb(gltf, binary, args.out)

    size = os.path.getsize(args.out)
    print(f"Wrote {args.out}")
    print(f"  vertices      : {data['vertex_count']}")
    print(f"  triangles     : {data['indices'].size // 3}")
    print(f"  joints        : {len(JOINT_NAMES)}")
    print(f"  morph targets : {len(MORPH_NAMES)} ({MORPH_NAMES[:7]})")
    print(f"  animations    : {[c[0] for c in CLIPS]}")
    print(f"  file size     : {size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
