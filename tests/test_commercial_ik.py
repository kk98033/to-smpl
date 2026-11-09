from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from smpl_0901.commercial_bridge import CommercialGenericIkBridge
from smpl_0901.commercial_ik import GenericIkTracker, GenericRig


def body25() -> np.ndarray:
    joints = np.zeros((25, 3), dtype=np.float32)
    joints[8] = (0.0, 0.0, 0.0)
    joints[1] = (0.0, 0.55, 0.0)
    joints[0] = (0.0, 0.72, 0.08)
    joints[2:5] = ((-0.22, 0.55, 0.0), (-0.48, 0.55, 0.0),
                   (-0.72, 0.55, 0.0))
    joints[5:8] = ((0.22, 0.55, 0.0), (0.48, 0.55, 0.0),
                   (0.72, 0.55, 0.0))
    joints[9:12] = ((-0.1, 0.0, 0.0), (-0.1, -0.4, 0.0),
                    (-0.1, -0.8, 0.0))
    joints[12:15] = ((0.1, 0.0, 0.0), (0.1, -0.4, 0.0),
                     (0.1, -0.8, 0.0))
    return joints


def tracker() -> GenericIkTracker:
    sample = body25()
    return GenericIkTracker(GenericRig.calibrate(np.stack([sample] * 30)))


def test_generic_solver_is_finite_and_fast_shape() -> None:
    result = tracker().solve(body25(), np.ones(25), 1_000_000_000)
    assert result.pose_rotvec.shape == (52, 3)
    assert result.joints24.shape == (24, 3)
    assert np.isfinite(result.pose_rotvec).all()
    assert result.residual_mm < 50.0


def test_arm_direction_follows_observation() -> None:
    solver = tracker()
    target = body25()
    target[6] = (0.35, 0.76, 0.0)
    target[7] = (0.30, 1.02, 0.0)
    result = solver.solve(target, np.ones(25), 1_000_000_000)
    observed = target[7] - target[6]
    fitted = result.joints24[20] - result.joints24[18]
    cosine = np.dot(observed, fitted) / np.linalg.norm(observed) / np.linalg.norm(fitted)
    assert cosine > 0.95


def test_generic_solver_tracks_full_body_when_legs_are_available() -> None:
    result = tracker().solve(body25(), np.ones(25), 1_000_000_000)
    assert {10, 11, 13, 14}.issubset(result.residual_joints)
    assert np.isfinite(result.joints24[[4, 5, 7, 8]]).all()


def test_imputed_finite_upper_joint_is_accepted() -> None:
    solver = tracker()
    confidence = np.ones(25, dtype=np.float32)
    confidence[7] = 0.0
    result = solver.solve(body25(), confidence, 1_000_000_000)
    assert np.isfinite(result.pose_rotvec).all()


def test_nonfinite_upper_joint_is_rejected() -> None:
    solver = tracker()
    target = body25()
    target[7] = np.nan
    try:
        solver.solve(target, np.ones(25), 1_000_000_000)
    except ValueError as error:
        assert "incomplete upper-body" in str(error)
    else:
        raise AssertionError("non-finite wrist should be rejected")


def test_runaway_joint_is_held_at_previous_trustworthy_position() -> None:
    solver = tracker()
    first = solver.solve(body25(), np.ones(25), 1_000_000_000)
    target = body25()
    target[7] = (9.0, 8.0, -7.0)
    second = solver.solve(target, np.ones(25), 1_033_333_333)

    assert 7 in second.held_joints
    assert np.linalg.norm(second.joints24[20] - first.joints24[20]) < 0.1


def test_generic_bridge_can_disable_unity_udp() -> None:
    class FailOnSend:
        def sendto(self, *_args) -> None:
            raise AssertionError("Unity UDP must remain disabled")

    bridge = CommercialGenericIkBridge.__new__(CommercialGenericIkBridge)
    bridge.args = SimpleNamespace(unity_host="127.0.0.1", unity_port=0)
    bridge.sock = FailOnSend()
    bridge.packet_recorder = None

    bridge.send(b"SMV2")
