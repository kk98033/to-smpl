using System;
using System.Collections.Generic;
using UnityEngine;

namespace CustomSMPL.Runtime0804
{
    public class RawHandRetargeter : MonoBehaviour
    {
        [Range(0f, 1f)] public float minimumConfidence = 0.5f;
        [Tooltip("Offline playback should snap to each Hand21 target. Disable only for noisy realtime input.")]
        public bool snapToInput = true;
        [Tooltip("Enable anatomical joint angle limits (Range of Motion) to prevent finger hyperextension/inversion.")]
        public bool enableJointLimits = true;
        [Tooltip("Adaptive velocity-aware temporal smoothing to reduce jitter while preserving fast responsiveness.")]
        public bool enableAdaptiveSmoothing = true;
        public float rotationSmoothing = 18f;
        public int holdFrames = 5;
        public float relaxSpeed = 4f;

        public int LeftMappedBones { get; private set; }
        public int RightMappedBones { get; private set; }
        public int LastAppliedLeftSegments { get; private set; }
        public int LastAppliedRightSegments { get; private set; }

        private sealed class Segment
        {
            public Transform bone;
            public Transform parent;
            public Transform wrist;
            public int sourceA;
            public int sourceB;
            public int fingerIndex;
            public int segmentIndex;
            public bool isLeft;
            public Quaternion bindLocalRotation;
            public Vector3 bindDirectionInParent;
            public Vector3 semanticXInWrist;
            public Vector3 semanticYInWrist;
            public Vector3 semanticZInWrist;
            public int missingFrames;
        }

        private readonly List<Segment> leftSegments = new List<Segment>();
        private readonly List<Segment> rightSegments = new List<Segment>();
        private Transform characterRoot;

        private static readonly string[] FingerNames = { "index", "middle", "ring", "pinky", "thumb" };
        private static readonly int[] SourceRoots = { 5, 9, 13, 17, 1 };

        public void Initialize(Transform newCharacterRoot)
        {
            characterRoot = newCharacterRoot;
            leftSegments.Clear();
            rightSegments.Clear();
            if (characterRoot == null) return;

            Dictionary<string, Transform> bones = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
            foreach (Transform item in characterRoot.GetComponentsInChildren<Transform>(true))
            {
                if (!bones.ContainsKey(item.name)) bones.Add(item.name, item);
            }
            Transform leftWrist = FindBone(bones, "L_Wrist", "left_wrist", "lwrist");
            Transform rightWrist = FindBone(bones, "R_Wrist", "right_wrist", "rwrist");
            BuildSide(bones, "l", leftWrist, leftSegments, true);
            BuildSide(bones, "r", rightWrist, rightSegments, false);
            LeftMappedBones = leftSegments.Count;
            RightMappedBones = rightSegments.Count;
            Debug.Log($"[RawHandRetargeter] mapped left={LeftMappedBones}, right={RightMappedBones} finger bones (ROM limits={(enableJointLimits ? "ON" : "OFF")}).");
        }

        private static Transform FindBone(Dictionary<string, Transform> bones, params string[] names)
        {
            foreach (string name in names)
            {
                if (bones.TryGetValue(name, out Transform result)) return result;
            }
            return null;
        }

        private static void BuildSide(
            Dictionary<string, Transform> bones,
            string prefix,
            Transform wrist,
            List<Segment> output,
            bool isLeft)
        {
            if (wrist == null)
            {
                Debug.LogWarning($"[RawHandRetargeter] Could not find {prefix} wrist.");
                return;
            }

            Vector3 semanticX = Vector3.right;
            Vector3 semanticY = Vector3.up;
            Vector3 semanticZ = Vector3.forward;
            if (bones.TryGetValue($"{prefix}index0", out Transform indexRoot) &&
                bones.TryGetValue($"{prefix}middle0", out Transform middleRoot) &&
                bones.TryGetValue($"{prefix}pinky0", out Transform pinkyRoot))
            {
                // Match protocol_v2.wrist_local_hand exactly: semantic X is
                // pinky->index for left and mirrored for right; semantic Y
                // points wrist->middle MCP; Z is the palm normal.
                Vector3 xWorld = indexRoot.position - pinkyRoot.position;
                if (prefix == "r") xWorld = -xWorld;
                semanticX = wrist.InverseTransformDirection(xWorld).normalized;
                Vector3 yHint = wrist.InverseTransformDirection(middleRoot.position - wrist.position).normalized;
                // Invert Cross product because Unity uses Left-Handed coordinates
                // while Python Protocol V2 wrist_local_hand uses Right-Handed coordinates.
                // This ensures flexion bends towards the palm instead of hyperextending backwards.
                semanticZ = -Vector3.Cross(semanticX, yHint).normalized;
                semanticY = Vector3.Cross(semanticZ, semanticX).normalized;
            }
            for (int finger = 0; finger < FingerNames.Length; finger++)
            {
                Transform[] chain = new Transform[3];
                for (int segment = 0; segment < 3; segment++)
                {
                    bones.TryGetValue($"{prefix}{FingerNames[finger]}{segment}", out chain[segment]);
                }
                for (int segment = 0; segment < 3; segment++)
                {
                    Transform bone = chain[segment];
                    if (bone == null || bone.parent == null) continue;
                    // SUP's SMPL-H prefab stores the *_end helper of every
                    // distal phalanx on local +Y, while the actual finger chain
                    // runs along local +/-X. Using that helper twists every
                    // final finger segment by roughly 90 degrees. For the
                    // distal phalanx, continue the preceding bone direction.
                    Vector3 worldDirection;
                    if (segment < 2 && chain[segment + 1] != null)
                    {
                        worldDirection = chain[segment + 1].position - bone.position;
                    }
                    else
                    {
                        worldDirection = bone.position - bone.parent.position;
                    }
                    if (worldDirection.sqrMagnitude < 1e-10f)
                        worldDirection = bone.parent.TransformDirection(Vector3.right);
                    Vector3 parentDirection = bone.parent.InverseTransformDirection(worldDirection).normalized;
                    output.Add(new Segment
                    {
                        bone = bone,
                        parent = bone.parent,
                        wrist = wrist,
                        sourceA = SourceRoots[finger] + segment,
                        sourceB = SourceRoots[finger] + segment + 1,
                        fingerIndex = finger,
                        segmentIndex = segment,
                        isLeft = isLeft,
                        bindLocalRotation = bone.localRotation,
                        bindDirectionInParent = parentDirection,
                        semanticXInWrist = semanticX,
                        semanticYInWrist = semanticY,
                        semanticZInWrist = semanticZ,
                        missingFrames = 0,
                    });
                }
            }
        }

        public void ApplyHands(ProtocolV2Hands hands)
        {
            if (hands == null) return;
            LastAppliedLeftSegments = ApplySide(leftSegments, hands.leftLocalJoints, hands.leftConfidence);
            LastAppliedRightSegments = ApplySide(rightSegments, hands.rightLocalJoints, hands.rightConfidence);
        }

        public void ResetToBindPose()
        {
            ResetSide(leftSegments);
            ResetSide(rightSegments);
            LastAppliedLeftSegments = 0;
            LastAppliedRightSegments = 0;
        }

        private static void ResetSide(List<Segment> segments)
        {
            foreach (Segment segment in segments)
            {
                if (segment.bone != null) segment.bone.localRotation = segment.bindLocalRotation;
                segment.missingFrames = 0;
            }
        }

        private int ApplySide(List<Segment> segments, float[] flatJoints, float[] confidence)
        {
            if (flatJoints == null || flatJoints.Length != 63 || confidence == null || confidence.Length != 21) return 0;
            float relaxBlend = 1f - Mathf.Exp(-Mathf.Max(0.01f, relaxSpeed) * Time.deltaTime);
            int applied = 0;
            foreach (Segment segment in segments)
            {
                float segmentConfidence = Mathf.Min(confidence[segment.sourceA], confidence[segment.sourceB]);
                Vector3 sourceA = ReadPoint(flatJoints, segment.sourceA);
                Vector3 sourceB = ReadPoint(flatJoints, segment.sourceB);
                Vector3 localDirection = sourceB - sourceA;
                bool valid = segmentConfidence >= minimumConfidence && localDirection.sqrMagnitude > 1e-8f;
                if (!valid)
                {
                    segment.missingFrames++;
                    if (segment.missingFrames > holdFrames)
                    {
                        segment.bone.localRotation = Quaternion.Slerp(segment.bone.localRotation, segment.bindLocalRotation, relaxBlend);
                    }
                    continue;
                }

                Vector3 semanticDirection = localDirection.normalized;

                // Apply anatomical Euler Hinge rotations matching SMPL-H rig (CustomAnimationPlayer standard)
                Quaternion targetRotation;
                if (segment.fingerIndex < 4) // Four fingers: Index (0), Middle (1), Ring (2), Pinky (3)
                {
                    // Flexion angle in degrees (0 = flat open hand, 90 = full fist curl)
                    float flexDeg = Mathf.Atan2(-semanticDirection.z, Mathf.Max(0.001f, semanticDirection.y)) * Mathf.Rad2Deg;
                    float maxFlex = segment.segmentIndex == 0 ? 85f : (segment.segmentIndex == 1 ? 100f : 85f);
                    flexDeg = Mathf.Clamp(flexDeg, 0f, maxFlex);

                    // Lateral spreading / abduction angle in degrees (MCP only: -15 to +15 deg)
                    float abdDeg = segment.segmentIndex == 0
                        ? Mathf.Clamp(Mathf.Atan2(semanticDirection.x, Mathf.Max(0.001f, semanticDirection.y)) * Mathf.Rad2Deg, -15f, 15f)
                        : 0f;

                    // In SMPL-H character rig:
                    // Left hand flexes around local +Z, Right hand flexes around local -Z
                    if (segment.isLeft)
                    {
                        targetRotation = Quaternion.Euler(0f, abdDeg, flexDeg);
                    }
                    else
                    {
                        targetRotation = Quaternion.Euler(0f, -abdDeg, -flexDeg);
                    }
                }
                else // Thumb (4)
                {
                    float thumbFlex = Mathf.Atan2(-semanticDirection.z, Mathf.Max(0.001f, semanticDirection.y)) * Mathf.Rad2Deg;
                    float maxFlex = segment.segmentIndex == 0 ? 50f : (segment.segmentIndex == 1 ? 65f : 80f);
                    thumbFlex = Mathf.Clamp(thumbFlex, -5f, maxFlex);

                    float thumbAbd = Mathf.Clamp(Mathf.Atan2(semanticDirection.x, Mathf.Max(0.001f, semanticDirection.y)) * Mathf.Rad2Deg, -25f, 25f);

                    if (segment.isLeft)
                    {
                        targetRotation = Quaternion.Euler(thumbFlex * 0.25f, -thumbFlex, thumbAbd);
                    }
                    else
                    {
                        targetRotation = Quaternion.Euler(thumbFlex * 0.25f, thumbFlex, -thumbAbd);
                    }
                }

                // Calculate smoothing rate
                float currentBlend;
                if (snapToInput)
                {
                    currentBlend = 1f;
                }
                else if (enableAdaptiveSmoothing)
                {
                    float angleDiff = Quaternion.Angle(segment.bone.localRotation, targetRotation);
                    float adaptiveRate = Mathf.Lerp(rotationSmoothing, rotationSmoothing * 2.5f, Mathf.Clamp01(angleDiff / 30f));
                    currentBlend = 1f - Mathf.Exp(-Mathf.Max(0.01f, adaptiveRate) * Time.deltaTime);
                }
                else
                {
                    currentBlend = 1f - Mathf.Exp(-Mathf.Max(0.01f, rotationSmoothing) * Time.deltaTime);
                }

                segment.bone.localRotation = Quaternion.Slerp(segment.bone.localRotation, targetRotation, currentBlend);
                applied++;
            }
            return applied;
        }

        /// <summary>
        /// Anatomical Range-of-Motion (ROM) clamping for human fingers.
        /// Prevents hyperextension backwards or unnatural sideways bending.
        /// </summary>
        private static Vector3 ClampSemanticDirection(Vector3 dir, int finger, int segment, bool isLeft)
        {
            float x = dir.x;
            float y = Mathf.Max(0.0001f, dir.y);
            float z = dir.z;

            if (finger < 4) // Four Fingers: Index (0), Middle (1), Ring (2), Pinky (3)
            {
                if (segment == 0) // MCP (Base Knuckle)
                {
                    // Flexion (-Z): -15 deg (slight extension) to +90 deg (full fist)
                    float flexDeg = Mathf.Atan2(-z, y) * Mathf.Rad2Deg;
                    flexDeg = Mathf.Clamp(flexDeg, -15f, 90f);

                    // Abduction (X): -20 deg to +20 deg splay
                    float abdDeg = Mathf.Atan2(x, y) * Mathf.Rad2Deg;
                    abdDeg = Mathf.Clamp(abdDeg, -20f, 20f);

                    float flexRad = flexDeg * Mathf.Deg2Rad;
                    float abdRad = abdDeg * Mathf.Deg2Rad;
                    y = Mathf.Cos(flexRad) * Mathf.Cos(abdRad);
                    z = -Mathf.Sin(flexRad);
                    x = Mathf.Sin(abdRad);
                }
                else // PIP (1) or DIP (2) - Pure Hinge Joints
                {
                    // Pure hinge: suppress lateral splay
                    x = 0f;
                    float maxFlex = segment == 1 ? 110f : 85f;
                    float flexDeg = Mathf.Atan2(-z, y) * Mathf.Rad2Deg;
                    // No hyperextension at PIP/DIP (flexion >= 0)
                    flexDeg = Mathf.Clamp(flexDeg, 0f, maxFlex);

                    float flexRad = flexDeg * Mathf.Deg2Rad;
                    y = Mathf.Cos(flexRad);
                    z = -Mathf.Sin(flexRad);
                }
            }
            else // Thumb (4)
            {
                float maxFlex = segment == 0 ? 55f : (segment == 1 ? 70f : 90f);
                float flexDeg = Mathf.Atan2(-z, y) * Mathf.Rad2Deg;
                flexDeg = Mathf.Clamp(flexDeg, -10f, maxFlex);

                float abdDeg = Mathf.Atan2(x, y) * Mathf.Rad2Deg;
                abdDeg = Mathf.Clamp(abdDeg, -35f, 35f);

                float flexRad = flexDeg * Mathf.Deg2Rad;
                float abdRad = abdDeg * Mathf.Deg2Rad;
                y = Mathf.Cos(flexRad) * Mathf.Cos(abdRad);
                z = -Mathf.Sin(flexRad);
                x = Mathf.Sin(abdRad);
            }

            return new Vector3(x, y, z).normalized;
        }

        private static Vector3 ReadPoint(float[] values, int index)
        {
            int offset = index * 3;
            return new Vector3(values[offset], values[offset + 1], values[offset + 2]);
        }
    }
}
