using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using System.Collections.Generic;

namespace CustomSMPL.H36M.UI
{
    public class H36M_UIManager : MonoBehaviour
    {
        [Header("References")]
        public H36MAnimationPlayer player;

        [Header("Settings")]
        public KeyCode toggleKey = KeyCode.H;
        public bool showOnStart = true;

        // Internal UI Builder
        private H36M_UIBuilder uiBuilder;
        private bool isPanelVisible = true;

        // Action and Subaction bindings
        private Dictionary<string, Button> actionButtons = new Dictionary<string, Button>();
        private string activeActionKey = "";
        private string activeSubactionKey = "1";

        void Awake()
        {
            if (player == null)
            {
                player = GetComponentInParent<H36MAnimationPlayer>();
                if (player == null)
                {
                    player = FindObjectOfType<H36MAnimationPlayer>();
                }
                if (player == null)
                {
                    UnityEngine.Debug.LogError("[H36M_UI] Cannot find H36MAnimationPlayer in scene! Please assign it in Inspector.");
                    return;
                }
            }

            // Ensure EventSystem
            EnsureEventSystem();

            // Spawn UI Builder
            uiBuilder = gameObject.AddComponent<H36M_UIBuilder>();
            uiBuilder.Build();

            // Set initial path input
            uiBuilder.DatasetPathInput.text = player.jsonFilePath;

            // Bind Load Button
            uiBuilder.LoadDatasetButton.onClick.AddListener(OnLoadClicked);

            // Bind Subaction Buttons
            uiBuilder.Subaction1Button.onClick.AddListener(() => OnSubactionClicked("1"));
            uiBuilder.Subaction2Button.onClick.AddListener(() => OnSubactionClicked("2"));

            // Bind Playback buttons
            uiBuilder.PauseButton.onClick.AddListener(OnPauseClicked);
            uiBuilder.StopButton.onClick.AddListener(OnStopClicked);
            uiBuilder.SpeedSlider.onValueChanged.AddListener(OnSpeedChanged);
            uiBuilder.ProgressSlider.onValueChanged.AddListener(OnProgressChanged);

            // Generate Action buttons in scroll view
            PopulateActionList();

            // Initial UI state
            isPanelVisible = showOnStart;
            uiBuilder.PanelRoot.SetActive(isPanelVisible);
            UpdateSubactionHighlights();
        }

        private float fpsDeltaTime = 0.0f;

        void Update()
        {
            if (Input.GetKeyDown(toggleKey))
            {
                isPanelVisible = !isPanelVisible;
                uiBuilder.PanelRoot.SetActive(isPanelVisible);
            }

            if (player == null || uiBuilder == null) return;

            fpsDeltaTime += (Time.unscaledDeltaTime - fpsDeltaTime) * 0.1f;
            float renderFPS = fpsDeltaTime > 0.0f ? 1.0f / fpsDeltaTime : 0.0f;

            UpdateUIState(renderFPS);
        }

        void PopulateActionList()
        {
            // Clear content just in case
            foreach (Transform child in uiBuilder.ActionListContent)
            {
                Destroy(child.gameObject);
            }
            actionButtons.Clear();

            // Create buttons for each action in ActionNames
            foreach (var pair in H36MAnimationPlayer.ActionNames)
            {
                string actKey = pair.Key;
                string actName = pair.Value;

                Button btn = uiBuilder.CreateActionButton(uiBuilder.ActionListContent, actName);
                btn.onClick.AddListener(() => OnActionClicked(actKey, btn));
                actionButtons.Add(actKey, btn);
            }
        }

        void OnLoadClicked()
        {
            string path = uiBuilder.DatasetPathInput.text.Trim().Trim('"');
            if (System.IO.File.Exists(path))
            {
                player.StartLoadDataset(path);
            }
            else
            {
                uiBuilder.StatusLabel.text = "Dataset file not found!";
                UnityEngine.Debug.LogError($"[H36M_UI] File does not exist: {path}");
            }
        }

        void OnActionClicked(string actKey, Button clickedButton)
        {
            if (!player.IsLoaded) return;

            activeActionKey = actKey;
            
            // Highlight action button
            foreach (var pair in actionButtons)
            {
                uiBuilder.SetActionButtonHighlight(pair.Value, pair.Key == actKey);
            }

            // Play
            bool success = player.PlayAction(actKey, activeSubactionKey);
            if (success)
            {
                uiBuilder.StatusLabel.text = $"Playing: {H36MAnimationPlayer.GetActionName(actKey)} (Sub {activeSubactionKey})";
            }
        }

        void OnSubactionClicked(string subKey)
        {
            if (!player.IsLoaded) return;

            activeSubactionKey = subKey;
            UpdateSubactionHighlights();

            if (!string.IsNullOrEmpty(activeActionKey))
            {
                bool success = player.PlayAction(activeActionKey, subKey);
                if (success)
                {
                    uiBuilder.StatusLabel.text = $"Playing: {H36MAnimationPlayer.GetActionName(activeActionKey)} (Sub {subKey})";
                }
            }
        }

        void UpdateSubactionHighlights()
        {
            uiBuilder.SetSubactionButtonHighlight(uiBuilder.Subaction1Button, activeSubactionKey == "1");
            uiBuilder.SetSubactionButtonHighlight(uiBuilder.Subaction2Button, activeSubactionKey == "2");
        }

        void OnPauseClicked()
        {
            if (player != null && player.IsAnimPlaying)
            {
                player.TogglePause();
            }
        }

        void OnStopClicked()
        {
            if (player != null)
            {
                player.StopAndCleanup();
                uiBuilder.StatusLabel.text = "Stopped. Choose an action.";
            }
        }

        void OnSpeedChanged(float value)
        {
            if (player != null)
            {
                player.SetPlaybackSpeed(value);
            }
        }

        void OnProgressChanged(float value)
        {
            if (player != null && player.IsAnimPlaying)
            {
                player.ScrubToProgress(value);
            }
        }

        void UpdateUIState(float renderFPS)
        {
            // 1. Handle loading state
            if (player.IsLoading)
            {
                uiBuilder.StatusLabel.text = "Loading dataset (64MB)... Please wait";
                SetUIInteractable(false);
                uiBuilder.InfoLabel.text = "Parsing JSON dataset asynchronously...";
                return;
            }

            SetUIInteractable(player.IsLoaded);

            // 2. Playback state
            bool playing = player.IsAnimPlaying;
            bool paused = player.IsPaused;

            // Pause button text
            if (uiBuilder.PauseButtonText != null)
            {
                uiBuilder.PauseButtonText.text = paused ? "Resume" : "Pause";
            }

            uiBuilder.PauseButton.interactable = playing;
            uiBuilder.StopButton.interactable = playing;

            // 3. Highlight current active action
            string playerAct = player.CurrentActionKey;
            string playerSub = player.CurrentSubactionKey;

            if (player.IsLoaded)
            {
                if (playerAct != activeActionKey || playerSub != activeSubactionKey)
                {
                    activeActionKey = playerAct;
                    activeSubactionKey = playerSub;

                    // Sync action button highlights
                    foreach (var pair in actionButtons)
                    {
                        uiBuilder.SetActionButtonHighlight(pair.Value, pair.Key == activeActionKey);
                    }
                    UpdateSubactionHighlights();
                }
            }

            // 4. Update progress bar
            if (player.TotalFrames > 0)
            {
                float progress = (float)player.CurrentFrame / player.TotalFrames;
                
                // Event loop prevention
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

            // 5. Update speed label
            uiBuilder.SpeedLabel.text = $"{uiBuilder.SpeedSlider.value:F1}x";

            // 6. Update info label
            if (playing)
            {
                string actName = H36MAnimationPlayer.GetActionName(activeActionKey);
                string status = paused ? " (Paused)" : "";
                uiBuilder.InfoLabel.text = $"Action: {actName} | Frame rate: {player.targetFPS} FPS (Render: {renderFPS:F0}){status}";
                
                if (uiBuilder.StatusLabel.text.StartsWith("Ready") || uiBuilder.StatusLabel.text.StartsWith("Stopped"))
                {
                    uiBuilder.StatusLabel.text = $"Playing: {actName} (Sub {activeSubactionKey})";
                }
            }
            else if (player.IsLoaded)
            {
                uiBuilder.InfoLabel.text = $"Dataset loaded  |  Render: {renderFPS:F0} FPS";
            }
            else
            {
                uiBuilder.InfoLabel.text = $"Click 'Load' to load H36M dataset  |  Render: {renderFPS:F0} FPS";
            }
        }

        void SetUIInteractable(bool interactable)
        {
            uiBuilder.Subaction1Button.interactable = interactable;
            uiBuilder.Subaction2Button.interactable = interactable;
            uiBuilder.ProgressSlider.interactable = interactable;
            uiBuilder.SpeedSlider.interactable = interactable;

            foreach (var btn in actionButtons.Values)
            {
                btn.interactable = interactable;
            }
        }

        void EnsureEventSystem()
        {
            if (FindObjectOfType<EventSystem>() == null)
            {
                GameObject esObj = new GameObject("EventSystem");
                esObj.AddComponent<EventSystem>();
                esObj.AddComponent<StandaloneInputModule>();
                UnityEngine.Debug.Log("[H36M_UI] Auto-created EventSystem.");
            }
        }
    }
}
