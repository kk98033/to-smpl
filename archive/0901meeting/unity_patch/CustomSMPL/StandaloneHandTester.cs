using UnityEngine;
using System.Collections.Generic;

namespace CustomSMPL
{
    public class StandaloneHandTester : MonoBehaviour
    {
        [Header("Model Settings")]
        public GameObject characterPrefab; // 請在此拖入您的 SMPL 模型 Prefab

        [Header("Debug Info (Read Only)")]
        public int leftFingerCount = 0;
        public int rightFingerCount = 0;

        private GameObject instantiatedCharacter;
        private List<Transform> leftFingers = new List<Transform>();
        private List<Transform> rightFingers = new List<Transform>();

        void Start()
        {
            if (characterPrefab == null)
            {
                Debug.LogError("[HandTester] 請在 Unity 面板中，把您的模型 Prefab 拖到 Character Prefab 欄位裡！");
                return;
            }

            // 動態生成模型
            instantiatedCharacter = Instantiate(characterPrefab, transform.position, Quaternion.identity, this.transform);

            // 改為掃描「剛生成的模型」底下所有的子物件(骨架)
            Transform[] allBones = instantiatedCharacter.GetComponentsInChildren<Transform>();

            foreach (Transform t in allBones)
            {
                string nameLower = t.name.ToLower();

                // 初步過濾是否有手指的關鍵字
                if (nameLower.Contains("index") || nameLower.Contains("middle") ||
                    nameLower.Contains("ring") || nameLower.Contains("pinky") || nameLower.Contains("thumb"))
                {
                    // 分辨是左手還是右手
                    if (nameLower.StartsWith("l") || nameLower.Contains("left"))
                    {
                        leftFingers.Add(t);
                    }
                    else if (nameLower.StartsWith("r") || nameLower.Contains("right"))
                    {
                        rightFingers.Add(t);
                    }
                }
            }

            leftFingerCount = leftFingers.Count;
            rightFingerCount = rightFingers.Count;

            Debug.Log($"[HandTester] 掃描完成！找到 {leftFingerCount} 個左手關節，以及 {rightFingerCount} 個右手關節。");

            if (leftFingerCount == 0 && rightFingerCount == 0)
            {
                Debug.LogError("[HandTester] 警告：在目前物件底下完全沒有找到任何手指骨骼！請確認模型本身是否包含手指陣列！");
            }
        }

        void Update()
        {
            // 利用 Sin 波形讓數值在 0 ~ 1 之間平滑來回跳動 (模擬呼吸頻率)
            float pulse = (Mathf.Sin(Time.time * 5f) + 1f) / 2f;

            // 將數值放大到 90 度，代表手指極限彎曲的角度
            float bendAngle = pulse * 90f;

            // 讓左手所有手指彎曲
            foreach (Transform bone in leftFingers)
            {
                // 在 SMPL 模型中，Z 軸通常代表主要的彎曲方向 (這取決於模型的匯出設定，如果方向不對，可嘗試改為 X 或 Y)
                bone.localRotation = Quaternion.Euler(0, 0, bendAngle);
            }

            // 讓右手所有手指彎曲 (鏡像方向，所以通常是負的)
            foreach (Transform bone in rightFingers)
            {
                bone.localRotation = Quaternion.Euler(0, 0, -bendAngle);
            }
        }
    }
}
