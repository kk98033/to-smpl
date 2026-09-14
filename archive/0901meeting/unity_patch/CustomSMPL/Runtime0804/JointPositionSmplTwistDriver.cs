using System;
using System.Collections.Generic;
using SMPLModel;
using UnityEngine;

namespace CustomSMPL.Runtime0804
{
    /// <summary>
    /// Controlled AMASS comparison driver. The reference SMPL-H axis-angle is
    /// applied first. Source joints then correct only each bone's swing so the
    /// segment follows the observed joint pair; the SMPL rotation supplies the
    /// otherwise unobservable axial twist.
    /// </summary>
    public class JointPositionSmplTwistDriver : MonoBehaviour
    {
        [Range(0f, 1f)] public float minimumConfidence = 0.5f;
        [Tooltip("Translate mapped bone origins onto source joints before applying swing correction.")]
        public bool pullBonePositions = true;
        public int DrivenSegments { get; private set; }
        public float MaxDirectionErrorDegrees { get; private set; }
        public float MaxPositionErrorM { get; private set; }

        private sealed class Driver
        {
            public Transform bone;
            public int sourceA;
            public int sourceB;
            public Vector3 bindAxisLocal;
            public float positionAlongSegment;
        }

        private sealed class Anchor
        {
            public Transform bone;
            public int sourceA;
            public int sourceB;
            public float fraction;
        }

        private readonly List<Driver> drivers = new List<Driver>();
        private readonly List<Anchor> anchors = new List<Anchor>();
        private Transform playerRoot;

        private static readonly string[] FingerNames = { "index", "middle", "ring", "pinky", "thumb" };
        private static readonly int[] HandRoots = { 5, 9, 13, 17, 1 };

        public void Initialize(Transform characterRoot, Transform sourcePlayerRoot)
        {
            drivers.Clear();
            anchors.Clear();
            playerRoot = sourcePlayerRoot;
            if (characterRoot == null || playerRoot == null) return;

            Dictionary<string, Transform> bones = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
            foreach (Transform item in characterRoot.GetComponentsInChildren<Transform>(true))
                if (!bones.ContainsKey(item.name)) bones.Add(item.name, item);

            // Body25 direction constraints. Parent segments are registered
            // before children so every correction uses the updated hierarchy.
            AddAnchor(bones, Bones.Pelvis, 8, 8, 0f);
            AddAnchor(bones, Bones.Spine1, 8, 1, 0.25f);
            AddAnchor(bones, Bones.Spine2, 8, 1, 0.50f);
            Add(bones, Bones.Spine3, Bones.Neck, 8, 1, 0.75f);
            Add(bones, Bones.Neck, Bones.Head, 1, 0);
            Add(bones, Bones.LeftCollar, Bones.LeftShoulder, 1, 5);
            Add(bones, Bones.LeftShoulder, Bones.LeftElbow, 5, 6);
            Add(bones, Bones.LeftElbow, Bones.LeftWrist, 6, 7);
            Add(bones, Bones.RightCollar, Bones.RightShoulder, 1, 2);
            Add(bones, Bones.RightShoulder, Bones.RightElbow, 2, 3);
            Add(bones, Bones.RightElbow, Bones.RightWrist, 3, 4);
            Add(bones, Bones.LeftHip, Bones.LeftKnee, 12, 13);
            Add(bones, Bones.LeftKnee, Bones.LeftAnkle, 13, 14);
            Add(bones, Bones.RightHip, Bones.RightKnee, 9, 10);
            Add(bones, Bones.RightKnee, Bones.RightAnkle, 10, 11);
            AddAnchor(bones, Bones.LeftWrist, 7, 7, 0f);
            AddAnchor(bones, Bones.RightWrist, 4, 4, 0f);
            AddAnchor(bones, Bones.LeftAnkle, 14, 14, 0f);
            AddAnchor(bones, Bones.RightAnkle, 11, 11, 0f);

            AddHand(bones, "l", 25);
            AddHand(bones, "r", 46);
            Debug.Log($"[JointPositionSmplTwistDriver] initialized {drivers.Count} body/hand segment constraints.");
        }

        private void Add(
            Dictionary<string, Transform> bones,
            string boneName,
            string childName,
            int sourceA,
            int sourceB,
            float positionAlongSegment = 0f)
        {
            if (!bones.TryGetValue(boneName, out Transform bone) ||
                !bones.TryGetValue(childName, out Transform child)) return;
            Vector3 direction = child.position - bone.position;
            if (direction.sqrMagnitude < 1e-10f) return;
            drivers.Add(new Driver
            {
                bone = bone,
                sourceA = sourceA,
                sourceB = sourceB,
                bindAxisLocal = bone.InverseTransformDirection(direction.normalized),
                positionAlongSegment = positionAlongSegment,
            });
        }

        private void AddAnchor(
            Dictionary<string, Transform> bones,
            string boneName,
            int sourceA,
            int sourceB,
            float fraction)
        {
            if (!bones.TryGetValue(boneName, out Transform bone)) return;
            anchors.Add(new Anchor
            {
                bone = bone,
                sourceA = sourceA,
                sourceB = sourceB,
                fraction = Mathf.Clamp01(fraction),
            });
        }

        private void AddHand(Dictionary<string, Transform> bones, string prefix, int handOffset)
        {
            for (int finger = 0; finger < FingerNames.Length; finger++)
            {
                Transform[] chain = new Transform[3];
                for (int segment = 0; segment < 3; segment++)
                    bones.TryGetValue($"{prefix}{FingerNames[finger]}{segment}", out chain[segment]);

                int sourceRoot = handOffset + HandRoots[finger];
                for (int segment = 0; segment < 3; segment++)
                {
                    Transform bone = chain[segment];
                    if (bone == null || bone.parent == null) continue;
                    Vector3 direction = segment < 2 && chain[segment + 1] != null
                        ? chain[segment + 1].position - bone.position
                        : bone.position - bone.parent.position;
                    if (direction.sqrMagnitude < 1e-10f) continue;
                    drivers.Add(new Driver
                    {
                        bone = bone,
                        sourceA = sourceRoot + segment,
                        sourceB = sourceRoot + segment + 1,
                        bindAxisLocal = bone.InverseTransformDirection(direction.normalized),
                        positionAlongSegment = 0f,
                    });
                }
            }
        }

        public void Apply(ProtocolV2Frame frame, Vector3 sourceEuler)
        {
            DrivenSegments = 0;
            MaxDirectionErrorDegrees = 0f;
            MaxPositionErrorM = 0f;
            if (frame == null || frame.observation == null || frame.observation.joints == null ||
                frame.observation.jointCount < 67 || playerRoot == null) return;

            float[] joints = frame.observation.joints;
            float[] confidence = frame.observation.confidence;
            Quaternion calibration = Quaternion.Euler(sourceEuler);
            if (pullBonePositions)
            {
                // Root/spine/end-effector anchors first. Subsequent parent-to-
                // child driver updates re-place every mapped branch after its
                // parent's transform changes.
                foreach (Anchor anchor in anchors)
                {
                    if (anchor.bone == null || !Reliable(confidence, anchor.sourceA, anchor.sourceB)) continue;
                    Vector3 a = TargetWorldPoint(joints, anchor.sourceA, calibration);
                    Vector3 b = TargetWorldPoint(joints, anchor.sourceB, calibration);
                    anchor.bone.position = Vector3.Lerp(a, b, anchor.fraction);
                }
            }
            foreach (Driver driver in drivers)
            {
                if (driver.bone == null || driver.sourceA >= 67 || driver.sourceB >= 67) continue;
                if (!Reliable(confidence, driver.sourceA, driver.sourceB)) continue;

                Vector3 targetA = TargetWorldPoint(joints, driver.sourceA, calibration);
                Vector3 targetB = TargetWorldPoint(joints, driver.sourceB, calibration);
                if (pullBonePositions)
                    driver.bone.position = Vector3.Lerp(targetA, targetB, driver.positionAlongSegment);
                Vector3 targetWorld = (targetB - targetA).normalized;
                Vector3 currentWorld = driver.bone.TransformDirection(driver.bindAxisLocal).normalized;
                if (targetWorld.sqrMagnitude < 1e-10f || currentWorld.sqrMagnitude < 1e-10f) continue;

                Quaternion swingCorrection = Quaternion.FromToRotation(currentWorld, targetWorld.normalized);
                driver.bone.rotation = swingCorrection * driver.bone.rotation;
                float error = Vector3.Angle(
                    driver.bone.TransformDirection(driver.bindAxisLocal), targetWorld
                );
                MaxDirectionErrorDegrees = Mathf.Max(MaxDirectionErrorDegrees, error);
                DrivenSegments++;
            }

            if (pullBonePositions)
            {
                foreach (Anchor anchor in anchors)
                {
                    if (anchor.bone == null || !Reliable(confidence, anchor.sourceA, anchor.sourceB)) continue;
                    Vector3 target = Vector3.Lerp(
                        TargetWorldPoint(joints, anchor.sourceA, calibration),
                        TargetWorldPoint(joints, anchor.sourceB, calibration),
                        anchor.fraction
                    );
                    MaxPositionErrorM = Mathf.Max(MaxPositionErrorM, Vector3.Distance(anchor.bone.position, target));
                }
                foreach (Driver driver in drivers)
                {
                    if (driver.bone == null || !Reliable(confidence, driver.sourceA, driver.sourceB)) continue;
                    Vector3 target = Vector3.Lerp(
                        TargetWorldPoint(joints, driver.sourceA, calibration),
                        TargetWorldPoint(joints, driver.sourceB, calibration),
                        driver.positionAlongSegment
                    );
                    MaxPositionErrorM = Mathf.Max(MaxPositionErrorM, Vector3.Distance(driver.bone.position, target));
                }
            }
        }

        private bool Reliable(float[] confidence, int sourceA, int sourceB)
        {
            float confA = confidence != null && sourceA < confidence.Length ? confidence[sourceA] : 1f;
            float confB = confidence != null && sourceB < confidence.Length ? confidence[sourceB] : 1f;
            return Mathf.Min(confA, confB) >= minimumConfidence;
        }

        private Vector3 TargetWorldPoint(float[] joints, int index, Quaternion calibration)
        {
            Vector3 point = ReadPoint(joints, index);
            point.x = -point.x;
            return playerRoot.TransformPoint(calibration * point);
        }

        private static Vector3 ReadPoint(float[] values, int index)
        {
            int offset = index * 3;
            return new Vector3(values[offset], values[offset + 1], values[offset + 2]);
        }
    }
}
