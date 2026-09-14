using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CustomSMPL.UI
{
    /// <summary>
    /// Playback control panel: displays playback status, provides pause/stop/speed controls.
    /// </summary>
    public class PlaybackControlPanel : MonoBehaviour
    {
        private RuntimeUIBuilder uiBuilder;
        private CustomAnimationPlayer player;

        public void Initialize(RuntimeUIBuilder builder, CustomAnimationPlayer animPlayer)
        {
            uiBuilder = builder;
            player = animPlayer;

            // Bind button events
            uiBuilder.PauseButton.onClick.AddListener(OnPauseClicked);
            uiBuilder.StopButton.onClick.AddListener(OnStopClicked);
            uiBuilder.SpeedSlider.onValueChanged.AddListener(OnSpeedChanged);
            uiBuilder.ProgressSlider.onValueChanged.AddListener(OnProgressChanged);

            // Initial state
            UpdatePlaybackUI(0f);
        }

        private float fpsDeltaTime = 0.0f;

        void Update()
        {
            if (player == null) return;

            fpsDeltaTime += (Time.unscaledDeltaTime - fpsDeltaTime) * 0.1f;
            float renderFPS = fpsDeltaTime > 0.0f ? 1.0f / fpsDeltaTime : 0.0f;

            UpdatePlaybackUI(renderFPS);
        }

        void UpdatePlaybackUI(float renderFPS)
        {
            bool playing = player.IsAnimPlaying;
            bool paused = player.IsPaused;

            // Pause button text
            if (uiBuilder.PauseButtonText != null)
            {
                if (!playing)
                    uiBuilder.PauseButtonText.text = "Pause";
                else if (paused)
                    uiBuilder.PauseButtonText.text = "Resume";
                else
                    uiBuilder.PauseButtonText.text = "Pause";
            }

            // Button interactability
            uiBuilder.PauseButton.interactable = playing;
            uiBuilder.StopButton.interactable = playing;

            // Progress bar
            if (player.TotalFrames > 0)
            {
                float progress = (float)player.CurrentFrame / player.TotalFrames;
                uiBuilder.ProgressSlider.onValueChanged.RemoveListener(OnProgressChanged);
                uiBuilder.ProgressSlider.value = progress;
                uiBuilder.ProgressSlider.onValueChanged.AddListener(OnProgressChanged);
                uiBuilder.ProgressLabel.text = $"{player.CurrentFrame} / {player.TotalFrames}";
            }
            else
            {
                uiBuilder.ProgressSlider.onValueChanged.RemoveListener(OnProgressChanged);
                uiBuilder.ProgressSlider.value = 0;
                uiBuilder.ProgressSlider.onValueChanged.AddListener(OnProgressChanged);
                uiBuilder.ProgressLabel.text = "0 / 0";
            }

            // Speed label
            uiBuilder.SpeedLabel.text = $"{uiBuilder.SpeedSlider.value:F1}x";

            // Animation info
            if (playing)
            {
                string format = player.IsSMPLX ? "SMPL-X" : "SMPL-H";
                string status = paused ? " (Paused)" : "";
                uiBuilder.InfoLabel.text = $"FPS: {player.CurrentTargetFPS} (Render: {renderFPS:F0})  |  Joints: {player.NumJoints}  |  {format}{status}";
            }
            else
            {
                uiBuilder.InfoLabel.text = $"No animation loaded  |  Render: {renderFPS:F0} FPS";
            }
        }

        void OnPauseClicked()
        {
            UnityEngine.Debug.Log("[PlaybackControl] Pause clicked");
            if (player != null && player.IsAnimPlaying)
            {
                player.TogglePause();
            }
        }

        void OnStopClicked()
        {
            UnityEngine.Debug.Log("[PlaybackControl] Stop clicked");
            if (player != null)
            {
                player.StopAndCleanup();
                uiBuilder.StatusLabel.text = "Stopped. Select a file to play.";
            }
        }

        void OnSpeedChanged(float newSpeed)
        {
            if (player != null)
            {
                player.SetPlaybackSpeed(newSpeed);
            }
        }

        void OnProgressChanged(float value)
        {
            if (player != null && player.IsAnimPlaying)
            {
                player.ScrubToProgress(value);
            }
        }
    }
}
