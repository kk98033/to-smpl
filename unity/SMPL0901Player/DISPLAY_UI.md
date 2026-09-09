# Display, UI, and demo-scene controls

These controls operate above the existing SMV2/RSV1 pose application. They do
not change packet decoding, SMPL joint indices, bind-relative bone rotations,
or Hand21 retargeting.

## Facing defaults

- Bind-relative SMPL mesh and fitted skeleton: additional Y `180` degrees.
- Raw 59-point skeleton: additional Y `-90` degrees (left turn).
- Raw-to-avatar baseline: the same Y `-90` degrees as the Raw skeleton.
- With Bind-relative disabled, the SMPL display uses the Raw display turn.

The runtime UI exposes the two facing yaw values and a `Reset Facing` button.
`Display Rot` remains a common parent/world placement rotation.

## Raw avatar scale and visibility

`Raw Avatar` toggles the comparison character driven directly from RSV1 joint
directions. `matchSmplCharacterScale` is enabled by default, so it uses the
same prefab scale as the SMPL character. The older raw-span auto-scaling path
remains available in the Inspector but is disabled by default.

## Hybrid fingers

The existing hybrid order is unchanged: SMPL body rotations are applied first,
then `Smpl0901RawHandRetargeter` applies the wrist-local left/right Hand21 data
derived from factory-59. SMPL does not drive the finger slots.

## UI collapse animation

Press `Hide UI <` to slide the panel off screen. The remaining `SMPL Player >`
button slides it back in. This does not stop either UDP receiver.

## One-click room

Use `SMPL 0901/Create Demo Room + Camera + Live Player`. It creates or repairs:

```text
SMPL0901_DemoScene
|- Environment
|  |- Floor
|  |- Back Wall
|  |- Left Wall
|  `- Right Wall
|- Actors
|  `- SMPL0901_LivePlayer
|- Cameras
|  `- Main Camera or SMPL0901_Camera
`- Lighting
   `- Key Light
```

The player pelvis starts at Y=1 above a floor whose top is Y=0, and the camera
is aimed at the standing character.
