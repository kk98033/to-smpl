# Web avatar rig output

The commercial Generic IK fit record includes `generic_rig` for a browser-side
skinned GLB avatar. This uses the same analytic IK result as the UDP body pose,
without generating a per-frame SMPL/SMPL-X mesh.

- `root_rotation_xyzw`: root quaternion in x, y, z, w order.
- `body_pose_rotvec`: 23 body joint rotation vectors, radians.
- `left_hand_local_joints` / `right_hand_local_joints`: 21 wrist-local points.
- `left_hand_confidence` / `right_hand_confidence`: 21 scores; invalid hands have zero scores.

The existing fit record axis/units fields remain authoritative. Avatar bind-pose
retargeting is performed by the browser. SMPL-X preview is optional; no body asset
is required when that preview is disabled.
