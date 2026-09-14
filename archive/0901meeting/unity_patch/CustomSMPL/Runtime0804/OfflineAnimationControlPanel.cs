using System.Collections.Generic;
using UnityEngine;

namespace CustomSMPL.Runtime0804
{
    public class OfflineAnimationControlPanel : MonoBehaviour
    {
        public ProtocolV2PlaybackPlayer playback;
        public RealtimePipelinePlayer player;
        public bool visible = true;
        public KeyCode toggleKey = KeyCode.H;
        public Rect windowRect = new Rect(15f, 15f, 430f, 520f);

        private Vector2 scroll;

        void Awake()
        {
            if (playback == null) playback = GetComponent<ProtocolV2PlaybackPlayer>();
            if (player == null) player = GetComponent<RealtimePipelinePlayer>();
        }

        void Update()
        {
            if (Input.GetKeyDown(toggleKey)) visible = !visible;
        }

        void OnGUI()
        {
            if (!visible || playback == null || player == null) return;
            windowRect = GUILayout.Window(GetInstanceID(), windowRect, DrawWindow, "0804 Offline SMPL-H Player");
        }

        private void DrawWindow(int id)
        {
            GUILayout.Label("Choose this week's inferred animation");
            IReadOnlyList<string> names = playback.GetAnimationNames();
            scroll = GUILayout.BeginScrollView(scroll, GUILayout.Height(185));
            for (int index = 0; index < names.Count; index++)
            {
                bool selected = index == playback.SelectedAnimationIndex;
                GUI.enabled = !selected;
                if (GUILayout.Button((selected ? "▶ " : "") + names[index])) playback.SelectAnimation(index);
                GUI.enabled = true;
            }
            GUILayout.EndScrollView();

            GUILayout.Space(6);
            player.renderSMPL = GUILayout.Toggle(player.renderSMPL, "Show SMPL body (Learnable output)");
            playback.showSourceSkeleton = GUILayout.Toggle(playback.showSourceSkeleton, "Show source joint skeleton");
            playback.applyRootMotion = GUILayout.Toggle(playback.applyRootMotion, "Apply root displacement");
            GUI.enabled = playback.CurrentHasHands && !playback.EffectiveUsesSmplHandPose;
            playback.driveHands = GUILayout.Toggle(playback.driveHands, "Drive SMPL-H fingers from raw Hand21 joints");
            GUI.enabled = true;
            playback.loop = GUILayout.Toggle(playback.loop, "Loop");

            GUILayout.BeginHorizontal();
            if (GUILayout.Button(playback.IsPlaying ? "Pause" : "Play")) playback.TogglePlayPause();
            if (GUILayout.Button("Restart")) playback.Restart();
            GUILayout.EndHorizontal();

            int maxFrame = Mathf.Max(0, playback.FrameCount - 1);
            int selectedFrame = Mathf.RoundToInt(GUILayout.HorizontalSlider(playback.CurrentIndex, 0, maxFrame));
            if (selectedFrame != playback.CurrentIndex && !playback.IsPlaying) playback.SetFrame(selectedFrame);

            string sourceKind = playback.CurrentHasGroundTruth ? "GT/source joints" : "Input joints (NO GT)";
            GUILayout.Label($"Animation: {playback.CurrentDisplayName}");
            GUILayout.Label($"Frame: {playback.CurrentIndex + 1}/{playback.FrameCount} | {playback.PlaybackFps:F0} FPS");
            GUILayout.Label("Body source: Learnable pose (pelvis/body/wrists only)");
            GUILayout.Label(playback.EffectiveUsesSmplHandPose
                ? "Finger source: original SMPL-H axis-angle (includes twist)"
                : "Finger source: raw Hand21 joint directions only");
            GUILayout.Label($"Skeleton: {sourceKind}");
            GUILayout.Label(playback.CurrentHasHands ? "Hands: raw 21 + 21 joints available" : "Hands: unavailable in this dataset");
            GUILayout.Label("Press H to hide/show this panel");
            GUI.DragWindow();
        }
    }
}
