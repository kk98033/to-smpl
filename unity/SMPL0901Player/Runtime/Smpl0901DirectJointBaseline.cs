using System;
using System.Collections.Generic;
using UnityEngine;
using Utilities;
using SMPLModel;

namespace SMPL0901Player.Runtime
{
    /// <summary>
    /// A comparison character driven only by RSV1 spatial joint directions.
    /// It deliberately does not consume SMV2 root_orient/body_pose. From-to
    /// rotations retain the prefab's bind twist, which makes this useful for
    /// separating SMPL pose errors from Unity rig/coordinate errors.
    /// </summary>
    public sealed class Smpl0901DirectJointBaseline : MonoBehaviour
    {
        [Header("Sources")]
        public Smpl0901LivePlayer player;
        public Rsv1RawSkeletonRenderer rawSkeleton;

        [Header("Display")]
        public bool renderBaseline = true;
        [Tooltip("Pelvis offset from the SMPL-driven character, in player-local metres.")]
        public Vector3 baselineOffset = new Vector3(2f, 0f, 0f);
        [Tooltip("Uniformly match the direct character's pelvis-to-ankle/neck size to RSV1.")]
        public bool autoScaleToRaw = true;
        [Range(0.25f, 3f)] public float minimumScale = 0.5f;
        [Range(0.25f, 3f)] public float maximumScale = 1.8f;

        public bool IsReady => runtimeCharacter != null && pelvis != null;
        public string Status { get; private set; } = "not built";

        private const int VirtualPelvis = 59;
        private const int VirtualNeck = 60;
        private const int VirtualAnkleMid = 61;

        private static readonly DriverSpec[] DriverSpecs =
        {
            new DriverSpec("Spine1", "Spine2", VirtualPelvis, VirtualNeck),
            new DriverSpec("Spine2", "Spine3", VirtualPelvis, VirtualNeck),
            new DriverSpec("Spine3", "Neck", VirtualPelvis, VirtualNeck),
            new DriverSpec("Neck", "Head", VirtualNeck, 0),
            new DriverSpec("L_Collar", "L_Shoulder", VirtualNeck, 5),
            new DriverSpec("L_Shoulder", "L_Elbow", 5, 7),
            new DriverSpec("L_Elbow", "L_Wrist", 7, 9),
            new DriverSpec("R_Collar", "R_Shoulder", VirtualNeck, 6),
            new DriverSpec("R_Shoulder", "R_Elbow", 6, 8),
            new DriverSpec("R_Elbow", "R_Wrist", 8, 10),
            new DriverSpec("L_Hip", "L_Knee", 11, 13),
            new DriverSpec("L_Knee", "L_Ankle", 13, 15),
            new DriverSpec("R_Hip", "R_Knee", 12, 14),
            new DriverSpec("R_Knee", "R_Ankle", 14, 16),
        };

        private Transform baselineRoot;
        private GameObject runtimeCharacter;
        private Transform pelvis;
        private Transform neck;
        private Transform leftHip;
        private Transform rightHip;
        private Transform leftAnkle;
        private Transform rightAnkle;
        private Transform[] rigBones;
        private Quaternion[] bindLocalRotations;
        private Vector3[] bindLocalPositions;
        private SkinnedMeshRenderer[] renderers;
        private readonly List<DirectionDriver> drivers = new List<DirectionDriver>();
        private Quaternion bindBodyBasis = Quaternion.identity;
        private float bindBodySpan = 1f;
        private int appliedRevision = -1;

        private void Start()
        {
            ResolveSources();
            TryBuild();
        }

        private void Update()
        {
            ResolveSources();
            if (!IsReady) TryBuild();
            if (!IsReady || rawSkeleton == null) return;
            if (!rawSkeleton.TryGetLatestPelvisRelativePose(
                    out Vector3[] points, out bool[] valid, out int revision)) return;
            if (revision == appliedRevision) return;
            appliedRevision = revision;
            ApplyDirectPose(points, valid);
        }

        public void SetVisible(bool visible)
        {
            renderBaseline = visible;
            if (runtimeCharacter != null) runtimeCharacter.SetActive(visible);
        }

        public void SetBaselineOffset(Vector3 offset)
        {
            baselineOffset = offset;
            if (baselineRoot != null) baselineRoot.localPosition = offset;
        }

        public void ResetBaselineOffset()
        {
            SetBaselineOffset(new Vector3(2f, 0f, 0f));
        }

        public void ShowBindPose()
        {
            if (!IsReady) return;
            ResetRigToBindPose();
            baselineRoot.localPosition = baselineOffset;
            baselineRoot.localRotation = Quaternion.identity;
            baselineRoot.localScale = Vector3.one;
        }

        private void ResolveSources()
        {
            if (player == null) player = GetComponent<Smpl0901LivePlayer>();
            if (rawSkeleton == null) rawSkeleton = GetComponent<Rsv1RawSkeletonRenderer>();
        }

        private void TryBuild()
        {
            if (runtimeCharacter != null || player == null || player.characterPrefab == null) return;

            GameObject rootObject = new GameObject("SMPL0901_DirectXYZ_BaselineRoot");
            rootObject.transform.SetParent(transform, false);
            baselineRoot = rootObject.transform;
            baselineRoot.localPosition = baselineOffset;

            runtimeCharacter = Instantiate(
                player.characterPrefab, baselineRoot.position, Quaternion.identity, baselineRoot);
            runtimeCharacter.name = player.characterPrefab.name + "_DirectXYZ_Baseline";
            runtimeCharacter.transform.localRotation = Quaternion.identity;

            CharacterPoser poser = runtimeCharacter.GetComponentInChildren<CharacterPoser>(true);
            if (poser != null) poser.enabled = false;
            CharacterComponent character =
                runtimeCharacter.GetComponentInChildren<CharacterComponent>(true);
            if (character != null) character.enabled = false;
            foreach (CharacterTranslater translator in
                     runtimeCharacter.GetComponentsInChildren<CharacterTranslater>(true))
                translator.enabled = false;

            SkinnedMeshRenderer skinned = null;
            foreach (SkinnedMeshRenderer candidate in
                     runtimeCharacter.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (candidate.bones != null && candidate.bones.Length > 0)
                {
                    skinned = candidate;
                    break;
                }
            }
            if (skinned == null)
            {
                Status = "prefab has no skinned bones";
                Debug.LogError("[SMPL0901] Direct XYZ baseline could not find a skinned rig.", this);
                return;
            }

            rigBones = skinned.bones;
            renderers = runtimeCharacter.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            Dictionary<string, Transform> byName = new Dictionary<string, Transform>();
            foreach (Transform bone in rigBones)
                if (bone != null && !byName.ContainsKey(bone.name)) byName.Add(bone.name, bone);

            byName.TryGetValue("Pelvis", out pelvis);
            byName.TryGetValue("Neck", out neck);
            byName.TryGetValue("L_Hip", out leftHip);
            byName.TryGetValue("R_Hip", out rightHip);
            byName.TryGetValue("L_Ankle", out leftAnkle);
            byName.TryGetValue("R_Ankle", out rightAnkle);
            if (pelvis == null || neck == null || leftHip == null || rightHip == null)
            {
                Status = "required SUP bones are missing";
                Debug.LogError("[SMPL0901] Direct XYZ baseline requires Pelvis/Neck/L_Hip/R_Hip.", this);
                return;
            }

            runtimeCharacter.transform.position += baselineRoot.position - pelvis.position;

            bindLocalRotations = new Quaternion[rigBones.Length];
            bindLocalPositions = new Vector3[rigBones.Length];
            for (int index = 0; index < rigBones.Length; index++)
            {
                if (rigBones[index] == null) continue;
                bindLocalRotations[index] = rigBones[index].localRotation;
                bindLocalPositions[index] = rigBones[index].localPosition;
            }

            Vector3 bindRight = baselineRoot.InverseTransformDirection(
                rightHip.position - leftHip.position);
            Vector3 bindUp = baselineRoot.InverseTransformDirection(neck.position - pelvis.position);
            bindBodyBasis = BuildBasis(bindRight, bindUp);

            Vector3 ankleMid = leftAnkle != null && rightAnkle != null
                ? (leftAnkle.position + rightAnkle.position) * 0.5f
                : pelvis.position - (neck.position - pelvis.position);
            bindBodySpan = Vector3.Distance(neck.position, ankleMid);

            drivers.Clear();
            foreach (DriverSpec spec in DriverSpecs)
            {
                if (!byName.TryGetValue(spec.boneName, out Transform bone) ||
                    !byName.TryGetValue(spec.childName, out Transform child)) continue;
                Vector3 direction = baselineRoot.InverseTransformDirection(child.position - bone.position);
                if (direction.sqrMagnitude < 1e-8f) continue;
                drivers.Add(new DirectionDriver
                {
                    bone = bone,
                    sourcePoint = spec.sourcePoint,
                    targetPoint = spec.targetPoint,
                    bindDirectionInRoot = direction.normalized,
                    bindRotationInRoot = Quaternion.Inverse(baselineRoot.rotation) * bone.rotation,
                });
            }

            Status = $"ready: {drivers.Count}/{DriverSpecs.Length} direct bone directions";
            SetVisible(renderBaseline);
            ShowBindPose();
            Debug.Log($"[SMPL0901] Direct XYZ baseline {Status}; no SMV2 pose is used.", this);
        }

        private void ApplyDirectPose(Vector3[] points, bool[] valid)
        {
            if (points.Length < 17 || valid.Length < 17 || !valid[11] || !valid[12]) return;

            ResetRigToBindPose();
            baselineRoot.localPosition = baselineOffset;

            if (TryGetPoint(points, valid, VirtualPelvis, out Vector3 targetPelvis) &&
                TryGetPoint(points, valid, VirtualNeck, out Vector3 targetNeck))
            {
                Vector3 targetRight = points[12] - points[11];
                Vector3 targetUp = targetNeck - targetPelvis;
                Quaternion targetBasis = BuildBasis(targetRight, targetUp);
                baselineRoot.localRotation = targetBasis * Quaternion.Inverse(bindBodyBasis);

                if (autoScaleToRaw &&
                    TryGetPoint(points, valid, VirtualAnkleMid, out Vector3 targetAnkle))
                {
                    float targetSpan = Vector3.Distance(targetNeck, targetAnkle);
                    float scale = bindBodySpan > 1e-5f ? targetSpan / bindBodySpan : 1f;
                    baselineRoot.localScale = Vector3.one * Mathf.Clamp(scale, minimumScale, maximumScale);
                }
                else baselineRoot.localScale = Vector3.one;
            }

            foreach (DirectionDriver driver in drivers)
            {
                if (!TryGetPoint(points, valid, driver.sourcePoint, out Vector3 source) ||
                    !TryGetPoint(points, valid, driver.targetPoint, out Vector3 target)) continue;
                Vector3 targetLocalDirection = target - source;
                if (targetLocalDirection.sqrMagnitude < 1e-8f) continue;

                Vector3 targetWorldDirection = transform.TransformDirection(targetLocalDirection.normalized);
                Vector3 bindWorldDirection = baselineRoot.TransformDirection(driver.bindDirectionInRoot);
                Quaternion delta = Quaternion.FromToRotation(bindWorldDirection, targetWorldDirection);
                Quaternion bindWorldRotation = baselineRoot.rotation * driver.bindRotationInRoot;
                driver.bone.rotation = delta * bindWorldRotation;
            }
        }

        private void ResetRigToBindPose()
        {
            if (rigBones == null) return;
            for (int index = 0; index < rigBones.Length; index++)
            {
                if (rigBones[index] == null) continue;
                rigBones[index].localPosition = bindLocalPositions[index];
                rigBones[index].localRotation = bindLocalRotations[index];
            }
        }

        private static bool TryGetPoint(
            Vector3[] points, bool[] valid, int index, out Vector3 point)
        {
            if (index >= 0 && index < 59)
            {
                point = index < points.Length ? points[index] : Vector3.zero;
                return index < valid.Length && valid[index];
            }
            if (index == VirtualPelvis)
            {
                point = (points[11] + points[12]) * 0.5f;
                return valid[11] && valid[12];
            }
            if (index == VirtualNeck)
            {
                point = (points[5] + points[6]) * 0.5f;
                return valid[5] && valid[6];
            }
            if (index == VirtualAnkleMid)
            {
                point = (points[15] + points[16]) * 0.5f;
                return valid[15] && valid[16];
            }
            point = Vector3.zero;
            return false;
        }

        private static Quaternion BuildBasis(Vector3 right, Vector3 up)
        {
            if (right.sqrMagnitude < 1e-8f || up.sqrMagnitude < 1e-8f)
                return Quaternion.identity;
            right.Normalize();
            up = Vector3.ProjectOnPlane(up, right).normalized;
            Vector3 forward = Vector3.Cross(right, up).normalized;
            if (forward.sqrMagnitude < 1e-8f) return Quaternion.identity;
            up = Vector3.Cross(forward, right).normalized;
            return Quaternion.LookRotation(forward, up);
        }

        private readonly struct DriverSpec
        {
            public readonly string boneName;
            public readonly string childName;
            public readonly int sourcePoint;
            public readonly int targetPoint;

            public DriverSpec(string bone, string child, int source, int target)
            {
                boneName = bone;
                childName = child;
                sourcePoint = source;
                targetPoint = target;
            }
        }

        private sealed class DirectionDriver
        {
            public Transform bone;
            public int sourcePoint;
            public int targetPoint;
            public Vector3 bindDirectionInRoot;
            public Quaternion bindRotationInRoot;
        }
    }
}
