using UnityEngine;
using System.IO;
using System.Collections.Generic;
using ThirdParty.SimpleJSON;
using Utilities;
using SMPLModel;

namespace CustomSMPL
{
    public class CustomAnimationPlayer : MonoBehaviour
    {
        [Header("Settings")]
        [Tooltip("請將您的角色 Prefab (例如 SMPLH Character Male New) 拖拉至此")]
        public GameObject characterPrefab;

        [Tooltip("JSON 動畫檔的絕對路徑（留空則由 UI 控制）")]
        public string jsonFilePath = "";

        [Header("Playback Options")]
        public float playbackSpeed = 1.0f;
        public int targetFPS = 30;

        [Header("Debug")]
        [Tooltip("打勾後角色不會位移，定在原地方便觀察")]
        public bool freezePosition = false;

        [Tooltip("打勾後無視 JSON 手指資料，強制握拳張開")]
        public bool forceClenchFist = false;

        // === 公開唯讀屬性（供 UI 讀取） ===
        public int CurrentFrame { get; private set; }
        public int TotalFrames => totalFrames;
        public bool IsAnimPlaying => isPlaying;
        public bool IsPaused => isPaused;
        public int NumJoints => numJoints;
        public bool IsSMPLX => isSMPLX;
        public int CurrentTargetFPS => targetFPS;
        public string CurrentFilePath { get; private set; } = "";

        // Internal State
        private GameObject instantiatedCharacter;
        private SkinnedMeshRenderer skinnedMeshRenderer;
        private Transform[] bones;       // 跟原廠一模一樣，用 SkinnedMeshRenderer.bones
        private Transform pelvisBone;

        // Animation Data
        private int totalFrames = 0;
        private int numJoints = 0;
        private int handIndexOffset = 0; // SMPL-H:0, SMPL-X:3 (因為 22=jaw, 23=leye, 24=reye)
        private bool isSMPLX = false;
        private Vector3[] translations;
        private Quaternion[,] poses;

        private float currentTime = 0f;
        private bool isPlaying = false;
        private bool isPaused = false;

        // === 向後相容：如果 Inspector 有填路徑，Start 時自動播放 ===
        void Start()
        {
            if (characterPrefab == null)
            {
                UnityEngine.Debug.LogError("[CustomPlayer] 錯誤：沒有設定 Character Prefab！");
                return;
            }

            // 如果有預設路徑，自動播放（向後相容）
            if (!string.IsNullOrEmpty(jsonFilePath) && File.Exists(jsonFilePath))
            {
                LoadAndPlay(jsonFilePath);
            }
            else if (!string.IsNullOrEmpty(jsonFilePath))
            {
                UnityEngine.Debug.LogWarning($"[CustomPlayer] Inspector 指定的 JSON 不存在 ({jsonFilePath})，等待 UI 操作。");
            }
            else
            {
                UnityEngine.Debug.Log("[CustomPlayer] 未指定 JSON 路徑，等待 UI 操作。");
            }
        }

        // ===================================================================
        //  公開 API — 供 UI 或外部腳本呼叫
        // ===================================================================

        /// <summary>
        /// 載入指定 JSON 檔案並開始播放動畫。
        /// 如果目前有動畫在播放，會先停止並清理。
        /// </summary>
        public bool LoadAndPlay(string jsonPath)
        {
            if (characterPrefab == null)
            {
                UnityEngine.Debug.LogError("[CustomPlayer] 錯誤：沒有設定 Character Prefab！");
                return false;
            }
            if (string.IsNullOrEmpty(jsonPath) || !File.Exists(jsonPath))
            {
                UnityEngine.Debug.LogError($"[CustomPlayer] 錯誤：找不到 JSON 檔案 ({jsonPath})");
                return false;
            }

            // 先清理舊的
            StopAndCleanup();

            CurrentFilePath = jsonPath;

            UnityEngine.Debug.Log("[CustomPlayer] 1/4 開始建立角色...");
            instantiatedCharacter = Instantiate(characterPrefab, transform.position, Quaternion.identity, this.transform);

            // 關閉舊腳本
            var oldPoser = instantiatedCharacter.GetComponentInChildren<CharacterPoser>();
            if (oldPoser != null) oldPoser.enabled = false;
            var oldComponent = instantiatedCharacter.GetComponentInChildren<CharacterComponent>();
            if (oldComponent != null) oldComponent.enabled = false;

            UnityEngine.Debug.Log("[CustomPlayer] 2/4 取得骨架結構 (使用 SkinnedMeshRenderer.bones，跟原廠一模一樣)...");
            SetupBones();

            if (bones == null)
            {
                UnityEngine.Debug.LogError("[CustomPlayer] SetupBones 失敗，取消播放。");
                StopAndCleanup();
                return false;
            }

            UnityEngine.Debug.Log("[CustomPlayer] 3/4 解析 JSON 動畫資料...");
            if (!LoadJsonData(jsonPath))
            {
                StopAndCleanup();
                return false;
            }

            UnityEngine.Debug.Log("[CustomPlayer] 4/4 驗證骨骼映射...");
            VerifyMapping();

            UnityEngine.Debug.Log($"[CustomPlayer] 準備完成！{totalFrames} 幀, {numJoints} 關節, {bones.Length} 骨骼, 開始播放！");
            currentTime = 0f;
            isPaused = false;
            isPlaying = true;
            return true;
        }

        /// <summary>
        /// 停止當前動畫並銷毀角色。
        /// </summary>
        public void StopAndCleanup()
        {
            isPlaying = false;
            isPaused = false;
            currentTime = 0f;
            CurrentFrame = 0;
            totalFrames = 0;
            numJoints = 0;

            if (instantiatedCharacter != null)
            {
                Destroy(instantiatedCharacter);
                instantiatedCharacter = null;
            }

            bones = null;
            pelvisBone = null;
            skinnedMeshRenderer = null;
            translations = null;
            poses = null;
        }

        /// <summary>
        /// 暫停或恢復播放。
        /// </summary>
        public void SetPaused(bool paused)
        {
            isPaused = paused;
        }

        /// <summary>
        /// 切換暫停狀態。
        /// </summary>
        public void TogglePause()
        {
            isPaused = !isPaused;
        }

        /// <summary>
        /// 動態設定播放速度。
        /// </summary>
        public void SetPlaybackSpeed(float speed)
        {
            playbackSpeed = Mathf.Clamp(speed, 0.1f, 5.0f);
        }

        /// <summary>
        /// 尋求到特定的播放進度百分比 (0 到 1)。
        /// </summary>
        public void ScrubToProgress(float progress)
        {
            if (totalFrames == 0 || bones == null) return;
            progress = Mathf.Clamp01(progress);

            float totalDuration = (float)totalFrames / targetFPS;
            currentTime = progress * totalDuration;

            CurrentFrame = Mathf.FloorToInt(currentTime * targetFPS);
            CurrentFrame = Mathf.Clamp(CurrentFrame, 0, totalFrames - 1);

            ApplyFrame(CurrentFrame);
        }

        // ===================================================================
        //  內部邏輯
        // ===================================================================

        void SetupBones()
        {
            skinnedMeshRenderer = instantiatedCharacter.GetComponentInChildren<SkinnedMeshRenderer>();
            if (skinnedMeshRenderer == null)
            {
                UnityEngine.Debug.LogError("[CustomPlayer] 找不到 SkinnedMeshRenderer！");
                return;
            }

            bones = skinnedMeshRenderer.bones;
            UnityEngine.Debug.Log($"[CustomPlayer] SkinnedMeshRenderer 有 {bones.Length} 根骨骼：");

            for (int i = 0; i < bones.Length; i++)
            {
                string boneName = bones[i].name;
                bool inDict = Bones.NameToJointIndex.TryGetValue(boneName, out int jointIdx);
                UnityEngine.Debug.Log($"  bones[{i}] = '{boneName}' → jointIndex = {(inDict ? jointIdx.ToString() : "NOT FOUND")}");

                if (boneName == Bones.Pelvis)
                {
                    pelvisBone = bones[i];
                }
            }
        }

        bool LoadJsonData(string filePath)
        {
            string jsonString = File.ReadAllText(filePath);
            JSONNode jsonNode = JSON.Parse(jsonString);

            JSONNode transNode = jsonNode["trans"];
            JSONNode posesNode = jsonNode["poses"];

            if (transNode == null || posesNode == null)
            {
                if (jsonNode["2"] != null || jsonNode["3"] != null)
                {
                    UnityEngine.Debug.LogError("[CustomPlayer] 載入失敗：此檔案為 Human3.6M 格式，請使用選單中的 H36M Player 播放器進行播放！");
                }
                else
                {
                    UnityEngine.Debug.LogError("[CustomPlayer] 載入失敗：無效的 SMPL JSON 檔案格式（缺少 'trans' 或 'poses' 欄位）。");
                }
                return false;
            }

            totalFrames = transNode.Count;
            if (totalFrames == 0)
            {
                UnityEngine.Debug.LogError("[CustomPlayer] 載入失敗：動畫總幀數為 0。");
                return false;
            }

            numJoints = posesNode[0].Count;

            // 自動偵測 SMPL-H (52) vs SMPL-X (55)
            if (numJoints == 55)
            {
                isSMPLX = true;
                handIndexOffset = 3;  // SMPL-X 的 22=jaw, 23=leye, 24=reye，手指從 25 開始
                UnityEngine.Debug.LogWarning("[CustomPlayer] 🔍 偵測到 SMPL-X 格式 (55關節)！手指索引偏移 +3");
            }
            else
            {
                isSMPLX = false;
                handIndexOffset = 0;
                UnityEngine.Debug.Log($"[CustomPlayer] 偵測到 SMPL-H 格式 ({numJoints}關節)");
            }

            // 讀取 FPS (如果 JSON 有提供)
            if (jsonNode["fps"] != null)
            {
                targetFPS = jsonNode["fps"].AsInt;
                UnityEngine.Debug.Log($"[CustomPlayer] 使用 JSON 內建 FPS: {targetFPS}");
            }

            translations = new Vector3[totalFrames];
            poses = new Quaternion[totalFrames, numJoints];

            for (int f = 0; f < totalFrames; f++)
            {
                Vector3 tMaya = new Vector3(transNode[f][0], transNode[f][1], transNode[f][2]);
                translations[f] = tMaya.ConvertTranslationFromMayaToUnity();

                for (int j = 0; j < numJoints; j++)
                {
                    // scipy as_quat() 輸出 (x,y,z,w) → Unity Quaternion(x,y,z,w)
                    float x = posesNode[f][j][0];
                    float y = posesNode[f][j][1];
                    float z = posesNode[f][j][2];
                    float w = posesNode[f][j][3];

                    // ToLeftHanded: 跟原廠 CharacterPoser 一模一樣的轉換
                    Quaternion raw = new Quaternion(x, y, z, w);
                    poses[f, j] = raw.ToLeftHanded();
                }
            }

            // 偵測手部資料
            bool hasHandMotion = false;
            bool hasVariation = false;

            for (int j = 22; j < numJoints; j++)
            {
                Quaternion q0 = poses[0, j];
                if (Mathf.Abs(q0.x) > 0.001f || Mathf.Abs(q0.y) > 0.001f || Mathf.Abs(q0.z) > 0.001f)
                {
                    hasHandMotion = true;
                }
                for (int f = 1; f < totalFrames; f++)
                {
                    Quaternion qf = poses[f, j];
                    if (Mathf.Abs(qf.x - q0.x) > 0.0001f)
                    {
                        hasVariation = true;
                        break;
                    }
                }
                if (hasHandMotion && hasVariation) break;
            }

            UnityEngine.Debug.Log(hasHandMotion ? "✅ 手指有旋轉數據" : "❌ 手指旋轉全為零");
            UnityEngine.Debug.Log(hasVariation ? "✅ 手指有逐幀動畫" : "⚠️ 手指為靜態姿勢");
            UnityEngine.Debug.Log($"[CustomPlayer] JSON 共 {totalFrames} 幀, {numJoints} 關節。");
            return true;
        }

        void VerifyMapping()
        {
            int matchedCount = 0;
            int handMatchedCount = 0;

            foreach (Transform bone in bones)
            {
                if (Bones.NameToJointIndex.TryGetValue(bone.name, out int jointIdx))
                {
                    matchedCount++;
                    if (jointIdx >= 22) handMatchedCount++;

                    if (jointIdx >= numJoints)
                    {
                        UnityEngine.Debug.LogWarning($"⚠️ 骨骼 '{bone.name}' 映射到 jointIndex={jointIdx}，但 JSON 只有 {numJoints} 個關節！");
                    }
                }
            }

            UnityEngine.Debug.Log($"[CustomPlayer] 骨骼映射結果：{matchedCount}/{bones.Length} 匹配成功，其中 {handMatchedCount} 個是手指骨骼。");
        }

        void Update()
        {
            if (!isPlaying || isPaused || totalFrames == 0 || bones == null) return;

            currentTime += Time.deltaTime * playbackSpeed;
            float totalDuration = (float)totalFrames / targetFPS;
            if (currentTime >= totalDuration) currentTime %= totalDuration;

            CurrentFrame = Mathf.FloorToInt(currentTime * targetFPS);
            CurrentFrame = Mathf.Clamp(CurrentFrame, 0, totalFrames - 1);
            ApplyFrame(CurrentFrame);
        }

        bool IsThumb(int jointIndex)
        {
            return (jointIndex >= 34 && jointIndex <= 36) || (jointIndex >= 49 && jointIndex <= 51);
        }

        void ApplyFrame(int frame)
        {
            // Debug 握拳
            float pulse = (Mathf.Sin(Time.time * 3f) + 1f) / 2f;
            float bendAngle = pulse * 80f;

            // === 完全模仿原廠 CharacterPoser.UpdatePoses() 的邏輯 ===
            for (int boneIndex = 0; boneIndex < bones.Length; boneIndex++)
            {
                Transform bone = bones[boneIndex];
                string boneName = bone.name;

                if (!Bones.NameToJointIndex.TryGetValue(boneName, out int poseIndex)) continue;

                // === 核心修正：SMPL-X 格式的手指索引偏移 ===
                // Bones.cs 裡 hand joints 映射到 22-51 (SMPL-H 標準)
                // 但 SMPL-X 的 JSON 裡 22=jaw, 23=leye, 24=reye，手指從 25 開始
                // 所以要把 poseIndex 22 → 25, 23 → 26, ... (加 3)
                int actualJsonIndex = poseIndex;
                if (poseIndex >= 22)
                {
                    actualJsonIndex = poseIndex + handIndexOffset;
                }

                if (actualJsonIndex >= numJoints) continue;

                // 先清零
                bone.localEulerAngles = Vector3.zero;

                // Pelvis 特殊處理
                if (boneName == Bones.Pelvis)
                {
                    bone.Rotate(-90, 0, 0, Space.Self);
                    if (!freezePosition)
                    {
                        bone.localPosition = translations[frame];
                    }
                }

                // 判斷是否是手指
                bool isHandJoint = (poseIndex >= 22);

                if (isHandJoint && forceClenchFist)
                {
                    // Debug 握拳模式
                    bool isLeft = (poseIndex <= 36);
                    if (IsThumb(poseIndex))
                    {
                        bone.localRotation = Quaternion.Euler(0, bendAngle * (isLeft ? -1f : 1f), 0);
                    }
                    else
                    {
                        bone.localRotation = Quaternion.Euler(0, 0, bendAngle * (isLeft ? 1f : -1f));
                    }
                }
                else
                {
                    // 套用正確偏移後的 pose 數據
                    bone.localRotation = bone.localRotation * poses[frame, actualJsonIndex];
                }
            }
        }
    }
}
