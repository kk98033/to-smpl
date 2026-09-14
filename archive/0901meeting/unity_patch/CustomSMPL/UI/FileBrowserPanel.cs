using UnityEngine;
using UnityEngine.UI;
using System.IO;
using System.Collections.Generic;
using System.Linq;

namespace CustomSMPL.UI
{
    /// <summary>
    /// File browser panel: scans a folder for .json files and creates clickable buttons.
    /// </summary>
    public class FileBrowserPanel : MonoBehaviour
    {
        private RuntimeUIBuilder uiBuilder;
        private CustomAnimationPlayer player;

        private string currentFolderPath = "";
        private List<string> jsonFiles = new List<string>();
        private List<Button> fileButtons = new List<Button>();
        private Button currentSelectedButton = null;

        public void Initialize(RuntimeUIBuilder builder, CustomAnimationPlayer animPlayer)
        {
            uiBuilder = builder;
            player = animPlayer;

            // Default path: Animations folder next to EXE
            string defaultPath = Path.Combine(Application.dataPath, "..", "Animations");
            defaultPath = Path.GetFullPath(defaultPath);

            // Create default folder if not exists
            if (!Directory.Exists(defaultPath))
            {
                try
                {
                    Directory.CreateDirectory(defaultPath);
                    UnityEngine.Debug.Log($"[FileBrowser] Created default folder: {defaultPath}");
                }
                catch (System.Exception e)
                {
                    UnityEngine.Debug.LogWarning($"[FileBrowser] Cannot create default folder: {e.Message}");
                }
            }

            uiBuilder.FolderPathInput.text = defaultPath;

            // Bind events
            uiBuilder.FolderPathInput.onEndEdit.AddListener(OnFolderPathChanged);
            uiBuilder.RefreshButton.onClick.AddListener(OnRefreshClicked);

            // Initial scan
            SetFolder(defaultPath);
        }

        void OnRefreshClicked()
        {
            UnityEngine.Debug.Log("[FileBrowser] Refresh button clicked");
            // Re-read from input field in case user typed a new path
            string inputPath = uiBuilder.FolderPathInput.text.Trim().Trim('"');
            if (!string.IsNullOrEmpty(inputPath))
            {
                currentFolderPath = inputPath;
            }
            RefreshFileList();
        }

        /// <summary>
        /// Set folder path and scan files.
        /// </summary>
        public void SetFolder(string folderPath)
        {
            if (string.IsNullOrEmpty(folderPath))
            {
                UpdateStatus("Warning: path is empty");
                return;
            }

            // Normalize path
            folderPath = folderPath.Trim().Trim('"');

            if (!Directory.Exists(folderPath))
            {
                UpdateStatus($"Folder not found: {Path.GetFileName(folderPath)}");
                return;
            }

            currentFolderPath = folderPath;
            uiBuilder.FolderPathInput.text = folderPath;
            RefreshFileList();
        }

        /// <summary>
        /// Re-scan current folder for .json files.
        /// </summary>
        public void RefreshFileList()
        {
            if (string.IsNullOrEmpty(currentFolderPath) || !Directory.Exists(currentFolderPath))
            {
                UpdateStatus("Invalid folder path");
                return;
            }

            // Clear old buttons
            ClearFileList();

            // Scan for .json files
            try
            {
                string[] files = Directory.GetFiles(currentFolderPath, "*.json");
                jsonFiles = files.OrderBy(f => f).ToList();
            }
            catch (System.Exception e)
            {
                UpdateStatus($"Scan error: {e.Message}");
                return;
            }

            if (jsonFiles.Count == 0)
            {
                UpdateStatus("No .json files found in folder");
                return;
            }

            // Create file buttons
            foreach (string filePath in jsonFiles)
            {
                string fileName = Path.GetFileName(filePath);
                string capturedPath = filePath; // Capture for closure

                Button btn = uiBuilder.CreateFileButton(uiBuilder.FileListContent, fileName);
                btn.onClick.AddListener(() => OnFileSelected(capturedPath, btn));
                fileButtons.Add(btn);
            }

            UpdateStatus($"Found {jsonFiles.Count} JSON file(s)");
            UnityEngine.Debug.Log($"[FileBrowser] Scanned: {currentFolderPath}, {jsonFiles.Count} files found");
        }

        void OnFileSelected(string filePath, Button clickedButton)
        {
            UnityEngine.Debug.Log($"[FileBrowser] File selected: {filePath}");

            // Update highlight
            if (currentSelectedButton != null)
            {
                uiBuilder.SetFileButtonHighlight(currentSelectedButton, false);
            }
            currentSelectedButton = clickedButton;
            uiBuilder.SetFileButtonHighlight(clickedButton, true);

            // Load and play
            string fileName = Path.GetFileName(filePath);
            UpdateStatus($"Loading: {fileName}...");

            bool success = player.LoadAndPlay(filePath);

            if (success)
            {
                UpdateStatus($"Playing: {fileName}");
            }
            else
            {
                UpdateStatus($"Load failed: {fileName}");
                uiBuilder.SetFileButtonHighlight(clickedButton, false);
                currentSelectedButton = null;
            }
        }

        void OnFolderPathChanged(string newPath)
        {
            UnityEngine.Debug.Log($"[FileBrowser] Path changed: {newPath}");
            SetFolder(newPath);
        }

        void ClearFileList()
        {
            foreach (Button btn in fileButtons)
            {
                if (btn != null)
                    Destroy(btn.gameObject);
            }
            fileButtons.Clear();
            currentSelectedButton = null;
        }

        void UpdateStatus(string message)
        {
            if (uiBuilder != null && uiBuilder.StatusLabel != null)
            {
                uiBuilder.StatusLabel.text = message;
            }
            UnityEngine.Debug.Log($"[FileBrowser] Status: {message}");
        }
    }
}
