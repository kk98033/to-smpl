"""Commercial-safe bridge backed by asset-independent Generic IK."""

from __future__ import annotations

import socket

import numpy as np
from scipy.spatial.transform import Rotation

from .commercial_ik import GenericIkTracker, GenericRig, LOWER4, UPPER11


class CommercialGenericIkBridge:
    """Protocol-compatible bridge without SMPL assets or learned checkpoints."""

    def __init__(self, args) -> None:
        from .pkssm_v61 import OrientationAnatomyStateEstimator
        from .service import CausalBodyJointImputer

        self.args = args
        self.input_adapter = OrientationAnatomyStateEstimator()
        self.joint_imputer = CausalBodyJointImputer(args.missing_joint_hold_frames)
        self.calibration = []
        self.tracker = None
        self.pelvis_anchor = None
        self.last_input_ptp_ns = None
        self.last_fit_record = None
        self.last_mesh_record = None
        self.last_smplx_record = None
        self.smplx_preview = None
        self.smplx_vertex_indices_torch = None
        self.smplx_faces = None
        self.smplx_face_joints = None
        self.smplx_topology = None
        self.smplx_betas = None
        if args.smplx_preview_json is not None:
            import torch
            from .service import (
                compact_mesh_preview_preserving_faces,
                expand_vertex_region_to_faces,
            )
            from .smplx_preview import SmplXPreview

            self.smplx_preview = SmplXPreview(
                args.smplx_model, args.device,
                beta_scale=args.smplx_beta_scale,
                surface_retarget=args.smplx_surface_retarget,
            )
            full_weights = self.smplx_preview.model.lbs_weights.detach().cpu().numpy()
            full_faces = self.smplx_preview.faces
            hand_influence = (
                full_weights[:, 20:22].sum(axis=1)
                + full_weights[:, 25:55].sum(axis=1)
            )
            preserve_hands = expand_vertex_region_to_faces(
                full_faces, hand_influence > 0.01, rings=2
            )
            vertex_indices, self.smplx_faces = compact_mesh_preview_preserving_faces(
                self.smplx_preview.model.v_template.detach().cpu().numpy(),
                full_faces,
                args.smplx_preview_faces,
                preserve_hands,
            )
            self.smplx_vertex_indices_torch = torch.tensor(
                vertex_indices, dtype=torch.long, device=args.device
            )
            self.smplx_topology = (
                "official_full_topology"
                if args.smplx_preview_faces >= len(full_faces)
                else "clustered_body_official_hands_two_wrist_rings"
            )
            compact_weights = (
                self.smplx_preview.model.lbs_weights[self.smplx_vertex_indices_torch]
                .detach().cpu().numpy()
            )
            self.smplx_face_joints = np.argmax(
                compact_weights[self.smplx_faces].mean(axis=1), axis=1
            ).astype(np.int32)
            self.smplx_betas = torch.zeros(10, dtype=torch.float32, device=args.device)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.raw_destination = (
            args.raw_skeleton_host or args.unity_host, args.raw_skeleton_port
        ) if args.raw_skeleton_port else None
        self.packet_recorder = None
        if args.record_unity_packets is not None:
            from .unity_fake_sender import UnityPacketRecorder
            self.packet_recorder = UnityPacketRecorder(args.record_unity_packets)
        elif args.dashboard_recording_control is not None:
            from .unity_fake_sender import ControlledUnityPacketRecorder
            self.packet_recorder = ControlledUnityPacketRecorder(
                args.dashboard_recording_control
            )

    def close(self) -> None:
        if self.packet_recorder is not None:
            self.packet_recorder.close()
        self.sock.close()

    def _reset(self, reason: str) -> None:
        self.input_adapter.reset()
        self.joint_imputer.reset()
        self.calibration.clear()
        self.tracker = None
        self.pelvis_anchor = None
        print(f"[bridge] commercial Generic IK reset: {reason}", flush=True)

    def _observe_timestamp(self, timestamp_ns: int) -> None:
        current = int(timestamp_ns)
        if self.last_input_ptp_ns is not None and current <= self.last_input_ptp_ns:
            self._reset(f"PTP rewind {self.last_input_ptp_ns} -> {current}")
        self.last_input_ptp_ns = current

    def process(self, frame):
        from .protocol_v2 import wrist_local_hand
        from .protocol_v2_udp import pack_protocol_v2_frame
        from .service import (
            BODY25_JOINT_NAMES, CalibrationPending, UnsafeFit,
            body25_confidence_from_factory59, body25_from_factory59,
            pose_rotation_diagnostics, _json_points,
        )

        self._observe_timestamp(frame.ptp_epoch_ns)
        completed = self.input_adapter.update(
            frame.joints, frame.confidence, frame.ptp_epoch_ns
        )
        if not completed.ready:
            raise CalibrationPending(
                "Generic IK waiting for stable orientation/anatomy: "
                f"{completed.stable_streak}/{self.input_adapter.stable_frames}"
            )
        body25, left_hand, right_hand = body25_from_factory59(completed.joints)
        confidence = body25_confidence_from_factory59(completed.confidence)
        missing = [i for i in UPPER11 if not np.isfinite(body25[i]).all()]
        if missing:
            raise ValueError(f"commercial Generic IK missing Body25 joints={missing}")
        pelvis_world = body25[8].copy()
        if self.pelvis_anchor is None:
            self.pelvis_anchor = pelvis_world.copy()
        anchored_root = pelvis_world - self.pelvis_anchor
        target = body25 - pelvis_world

        if self.tracker is None:
            self.calibration.append(target)
            if len(self.calibration) < self.args.calibration_frames:
                raise CalibrationPending(
                    f"Generic IK calibrating {len(self.calibration)}/"
                    f"{self.args.calibration_frames}"
                )
            self.tracker = GenericIkTracker(
                GenericRig.calibrate(np.stack(self.calibration)),
                max_delta_deg=self.args.max_delta_deg,
            )
            print("[bridge] commercial Generic IK calibration complete", flush=True)
        result = self.tracker.solve(target, confidence, frame.ptp_epoch_ns)

        pose = result.pose_rotvec.reshape(-1)
        root = result.pose_rotvec[0]
        body = result.pose_rotvec[1:24]
        diagnostics = pose_rotation_diagnostics(
            root, body, self.tracker.rig.rest_joints)
        residuals = np.full(25, np.nan, dtype=np.float32)
        residuals[list(result.residual_joints)] = result.joint_residual_mm
        worst_index = max(result.residual_joints, key=lambda i: float(residuals[i]))
        worst = {
            "index": int(worst_index),
            "joint": BODY25_JOINT_NAMES[worst_index],
            "mm": float(residuals[worst_index]),
        }
        reasons = []
        if not np.isfinite(pose).all():
            reasons.append("nonfinite_pose")
        limit = float(getattr(self.args, "commercial_max_residual_mm", 180.0))
        if limit > 0 and result.residual_mm > limit:
            reasons.append(f"fit_residual>{limit:g}mm")
        left_local, left_conf, left_ok = wrist_local_hand(
            left_hand, completed.confidence[17:38], side="left")
        right_local, right_conf, right_ok = wrist_local_hand(
            right_hand, completed.confidence[38:59], side="right")
        if self.smplx_preview is not None and self.smplx_faces is not None:
            smplx = self.smplx_preview.forward(
                root,
                result.pose_rotvec[1:24],
                self.smplx_betas,
                result.joints24,
                left_hand,
                completed.confidence[17:38],
                right_hand,
                completed.confidence[38:59],
            )
            preview_vertices = (
                smplx.vertices[0]
                .index_select(0, self.smplx_vertex_indices_torch)
                .detach().cpu().numpy()
            )
            from .service import _json_points
            self.last_smplx_record = {
                "schema": "smpl-0901.smplx-preview/v1",
                "frame": frame.frame_id,
                "timestamp_ns": frame.ptp_epoch_ns,
                "accepted": not reasons,
                "units": "m",
                "coordinate_frame": "smpl_axes_pelvis_relative",
                "fit_profile": (
                    "full" if set(LOWER4).issubset(result.residual_joints)
                    else "upper-body"
                ),
                "source_solver": "commercial-generic-ik",
                "source_vertex_count": int(smplx.vertices.shape[1]),
                "left_hand_valid": smplx.left_valid,
                "right_hand_valid": smplx.right_valid,
                "surface_retarget": self.args.smplx_surface_retarget,
                "mesh_topology": self.smplx_topology,
                "retargeted_smpl22": _json_points(
                    smplx.joints[0, :22].detach().cpu().numpy()
                ),
                "vertices": _json_points(preview_vertices),
                "faces": self.smplx_faces.tolist(),
                "face_joint": self.smplx_face_joints.tolist(),
            }
        packet_frame = {
            "protocolVersion": 2,
            "frameId": frame.frame_id,
            "body": {
                "rootPosition": anchored_root.tolist(),
                "pelvisWorld": pelvis_world.tolist(),
                "rootRotation": Rotation.from_rotvec(root).as_quat().astype(np.float32).tolist(),
                "rootConfidence": float(np.mean(confidence[list(UPPER11)])),
                "pose": pose.tolist(),
            },
            "hands": {
                "leftLocalJoints": left_local.reshape(-1).tolist(),
                "leftConfidence": (left_conf if left_ok else np.zeros(21)).tolist(),
                "rightLocalJoints": right_local.reshape(-1).tolist(),
                "rightConfidence": (right_conf if right_ok else np.zeros(21)).tolist(),
            },
            "quality": {
                "inputValid": not reasons,
                "inputScore": float(np.mean(completed.confidence)),
                "fitResidualMm": result.residual_mm,
                "worstJointResidualMm": float(np.nanmax(residuals)),
                "torsoOrientationDeg": result.torso_orientation_deg,
                "solverState": "FAILED_HOLD" if reasons else "TRACKING",
                "stepsUsed": 1,
                "reasons": reasons,
            },
        }
        packet = pack_protocol_v2_frame(packet_frame)
        self.last_fit_record = {
            "schema": "smpl-0901.fit/v1",
            "frame": frame.frame_id,
            "timestamp_ns": frame.ptp_epoch_ns,
            "accepted": not reasons,
            "action": "hold_previous" if reasons else "send",
            "reasons": reasons,
            "units": "m",
            "coordinate_frame": "smpl_axes_pelvis_relative",
            "axis_map": self.args.axis_map,
            "fit_profile": (
                "full" if set(LOWER4).issubset(result.residual_joints)
                else "upper-body"
            ),
            "imputed_factory59_joints": list(completed.predicted),
            "stale_factory59_joints": list(completed.stale),
            "rejected_outlier_factory59_joints": list(completed.rejected_outliers),
            "missing_joint_hold_frames": self.joint_imputer.max_hold_frames,
            "solver": {
                "profile": "commercial-generic-ik",
                "commercial_asset_independent": True,
                "dependencies": ["numpy", "scipy"],
                "learned_checkpoint": None,
                "parametric_body_asset": None,
            },
            "selected_body25_joints": list(result.residual_joints),
            "target_factory59": _json_points(completed.joints - pelvis_world),
            "target_body25": _json_points(target),
            "fitted_body25": _json_points(result.body25),
            "fitted_smpl24": _json_points(result.joints24),
            # Dashboard-only rig payload. This is the same asset-independent
            # Generic IK solution sent to Unity, exposed so a browser can
            # retarget a static skinned GLB without generating an SMPL-X mesh
            # for every frame. Quaternion order is x, y, z, w.
            "generic_rig": {
                "root_rotation_xyzw": Rotation.from_rotvec(root).as_quat()
                .astype(np.float32).tolist(),
                "body_pose_rotvec": result.pose_rotvec[1:24]
                .astype(np.float32).tolist(),
                "left_hand_local_joints": _json_points(left_local),
                "left_hand_confidence": (
                    left_conf if left_ok else np.zeros(21)
                ).astype(np.float32).tolist(),
                "right_hand_local_joints": _json_points(right_local),
                "right_hand_confidence": (
                    right_conf if right_ok else np.zeros(21)
                ).astype(np.float32).tolist(),
            },
            "joint_residual_mm": [
                None if not np.isfinite(v) else float(v) for v in residuals
            ],
            "fit_residual_mm": result.residual_mm,
            "worst_joint_residual_mm": float(np.nanmax(residuals)),
            "torso_orientation_deg": result.torso_orientation_deg,
            "fit_elapsed_ms": result.elapsed_seconds * 1000.0,
            "fit_iterations": 1,
            "body_facing_mismatch_deg": result.torso_orientation_deg,
            "consecutive_unsafe": 0,
            "reinitialize_next": False,
            "worst_target_joint": worst,
            "pose_diagnostics": diagnostics,
            "fixed_betas": None,
            "adaptive": None,
            "v61_input": {
                "ready": bool(completed.ready),
                "stable_streak": int(completed.stable_streak),
                "corrected_left_right": bool(completed.corrected_left_right),
                "rejected_regions": list(completed.rejected_regions),
                "orientation_jump_deg": completed.orientation_jump_deg,
                "shoulder_jump_deg": completed.shoulder_jump_deg,
            },
        }
        if reasons:
            raise UnsafeFit({
                "schema": "smpl-0901.distortion-log/v1",
                "frame": frame.frame_id,
                "timestamp_ns": frame.ptp_epoch_ns,
                "accepted": False,
                "action": "hold_previous",
                "reasons": reasons,
                "fit_residual_mm": result.residual_mm,
                "torso_orientation_deg": result.torso_orientation_deg,
                "fit_elapsed_ms": result.elapsed_seconds * 1000.0,
                "fit_iterations": 1,
                "body_facing_mismatch_deg": result.torso_orientation_deg,
                "worst_target_joint": worst,
                "worst_rotation": diagnostics["worst_rotation"],
                "worst_twist": diagnostics["worst_twist"],
                "worst_delta": diagnostics["worst_delta"],
                "warning_joints": diagnostics["warning_joints"],
            }, packet)
        return packet, result.residual_mm

    def send(self, packet: bytes) -> None:
        if self.args.unity_port:
            self.sock.sendto(packet, (self.args.unity_host, self.args.unity_port))
        if self.packet_recorder is not None:
            self.packet_recorder.record("SMV2", packet)

    def send_raw_skeleton(self, frame) -> bool:
        if self.raw_destination is None:
            return False
        from .raw_skeleton_udp import pack_raw_skeleton_frame
        packet = pack_raw_skeleton_frame(
            frame_id=frame.frame_id,
            ptp_epoch_ns=frame.ptp_epoch_ns,
            points=frame.raw_joints,
            confidence=frame.confidence,
            unit=frame.input_unit,
            coordinate_frame=frame.coordinate_frame,
            ptp_exact=frame.ptp_exact,
        )
        self.sock.sendto(packet, self.raw_destination)
        if self.packet_recorder is not None:
            self.packet_recorder.record("RSV1", packet)
        return True
