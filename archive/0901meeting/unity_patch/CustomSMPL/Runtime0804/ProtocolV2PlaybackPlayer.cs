using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace CustomSMPL.Runtime0804
{
    /// <summary>Offline, selectable animation player. No UDP is required.</summary>
    public class ProtocolV2PlaybackPlayer : MonoBehaviour
    {
        public RealtimePipelinePlayer targetPlayer;
        [Tooltip("Absolute path to playback_catalog.json")]
        public string catalogJsonPath =
            @"F:\School\Projects\main\0804meeting\unity_playback\playback_catalog.json";
        public bool playOnStart = false;
        public bool loop = true;
        public bool applyRootMotion = true;
        public bool driveHands = true;
        public bool showSourceSkeleton = true;
        [Tooltip("Comparison-only: force the previous raw-Hand21 method even when the clip has SMPL hand pose.")]
        public bool forceRawHand21 = false;
        [Tooltip("Comparison-only: apply body.referencePose before joint swing corrections.")]
        public bool useReferenceSmplPose = false;
        public JointPositionSmplTwistDriver jointTwistDriver;

        public int CurrentIndex { get; private set; }
        public int SelectedAnimationIndex { get; private set; }
        public int FrameCount => playback != null && playback.frames != null ? playback.frames.Length : 0;
        public bool IsPlaying { get; private set; }
        public string CurrentDisplayName => currentEntry != null ? currentEntry.displayName : "No animation";
        public bool CurrentHasHands => currentEntry != null && currentEntry.hasHands;
        public bool CurrentUsesSmplHandPose => currentEntry != null && currentEntry.useSmplHandPose;
        public bool EffectiveUsesSmplHandPose => CurrentUsesSmplHandPose && !forceRawHand21;
        public bool CurrentHasGroundTruth => currentEntry != null && currentEntry.gtAvailable;
        public float PlaybackFps => currentEntry != null ? Mathf.Max(1f, currentEntry.fps) : 15f;

        private OfflineAnimationCatalog catalog;
        private OfflineAnimationEntry currentEntry;
        private ProtocolV2PlaybackFile playback;
        private float accumulator;
        private Vector3 basePosition;
        private Quaternion baseRotation;
        private bool baseTransformCaptured;

        void Awake()
        {
            if (targetPlayer == null) targetPlayer = GetComponent<RealtimePipelinePlayer>();
            CaptureBaseTransform();
        }

        private void CaptureBaseTransform()
        {
            if (baseTransformCaptured) return;
            basePosition = transform.position;
            baseRotation = transform.rotation;
            baseTransformCaptured = true;
        }

        void Start()
        {
            if (LoadCatalog(catalogJsonPath))
            {
                SelectAnimation(Mathf.Clamp(catalog.defaultIndex, 0, catalog.animations.Length - 1));
                IsPlaying = playOnStart && FrameCount > 0;
            }
        }

        void Update()
        {
            if (!IsPlaying || FrameCount == 0 || targetPlayer == null || !targetPlayer.IsRuntimeReady) return;
            accumulator += Time.deltaTime;
            float frameDuration = 1f / PlaybackFps;
            while (accumulator >= frameDuration)
            {
                accumulator -= frameDuration;
                ApplyCurrentFrame();
                CurrentIndex++;
                if (CurrentIndex >= FrameCount)
                {
                    CurrentIndex = loop ? 0 : FrameCount - 1;
                    if (!loop) IsPlaying = false;
                    break;
                }
            }
        }

        public bool LoadCatalog(string path)
        {
            try
            {
                CaptureBaseTransform();
                if (!File.Exists(path))
                {
                    Debug.LogError($"[OfflinePlayback] Catalog not found: {path}");
                    return false;
                }
                OfflineAnimationCatalog loaded = JsonUtility.FromJson<OfflineAnimationCatalog>(File.ReadAllText(path));
                if (loaded == null || loaded.animations == null || loaded.animations.Length == 0)
                {
                    Debug.LogError("[OfflinePlayback] Catalog is empty or invalid.");
                    return false;
                }
                catalog = loaded;
                catalogJsonPath = path;
                return true;
            }
            catch (Exception exception)
            {
                Debug.LogError($"[OfflinePlayback] Catalog load failed: {exception.Message}");
                return false;
            }
        }

        public IReadOnlyList<string> GetAnimationNames()
        {
            List<string> names = new List<string>();
            if (catalog != null && catalog.animations != null)
            {
                foreach (OfflineAnimationEntry entry in catalog.animations) names.Add(entry.displayName);
            }
            return names;
        }

        public bool SelectAnimation(int index)
        {
            if (catalog == null || catalog.animations == null || index < 0 || index >= catalog.animations.Length)
                return false;
            OfflineAnimationEntry entry = catalog.animations[index];
            if (!LoadPlayback(entry.path)) return false;
            SelectedAnimationIndex = index;
            currentEntry = entry;
            IsPlaying = false;
            ApplyDatasetCalibration(entry);
            if (targetPlayer != null && targetPlayer.rawHandRetargeter != null)
                targetPlayer.rawHandRetargeter.ResetToBindPose();
            SetFrame(0);
            Debug.Log($"[OfflinePlayback] Selected {entry.displayName}: {FrameCount} frames, hands={entry.hasHands}, GT={entry.gtAvailable}");
            return true;
        }

        public bool SelectAnimationById(string animationId)
        {
            if (catalog == null || catalog.animations == null) return false;
            for (int index = 0; index < catalog.animations.Length; index++)
                if (catalog.animations[index].id == animationId) return SelectAnimation(index);
            Debug.LogError($"[OfflinePlayback] Animation id not found: {animationId}");
            return false;
        }

        public bool LoadPlayback(string path)
        {
            try
            {
                if (!File.Exists(path))
                {
                    Debug.LogError($"[OfflinePlayback] File not found: {path}");
                    return false;
                }
                ProtocolV2PlaybackFile loaded = JsonUtility.FromJson<ProtocolV2PlaybackFile>(File.ReadAllText(path));
                if (loaded == null || loaded.protocolVersion != 2 || loaded.frames == null || loaded.frames.Length == 0)
                {
                    Debug.LogError($"[OfflinePlayback] Invalid playback file: {path}");
                    return false;
                }
                playback = loaded;
                CurrentIndex = 0;
                accumulator = 0f;
                return true;
            }
            catch (Exception exception)
            {
                Debug.LogError($"[OfflinePlayback] Load failed: {exception.Message}");
                return false;
            }
        }

        private void ApplyDatasetCalibration(OfflineAnimationEntry entry)
        {
            Vector3 euler = entry.rootEuler != null && entry.rootEuler.Length >= 3
                ? new Vector3(entry.rootEuler[0], entry.rootEuler[1], entry.rootEuler[2])
                : Vector3.zero;
            transform.position = basePosition;
            // Keep the SMPL prefab in its proven CharacterPoser coordinate
            // convention. Dataset calibration belongs to observations/root,
            // otherwise the same euler rotates the character a second time.
            transform.rotation = baseRotation;
            if (targetPlayer != null)
            {
                targetPlayer.sourceSkeletonEuler = euler;
                // AMASS supplies observable SMPL-H hand axis-angle rotations,
                // including axial twist. Other datasets keep the Learnable
                // body separated from direction-only raw Hand21 retargeting.
                targetPlayer.bodyPoseOnly = !EffectiveUsesSmplHandPose;
            }
            if (targetPlayer != null && targetPlayer.rootMotionDriver != null)
            {
                targetPlayer.rootMotionDriver.calibrationEuler = euler;
                targetPlayer.rootMotionDriver.ResetAnchor(basePosition);
            }
        }

        public void Play() => IsPlaying = FrameCount > 0;
        public void Pause() => IsPlaying = false;
        public void TogglePlayPause() { if (IsPlaying) Pause(); else Play(); }
        public void Restart() { SetFrame(0); Play(); }

        public void SetFrame(int index)
        {
            if (FrameCount == 0 || targetPlayer == null) return;
            CurrentIndex = Mathf.Clamp(index, 0, FrameCount - 1);
            ApplyCurrentFrame();
        }

        private void ApplyCurrentFrame()
        {
            if (CurrentIndex < 0 || CurrentIndex >= FrameCount || targetPlayer == null) return;
            ProtocolV2Frame frame = playback.frames[CurrentIndex];
            float[] fittedPose = frame.body.pose;
            bool referenceAvailable = useReferenceSmplPose && frame.body.referencePose != null &&
                                      frame.body.referencePose.Length == 156;
            if (referenceAvailable) frame.body.pose = frame.body.referencePose;
            try
            {
                targetPlayer.ApplyProtocolV2Frame(
                    frame, applyRootMotion,
                    driveHands && CurrentHasHands && !EffectiveUsesSmplHandPose,
                    showSourceSkeleton
                );
                if (referenceAvailable && jointTwistDriver != null)
                    jointTwistDriver.Apply(frame, targetPlayer.sourceSkeletonEuler);
            }
            finally
            {
                frame.body.pose = fittedPose;
            }
        }
    }
}
