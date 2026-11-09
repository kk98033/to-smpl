"""Web retargeting must expose the same analytic IK pose as the UDP payload."""
from types import SimpleNamespace
import json

import numpy as np

from smpl_0901.commercial_bridge import CommercialGenericIkBridge
from smpl_0901.service import CalibrationPending
from smpl_0901 import protocol_v2_udp
from test_v61_orientation_guard import body17


def test_web_rig_matches_udp_pose_and_marks_unobserved_hands(monkeypatch):
    args=SimpleNamespace(missing_joint_hold_frames=3,smplx_preview_json=None,
        raw_skeleton_port=0,raw_skeleton_host=None,unity_host="127.0.0.1",unity_port=0,
        record_unity_packets=None,dashboard_recording_control=None,calibration_frames=3,
        axis_map="x,y,z",max_delta_deg=180,commercial_max_residual_mm=0)
    bridge=CommercialGenericIkBridge(args)
    captured=[]
    pack=protocol_v2_udp.pack_protocol_v2_frame
    def record(frame):
        captured.append(frame)
        return pack(frame)
    monkeypatch.setattr(protocol_v2_udp,"pack_protocol_v2_frame",record)
    joints=body17();joints[17:]=np.nan
    confidence=np.ones(59,dtype=np.float32);confidence[17:]=0
    try:
        for index in range(12):
            frame=SimpleNamespace(joints=joints,confidence=confidence,frame_id=index,
                                  ptp_epoch_ns=1_000_000_000+index*33_333_333)
            try:bridge.process(frame)
            except CalibrationPending:continue
        assert captured
        rig=bridge.last_fit_record["generic_rig"]
        assert np.asarray(rig["body_pose_rotvec"]).shape==(23,3)
        np.testing.assert_allclose(rig["root_rotation_xyzw"],captured[-1]["body"]["rootRotation"])
        assert rig["left_hand_confidence"]==[0.0]*21
        assert rig["right_hand_confidence"]==[0.0]*21
        assert len(rig["left_hand_local_joints"])==21
        json.dumps(rig,allow_nan=False)
        assert bridge.last_fit_record["solver"]["parametric_body_asset"] is None
    finally:
        bridge.close()
