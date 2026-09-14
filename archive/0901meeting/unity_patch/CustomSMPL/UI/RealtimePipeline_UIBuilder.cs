using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using TMPro;

namespace CustomSMPL.UI
{
    public class RealtimePipeline_UIBuilder : MonoBehaviour
    {
        public Canvas MainCanvas { get; private set; }
        public GameObject PanelRoot { get; private set; }

        public TMP_InputField PortInput { get; private set; }
        public Button ConnectButton { get; private set; }
        public TextMeshProUGUI ConnectButtonText { get; private set; }
        
        public Toggle RenderSMPLToggle { get; private set; }
        public Toggle RenderJointsToggle { get; private set; }
        public Toggle FreezeLowerBodyToggle { get; private set; }
        public Toggle OriginalVideoToggle { get; private set; }
        public Toggle FullscreenToggle { get; private set; }
        public Slider VideoSizeSlider { get; private set; }

        public TextMeshProUGUI StatusLabel { get; private set; }
        public TextMeshProUGUI InfoLabel { get; private set; }

        // Playback Controls
        public Toggle PlaybackModeToggle { get; private set; }
        public TextMeshProUGUI CacheInfoLabel { get; private set; }
        public Slider ScrubSlider { get; private set; }
        public Button PlayPauseButton { get; private set; }
        public TextMeshProUGUI PlayPauseText { get; private set; }
        public Button ClearCacheButton { get; private set; }
        public Button ExportJsonButton { get; private set; }

        // Video Sync
        public RawImage VideoRawImage { get; private set; }
        public GameObject VideoPanelRoot { get; private set; }

        // Style constants
        private static readonly Color PanelBg = new Color(0.12f, 0.12f, 0.15f, 0.92f);
        private static readonly Color HeaderBg = new Color(0.18f, 0.55f, 0.82f, 1f);
        private static readonly Color ButtonNormal = new Color(0.22f, 0.22f, 0.28f, 1f);
        private static readonly Color ButtonHover = new Color(0.30f, 0.30f, 0.38f, 1f);
        private static readonly Color ButtonActive = new Color(0.18f, 0.55f, 0.82f, 1f);
        private static readonly Color InputBg = new Color(0.08f, 0.08f, 0.10f, 1f);
        private static readonly Color AccentColor = new Color(0.30f, 0.70f, 1f, 1f);
        private static readonly Color TextPrimary = new Color(0.92f, 0.92f, 0.95f, 1f);
        private static readonly Color TextSecondary = new Color(0.60f, 0.62f, 0.68f, 1f);

        private const float PANEL_WIDTH = 320f;

        public void Build()
        {
            CreateCanvas();
            CreateMainPanel();
            CreateVideoPanel(MainCanvas.transform);
            EnsureEventSystem();
        }

        void CreateCanvas()
        {
            GameObject canvasObj = new GameObject("RealtimePipeline_Canvas");
            canvasObj.transform.SetParent(this.transform);

            MainCanvas = canvasObj.AddComponent<Canvas>();
            MainCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
            MainCanvas.sortingOrder = 100;

            CanvasScaler scaler = canvasObj.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920, 1080);
            scaler.matchWidthOrHeight = 0.5f;

            canvasObj.AddComponent<GraphicRaycaster>();
        }

        void CreateMainPanel()
        {
            PanelRoot = CreatePanel("SidePanel", MainCanvas.transform);
            RectTransform panelRect = PanelRoot.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0, 0);
            panelRect.anchorMax = new Vector2(0, 1);
            panelRect.pivot = new Vector2(0, 0.5f);
            panelRect.offsetMin = new Vector2(16, 16);
            panelRect.offsetMax = new Vector2(PANEL_WIDTH + 16, -16);

            Image panelImage = PanelRoot.GetComponent<Image>();
            panelImage.color = PanelBg;

            VerticalLayoutGroup vlg = PanelRoot.AddComponent<VerticalLayoutGroup>();
            vlg.padding = new RectOffset(16, 16, 12, 12);
            vlg.spacing = 10;
            vlg.childForceExpandWidth = true;
            vlg.childForceExpandHeight = false;
            vlg.childControlWidth = true;
            vlg.childControlHeight = true;

            // 1. Header
            CreateHeader(PanelRoot.transform);

            // 2. Connection
            CreateConnectionSection(PanelRoot.transform);

            // 3. Toggles
            CreateTogglesSection(PanelRoot.transform);

            // 4. Separator
            CreateSeparator(PanelRoot.transform);

            // 5. Playback Section
            CreatePlaybackSection(PanelRoot.transform);

            // 6. Separator
            CreateSeparator(PanelRoot.transform);

            // 7. Status
            StatusLabel = CreateLabel(PanelRoot.transform, "StatusLabel", "Ready to connect", 14, AccentColor);

            // 6. Info
            InfoLabel = CreateLabel(PanelRoot.transform, "InfoLabel", "FPS: 0\nFrame: 0", 13, TextSecondary);
            
            // Spacer
            GameObject spacer = new GameObject("Spacer");
            spacer.transform.SetParent(PanelRoot.transform, false);
            LayoutElement spacerLE = spacer.AddComponent<LayoutElement>();
            spacerLE.flexibleHeight = 1;

            CreateLabel(PanelRoot.transform, "HotkeyHint", "Press H to toggle panel", 11, TextSecondary);
        }

        void CreateHeader(Transform parent)
        {
            GameObject headerObj = CreatePanel("Header", parent);
            headerObj.GetComponent<Image>().color = HeaderBg;

            LayoutElement headerLE = headerObj.AddComponent<LayoutElement>();
            headerLE.preferredHeight = 44;

            HorizontalLayoutGroup hlg = headerObj.AddComponent<HorizontalLayoutGroup>();
            hlg.padding = new RectOffset(14, 14, 8, 8);
            hlg.childAlignment = TextAnchor.MiddleLeft;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;

            TextMeshProUGUI title = CreateLabel(headerObj.transform, "Title", "Realtime Pipeline", 16, Color.white);
            title.fontStyle = FontStyles.Bold;
        }

        void CreateConnectionSection(Transform parent)
        {
            CreateLabel(parent, "ConnLabel", "Connection Settings", 13, AccentColor);

            GameObject row = CreatePanel("ConnRow", parent);
            row.GetComponent<Image>().color = Color.clear;
            LayoutElement rowLE = row.AddComponent<LayoutElement>();
            rowLE.preferredHeight = 36;

            HorizontalLayoutGroup hlg = row.AddComponent<HorizontalLayoutGroup>();
            hlg.spacing = 6;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;

            CreateLabel(row.transform, "PortLabel", "UDP Port:", 13, TextPrimary).gameObject.AddComponent<LayoutElement>().preferredWidth = 65;

            PortInput = CreateInputField(row.transform, "PortInput", "9095");
            PortInput.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;
            PortInput.contentType = TMP_InputField.ContentType.IntegerNumber;

            ConnectButton = CreateButton(row.transform, "ConnectBtn", "Apply", 13);
            ConnectButton.gameObject.AddComponent<LayoutElement>().preferredWidth = 65;
            ConnectButtonText = ConnectButton.GetComponentInChildren<TextMeshProUGUI>();
        }

        void CreateTogglesSection(Transform parent)
        {
            CreateLabel(parent, "RenderLabel", "Render Settings", 13, AccentColor);

            RenderSMPLToggle = CreateToggle(parent, "RenderSMPLToggle", "Render SMPL Character");
            RenderJointsToggle = CreateToggle(parent, "RenderJointsToggle", "Render 3D Joints");
            FreezeLowerBodyToggle = CreateToggle(parent, "FreezeLowerBody", "Freeze Lower Body");
            OriginalVideoToggle = CreateToggle(parent, "OriginalVideoToggle", "Show Original Video");
            
            // Video Size Controls
            GameObject sliderRow = new GameObject("VideoSizeRow");
            sliderRow.transform.SetParent(parent, false);
            HorizontalLayoutGroup hlg = sliderRow.AddComponent<HorizontalLayoutGroup>();
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;
            hlg.spacing = 10;
            LayoutElement sliderLE = sliderRow.AddComponent<LayoutElement>();
            sliderLE.preferredHeight = 24;

            CreateLabel(sliderRow.transform, "VideoSizeLabel", "Video Size:", 13, TextPrimary).gameObject.AddComponent<LayoutElement>().preferredWidth = 70;
            VideoSizeSlider = CreateSlider(sliderRow.transform, "VideoSizeSlider");
            VideoSizeSlider.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;
            VideoSizeSlider.minValue = 0.5f;
            VideoSizeSlider.maxValue = 3.0f;
            VideoSizeSlider.value = 1.0f;

            FullscreenToggle = CreateToggle(parent, "FullscreenToggle", "Fullscreen Video");
        }

        void CreatePlaybackSection(Transform parent)
        {
            CreateLabel(parent, "PlaybackLabel", "Playback & Cache", 13, AccentColor);

            CacheInfoLabel = CreateLabel(parent, "CacheInfo", "Cached Frames: 0", 13, TextSecondary);

            PlaybackModeToggle = CreateToggle(parent, "PlaybackModeToggle", "Enable Playback Mode");

            // Scrub Slider
            GameObject sliderRow = new GameObject("SliderRow");
            sliderRow.transform.SetParent(parent, false);
            HorizontalLayoutGroup hlg = sliderRow.AddComponent<HorizontalLayoutGroup>();
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;
            hlg.spacing = 10;
            LayoutElement sliderLE = sliderRow.AddComponent<LayoutElement>();
            sliderLE.preferredHeight = 24;

            ScrubSlider = CreateSlider(sliderRow.transform, "ScrubSlider");
            ScrubSlider.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;

            PlayPauseButton = CreateButton(sliderRow.transform, "PlayPauseBtn", "Play", 13);
            PlayPauseButton.gameObject.AddComponent<LayoutElement>().preferredWidth = 60;
            PlayPauseText = PlayPauseButton.GetComponentInChildren<TextMeshProUGUI>();

            // Actions Row
            GameObject actionRow = new GameObject("ActionRow");
            actionRow.transform.SetParent(parent, false);
            HorizontalLayoutGroup ahlg = actionRow.AddComponent<HorizontalLayoutGroup>();
            ahlg.childControlWidth = true;
            ahlg.childControlHeight = true;
            ahlg.childForceExpandWidth = false;
            ahlg.childForceExpandHeight = true;
            ahlg.spacing = 10;
            LayoutElement actionLE = actionRow.AddComponent<LayoutElement>();
            actionLE.preferredHeight = 24;

            ClearCacheButton = CreateButton(actionRow.transform, "ClearCacheBtn", "Clear Cache", 13);
            ClearCacheButton.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;

            ExportJsonButton = CreateButton(actionRow.transform, "ExportJsonBtn", "Export JSON", 13);
            ExportJsonButton.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;
        }

        void CreateVideoPanel(Transform parent)
        {
            VideoPanelRoot = new GameObject("VideoPanelRoot");
            VideoPanelRoot.transform.SetParent(parent, false);
            
            RectTransform rt = VideoPanelRoot.AddComponent<RectTransform>();
            rt.anchorMin = new Vector2(1, 1);
            rt.anchorMax = new Vector2(1, 1);
            rt.pivot = new Vector2(1, 1);
            rt.anchoredPosition = new Vector2(-16, -16);
            rt.sizeDelta = new Vector2(480, 270); // 16:9 ratio

            VideoRawImage = VideoPanelRoot.AddComponent<RawImage>();
            VideoRawImage.color = Color.white; // Start white so we can see the empty RenderTexture if it's there
            
            // Add a small border
            Outline outline = VideoPanelRoot.AddComponent<Outline>();
            outline.effectColor = new Color(1, 1, 1, 0.5f); // Make outline white so it stands out against black
            outline.effectDistance = new Vector2(2, -2);

            // Add placeholder text
            GameObject textObj = new GameObject("VideoText");
            textObj.transform.SetParent(VideoPanelRoot.transform, false);
            RectTransform textRt = textObj.AddComponent<RectTransform>();
            textRt.anchorMin = Vector2.zero;
            textRt.anchorMax = Vector2.one;
            textRt.sizeDelta = Vector2.zero;
            
            TextMeshProUGUI tmp = textObj.AddComponent<TextMeshProUGUI>();
            tmp.text = "Waiting for Video...";
            tmp.color = Color.gray;
            tmp.alignment = TextAlignmentOptions.Center;
            
            VideoPanelRoot.SetActive(false);
        }

        void EnsureEventSystem()
        {
            if (Object.FindObjectOfType<EventSystem>() == null)
            {
                GameObject es = new GameObject("EventSystem");
                es.AddComponent<EventSystem>();
                es.AddComponent<StandaloneInputModule>();
            }
        }

        // --- Factories ---
        GameObject CreatePanel(string name, Transform parent)
        {
            GameObject obj = new GameObject(name);
            obj.transform.SetParent(parent, false);
            obj.AddComponent<RectTransform>();
            Image img = obj.AddComponent<Image>();
            return obj;
        }

        TextMeshProUGUI CreateLabel(Transform parent, string name, string text, int fontSize, Color color)
        {
            GameObject obj = new GameObject(name);
            obj.transform.SetParent(parent, false);
            TextMeshProUGUI tmp = obj.AddComponent<TextMeshProUGUI>();
            tmp.text = text;
            tmp.fontSize = fontSize;
            tmp.color = color;
            tmp.alignment = TextAlignmentOptions.Left;
            tmp.enableWordWrapping = false;
            return tmp;
        }

        TMP_InputField CreateInputField(Transform parent, string name, string placeholder)
        {
            GameObject inputObj = CreatePanel(name, parent);
            inputObj.GetComponent<Image>().color = InputBg;

            GameObject textAreaObj = new GameObject("TextArea");
            textAreaObj.transform.SetParent(inputObj.transform, false);
            RectTransform textAreaRect = textAreaObj.AddComponent<RectTransform>();
            textAreaRect.anchorMin = Vector2.zero; textAreaRect.anchorMax = Vector2.one;
            textAreaRect.offsetMin = new Vector2(10, 2); textAreaRect.offsetMax = new Vector2(-10, -2);
            textAreaObj.AddComponent<RectMask2D>();

            GameObject textObj = new GameObject("Text");
            textObj.transform.SetParent(textAreaObj.transform, false);
            RectTransform textRect = textObj.AddComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero; textRect.anchorMax = Vector2.one;
            textRect.offsetMin = Vector2.zero; textRect.offsetMax = Vector2.zero;

            TextMeshProUGUI inputText = textObj.AddComponent<TextMeshProUGUI>();
            inputText.fontSize = 13;
            inputText.color = TextPrimary;
            inputText.alignment = TextAlignmentOptions.Left;
            inputText.verticalAlignment = VerticalAlignmentOptions.Middle;

            TMP_InputField inputField = inputObj.AddComponent<TMP_InputField>();
            inputField.textViewport = textAreaRect;
            inputField.textComponent = inputText;
            return inputField;
        }

        Button CreateButton(Transform parent, string name, string label, int fontSize)
        {
            GameObject btnObj = CreatePanel(name, parent);
            Image btnImg = btnObj.GetComponent<Image>();
            btnImg.color = ButtonNormal;

            Button btn = btnObj.AddComponent<Button>();
            ColorBlock cb = btn.colors;
            cb.normalColor = ButtonNormal;
            cb.highlightedColor = ButtonHover;
            cb.pressedColor = ButtonActive;
            cb.selectedColor = ButtonHover;
            btn.colors = cb;
            btn.targetGraphic = btnImg;

            TextMeshProUGUI btnText = CreateLabel(btnObj.transform, "Text", label, fontSize, TextPrimary);
            btnText.alignment = TextAlignmentOptions.Center;

            return btn;
        }

        Toggle CreateToggle(Transform parent, string name, string label)
        {
            GameObject toggleObj = CreatePanel(name, parent);
            toggleObj.GetComponent<Image>().color = Color.clear;
            LayoutElement le = toggleObj.AddComponent<LayoutElement>();
            le.preferredHeight = 24;

            HorizontalLayoutGroup hlg = toggleObj.AddComponent<HorizontalLayoutGroup>();
            hlg.spacing = 8;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;
            hlg.childAlignment = TextAnchor.MiddleLeft;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;

            // Background
            GameObject bgObj = CreatePanel("Background", toggleObj.transform);
            bgObj.GetComponent<Image>().color = InputBg;
            LayoutElement bgLE = bgObj.AddComponent<LayoutElement>();
            bgLE.preferredWidth = 20;
            bgLE.preferredHeight = 20;

            // Checkmark
            GameObject checkObj = CreatePanel("Checkmark", bgObj.transform);
            checkObj.GetComponent<Image>().color = AccentColor;
            RectTransform checkRect = checkObj.GetComponent<RectTransform>();
            checkRect.anchorMin = new Vector2(0.2f, 0.2f);
            checkRect.anchorMax = new Vector2(0.8f, 0.8f);
            checkRect.offsetMin = Vector2.zero; checkRect.offsetMax = Vector2.zero;

            TextMeshProUGUI text = CreateLabel(toggleObj.transform, "Label", label, 13, TextPrimary);
            text.gameObject.AddComponent<LayoutElement>().flexibleWidth = 1;

            Toggle toggle = toggleObj.AddComponent<Toggle>();
            toggle.targetGraphic = bgObj.GetComponent<Image>();
            toggle.graphic = checkObj.GetComponent<Image>();

            return toggle;
        }

        Slider CreateSlider(Transform parent, string name)
        {
            GameObject sliderObj = CreatePanel(name, parent);
            sliderObj.GetComponent<Image>().color = Color.clear;

            // Background
            GameObject bgObj = CreatePanel("Background", sliderObj.transform);
            bgObj.GetComponent<Image>().color = InputBg;
            RectTransform bgRect = bgObj.GetComponent<RectTransform>();
            bgRect.anchorMin = new Vector2(0, 0.25f);
            bgRect.anchorMax = new Vector2(1, 0.75f);
            bgRect.offsetMin = Vector2.zero; bgRect.offsetMax = Vector2.zero;

            // Fill Area
            GameObject fillAreaObj = new GameObject("Fill Area");
            fillAreaObj.transform.SetParent(sliderObj.transform, false);
            RectTransform fillAreaRect = fillAreaObj.AddComponent<RectTransform>();
            fillAreaRect.anchorMin = Vector2.zero; fillAreaRect.anchorMax = Vector2.one;
            fillAreaRect.offsetMin = new Vector2(5, 0); fillAreaRect.offsetMax = new Vector2(-15, 0);

            // Fill
            GameObject fillObj = CreatePanel("Fill", fillAreaObj.transform);
            fillObj.GetComponent<Image>().color = AccentColor;
            RectTransform fillRect = fillObj.GetComponent<RectTransform>();
            fillRect.anchorMin = Vector2.zero; fillRect.anchorMax = Vector2.one;
            fillRect.offsetMin = Vector2.zero; fillRect.offsetMax = Vector2.zero;

            // Handle Slide Area
            GameObject handleAreaObj = new GameObject("Handle Slide Area");
            handleAreaObj.transform.SetParent(sliderObj.transform, false);
            RectTransform handleAreaRect = handleAreaObj.AddComponent<RectTransform>();
            handleAreaRect.anchorMin = Vector2.zero; handleAreaRect.anchorMax = Vector2.one;
            handleAreaRect.offsetMin = new Vector2(10, 0); handleAreaRect.offsetMax = new Vector2(-10, 0);

            // Handle
            GameObject handleObj = CreatePanel("Handle", handleAreaObj.transform);
            handleObj.GetComponent<Image>().color = TextPrimary;
            RectTransform handleRect = handleObj.GetComponent<RectTransform>();
            handleRect.anchorMin = new Vector2(0, 0); handleRect.anchorMax = new Vector2(0, 1);
            handleRect.sizeDelta = new Vector2(20, 0);

            Slider slider = sliderObj.AddComponent<Slider>();
            slider.fillRect = fillRect;
            slider.handleRect = handleRect;
            slider.targetGraphic = handleObj.GetComponent<Image>();
            slider.direction = Slider.Direction.LeftToRight;

            return slider;
        }

        void CreateSeparator(Transform parent)
        {
            GameObject sep = new GameObject("Separator");
            sep.transform.SetParent(parent, false);
            Image sepImg = sep.AddComponent<Image>();
            sepImg.color = new Color(1f, 1f, 1f, 0.1f);
            LayoutElement sepLE = sep.AddComponent<LayoutElement>();
            sepLE.preferredHeight = 1;
        }
    }
}
