using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace CustomSMPL.UI
{
    /// <summary>
    /// Runtime UI Builder - constructs all UI elements via code at runtime.
    /// Attached to a GameObject, builds Canvas + full UI on Build().
    /// </summary>
    public class RuntimeUIBuilder : MonoBehaviour
    {
        // === Built UI references (for other scripts) ===
        public Canvas MainCanvas { get; private set; }
        public GameObject PanelRoot { get; private set; }

        // File browser section
        public TMP_InputField FolderPathInput { get; private set; }
        public Button RefreshButton { get; private set; }
        public ScrollRect FileListScrollRect { get; private set; }
        public RectTransform FileListContent { get; private set; }

        // Playback controls
        public Button PauseButton { get; private set; }
        public Button StopButton { get; private set; }
        public Slider SpeedSlider { get; private set; }
        public TextMeshProUGUI SpeedLabel { get; private set; }
        public Slider ProgressSlider { get; private set; }
        public TextMeshProUGUI ProgressLabel { get; private set; }
        public TextMeshProUGUI InfoLabel { get; private set; }
        public TextMeshProUGUI StatusLabel { get; private set; }
        public TextMeshProUGUI PauseButtonText { get; private set; }

        // Style constants
        private static readonly Color PanelBg = new Color(0.12f, 0.12f, 0.15f, 0.92f);
        private static readonly Color HeaderBg = new Color(0.18f, 0.55f, 0.82f, 1f);
        private static readonly Color ButtonNormal = new Color(0.22f, 0.22f, 0.28f, 1f);
        private static readonly Color ButtonHover = new Color(0.30f, 0.30f, 0.38f, 1f);
        private static readonly Color ButtonActive = new Color(0.18f, 0.55f, 0.82f, 1f);
        private static readonly Color InputBg = new Color(0.08f, 0.08f, 0.10f, 1f);
        private static readonly Color ScrollBg = new Color(0.06f, 0.06f, 0.08f, 1f);
        private static readonly Color AccentColor = new Color(0.30f, 0.70f, 1f, 1f);
        private static readonly Color TextPrimary = new Color(0.92f, 0.92f, 0.95f, 1f);
        private static readonly Color TextSecondary = new Color(0.60f, 0.62f, 0.68f, 1f);
        private static readonly Color FileButtonNormal = new Color(0.14f, 0.14f, 0.18f, 1f);
        private static readonly Color FileButtonHover = new Color(0.22f, 0.22f, 0.30f, 1f);
        private static readonly Color FileButtonSelected = new Color(0.18f, 0.40f, 0.60f, 1f);
        private static readonly Color FileButtonSelectedHover = new Color(0.22f, 0.48f, 0.70f, 1f);

        private const float PANEL_WIDTH = 360f;

        public void Build()
        {
            CreateCanvas();
            CreateMainPanel();
        }

        void CreateCanvas()
        {
            GameObject canvasObj = new GameObject("CustomSMPL_Canvas");
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
            // Side panel (left)
            PanelRoot = CreatePanel("SidePanel", MainCanvas.transform);
            RectTransform panelRect = PanelRoot.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0, 0);
            panelRect.anchorMax = new Vector2(0, 1);
            panelRect.pivot = new Vector2(0, 0.5f);
            panelRect.offsetMin = new Vector2(16, 16);
            panelRect.offsetMax = new Vector2(PANEL_WIDTH + 16, -16);

            Image panelImage = PanelRoot.GetComponent<Image>();
            panelImage.color = PanelBg;
            panelImage.raycastTarget = true;

            // VerticalLayoutGroup
            VerticalLayoutGroup vlg = PanelRoot.AddComponent<VerticalLayoutGroup>();
            vlg.padding = new RectOffset(16, 16, 12, 12);
            vlg.spacing = 10;
            vlg.childForceExpandWidth = true;
            vlg.childForceExpandHeight = false;
            vlg.childControlWidth = true;
            vlg.childControlHeight = true;

            // === 1. Header ===
            CreateHeader(PanelRoot.transform);

            // === 2. Folder path ===
            CreateFolderSection(PanelRoot.transform);

            // === 3. File list ===
            CreateFileListSection(PanelRoot.transform);

            // === 4. Status ===
            StatusLabel = CreateLabel(PanelRoot.transform, "StatusLabel", "Select a folder or enter path", 13, TextSecondary);

            // === 5. Separator ===
            CreateSeparator(PanelRoot.transform);

            // === 6. Playback controls ===
            CreatePlaybackSection(PanelRoot.transform);

            // === 7. Info ===
            CreateInfoSection(PanelRoot.transform);

            // === 8. Hotkey hint ===
            CreateLabel(PanelRoot.transform, "HotkeyHint", "Press H to toggle panel", 11, TextSecondary);
        }

        void CreateHeader(Transform parent)
        {
            GameObject headerObj = CreatePanel("Header", parent);
            Image headerImg = headerObj.GetComponent<Image>();
            headerImg.color = HeaderBg;
            headerImg.raycastTarget = false;

            LayoutElement headerLE = headerObj.AddComponent<LayoutElement>();
            headerLE.preferredHeight = 44;
            headerLE.flexibleWidth = 1;

            HorizontalLayoutGroup hlg = headerObj.AddComponent<HorizontalLayoutGroup>();
            hlg.padding = new RectOffset(14, 14, 8, 8);
            hlg.childAlignment = TextAnchor.MiddleLeft;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;

            TextMeshProUGUI title = CreateLabel(headerObj.transform, "Title", "SMPL Animation Player", 16, Color.white);
            title.fontStyle = FontStyles.Bold;
            LayoutElement titleLE = title.gameObject.AddComponent<LayoutElement>();
            titleLE.flexibleWidth = 1;
        }

        void CreateFolderSection(Transform parent)
        {
            CreateLabel(parent, "FolderLabel", "Animation Folder", 13, AccentColor);

            // Path input + button row
            GameObject row = CreatePanel("FolderRow", parent);
            row.GetComponent<Image>().color = Color.clear;
            row.GetComponent<Image>().raycastTarget = false;
            LayoutElement rowLE = row.AddComponent<LayoutElement>();
            rowLE.preferredHeight = 36;

            HorizontalLayoutGroup hlg = row.AddComponent<HorizontalLayoutGroup>();
            hlg.spacing = 6;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;

            // Path input field
            FolderPathInput = CreateInputField(row.transform, "FolderPathInput", "Enter folder path...");
            LayoutElement inputLE = FolderPathInput.gameObject.AddComponent<LayoutElement>();
            inputLE.flexibleWidth = 1;
            inputLE.preferredHeight = 36;

            // Refresh button
            RefreshButton = CreateButton(row.transform, "RefreshBtn", "Reload", 13);
            LayoutElement refreshLE = RefreshButton.gameObject.AddComponent<LayoutElement>();
            refreshLE.preferredWidth = 65;
        }

        void CreateFileListSection(Transform parent)
        {
            CreateLabel(parent, "FileListLabel", "JSON Files", 13, AccentColor);

            // ScrollView
            GameObject scrollObj = new GameObject("FileListScroll");
            scrollObj.transform.SetParent(parent, false);

            Image scrollBg = scrollObj.AddComponent<Image>();
            scrollBg.color = ScrollBg;
            scrollBg.raycastTarget = true;

            LayoutElement scrollLE = scrollObj.AddComponent<LayoutElement>();
            scrollLE.preferredHeight = 300;
            scrollLE.flexibleHeight = 1;
            scrollLE.flexibleWidth = 1;

            FileListScrollRect = scrollObj.AddComponent<ScrollRect>();
            FileListScrollRect.horizontal = false;
            FileListScrollRect.vertical = true;
            FileListScrollRect.movementType = ScrollRect.MovementType.Clamped;
            FileListScrollRect.scrollSensitivity = 30f;

            // Viewport
            GameObject viewportObj = new GameObject("Viewport");
            viewportObj.transform.SetParent(scrollObj.transform, false);
            RectTransform viewportRect = viewportObj.AddComponent<RectTransform>();
            viewportRect.anchorMin = Vector2.zero;
            viewportRect.anchorMax = Vector2.one;
            viewportRect.offsetMin = new Vector2(4, 4);
            viewportRect.offsetMax = new Vector2(-4, -4);

            // Use RectMask2D instead of Mask for better performance and no Image needed
            viewportObj.AddComponent<RectMask2D>();

            FileListScrollRect.viewport = viewportRect;

            // Content
            GameObject contentObj = new GameObject("Content");
            contentObj.transform.SetParent(viewportObj.transform, false);
            FileListContent = contentObj.AddComponent<RectTransform>();
            FileListContent.anchorMin = new Vector2(0, 1);
            FileListContent.anchorMax = new Vector2(1, 1);
            FileListContent.pivot = new Vector2(0.5f, 1);
            FileListContent.offsetMin = new Vector2(0, 0);
            FileListContent.offsetMax = new Vector2(0, 0);

            VerticalLayoutGroup contentVlg = contentObj.AddComponent<VerticalLayoutGroup>();
            contentVlg.spacing = 3;
            contentVlg.padding = new RectOffset(2, 2, 2, 2);
            contentVlg.childForceExpandWidth = true;
            contentVlg.childForceExpandHeight = false;
            contentVlg.childControlWidth = true;
            contentVlg.childControlHeight = true;

            ContentSizeFitter contentCsf = contentObj.AddComponent<ContentSizeFitter>();
            contentCsf.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            FileListScrollRect.content = FileListContent;

            // Scrollbar
            GameObject scrollbarObj = new GameObject("Scrollbar");
            scrollbarObj.transform.SetParent(scrollObj.transform, false);
            RectTransform scrollbarRect = scrollbarObj.AddComponent<RectTransform>();
            scrollbarRect.anchorMin = new Vector2(1, 0);
            scrollbarRect.anchorMax = new Vector2(1, 1);
            scrollbarRect.pivot = new Vector2(1, 0.5f);
            scrollbarRect.sizeDelta = new Vector2(8, 0);
            scrollbarRect.anchoredPosition = Vector2.zero;

            Image scrollbarBg = scrollbarObj.AddComponent<Image>();
            scrollbarBg.color = new Color(0.15f, 0.15f, 0.18f, 0.5f);

            // Handle
            GameObject handleObj = new GameObject("Handle");
            handleObj.transform.SetParent(scrollbarObj.transform, false);
            RectTransform handleRect = handleObj.AddComponent<RectTransform>();
            handleRect.sizeDelta = Vector2.zero;

            Image handleImg = handleObj.AddComponent<Image>();
            handleImg.color = new Color(0.4f, 0.4f, 0.48f, 0.8f);

            Scrollbar scrollbar = scrollbarObj.AddComponent<Scrollbar>();
            scrollbar.handleRect = handleRect;
            scrollbar.direction = Scrollbar.Direction.BottomToTop;
            scrollbar.targetGraphic = handleImg;

            FileListScrollRect.verticalScrollbar = scrollbar;
            FileListScrollRect.verticalScrollbarVisibility = ScrollRect.ScrollbarVisibility.AutoHideAndExpandViewport;
            FileListScrollRect.verticalScrollbarSpacing = 2;
        }

        void CreateSeparator(Transform parent)
        {
            GameObject sep = new GameObject("Separator");
            sep.transform.SetParent(parent, false);
            Image sepImg = sep.AddComponent<Image>();
            sepImg.color = new Color(1f, 1f, 1f, 0.1f);
            sepImg.raycastTarget = false;
            LayoutElement sepLE = sep.AddComponent<LayoutElement>();
            sepLE.preferredHeight = 1;
            sepLE.flexibleWidth = 1;
        }

        void CreatePlaybackSection(Transform parent)
        {
            CreateLabel(parent, "PlaybackLabel", "Playback Controls", 13, AccentColor);

            // Pause + Stop button row
            GameObject btnRow = CreatePanel("ButtonRow", parent);
            btnRow.GetComponent<Image>().color = Color.clear;
            btnRow.GetComponent<Image>().raycastTarget = false;
            LayoutElement btnRowLE = btnRow.AddComponent<LayoutElement>();
            btnRowLE.preferredHeight = 38;

            HorizontalLayoutGroup hlg = btnRow.AddComponent<HorizontalLayoutGroup>();
            hlg.spacing = 8;
            hlg.childForceExpandWidth = true;
            hlg.childForceExpandHeight = true;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;

            PauseButton = CreateButton(btnRow.transform, "PauseBtn", "Pause", 15);
            PauseButtonText = PauseButton.GetComponentInChildren<TextMeshProUGUI>();
            StopButton = CreateButton(btnRow.transform, "StopBtn", "Stop", 15);

            // Speed slider row
            GameObject speedRow = CreatePanel("SpeedRow", parent);
            speedRow.GetComponent<Image>().color = Color.clear;
            speedRow.GetComponent<Image>().raycastTarget = false;
            LayoutElement speedRowLE = speedRow.AddComponent<LayoutElement>();
            speedRowLE.preferredHeight = 30;

            HorizontalLayoutGroup speedHlg = speedRow.AddComponent<HorizontalLayoutGroup>();
            speedHlg.spacing = 8;
            speedHlg.childForceExpandHeight = true;
            speedHlg.childForceExpandWidth = false;
            speedHlg.childControlWidth = true;
            speedHlg.childControlHeight = true;
            speedHlg.childAlignment = TextAnchor.MiddleLeft;

            TextMeshProUGUI speedPrefix = CreateLabel(speedRow.transform, "SpeedPrefix", "Speed", 12, TextSecondary);
            LayoutElement spLE = speedPrefix.gameObject.AddComponent<LayoutElement>();
            spLE.preferredWidth = 42;

            SpeedSlider = CreateSlider(speedRow.transform, "SpeedSlider", 0.1f, 3.0f, 1.0f);
            LayoutElement sliderLE = SpeedSlider.gameObject.AddComponent<LayoutElement>();
            sliderLE.flexibleWidth = 1;

            SpeedLabel = CreateLabel(speedRow.transform, "SpeedValue", "1.0x", 12, TextPrimary);
            LayoutElement svLE = SpeedLabel.gameObject.AddComponent<LayoutElement>();
            svLE.preferredWidth = 40;

            // Progress row
            GameObject progressRow = CreatePanel("ProgressRow", parent);
            progressRow.GetComponent<Image>().color = Color.clear;
            progressRow.GetComponent<Image>().raycastTarget = false;
            LayoutElement progressRowLE = progressRow.AddComponent<LayoutElement>();
            progressRowLE.preferredHeight = 20;

            HorizontalLayoutGroup progHlg = progressRow.AddComponent<HorizontalLayoutGroup>();
            progHlg.spacing = 8;
            progHlg.childForceExpandHeight = true;
            progHlg.childForceExpandWidth = false;
            progHlg.childControlWidth = true;
            progHlg.childControlHeight = true;
            progHlg.childAlignment = TextAnchor.MiddleLeft;

            TextMeshProUGUI progPrefix = CreateLabel(progressRow.transform, "ProgressPrefix", "Frame", 12, TextSecondary);
            LayoutElement ppLE = progPrefix.gameObject.AddComponent<LayoutElement>();
            ppLE.preferredWidth = 42;

            ProgressSlider = CreateSlider(progressRow.transform, "ProgressSlider", 0f, 1f, 0f);
            LayoutElement psLE = ProgressSlider.gameObject.AddComponent<LayoutElement>();
            psLE.flexibleWidth = 1;

            ProgressLabel = CreateLabel(progressRow.transform, "ProgressValue", "0 / 0", 11, TextSecondary);
            LayoutElement pvLE = ProgressLabel.gameObject.AddComponent<LayoutElement>();
            pvLE.preferredWidth = 75;
        }

        void CreateInfoSection(Transform parent)
        {
            InfoLabel = CreateLabel(parent, "InfoLabel", "No animation loaded", 12, TextSecondary);
        }

        // ===================================================================
        //  UI Element Factory Methods
        // ===================================================================

        GameObject CreatePanel(string name, Transform parent)
        {
            GameObject obj = new GameObject(name);
            obj.transform.SetParent(parent, false);
            obj.AddComponent<RectTransform>();
            Image img = obj.AddComponent<Image>();
            img.raycastTarget = true;
            return obj;
        }

        TextMeshProUGUI CreateLabel(Transform parent, string name, string text, int fontSize, Color color)
        {
            GameObject obj = new GameObject(name);
            obj.transform.SetParent(parent, false);
            obj.AddComponent<RectTransform>();

            TextMeshProUGUI tmp = obj.AddComponent<TextMeshProUGUI>();
            tmp.text = text;
            tmp.fontSize = fontSize;
            tmp.color = color;
            tmp.alignment = TextAlignmentOptions.Left;
            tmp.overflowMode = TextOverflowModes.Ellipsis;
            tmp.enableWordWrapping = true;
            tmp.raycastTarget = false; // Labels should NOT block clicks

            return tmp;
        }

        Button CreateButton(Transform parent, string name, string label, int fontSize)
        {
            GameObject btnObj = CreatePanel(name, parent);
            Image btnImg = btnObj.GetComponent<Image>();
            btnImg.color = ButtonNormal;
            btnImg.raycastTarget = true; // Button image MUST receive raycasts

            Button btn = btnObj.AddComponent<Button>();
            ColorBlock cb = btn.colors;
            cb.normalColor = ButtonNormal;
            cb.highlightedColor = ButtonHover;
            cb.pressedColor = ButtonActive;
            cb.selectedColor = ButtonHover;
            cb.fadeDuration = 0.1f;
            btn.colors = cb;
            btn.targetGraphic = btnImg;

            TextMeshProUGUI btnText = CreateLabel(btnObj.transform, "Text", label, fontSize, TextPrimary);
            btnText.alignment = TextAlignmentOptions.Center;
            btnText.raycastTarget = false; // Text must NOT block button clicks

            return btn;
        }

        TMP_InputField CreateInputField(Transform parent, string name, string placeholder)
        {
            GameObject inputObj = CreatePanel(name, parent);
            Image inputImg = inputObj.GetComponent<Image>();
            inputImg.color = InputBg;
            inputImg.raycastTarget = true;

            // Text Area
            GameObject textAreaObj = new GameObject("TextArea");
            textAreaObj.transform.SetParent(inputObj.transform, false);
            RectTransform textAreaRect = textAreaObj.AddComponent<RectTransform>();
            textAreaRect.anchorMin = Vector2.zero;
            textAreaRect.anchorMax = Vector2.one;
            textAreaRect.offsetMin = new Vector2(10, 2);
            textAreaRect.offsetMax = new Vector2(-10, -2);
            textAreaObj.AddComponent<RectMask2D>();

            // Placeholder
            GameObject placeholderObj = new GameObject("Placeholder");
            placeholderObj.transform.SetParent(textAreaObj.transform, false);
            RectTransform phRect = placeholderObj.AddComponent<RectTransform>();
            phRect.anchorMin = Vector2.zero;
            phRect.anchorMax = Vector2.one;
            phRect.offsetMin = Vector2.zero;
            phRect.offsetMax = Vector2.zero;

            TextMeshProUGUI phText = placeholderObj.AddComponent<TextMeshProUGUI>();
            phText.text = placeholder;
            phText.fontSize = 13;
            phText.color = new Color(0.5f, 0.5f, 0.55f, 0.7f);
            phText.fontStyle = FontStyles.Italic;
            phText.alignment = TextAlignmentOptions.Left;
            phText.verticalAlignment = VerticalAlignmentOptions.Middle;
            phText.raycastTarget = false;

            // Text
            GameObject textObj = new GameObject("Text");
            textObj.transform.SetParent(textAreaObj.transform, false);
            RectTransform textRect = textObj.AddComponent<RectTransform>();
            textRect.anchorMin = Vector2.zero;
            textRect.anchorMax = Vector2.one;
            textRect.offsetMin = Vector2.zero;
            textRect.offsetMax = Vector2.zero;

            TextMeshProUGUI inputText = textObj.AddComponent<TextMeshProUGUI>();
            inputText.fontSize = 13;
            inputText.color = TextPrimary;
            inputText.alignment = TextAlignmentOptions.Left;
            inputText.verticalAlignment = VerticalAlignmentOptions.Middle;
            inputText.raycastTarget = true; // Input text needs raycast for caret positioning

            // Input Field component
            TMP_InputField inputField = inputObj.AddComponent<TMP_InputField>();
            inputField.textViewport = textAreaRect;
            inputField.textComponent = inputText;
            inputField.placeholder = phText;
            inputField.fontAsset = inputText.font;
            inputField.pointSize = 13;
            inputField.caretColor = AccentColor;
            inputField.selectionColor = new Color(AccentColor.r, AccentColor.g, AccentColor.b, 0.3f);

            return inputField;
        }

        Slider CreateSlider(Transform parent, string name, float min, float max, float value)
        {
            GameObject sliderObj = new GameObject(name);
            sliderObj.transform.SetParent(parent, false);
            RectTransform sliderRect = sliderObj.AddComponent<RectTransform>();

            // Background
            GameObject bgObj = new GameObject("Background");
            bgObj.transform.SetParent(sliderObj.transform, false);
            RectTransform bgRect = bgObj.AddComponent<RectTransform>();
            bgRect.anchorMin = new Vector2(0, 0.35f);
            bgRect.anchorMax = new Vector2(1, 0.65f);
            bgRect.offsetMin = Vector2.zero;
            bgRect.offsetMax = Vector2.zero;

            Image bgImg = bgObj.AddComponent<Image>();
            bgImg.color = new Color(0.2f, 0.2f, 0.25f, 1f);
            bgImg.raycastTarget = true;

            // Fill Area
            GameObject fillAreaObj = new GameObject("FillArea");
            fillAreaObj.transform.SetParent(sliderObj.transform, false);
            RectTransform fillAreaRect = fillAreaObj.AddComponent<RectTransform>();
            fillAreaRect.anchorMin = new Vector2(0, 0.35f);
            fillAreaRect.anchorMax = new Vector2(1, 0.65f);
            fillAreaRect.offsetMin = Vector2.zero;
            fillAreaRect.offsetMax = Vector2.zero;

            GameObject fillObj = new GameObject("Fill");
            fillObj.transform.SetParent(fillAreaObj.transform, false);
            RectTransform fillRect = fillObj.AddComponent<RectTransform>();
            fillRect.anchorMin = Vector2.zero;
            fillRect.anchorMax = Vector2.one;
            fillRect.offsetMin = Vector2.zero;
            fillRect.offsetMax = Vector2.zero;

            Image fillImg = fillObj.AddComponent<Image>();
            fillImg.color = AccentColor;
            fillImg.raycastTarget = false;

            // Handle Area
            GameObject handleAreaObj = new GameObject("HandleSlideArea");
            handleAreaObj.transform.SetParent(sliderObj.transform, false);
            RectTransform handleAreaRect = handleAreaObj.AddComponent<RectTransform>();
            handleAreaRect.anchorMin = Vector2.zero;
            handleAreaRect.anchorMax = Vector2.one;
            handleAreaRect.offsetMin = new Vector2(5, 0);
            handleAreaRect.offsetMax = new Vector2(-5, 0);

            GameObject handleObj = new GameObject("Handle");
            handleObj.transform.SetParent(handleAreaObj.transform, false);
            RectTransform handleRect = handleObj.AddComponent<RectTransform>();
            handleRect.sizeDelta = new Vector2(16, 16);

            Image handleImg = handleObj.AddComponent<Image>();
            handleImg.color = Color.white;
            handleImg.raycastTarget = true;

            Slider slider = sliderObj.AddComponent<Slider>();
            slider.fillRect = fillRect;
            slider.handleRect = handleRect;
            slider.targetGraphic = handleImg;
            slider.minValue = min;
            slider.maxValue = max;
            slider.value = value;

            return slider;
        }

        // ===================================================================
        //  Public factory methods (for FileBrowserPanel to create file buttons)
        // ===================================================================

        /// <summary>
        /// Creates a file list button.
        /// </summary>
        public Button CreateFileButton(Transform parent, string fileName)
        {
            GameObject btnObj = CreatePanel("FileBtn_" + fileName, parent);
            Image btnImg = btnObj.GetComponent<Image>();
            btnImg.color = FileButtonNormal;
            btnImg.raycastTarget = true;

            LayoutElement le = btnObj.AddComponent<LayoutElement>();
            le.preferredHeight = 34;

            Button btn = btnObj.AddComponent<Button>();
            ColorBlock cb = btn.colors;
            cb.normalColor = FileButtonNormal;
            cb.highlightedColor = FileButtonHover;
            cb.pressedColor = ButtonActive;
            cb.selectedColor = FileButtonSelected;
            cb.fadeDuration = 0.08f;
            btn.colors = cb;
            btn.targetGraphic = btnImg;

            // Horizontal layout: icon + filename
            HorizontalLayoutGroup hlg = btnObj.AddComponent<HorizontalLayoutGroup>();
            hlg.padding = new RectOffset(10, 10, 4, 4);
            hlg.spacing = 6;
            hlg.childAlignment = TextAnchor.MiddleLeft;
            hlg.childForceExpandWidth = false;
            hlg.childForceExpandHeight = true;
            hlg.childControlWidth = true;
            hlg.childControlHeight = true;

            // Icon
            TextMeshProUGUI icon = CreateLabel(btnObj.transform, "Icon", ">", 13, TextSecondary);
            LayoutElement iconLE = icon.gameObject.AddComponent<LayoutElement>();
            iconLE.preferredWidth = 14;

            // Filename
            TextMeshProUGUI nameText = CreateLabel(btnObj.transform, "FileName", fileName, 13, TextPrimary);
            nameText.overflowMode = TextOverflowModes.Ellipsis;
            nameText.enableWordWrapping = false;
            LayoutElement nameLE = nameText.gameObject.AddComponent<LayoutElement>();
            nameLE.flexibleWidth = 1;

            return btn;
        }

        /// <summary>
        /// Highlight/unhighlight a file button.
        /// </summary>
        public void SetFileButtonHighlight(Button btn, bool isSelected)
        {
            if (btn == null) return;

            ColorBlock cb = btn.colors;
            if (isSelected)
            {
                cb.normalColor = FileButtonSelected;
                cb.highlightedColor = FileButtonSelectedHover;
            }
            else
            {
                cb.normalColor = FileButtonNormal;
                cb.highlightedColor = FileButtonHover;
            }
            btn.colors = cb;

            // Update icon
            Transform iconTrans = btn.transform.Find("Icon");
            if (iconTrans != null)
            {
                TextMeshProUGUI icon = iconTrans.GetComponent<TextMeshProUGUI>();
                if (icon != null)
                {
                    icon.text = isSelected ? ">" : ">";
                    icon.color = isSelected ? AccentColor : TextSecondary;
                }
            }

            // Force color update
            Image img = btn.GetComponent<Image>();
            if (img != null)
            {
                img.color = cb.normalColor;
            }
        }
    }
}
