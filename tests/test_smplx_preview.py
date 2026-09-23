from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from smpl_0901.service import (
    compact_mesh_preview_topology,
    compact_mesh_preview_preserving_faces,
    expand_vertex_region_to_faces,
)
from smpl_0901.smplx_preview import _align, _limit_delta


def test_align_maps_source_direction_to_target() -> None:
    source = np.asarray((1.0, 0.0, 0.0))
    target = np.asarray((0.0, 1.0, 0.0))
    solved = _align(source, target).apply(source)
    np.testing.assert_allclose(solved, target, atol=1e-6)


def test_limit_delta_caps_rotation_change() -> None:
    previous = np.zeros(3)
    current = Rotation.from_euler("z", 120, degrees=True).as_rotvec()
    limited = _limit_delta(previous, current, 55.0)
    angle = np.degrees(Rotation.from_rotvec(limited).magnitude())
    assert np.isclose(angle, 55.0, atol=1e-5)


def test_hand_preserving_compaction_keeps_selected_face_vertices_exact() -> None:
    vertices = np.asarray([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        [2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [2.0, 1.0, 0.0],
    ], dtype=np.float32)
    faces = np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
    indices, compact = compact_mesh_preview_preserving_faces(
        vertices, faces, 2, np.asarray([False, True])
    )
    restored = indices[compact]
    assert any(np.array_equal(face, faces[1]) for face in restored)
    assert len(compact) == 2


def test_full_face_budget_retains_original_topology_exactly() -> None:
    vertices = np.asarray([
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float32)
    faces = np.asarray([
        [0, 1, 2], [0, 3, 1], [1, 3, 2], [0, 2, 3],
    ], dtype=np.int32)
    indices, compact = compact_mesh_preview_topology(
        vertices, faces, max_faces=len(faces)
    )
    np.testing.assert_array_equal(indices[compact], faces)


def test_face_region_expansion_keeps_a_wrist_transition_ring() -> None:
    faces = np.asarray([[0, 1, 2], [2, 3, 4], [4, 5, 6]], dtype=np.int32)
    seed = np.asarray([True, False, False, False, False, False, False])
    np.testing.assert_array_equal(
        expand_vertex_region_to_faces(faces, seed, rings=0),
        [True, False, False],
    )
    np.testing.assert_array_equal(
        expand_vertex_region_to_faces(faces, seed, rings=1),
        [True, True, False],
    )
    np.testing.assert_array_equal(
        expand_vertex_region_to_faces(faces, seed, rings=2),
        [True, True, True],
    )
