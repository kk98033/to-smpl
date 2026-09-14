using UnityEngine;
using System.IO;
using System.Collections.Generic;
using ThirdParty.SimpleJSON;
using SMPLModel;
using UnityEngine.Animations.Rigging;

namespace CustomSMPL.Experiment
{
    public class DirectJointPlayer : MonoBehaviour
    {
        [Header("Model Settings")]
        [Tooltip("請將您的角色 Prefab (例如 SMPLH Character Male New) 拖拉至此")]
        public GameObject characterPrefab;

        [Header("Data Settings")]
        [Tooltip("Human3.6M JSON 檔案的路徑")]
        public string jsonFilePath = "Assets/hu36_dataset/Human36M_subject1_joint_3d.json";

        [Header("Playback Options")]
        public float playbackSpeed = 1.0f;
        public int targetFPS = 50;
        
        [Header("Debug")]
        public bool showSkeletonLines = true;
        public bool freezePosition = false;
        [Tooltip("使用 Unity Animation Rigging 的 TwoBoneIK 讓手腕/腳踝追 H36M 關節點。需要 Packages/manifest.json 內有 com.unity.animation.rigging。")]
        public bool useAnimationRiggingIK = true;
        [Tooltip("實驗用：用 H36M 關節段方向直接旋轉 SMPL-H bones。開啟 IK 時建議關閉，避免手算旋轉與 IK 同時拉扯模型。")]
        public bool useManualRotationDrivers = false;
        [Tooltip("如果四肢呈現交叉，代表資料左右與模型左右相反。開啟後會交換 IK 的左右手/左右腳 target。")]
        public bool swapLeftRightIKTargets = true;

        [Header("Coordinate Fix")]
        [Tooltip("用來修正面向問題，如果前後相反可以把 Z 或 X 設為 -1")]
        public Vector3 axisMultiplier = new Vector3(1f, 1f, 1f); 
        [Tooltip("用來旋轉模型的基準面向 (例如 Y 軸設為 180 即可讓模型往後轉)")]
        public Vector3 rootRotationOffset = new Vector3(0, 180, 0);

        // === 公開唯讀屬性（供 UI 讀取，可沿用 H36M_UI） ===
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

        private bool loadFinished = false;
        private bool loadSuccess = false;

        // Visual joints (Optional, to see where the target points are)
        private GameObject[] jointSpheres;
        
        // Character references
        private GameObject instantiatedCharacter;
        private SkinnedMeshRenderer skinnedMeshRenderer;
        
        // Mapping from H36M Joint Index (0~16) to Unity Bone Transform
        private Transform[] mappedBones = new Transform[17];
        private Transform[] allCharacterBones;
        private Vector3[] initialLocalPositions;
        private Quaternion[] initialLocalRotations;
        private Dictionary<Transform, int> boneArrayIndex = new Dictionary<Transform, int>();
        private Quaternion initialCharacterRootRotation;
        private Quaternion bindPelvisBasisWorld = Quaternion.identity;
        private RigBuilder rigBuilder;
        private Rig directJointRig;

        private struct RotationDriver
        {
            public int sourceJoint;
            public int targetJoint;
            public Transform bone;
            public Vector3 bindDirectionWorld;
            public Quaternion bindRotationWorld;
        }

        private readonly List<RotationDriver> rotationDrivers = new List<RotationDriver>();

        private static readonly int[,] H36MRotationPairs = new int[,]
        {
            { 7, 8 },   // spine -> neck
            { 8, 9 },   // neck -> head
            { 4, 5 },   // left hip -> left knee
            { 5, 6 },   // left knee -> left ankle
            { 1, 2 },   // right hip -> right knee
            { 2, 3 },   // right knee -> right ankle
            { 8, 11 },  // neck -> left shoulder
            { 11, 12 }, // left shoulder -> left elbow
            { 12, 13 }, // left elbow -> left wrist
            { 8, 14 },  // neck -> right shoulder
            { 14, 15 }, // right shoulder -> right elbow
            { 15, 16 }  // right elbow -> right wrist
        };

        // Define which H36M joint index corresponds to which SMPL-H bone name
        private string GetSMPLBoneNameForH36MIndex(int index)
        {
            switch (index)
            {
                case 0: return Bones.Pelvis;
                case 1: return Bones.RightHip;
                case 2: return Bones.RightKnee;
                case 3: return Bones.RightAnkle;
                case 4: return Bones.LeftHip;
                case 5: return Bones.LeftKnee;
                case 6: return Bones.LeftAnkle;
                case 7: return Bones.Spine2; // Approx for middle spine
                case 8: return Bones.Neck;
                case 9: return Bones.Head;
                case 10: return null; // Head Top, SMPL usually doesn't have a distinct bone for top of head
                case 11: return Bones.LeftShoulder;
                case 12: return Bones.LeftElbow;
                case 13: return Bones.LeftWrist;
                case 14: return Bones.RightShoulder;
                case 15: return Bones.RightElbow;
                case 16: return Bones.RightWrist;
                default: return null;
            }
        }

        void Start()
        {
            if (characterPrefab == null)
            {
                Debug.LogError("[DirectJointPlayer] 請指派 characterPrefab！");
                return;
            }

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
                Debug.LogWarning($"[DirectJointPlayer] 找不到預設路徑的 JSON 檔案 ({jsonFilePath})");
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

            Debug.Log($"[DirectJointPlayer] 開始異步解析 JSON 數據 ({filePath})...");

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
                                    // 加入 axisMultiplier 來修正前後相反的問題
                                    frame.joints[j] = new Vector3(
                                        (x / 1000f) * axisMultiplier.x, 
                                        (z / 1000f) * axisMultiplier.y, 
                                        (y / 1000f) * axisMultiplier.z
                                    );
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
                    Debug.LogError($"[DirectJointPlayer] 異步載入解析失敗: {e.Message}");
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
            if (loadFinished)
            {
                loadFinished = false;
                isLoading = false;
                if (loadSuccess)
                {
                    isLoaded = true;
                    Debug.Log("[DirectJointPlayer] 資料庫載入完成！建立骨架...");
                    SetupCharacter();
                    PlayDefault();
                }
            }

            if (!isPlaying || isPaused || activeSequence == null || instantiatedCharacter == null) return;

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

        private void SetupCharacter()
        {
            if (instantiatedCharacter != null) Destroy(instantiatedCharacter);

            instantiatedCharacter = Instantiate(characterPrefab, transform.position, Quaternion.Euler(rootRotationOffset), this.transform);
            initialCharacterRootRotation = instantiatedCharacter.transform.rotation;

            // 關閉既有的 IK 或自動 Pose 腳本
            var oldPoser = instantiatedCharacter.GetComponentInChildren<CharacterPoser>();
            if (oldPoser != null) oldPoser.enabled = false;
            var oldComponent = instantiatedCharacter.GetComponentInChildren<CharacterComponent>();
            if (oldComponent != null) oldComponent.enabled = false;

            skinnedMeshRenderer = instantiatedCharacter.GetComponentInChildren<SkinnedMeshRenderer>();
            if (skinnedMeshRenderer == null)
            {
                Debug.LogError("[DirectJointPlayer] 找不到 SkinnedMeshRenderer！");
                return;
            }

            // 建立映射
            Transform[] allBones = skinnedMeshRenderer.bones;
            allCharacterBones = allBones;
            initialLocalPositions = new Vector3[allBones.Length];
            initialLocalRotations = new Quaternion[allBones.Length];
            boneArrayIndex.Clear();

            Dictionary<string, Transform> boneDict = new Dictionary<string, Transform>();
            for (int i = 0; i < allBones.Length; i++)
            {
                Transform b = allBones[i];
                boneDict[b.name] = b;
                boneArrayIndex[b] = i;
                initialLocalPositions[i] = b.localPosition;
                initialLocalRotations[i] = b.localRotation;
            }

            for (int i = 0; i < 17; i++)
            {
                string targetName = GetSMPLBoneNameForH36MIndex(i);
                if (!string.IsNullOrEmpty(targetName) && boneDict.ContainsKey(targetName))
                {
                    mappedBones[i] = boneDict[targetName];
                }
                else
                {
                    mappedBones[i] = null;
                }
            }

            BuildRotationDrivers();
            BuildPelvisBasis();

            // 可視化目標點
            if (jointSpheres != null)
            {
                foreach (var s in jointSpheres) if (s) Destroy(s);
            }
            
            jointSpheres = new GameObject[17];
            for (int i = 0; i < 17; i++)
            {
                GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                sphere.name = $"TargetPoint_{i}";
                sphere.transform.SetParent(this.transform, false);
                sphere.transform.localScale = Vector3.one * 0.03f;
                Collider c = sphere.GetComponent<Collider>();
                if (c != null) Destroy(c);
                
                Renderer r = sphere.GetComponent<Renderer>();
                if (r != null)
                {
                    r.material = new Material(Shader.Find("Standard"));
                    r.material.color = Color.red; // 紅色代表目標點
                }
                jointSpheres[i] = sphere;
                sphere.SetActive(showSkeletonLines);
            }

            if (useAnimationRiggingIK)
            {
                SetupAnimationRiggingIK();
            }
        }

        private void SetupAnimationRiggingIK()
        {
            if (instantiatedCharacter == null || jointSpheres == null) return;

            rigBuilder = instantiatedCharacter.GetComponent<RigBuilder>();
            if (rigBuilder == null)
            {
                rigBuilder = instantiatedCharacter.AddComponent<RigBuilder>();
            }

            Transform oldRig = instantiatedCharacter.transform.Find("DirectJoint_IK_Rig");
            if (oldRig != null)
            {
                Destroy(oldRig.gameObject);
            }

            GameObject rigObj = new GameObject("DirectJoint_IK_Rig");
            rigObj.transform.SetParent(instantiatedCharacter.transform, false);
            directJointRig = rigObj.AddComponent<Rig>();

            int leftLegTarget = swapLeftRightIKTargets ? 3 : 6;
            int leftLegHint = swapLeftRightIKTargets ? 2 : 5;
            int rightLegTarget = swapLeftRightIKTargets ? 6 : 3;
            int rightLegHint = swapLeftRightIKTargets ? 5 : 2;
            int leftArmTarget = swapLeftRightIKTargets ? 16 : 13;
            int leftArmHint = swapLeftRightIKTargets ? 15 : 12;
            int rightArmTarget = swapLeftRightIKTargets ? 13 : 16;
            int rightArmHint = swapLeftRightIKTargets ? 12 : 15;

            AddTwoBoneIK(rigObj.transform, "LeftLeg_IK", 4, 5, 6, leftLegTarget, leftLegHint);
            AddTwoBoneIK(rigObj.transform, "RightLeg_IK", 1, 2, 3, rightLegTarget, rightLegHint);
            AddTwoBoneIK(rigObj.transform, "LeftArm_IK", 11, 12, 13, leftArmTarget, leftArmHint);
            AddTwoBoneIK(rigObj.transform, "RightArm_IK", 14, 15, 16, rightArmTarget, rightArmHint);

            rigBuilder.layers.Clear();
            rigBuilder.layers.Add(new RigLayer(directJointRig));
            rigBuilder.Build();

            Debug.Log($"[DirectJointPlayer] 已建立 Animation Rigging TwoBoneIK：四肢末端會追 H36M 手腕/腳踝 target。Swap LR Targets = {swapLeftRightIKTargets}");
        }

        private void AddTwoBoneIK(Transform rigRoot, string name, int rootJoint, int midJoint, int tipJoint, int targetJoint, int hintJoint)
        {
            Transform root = mappedBones[rootJoint];
            Transform mid = mappedBones[midJoint];
            Transform tip = mappedBones[tipJoint];

            if (root == null || mid == null || tip == null || jointSpheres[targetJoint] == null || jointSpheres[hintJoint] == null)
            {
                Debug.LogWarning($"[DirectJointPlayer] 無法建立 {name}，骨頭或 target 缺失。");
                return;
            }

            GameObject constraintObj = new GameObject(name);
            constraintObj.transform.SetParent(rigRoot, false);

            TwoBoneIKConstraint constraint = constraintObj.AddComponent<TwoBoneIKConstraint>();
            TwoBoneIKConstraintData data = constraint.data;
            data.root = root;
            data.mid = mid;
            data.tip = tip;
            data.target = jointSpheres[targetJoint].transform;
            data.hint = jointSpheres[hintJoint].transform;
            data.targetPositionWeight = 1f;
            data.targetRotationWeight = 0f;
            data.hintWeight = 1f;
            constraint.data = data;
            constraint.weight = 1f;
        }

        private void BuildRotationDrivers()
        {
            rotationDrivers.Clear();

            for (int i = 0; i < H36MRotationPairs.GetLength(0); i++)
            {
                int sourceJoint = H36MRotationPairs[i, 0];
                int targetJoint = H36MRotationPairs[i, 1];
                Transform sourceBone = mappedBones[sourceJoint];
                Transform targetBone = mappedBones[targetJoint];

                if (sourceBone == null || targetBone == null) continue;

                Vector3 bindDirection = targetBone.position - sourceBone.position;
                if (bindDirection.sqrMagnitude < 0.000001f) continue;

                rotationDrivers.Add(new RotationDriver
                {
                    sourceJoint = sourceJoint,
                    targetJoint = targetJoint,
                    bone = sourceBone,
                    bindDirectionWorld = bindDirection.normalized,
                    bindRotationWorld = sourceBone.rotation
                });
            }

            Debug.Log($"[DirectJointPlayer] 建立 {rotationDrivers.Count} 個直接關節旋轉驅動。這是實驗用近似法，不會像 SMPL pose 那樣估計完整人體參數。");
        }

        private void BuildPelvisBasis()
        {
            if (mappedBones[0] == null || mappedBones[1] == null || mappedBones[4] == null || mappedBones[7] == null)
            {
                bindPelvisBasisWorld = initialCharacterRootRotation;
                Debug.LogWarning("[DirectJointPlayer] 無法建立 pelvis basis，將使用 rootRotationOffset 作為固定根旋轉。");
                return;
            }

            bindPelvisBasisWorld = BuildBasisRotation(
                mappedBones[1].position - mappedBones[4].position,
                mappedBones[7].position - mappedBones[0].position,
                initialCharacterRootRotation
            );
        }

        private Quaternion BuildBasisRotation(Vector3 rightVector, Vector3 upVector, Quaternion fallback)
        {
            if (rightVector.sqrMagnitude < 0.000001f || upVector.sqrMagnitude < 0.000001f) return fallback;

            Vector3 right = rightVector.normalized;
            Vector3 up = upVector.normalized;
            Vector3 forward = Vector3.Cross(right, up);
            if (forward.sqrMagnitude < 0.000001f) return fallback;

            forward.Normalize();
            up = Vector3.Cross(forward, right).normalized;
            return Quaternion.LookRotation(forward, up);
        }

        private void ResetCharacterToBindPose()
        {
            if (allCharacterBones == null || initialLocalRotations == null) return;

            for (int i = 0; i < allCharacterBones.Length; i++)
            {
                if (allCharacterBones[i] == null) continue;
                allCharacterBones[i].localPosition = initialLocalPositions[i];
                allCharacterBones[i].localRotation = initialLocalRotations[i];
            }
        }

        private void PlayDefault()
        {
            if (dataset == null || dataset.Count == 0) return;
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

        public bool PlayAction(string actionKey, string subactionKey)
        {
            if (!isLoaded || dataset == null) return false;

            if (!dataset.ContainsKey(actionKey) || !dataset[actionKey].ContainsKey(subactionKey))
            {
                return false;
            }

            activeSequence = dataset[actionKey][subactionKey];
            currentActionKey = actionKey;
            currentSubactionKey = subactionKey;

            currentTime = 0f;
            CurrentFrame = 0;
            isPlaying = true;
            isPaused = false;
            
            ApplyFrame(0);
            return true;
        }

        public void SetPaused(bool paused) => isPaused = paused;
        public void TogglePause() => isPaused = !isPaused;
        public void SetPlaybackSpeed(float speed) => playbackSpeed = Mathf.Clamp(speed, 0.1f, 5.0f);
        
        public void ScrubToProgress(float progress)
        {
            if (activeSequence == null) return;
            progress = Mathf.Clamp01(progress);
            float totalDuration = (float)activeSequence.frames.Count / targetFPS;
            currentTime = progress * totalDuration;
            CurrentFrame = Mathf.FloorToInt(currentTime * targetFPS);
            CurrentFrame = Mathf.Clamp(CurrentFrame, 0, activeSequence.frames.Count - 1);
            ApplyFrame(CurrentFrame);
        }

        private void ApplyFrame(int frameIndex)
        {
            if (activeSequence == null || frameIndex >= activeSequence.frames.Count) return;
            H36MFrame frame = activeSequence.frames[frameIndex];

            Vector3 rootOffset = Vector3.zero;
            if (freezePosition)
            {
                // 計算 pelvis (index 0) 的位移量以凍結
                rootOffset = -frame.joints[0]; 
            }

            // 解決「模型跟紅點分開」的問題：
            // 因為模型根目錄如果留在原點 (0,0,0)，那些沒有被直接控制的骨骼（如手指、臉部、腳趾）
            // 會被拉扯在原點。所以我們先把整個角色的 Root 移動到骨盆 (Pelvis) 的位置。
            Vector3 pelvisWorldPos = this.transform.position + frame.joints[0] + rootOffset;
            if (instantiatedCharacter != null)
            {
                instantiatedCharacter.transform.position = pelvisWorldPos;
                if (useAnimationRiggingIK)
                {
                    instantiatedCharacter.transform.rotation = initialCharacterRootRotation;
                }
                else
                {
                    Quaternion targetPelvisBasis = BuildBasisRotation(
                        frame.joints[1] - frame.joints[4],
                        frame.joints[7] - frame.joints[0],
                        initialCharacterRootRotation
                    );
                    instantiatedCharacter.transform.rotation = targetPelvisBasis * Quaternion.Inverse(bindPelvisBasisWorld) * initialCharacterRootRotation;
                }
            }

            ResetCharacterToBindPose();

            for (int i = 0; i < 17; i++)
            {
                Vector3 targetWorldPos = this.transform.position + frame.joints[i] + rootOffset;
                
                // 更新紅色提示球
                if (jointSpheres != null && jointSpheres[i] != null)
                {
                    jointSpheres[i].transform.position = targetWorldPos;
                    jointSpheres[i].SetActive(showSkeletonLines);
                }

            }

            if (!useManualRotationDrivers || useAnimationRiggingIK) return;

            for (int i = 0; i < rotationDrivers.Count; i++)
            {
                RotationDriver driver = rotationDrivers[i];
                Vector3 sourceWorldPos = this.transform.position + frame.joints[driver.sourceJoint] + rootOffset;
                Vector3 targetWorldPos = this.transform.position + frame.joints[driver.targetJoint] + rootOffset;
                Vector3 targetDirection = targetWorldPos - sourceWorldPos;

                if (targetDirection.sqrMagnitude < 0.000001f || driver.bone == null) continue;

                Quaternion delta = Quaternion.FromToRotation(driver.bindDirectionWorld, targetDirection.normalized);
                driver.bone.rotation = delta * driver.bindRotationWorld;
            }
        }
    }
}
