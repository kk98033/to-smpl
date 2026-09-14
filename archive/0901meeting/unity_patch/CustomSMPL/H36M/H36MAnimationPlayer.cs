using UnityEngine;
using System.IO;
using System.Collections.Generic;
using ThirdParty.SimpleJSON;

namespace CustomSMPL.H36M
{
    public class H36MAnimationPlayer : MonoBehaviour
    {
        [Header("Settings")]
        [Tooltip("Human3.6M JSON 檔案的絕對或相對路徑")]
        public string jsonFilePath = "Assets/hu36_dataset/Human36M_subject1_joint_3d.json";

        [Header("Playback Options")]
        public float playbackSpeed = 1.0f;
        public int targetFPS = 50; // H36M 預設取樣為 50 FPS

        // === 公開唯讀屬性（供 UI 讀取） ===
        public int CurrentFrame { get; private set; }
        public int TotalFrames => activeSequence != null ? activeSequence.frames.Count : 0;
        public bool IsLoaded => isLoaded;
        public bool IsLoading => isLoading;
        public bool IsAnimPlaying => isPlaying;
        public bool IsPaused => isPaused;
        public string CurrentActionKey => currentActionKey;
        public string CurrentSubactionKey => currentSubactionKey;

        // Dataset representation
        public struct H36MFrame
        {
            public Vector3[] joints; // 17 關節
        }

        public class H36MSequence
        {
            public List<H36MFrame> frames = new List<H36MFrame>();
        }

        // Action ID mapping
        public static readonly Dictionary<string, string> ActionNames = new Dictionary<string, string>()
        {
            { "2", "Directions" },
            { "3", "Discussion" },
            { "4", "Eating" },
            { "5", "Greeting" },
            { "6", "Phoning" },
            { "7", "Posing" },
            { "8", "Purchases" },
            { "9", "Sitting" },
            { "10", "SittingDown" },
            { "11", "Smoking" },
            { "12", "Photo" },
            { "13", "Waiting" },
            { "14", "Walking" },
            { "15", "WalkDog" },
            { "16", "WalkTogether" }
        };

        public static string GetActionName(string key)
        {
            string name;
            if (ActionNames.TryGetValue(key, out name)) return name;
            return key;
        }

        // Bone connection structure
        private struct BoneConnection
        {
            public int jointA;
            public int jointB;
            public BoneConnection(int a, int b) { jointA = a; jointB = b; }
        }

        private static readonly BoneConnection[] BonesConnections = new BoneConnection[]
        {
            // Spine & Head
            new BoneConnection(0, 7),   // Pelvis to Spine
            new BoneConnection(7, 8),   // Spine to Neck
            new BoneConnection(8, 9),   // Neck to Head
            new BoneConnection(9, 10),  // Head to Head Top
            
            // Left Leg
            new BoneConnection(0, 4),   // Pelvis to Left Hip
            new BoneConnection(4, 5),   // Left Hip to Left Knee
            new BoneConnection(5, 6),   // Left Knee to Left Ankle
            
            // Right Leg
            new BoneConnection(0, 1),   // Pelvis to Right Hip
            new BoneConnection(1, 2),   // Right Hip to Right Knee
            new BoneConnection(2, 3),   // Right Knee to Right Ankle
            
            // Left Arm
            new BoneConnection(8, 11),  // Neck to Left Shoulder
            new BoneConnection(11, 12), // Left Shoulder to Left Elbow
            new BoneConnection(12, 13), // Left Elbow to Left Wrist
            
            // Right Arm
            new BoneConnection(8, 14),  // Neck to Right Shoulder
            new BoneConnection(14, 15), // Right Shoulder to Right Elbow
            new BoneConnection(15, 16)  // Right Elbow to Right Wrist
        };

        // Internal Dataset State
        private Dictionary<string, Dictionary<string, H36MSequence>> dataset;
        private H36MSequence activeSequence = null;
        private string currentActionKey = "";
        private string currentSubactionKey = "";

        // UI & Playback state
        private bool isLoaded = false;
        private bool isLoading = false;
        private bool isPlaying = false;
        private bool isPaused = false;
        private float currentTime = 0f;

        // Background loading flags
        private bool loadFinished = false;
        private bool loadSuccess = false;

        // Visual joints
        private GameObject[] jointSpheres;
        private LineRenderer[] boneLines;

        void Start()
        {
            // 自動偵測路徑並讀取
            string absolutePath = Path.Combine(Application.dataPath, "..", jsonFilePath);
            absolutePath = Path.GetFullPath(absolutePath);

            if (File.Exists(absolutePath))
            {
                StartLoadDataset(absolutePath);
            }
            else if (File.Exists(jsonFilePath))
            {
                StartLoadDataset(jsonFilePath);
            }
            else
            {
                UnityEngine.Debug.LogWarning($"[H36MPlayer] 找不到預設路徑的 JSON 檔案 ({jsonFilePath})，請於 UI 輸入路徑。");
            }
        }

        public void StartLoadDataset(string filePath)
        {
            if (isLoading) return;
            
            jsonFilePath = filePath;
            isLoading = true;
            isLoaded = false;
            loadFinished = false;
            loadSuccess = false;

            UnityEngine.Debug.Log($"[H36MPlayer] 開始異步解析 JSON 數據 ({filePath})...");

            System.Threading.Tasks.Task.Run(() =>
            {
                try
                {
                    string jsonString = File.ReadAllText(filePath);
                    JSONNode root = JSON.Parse(jsonString);

                    var newDataset = new Dictionary<string, Dictionary<string, H36MSequence>>();

                    foreach (KeyValuePair<string, JSONNode> actionPair in root.AsObject)
                    {
                        string actKey = actionPair.Key;
                        JSONNode subactionsNode = actionPair.Value;

                        var subactionDict = new Dictionary<string, H36MSequence>();

                        foreach (KeyValuePair<string, JSONNode> subactionPair in subactionsNode.AsObject)
                        {
                            string subactKey = subactionPair.Key;
                            JSONNode framesNode = subactionPair.Value;

                            var seq = new H36MSequence();

                            // 取得所有 Frame 鍵並排序
                            List<string> frameKeys = new List<string>();
                            foreach (KeyValuePair<string, JSONNode> framePair in framesNode.AsObject)
                            {
                                frameKeys.Add(framePair.Key);
                            }
                            frameKeys.Sort((a, b) => int.Parse(a).CompareTo(int.Parse(b)));

                            foreach (string fk in frameKeys)
                            {
                                JSONNode jointsNode = framesNode[fk];
                                H36MFrame frame = new H36MFrame();
                                frame.joints = new Vector3[17];

                                for (int j = 0; j < 17; j++)
                                {
                                    float x = jointsNode[j][0].AsFloat;
                                    float y = jointsNode[j][1].AsFloat;
                                    float z = jointsNode[j][2].AsFloat;

                                    // H36M (Z-up, mm) -> Unity (Y-up, m)
                                    // Unity X = X/1000, Y = Z/1000, Z = Y/1000
                                    frame.joints[j] = new Vector3(x / 1000f, z / 1000f, y / 1000f);
                                }

                                seq.frames.Add(frame);
                            }

                            subactionDict.Add(subactKey, seq);
                        }

                        newDataset.Add(actKey, subactionDict);
                    }

                    lock (this)
                    {
                        dataset = newDataset;
                        loadSuccess = true;
                    }
                }
                catch (System.Exception e)
                {
                    UnityEngine.Debug.LogError($"[H36MPlayer] 異步載入解析失敗: {e.Message}");
                    loadSuccess = false;
                }
                finally
                {
                    loadFinished = true;
                }
            });
        }

        void Update()
        {
            // 檢查異步載入是否完成
            if (loadFinished)
            {
                loadFinished = false;
                isLoading = false;
                if (loadSuccess)
                {
                    isLoaded = true;
                    UnityEngine.Debug.Log("[H36MPlayer] 資料庫載入完成！建立骨架...");
                    CreateSkeleton();
                    
                    // 預設播放第一個動作
                    PlayDefault();
                }
                else
                {
                    UnityEngine.Debug.LogError("[H36MPlayer] 資料庫載入失敗，請確認檔案格式及路徑！");
                }
            }

            if (!isPlaying || isPaused || activeSequence == null || jointSpheres == null) return;

            // 更新播放時間
            currentTime += Time.deltaTime * playbackSpeed;
            float totalDuration = (float)activeSequence.frames.Count / targetFPS;
            if (currentTime >= totalDuration)
            {
                currentTime %= totalDuration;
            }

            CurrentFrame = Mathf.FloorToInt(currentTime * targetFPS);
            CurrentFrame = Mathf.Clamp(CurrentFrame, 0, activeSequence.frames.Count - 1);

            ApplyFrame(CurrentFrame);
        }

        private void PlayDefault()
        {
            if (dataset == null || dataset.Count == 0) return;

            // 尋找第一個動作與子動作鍵
            string firstAction = "";
            foreach (var key in dataset.Keys)
            {
                firstAction = key;
                break;
            }

            if (!string.IsNullOrEmpty(firstAction))
            {
                PlayAction(firstAction, "1");
            }
        }

        /// <summary>
        /// 播放特定動作與子動作
        /// </summary>
        public bool PlayAction(string actionKey, string subactionKey)
        {
            if (!isLoaded || dataset == null) return false;

            if (!dataset.ContainsKey(actionKey) || !dataset[actionKey].ContainsKey(subactionKey))
            {
                UnityEngine.Debug.LogError($"[H36MPlayer] 找不到動作組合: Action {actionKey}, Subaction {subactionKey}");
                return false;
            }

            activeSequence = dataset[actionKey][subactionKey];
            currentActionKey = actionKey;
            currentSubactionKey = subactionKey;

            currentTime = 0f;
            CurrentFrame = 0;
            isPlaying = true;
            isPaused = false;

            UnityEngine.Debug.Log($"[H36MPlayer] 切換動作: Action '{GetActionName(actionKey)}', Subaction {subactionKey} ({activeSequence.frames.Count} 幀)");

            ApplyFrame(0);
            return true;
        }

        /// <summary>
        /// 暫停/恢復播放
        /// </summary>
        public void SetPaused(bool paused)
        {
            isPaused = paused;
        }

        public void TogglePause()
        {
            isPaused = !isPaused;
        }

        /// <summary>
        /// 停止播放並清除畫布
        /// </summary>
        public void StopAndCleanup()
        {
            isPlaying = false;
            isPaused = false;
            currentTime = 0f;
            CurrentFrame = 0;
            activeSequence = null;
            currentActionKey = "";
            currentSubactionKey = "";
            
            // 將所有關節設回原點或隱藏
            if (jointSpheres != null)
            {
                foreach (var sphere in jointSpheres)
                {
                    if (sphere != null) sphere.transform.localPosition = Vector3.zero;
                }
            }
            if (boneLines != null)
            {
                foreach (var line in boneLines)
                {
                    if (line != null)
                    {
                        line.SetPosition(0, Vector3.zero);
                        line.SetPosition(1, Vector3.zero);
                    }
                }
            }
        }

        /// <summary>
        /// 設定播放速度
        /// </summary>
        public void SetPlaybackSpeed(float speed)
        {
            playbackSpeed = Mathf.Clamp(speed, 0.1f, 5.0f);
        }

        /// <summary>
        /// 尋求特定的播放進度 (0 到 1)
        /// </summary>
        public void ScrubToProgress(float progress)
        {
            if (activeSequence == null || jointSpheres == null) return;
            progress = Mathf.Clamp01(progress);

            float totalDuration = (float)activeSequence.frames.Count / targetFPS;
            currentTime = progress * totalDuration;

            CurrentFrame = Mathf.FloorToInt(currentTime * targetFPS);
            CurrentFrame = Mathf.Clamp(CurrentFrame, 0, activeSequence.frames.Count - 1);

            ApplyFrame(CurrentFrame);
        }

        private void ApplyFrame(int frameIndex)
        {
            if (activeSequence == null || jointSpheres == null || frameIndex >= activeSequence.frames.Count) return;

            H36MFrame frame = activeSequence.frames[frameIndex];

            // 1. 更新關節節點的位置
            for (int i = 0; i < 17; i++)
            {
                if (jointSpheres[i] != null)
                {
                    jointSpheres[i].transform.localPosition = frame.joints[i];
                }
            }

            // 2. 更新骨骼連接線段位置
            for (int i = 0; i < BonesConnections.Length; i++)
            {
                var conn = BonesConnections[i];
                if (boneLines[i] != null && jointSpheres[conn.jointA] != null && jointSpheres[conn.jointB] != null)
                {
                    boneLines[i].SetPosition(0, jointSpheres[conn.jointA].transform.position);
                    boneLines[i].SetPosition(1, jointSpheres[conn.jointB].transform.position);
                }
            }
        }

        private void CreateSkeleton()
        {
            CleanupSkeleton();

            // 建立關節球體
            jointSpheres = new GameObject[17];
            for (int i = 0; i < 17; i++)
            {
                GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                sphere.name = $"H36M_Joint_{i}";
                sphere.transform.SetParent(this.transform, false);
                sphere.transform.localScale = Vector3.one * 0.05f; // 5 公分大小

                // 移除碰撞體
                Collider c = sphere.GetComponent<Collider>();
                if (c != null) Destroy(c);

                // 給予高彩度的亮青色
                Renderer r = sphere.GetComponent<Renderer>();
                if (r != null)
                {
                    r.material = new Material(Shader.Find("Standard"));
                    r.material.color = Color.cyan;
                }

                jointSpheres[i] = sphere;
            }

            // 建立骨骼 LineRenderers
            boneLines = new LineRenderer[BonesConnections.Length];
            for (int i = 0; i < BonesConnections.Length; i++)
            {
                GameObject lineObj = new GameObject($"H36M_Bone_{i}");
                lineObj.transform.SetParent(this.transform, false);

                LineRenderer lr = lineObj.AddComponent<LineRenderer>();
                lr.positionCount = 2;
                lr.startWidth = 0.02f; // 2 公分粗度
                lr.endWidth = 0.02f;

                // 使用 Sprites/Default 著色器 (Built-in 與 URP 皆相容)
                lr.material = new Material(Shader.Find("Sprites/Default"));
                lr.startColor = Color.green;
                lr.endColor = Color.green;

                boneLines[i] = lr;
            }
        }

        private void CleanupSkeleton()
        {
            if (jointSpheres != null)
            {
                for (int i = 0; i < jointSpheres.Length; i++)
                {
                    if (jointSpheres[i] != null) Destroy(jointSpheres[i]);
                }
                jointSpheres = null;
            }
            if (boneLines != null)
            {
                for (int i = 0; i < boneLines.Length; i++)
                {
                    if (boneLines[i] != null) Destroy(boneLines[i].gameObject);
                }
                boneLines = null;
            }
        }

        private void OnDestroy()
        {
            CleanupSkeleton();
        }
    }
}
