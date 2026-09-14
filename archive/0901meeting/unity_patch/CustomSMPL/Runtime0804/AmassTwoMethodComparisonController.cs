using System.Collections;
using UnityEngine;

namespace CustomSMPL.Runtime0804
{
    /// <summary>Synchronizes the two-model AMASS hand-method comparison.</summary>
    public class AmassTwoMethodComparisonController : MonoBehaviour
    {
        public ProtocolV2PlaybackPlayer previousMethod;
        public ProtocolV2PlaybackPlayer jointSmplMethod;
        public string catalogPath =
            @"F:\School\Projects\main\0804meeting\unity_playback\playback_catalog.json";
        public string animationId = "amass_hand_motion_300";
        public float playbackFps = 15f;
        public bool playOnStart = true;
        public bool loop = true;
        public bool showBothSourceSkeletons = true;

        public int CurrentFrame { get; private set; }
        public bool IsPlaying { get; private set; }
        public bool IsReady { get; private set; }

        private float accumulator;
        private Rect windowRect = new Rect(15f, 15f, 520f, 330f);

        private IEnumerator Start()
        {
            while (previousMethod == null || jointSmplMethod == null ||
                   previousMethod.targetPlayer == null || jointSmplMethod.targetPlayer == null ||
                   !previousMethod.targetPlayer.IsRuntimeReady || !jointSmplMethod.targetPlayer.IsRuntimeReady)
                yield return null;

            if (jointSmplMethod.jointTwistDriver != null)
            {
                jointSmplMethod.jointTwistDriver.Initialize(
                    jointSmplMethod.targetPlayer.RuntimeCharacter.transform,
                    jointSmplMethod.targetPlayer.transform
                );
            }

            previousMethod.forceRawHand21 = true;
            previousMethod.useReferenceSmplPose = false;
            previousMethod.applyRootMotion = false;
            previousMethod.driveHands = true;
            previousMethod.showSourceSkeleton = showBothSourceSkeletons;

            jointSmplMethod.forceRawHand21 = false;
            jointSmplMethod.useReferenceSmplPose = true;
            jointSmplMethod.applyRootMotion = false;
            jointSmplMethod.driveHands = false;
            jointSmplMethod.showSourceSkeleton = showBothSourceSkeletons;

            bool loaded = previousMethod.LoadCatalog(catalogPath) && jointSmplMethod.LoadCatalog(catalogPath) &&
                          previousMethod.SelectAnimationById(animationId) &&
                          jointSmplMethod.SelectAnimationById(animationId);
            if (!loaded)
            {
                Debug.LogError("[AMASS Comparison] Failed to load the comparison clip.");
                yield break;
            }

            CurrentFrame = 0;
            IsReady = true;
            IsPlaying = playOnStart;
            ApplyFrame();
            Debug.Log("[AMASS Comparison] Ready: Previous vs Joint Position + SMPL Rotation.");
        }

        private void Update()
        {
            if (!IsReady || !IsPlaying || previousMethod.FrameCount <= 0) return;
            accumulator += Time.deltaTime;
            float duration = 1f / Mathf.Max(1f, playbackFps);
            while (accumulator >= duration)
            {
                accumulator -= duration;
                CurrentFrame++;
                if (CurrentFrame >= previousMethod.FrameCount)
                {
                    CurrentFrame = loop ? 0 : previousMethod.FrameCount - 1;
                    if (!loop) IsPlaying = false;
                }
                ApplyFrame();
                if (!IsPlaying) break;
            }
        }

        private void ApplyFrame()
        {
            previousMethod.showSourceSkeleton = showBothSourceSkeletons;
            jointSmplMethod.showSourceSkeleton = showBothSourceSkeletons;
            previousMethod.SetFrame(CurrentFrame);
            jointSmplMethod.SetFrame(CurrentFrame);
        }

        private void OnGUI()
        {
            windowRect = GUILayout.Window(GetInstanceID(), windowRect, DrawWindow,
                "AMASS Two-Model Method Comparison");
        }

        private void DrawWindow(int id)
        {
            GUILayout.Label("LEFT — Previous method");
            GUILayout.Label("Learnable body fitting + raw Hand21 direction retarget");
            GUILayout.Space(4f);
            GUILayout.Label("RIGHT — Joint Position + SMPL Rotation");
            GUILayout.Label("Joint segments control swing; original SMPL-H supplies axial twist");
            GUILayout.Space(8f);

            bool newSkeleton = GUILayout.Toggle(showBothSourceSkeletons, "Show original skeleton beside BOTH models");
            if (newSkeleton != showBothSourceSkeletons)
            {
                showBothSourceSkeletons = newSkeleton;
                if (IsReady) ApplyFrame();
            }

            GUILayout.BeginHorizontal();
            GUI.enabled = IsReady;
            if (GUILayout.Button(IsPlaying ? "Pause" : "Play")) IsPlaying = !IsPlaying;
            if (GUILayout.Button("Restart"))
            {
                CurrentFrame = 0;
                accumulator = 0f;
                ApplyFrame();
            }
            GUI.enabled = true;
            GUILayout.EndHorizontal();

            int frameCount = previousMethod != null ? previousMethod.FrameCount : 0;
            int selected = Mathf.RoundToInt(GUILayout.HorizontalSlider(CurrentFrame, 0, Mathf.Max(0, frameCount - 1)));
            if (IsReady && selected != CurrentFrame)
            {
                CurrentFrame = selected;
                ApplyFrame();
            }
            GUILayout.Label(IsReady ? $"Frame {CurrentFrame + 1}/{frameCount}" : "Initializing both SMPL-H models...");
            if (jointSmplMethod != null && jointSmplMethod.jointTwistDriver != null)
                GUILayout.Label($"Right driven segments: {jointSmplMethod.jointTwistDriver.DrivenSegments}, " +
                                $"direction error: {jointSmplMethod.jointTwistDriver.MaxDirectionErrorDegrees:F3}°, " +
                                $"position error: {jointSmplMethod.jointTwistDriver.MaxPositionErrorM * 1000f:F2} mm");
            GUI.DragWindow();
        }
    }
}
