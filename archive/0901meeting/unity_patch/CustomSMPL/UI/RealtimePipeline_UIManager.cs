using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;

namespace CustomSMPL.UI
{
    public class RealtimePipeline_UIManager : MonoBehaviour
    {
        [Header("References")]
        public RealtimePipelinePlayer player;

        [Header("Settings")]
        public KeyCode toggleKey = KeyCode.H;
        public bool showOnStart = true;

        private RealtimePipeline_UIBuilder uiBuilder;
        private bool isPanelVisible = true;

        void Awake()
        {
            if (player == null)
            {
                player = FindObjectOfType<RealtimePipelinePlayer>();
                if (player == null)
                {
                    Debug.LogError("[RealtimePipeline_UI] Cannot find RealtimePipelinePlayer in scene!");
                    return;
                }
            }

            EnsureEventSystem();

            uiBuilder = gameObject.AddComponent<RealtimePipeline_UIBuilder>();
            uiBuilder.Build();

            // Init values
            uiBuilder.PortInput.text = player.listenPort.ToString();
            uiBuilder.RenderSMPLToggle.isOn = player.renderSMPL;
            uiBuilder.RenderJointsToggle.isOn = player.renderJoints;
            uiBuilder.FreezeLowerBodyToggle.isOn = player.freezeLowerBody;
            uiBuilder.OriginalVideoToggle.isOn = player.showOriginalVideo;

            // Bind events
            uiBuilder.ConnectButton.onClick.AddListener(OnConnectClicked);
            uiBuilder.RenderSMPLToggle.onValueChanged.AddListener(OnRenderSMPLToggled);
            uiBuilder.RenderJointsToggle.onValueChanged.AddListener(OnRenderJointsToggled);
            uiBuilder.FreezeLowerBodyToggle.onValueChanged.AddListener(OnFreezeLowerBodyToggled);
            uiBuilder.OriginalVideoToggle.onValueChanged.AddListener(OnOriginalVideoToggled);
            uiBuilder.VideoSizeSlider.onValueChanged.AddListener(OnVideoSizeSliderChanged);
            uiBuilder.FullscreenToggle.onValueChanged.AddListener(OnFullscreenToggled);
            
            uiBuilder.PlaybackModeToggle.onValueChanged.AddListener(OnPlaybackModeToggled);
            uiBuilder.ScrubSlider.onValueChanged.AddListener(OnScrubSliderChanged);
            uiBuilder.PlayPauseButton.onClick.AddListener(OnPlayPauseClicked);
            uiBuilder.ClearCacheButton.onClick.AddListener(OnClearCacheClicked);
            uiBuilder.ExportJsonButton.onClick.AddListener(OnExportJsonClicked);

            isPanelVisible = showOnStart;
            uiBuilder.PanelRoot.SetActive(isPanelVisible);
        }

        void Update()
        {
            if (Input.GetKeyDown(toggleKey))
            {
                isPanelVisible = !isPanelVisible;
                uiBuilder.PanelRoot.SetActive(isPanelVisible);
            }

            if (player == null || uiBuilder == null) return;

            UpdateUIState();
        }

        void OnConnectClicked()
        {
            if (int.TryParse(uiBuilder.PortInput.text, out int newPort))
            {
                player.Reconnect(newPort);
            }
            else
            {
                uiBuilder.StatusLabel.text = "Invalid port number!";
            }
        }

        void OnRenderSMPLToggled(bool value)
        {
            if (player != null) player.SetRenderSMPL(value);
        }

        void OnRenderJointsToggled(bool value)
        {
            if (player != null) player.SetRenderJoints(value);
        }

        void OnFreezeLowerBodyToggled(bool value)
        {
            if (player != null) player.SetFreezeLowerBody(value);
        }

        void OnOriginalVideoToggled(bool value)
        {
            Debug.Log($"[RealtimePipeline_UI] OriginalVideoToggled: {value}");
            if (player != null) player.showOriginalVideo = value;
            uiBuilder.VideoPanelRoot.SetActive(value);
        }

        void OnVideoSizeSliderChanged(float value)
        {
            if (!uiBuilder.FullscreenToggle.isOn)
            {
                RectTransform rt = uiBuilder.VideoPanelRoot.GetComponent<RectTransform>();
                rt.sizeDelta = new Vector2(480, 270) * value;
            }
        }

        void OnFullscreenToggled(bool isFullscreen)
        {
            RectTransform rt = uiBuilder.VideoPanelRoot.GetComponent<RectTransform>();
            if (isFullscreen)
            {
                // Fullscreen Mode
                rt.anchorMin = new Vector2(0, 0);
                rt.anchorMax = new Vector2(1, 1);
                rt.pivot = new Vector2(0.5f, 0.5f);
                rt.anchoredPosition = new Vector2(0, 0);
                rt.sizeDelta = new Vector2(0, 0);
                
                // Add or enable AspectRatioFitter
                UnityEngine.UI.AspectRatioFitter fitter = uiBuilder.VideoPanelRoot.GetComponent<UnityEngine.UI.AspectRatioFitter>();
                if (fitter == null) fitter = uiBuilder.VideoPanelRoot.AddComponent<UnityEngine.UI.AspectRatioFitter>();
                fitter.aspectRatio = 16f / 9f;
                fitter.aspectMode = UnityEngine.UI.AspectRatioFitter.AspectMode.FitInParent;
                fitter.enabled = true;
            }
            else
            {
                // Normal Mode
                UnityEngine.UI.AspectRatioFitter fitter = uiBuilder.VideoPanelRoot.GetComponent<UnityEngine.UI.AspectRatioFitter>();
                if (fitter != null) fitter.enabled = false;

                rt.anchorMin = new Vector2(1, 1);
                rt.anchorMax = new Vector2(1, 1);
                rt.pivot = new Vector2(1, 1);
                rt.anchoredPosition = new Vector2(-16, -16);
                rt.sizeDelta = new Vector2(480, 270) * uiBuilder.VideoSizeSlider.value;
            }
        }

        void OnPlaybackModeToggled(bool value)
        {
            if (player != null) player.isPlaybackMode = value;
        }

        void OnScrubSliderChanged(float value)
        {
            // Only update player if we are dragging (not playing automatically)
            if (player != null && !player.isPlaying)
            {
                player.SetPlaybackIndex((int)value);
            }
        }

        void OnPlayPauseClicked()
        {
            if (player != null) player.TogglePlayPause();
        }

        void OnClearCacheClicked()
        {
            if (player != null) player.ClearCache();
        }

        void OnExportJsonClicked()
        {
            if (player != null) player.ExportToJson();
        }

        void UpdateUIState()
        {
            // Status Label
            if (player.IsConnected)
            {
                uiBuilder.StatusLabel.text = "Status: Connected & Listening";
                uiBuilder.StatusLabel.color = Color.green;
            }
            else
            {
                uiBuilder.StatusLabel.text = "Status: Disconnected / Error";
                uiBuilder.StatusLabel.color = Color.red;
            }

            // Info Label
            uiBuilder.InfoLabel.text = $"Port: {player.listenPort}\nLatest Frame: {player.LatestFrameIdx}\nReceiving FPS: {player.FPS:F1}";

            // Playback State
            int cacheCount = player.GetCacheCount();
            uiBuilder.CacheInfoLabel.text = $"Cached Frames: {cacheCount}";

            bool isPlayback = player.isPlaybackMode;
            uiBuilder.ScrubSlider.gameObject.SetActive(isPlayback);
            uiBuilder.PlayPauseButton.gameObject.SetActive(isPlayback);

            if (isPlayback && cacheCount > 0)
            {
                uiBuilder.ScrubSlider.maxValue = cacheCount - 1;
                
                // Always sync slider without triggering onValueChanged event if not currently dragging
                uiBuilder.ScrubSlider.SetValueWithoutNotify(player.playbackIndex);

                uiBuilder.PlayPauseText.text = player.isPlaying ? "Pause" : "Play";
            }
            else
            {
                uiBuilder.ScrubSlider.maxValue = 0;
                uiBuilder.ScrubSlider.SetValueWithoutNotify(0);
                uiBuilder.PlayPauseText.text = "Play";
            }

            // Sync Video Texture
            if (player.showOriginalVideo && player.videoPlayer != null)
            {
                if (player.videoPlayer.targetTexture != null)
                {
                    if (uiBuilder.VideoRawImage.texture != player.videoPlayer.targetTexture)
                    {
                        Debug.Log("[RealtimePipeline_UI] Assigning targetTexture to VideoRawImage!");
                        uiBuilder.VideoRawImage.texture = player.videoPlayer.targetTexture;
                        uiBuilder.VideoRawImage.color = Color.white;
                    }
                }
                else
                {
                    // Uncommenting this could spam, but useful if it never assigns
                    // Debug.LogWarning("[RealtimePipeline_UI] targetTexture is null!");
                }
            }
        }

        void EnsureEventSystem()
        {
            if (FindObjectOfType<EventSystem>() == null)
            {
                GameObject esObj = new GameObject("EventSystem");
                esObj.AddComponent<EventSystem>();
                esObj.AddComponent<StandaloneInputModule>();
            }
        }
    }
}
