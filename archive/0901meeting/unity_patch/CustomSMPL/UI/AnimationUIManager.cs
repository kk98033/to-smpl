using UnityEngine;
using UnityEngine.EventSystems;

namespace CustomSMPL.UI
{
    /// <summary>
    /// UI Manager: initializes the entire UI system, manages panel show/hide.
    /// 
    /// Setup:
    /// 1. Create an empty GameObject in scene (e.g. "AnimationUI")
    /// 2. Attach this script
    /// 3. Drag the CustomAnimationPlayer GameObject to the animationPlayer field
    /// 4. UI will auto-build at runtime
    /// </summary>
    public class AnimationUIManager : MonoBehaviour
    {
        [Header("References")]
        [Tooltip("Drag the GameObject with CustomAnimationPlayer here")]
        public CustomAnimationPlayer animationPlayer;

        [Header("Settings")]
        [Tooltip("Key to toggle UI panel visibility")]
        public KeyCode toggleKey = KeyCode.H;

        [Tooltip("Show UI on start")]
        public bool showOnStart = true;

        // Internal components
        private RuntimeUIBuilder uiBuilder;
        private FileBrowserPanel fileBrowser;
        private PlaybackControlPanel playbackControl;
        private bool isPanelVisible = true;

        void Awake()
        {
            if (animationPlayer == null)
            {
                // Try to find it
                animationPlayer = GetComponentInParent<CustomAnimationPlayer>();
                if (animationPlayer == null)
                {
                    animationPlayer = FindObjectOfType<CustomAnimationPlayer>();
                }

                if (animationPlayer == null)
                {
                    UnityEngine.Debug.LogError("[AnimationUI] Cannot find CustomAnimationPlayer! Please assign in Inspector.");
                    return;
                }
            }

            UnityEngine.Debug.Log("[AnimationUI] Initializing UI...");

            // Ensure EventSystem exists (required for UI interaction)
            EnsureEventSystem();

            // Build UI
            uiBuilder = gameObject.AddComponent<RuntimeUIBuilder>();
            uiBuilder.Build();

            // Initialize sub-panels
            fileBrowser = gameObject.AddComponent<FileBrowserPanel>();
            fileBrowser.Initialize(uiBuilder, animationPlayer);

            playbackControl = gameObject.AddComponent<PlaybackControlPanel>();
            playbackControl.Initialize(uiBuilder, animationPlayer);

            // Initial visibility
            isPanelVisible = showOnStart;
            SetPanelVisible(isPanelVisible);

            UnityEngine.Debug.Log("[AnimationUI] UI initialized. Press H to toggle panel.");
        }

        void Update()
        {
            if (Input.GetKeyDown(toggleKey))
            {
                TogglePanel();
            }
        }

        /// <summary>
        /// Toggle panel visibility.
        /// </summary>
        public void TogglePanel()
        {
            isPanelVisible = !isPanelVisible;
            SetPanelVisible(isPanelVisible);
        }

        /// <summary>
        /// Set panel visibility.
        /// </summary>
        public void SetPanelVisible(bool visible)
        {
            isPanelVisible = visible;
            if (uiBuilder != null && uiBuilder.PanelRoot != null)
            {
                uiBuilder.PanelRoot.SetActive(visible);
            }
        }

        /// <summary>
        /// Ensure EventSystem exists in scene, otherwise UI won't receive clicks.
        /// </summary>
        void EnsureEventSystem()
        {
            if (FindObjectOfType<EventSystem>() == null)
            {
                GameObject eventSystemObj = new GameObject("EventSystem");
                eventSystemObj.AddComponent<EventSystem>();
                eventSystemObj.AddComponent<StandaloneInputModule>();
                UnityEngine.Debug.Log("[AnimationUI] Auto-created EventSystem.");
            }
        }
    }
}
