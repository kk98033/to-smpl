using UnityEngine;
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Generic;
using System.Collections.Concurrent;
#if UNITY_EDITOR
using UnityEditor;
#endif
using UnityEngine.Video;
using Utilities;
using SMPLModel;
using CustomSMPL.Runtime0804;

namespace CustomSMPL
{
    public class RealtimePipelinePlayer : MonoBehaviour
    {
        [Header("SMPL Settings")]
        [Tooltip("請將您的角色 Prefab (例如 SMPLH Character Male New) 拖拉至此")]
        public GameObject characterPrefab;

        [Header("UDP Settings")]
        public int listenPort = 9095;
        [Tooltip("0804 offline player does not need UDP. Enable only for legacy live streaming.")]
        public bool enableUdp = false;
        
        [Header("Render Toggles")]
        public bool renderSMPL = true;
        public bool renderJoints = true;
        
        [Header("Transform Adjustments")]
        [Tooltip("手動微調生成位置 (例如 Y=-0.9 可將人物拉出地底)")]
        public Vector3 positionOffset = new Vector3(0, 0, 0);

        private float lastSeekTime = 0f;

        [Header("Cache State")]
        public bool freezeLowerBody = false;

        [Header("Debug")]
        public bool freezePosition = false;

        [Header("Protocol V2 Integration")]
        public RootMotionDriver rootMotionDriver;
        public RawHandRetargeter rawHandRetargeter;
        public TrackingDebugPanel trackingDebugPanel;

        [Header("Offline body / hand separation")]
        [Tooltip("When enabled, Learnable pose drives only pelvis/body/wrists. Finger bones are exclusively driven by raw Hand21 joints.")]
        public bool bodyPoseOnly = false;
        [Tooltip("Dataset calibration applied only to source joints, not to the SMPL character.")]
        public Vector3 sourceSkeletonEuler = Vector3.zero;

        // Status
        public bool IsConnected { get; private set; }
        public uint LatestFrameIdx { get; private set; }
        public float FPS { get; private set; }
        public bool IsRuntimeReady => instantiatedCharacter != null && bones != null;
        public GameObject RuntimeCharacter => instantiatedCharacter;

        // Networking
        private UdpClient udpClient;
        private Thread receiveThread;
        private bool isRunning = false;
        private uint lastReceivedFrameIdx = 0;

        // --- Caching and Playback Data ---
        [Serializable]
        public class CachedFrame
        {
            public uint frameIdx;
            public Vector3 trans;
            public float[] poses = new float[156];
            public Vector3[] joints = new Vector3[67];
            public int activeJointCount;
        }

        [Serializable]
        public class PipelineFrameCache
        {
            public List<CachedFrame> frames = new List<CachedFrame>();
        }

        [Header("Playback & Cache")]
        public bool isPlaybackMode = false;
        public bool isPlaying = false;
        [Tooltip("如果覺得播放太快(例如2倍速)，可以將此數值調低 (預設 0.5)")]
        public float playbackSpeed = 0.5f;
        public int playbackIndex = 0;
        private float playbackTimer = 0f;
        private PipelineFrameCache frameCache = new PipelineFrameCache();
        private ConcurrentQueue<CachedFrame> frameQueue = new ConcurrentQueue<CachedFrame>();

        [Header("Original Video Sync")]
        public bool showOriginalVideo = false;
        public VideoPlayer videoPlayer;
        private string currentVideoPath = "";
        private bool hasNewVideoPath = false;
        // ---------------------------------

        // Data Buffers (Protected by Lock)
        private readonly object dataLock = new object();
        private bool hasNewData = false;
        private uint currentFrameIdx = 0;
        private Vector3 currentTranslation = Vector3.zero;
        private float[] currentPoses = new float[156];
        private Vector3[] currentJoints = new Vector3[67];
        private float[] currentJointConfidence = new float[67];
        private bool hasJointsData = false;
        private int activeJointCount = 25;
        private ProtocolV2Frame pendingProtocolV2Frame;
        private bool hasNewProtocolV2Data = false;

        // FPS tracking
        private int framesReceived = 0;
        private float lastFpsTime = 0f;

        // SMPL Character state
        private GameObject instantiatedCharacter;
        private SkinnedMeshRenderer skinnedMeshRenderer;
        private Transform[] bones;

        // Joints visualizer state
        private GameObject[] jointSpheres;
        private LineRenderer[] boneLines;

        // Body25 connections
        private struct BoneConnection {
            public int jointA; public int jointB;
            public BoneConnection(int a, int b) { jointA = a; jointB = b; }
        }
        
        private static readonly BoneConnection[] Body25Connections = new BoneConnection[]
        {
            new BoneConnection(0, 1),   // Nose -> Neck
            new BoneConnection(1, 2),   // Neck -> RShoulder
            new BoneConnection(2, 3),   // RShoulder -> RElbow
            new BoneConnection(3, 4),   // RElbow -> RWrist
            new BoneConnection(1, 5),   // Neck -> LShoulder
            new BoneConnection(5, 6),   // LShoulder -> LElbow
            new BoneConnection(6, 7),   // LElbow -> LWrist
            new BoneConnection(1, 8),   // Neck -> MidHip
            new BoneConnection(8, 9),   // MidHip -> RHip
            new BoneConnection(9, 10),  // RHip -> RKnee
            new BoneConnection(10, 11), // RKnee -> RAnkle
            new BoneConnection(8, 12),  // MidHip -> LHip
            new BoneConnection(12, 13), // LHip -> LKnee
            new BoneConnection(13, 14), // LKnee -> LAnkle
            new BoneConnection(0, 15),  // Nose -> REye
            new BoneConnection(15, 17), // REye -> REar
            new BoneConnection(0, 16),  // Nose -> LEye
            new BoneConnection(16, 18), // LEye -> LEar
            new BoneConnection(14, 19), // LAnkle -> LBigToe
            new BoneConnection(14, 20), // LAnkle -> LSmallToe
            new BoneConnection(14, 21), // LAnkle -> LHeel
            new BoneConnection(11, 22), // RAnkle -> RBigToe
            new BoneConnection(11, 23), // RAnkle -> RSmallToe
            new BoneConnection(11, 24), // RAnkle -> RHeel

            // Link body wrist to hand wrist
            new BoneConnection(7, 25),
            new BoneConnection(4, 46),

            // Left Hand (25 - 45)
            // Thumb
            new BoneConnection(25, 26), new BoneConnection(26, 27), new BoneConnection(27, 28), new BoneConnection(28, 29),
            // Index
            new BoneConnection(25, 30), new BoneConnection(30, 31), new BoneConnection(31, 32), new BoneConnection(32, 33),
            // Middle
            new BoneConnection(25, 34), new BoneConnection(34, 35), new BoneConnection(35, 36), new BoneConnection(36, 37),
            // Ring
            new BoneConnection(25, 38), new BoneConnection(38, 39), new BoneConnection(39, 40), new BoneConnection(40, 41),
            // Pinky
            new BoneConnection(25, 42), new BoneConnection(42, 43), new BoneConnection(43, 44), new BoneConnection(44, 45),

            // Right Hand (46 - 66)
            // Thumb
            new BoneConnection(46, 47), new BoneConnection(47, 48), new BoneConnection(48, 49), new BoneConnection(49, 50),
            // Index
            new BoneConnection(46, 51), new BoneConnection(51, 52), new BoneConnection(52, 53), new BoneConnection(53, 54),
            // Middle
            new BoneConnection(46, 55), new BoneConnection(55, 56), new BoneConnection(56, 57), new BoneConnection(57, 58),
            // Ring
            new BoneConnection(46, 59), new BoneConnection(59, 60), new BoneConnection(60, 61), new BoneConnection(61, 62),
            // Pinky
            new BoneConnection(46, 63), new BoneConnection(63, 64), new BoneConnection(64, 65), new BoneConnection(65, 66)
        };

        void OnEnable()
        {
            // Also runs after a Unity domain reload while Play Mode objects
            // already exist, preventing the package translator from resuming.
            DisablePackageTransformDrivers();
        }

        private void DisablePackageTransformDrivers()
        {
            foreach (CharacterTranslater translator in
                     GetComponentsInChildren<CharacterTranslater>(true))
                translator.enabled = false;
        }

        void Start()
        {
            if (characterPrefab == null)
            {
                Debug.LogError("[RealtimePipelinePlayer] 錯誤：沒有設定 Character Prefab！");
                return;
            }

            // Setup Video Player
            videoPlayer = gameObject.AddComponent<VideoPlayer>();
            videoPlayer.playOnAwake = false;
            
            // Use RGB565 to guarantee no alpha transparency channel (forces opacity)
            RenderTexture rt = new RenderTexture(1920, 1080, 0, RenderTextureFormat.RGB565);
            rt.Create();
            videoPlayer.renderMode = VideoRenderMode.RenderTexture;
            videoPlayer.targetTexture = rt;

            videoPlayer.isLooping = true;
            videoPlayer.skipOnDrop = true;

            SetupSMPL();
            CreateSkeleton();

            if (enableUdp) StartUDP();
        }

        void SetupSMPL()
        {
            instantiatedCharacter = Instantiate(characterPrefab, transform.position, Quaternion.identity, this.transform);

            // Disable existing posers
            var oldPoser = instantiatedCharacter.GetComponentInChildren<CharacterPoser>();
            if (oldPoser != null) oldPoser.enabled = false;
            var oldComponent = instantiatedCharacter.GetComponentInChildren<CharacterComponent>();
            if (oldComponent != null) oldComponent.enabled = false;
            // The SUP prefab translator expects its own playback state and
            // continuously rewrites rig/root transforms. In this standalone
            // player it also throws when that state is absent, so it must not
            // compete with protocol-v2 root or direct-joint positioning.
            DisablePackageTransformDrivers();

            skinnedMeshRenderer = instantiatedCharacter.GetComponentInChildren<SkinnedMeshRenderer>();
            if (skinnedMeshRenderer != null)
            {
                bones = skinnedMeshRenderer.bones;
                Debug.Log($"[RealtimePipelinePlayer] 成功初始化 SMPL，骨骼數：{bones.Length}");
                if (rawHandRetargeter != null)
                {
                    rawHandRetargeter.Initialize(instantiatedCharacter.transform);
                }
            }
            else
            {
                Debug.LogError("[RealtimePipelinePlayer] 找不到 SkinnedMeshRenderer！");
            }
        }

        void CreateSkeleton()
        {
            // Spheres
            jointSpheres = new GameObject[67];
            for (int i = 0; i < 67; i++)
            {
                GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                sphere.transform.SetParent(this.transform);
                // Make finger joints smaller
                float radius = i < 25 ? 0.05f : 0.015f;
                sphere.transform.localScale = Vector3.one * radius;
                
                var mr = sphere.GetComponent<MeshRenderer>();
                if (mr != null)
                {
                    mr.material = new Material(Shader.Find("Standard"));
                    mr.material.color = Color.cyan;
                }

                // Disable collider
                var col = sphere.GetComponent<Collider>();
                if (col != null) Destroy(col);

                jointSpheres[i] = sphere;
            }

            // Lines
            boneLines = new LineRenderer[Body25Connections.Length];
            for (int i = 0; i < Body25Connections.Length; i++)
            {
                GameObject lineObj = new GameObject($"BoneConnection_{i}");
                lineObj.transform.SetParent(this.transform, false);

                var conn = Body25Connections[i];
                bool isHandBone = conn.jointA >= 25 || conn.jointB >= 25;

                LineRenderer lr = lineObj.AddComponent<LineRenderer>();
                lr.positionCount = 2;
                lr.startWidth = isHandBone ? 0.005f : 0.02f;
                lr.endWidth = isHandBone ? 0.005f : 0.02f;
                lr.material = new Material(Shader.Find("Sprites/Default"));
                lr.startColor = Color.green;
                lr.endColor = Color.green;

                boneLines[i] = lr;
            }
        }

        void StartUDP()
        {
            try
            {
                udpClient = new UdpClient(listenPort);
                isRunning = true;
                IsConnected = true;
                
                receiveThread = new Thread(ReceiveData);
                receiveThread.IsBackground = true;
                receiveThread.Start();
                
                Debug.Log($"[RealtimePipelinePlayer] 開始監聽 UDP 封包於 Port {listenPort}...");
                lastFpsTime = Time.time;
            }
            catch (Exception e)
            {
                Debug.LogError($"[RealtimePipelinePlayer] UDP 初始化失敗: {e.Message}");
                IsConnected = false;
            }
        }

        void ReceiveData()
        {
            IPEndPoint endPoint = new IPEndPoint(IPAddress.Any, listenPort);

            while (isRunning)
            {
                try
                {
                    if (udpClient.Available > 0)
                    {
                        byte[] data = udpClient.Receive(ref endPoint);
                        ProcessPacket(data);
                    }
                    else
                    {
                        Thread.Sleep(1);
                    }
                }
                catch (SocketException)
                {
                    // Ignore socket aborts on close
                }
                catch (Exception e)
                {
                    Debug.LogError($"[RealtimePipelinePlayer] UDP 接收錯誤: {e.Message}");
                }
            }
        }

        void ProcessPacket(byte[] data)
        {
            if (data.Length < 4) return;

            using (MemoryStream ms = new MemoryStream(data))
            using (BinaryReader reader = new BinaryReader(ms))
            {
                char[] headerChars = reader.ReadChars(4);
                string header = new string(headerChars);

                if (header == "VIDE")
                {
                    int pathLen = data.Length - 4;
                    byte[] pathBytes = reader.ReadBytes(pathLen);
                    string path = Encoding.UTF8.GetString(pathBytes);
                    lock(dataLock)
                    {
                        if (currentVideoPath != path)
                        {
                            Debug.Log($"[RealtimePipelinePlayer] Received new VIDE packet with path: {path}");
                            currentVideoPath = path;
                            hasNewVideoPath = true;
                        }
                    }
                    return;
                }

                if (header == "SMV2")
                {
                    if (!ProtocolV2BinaryCodec.TryDecode(data, out ProtocolV2Frame protocolFrame, out string decodeError))
                    {
                        Debug.LogError($"[RealtimePipelinePlayer] SMV2 decode failed: {decodeError}");
                        return;
                    }
                    lock (dataLock)
                    {
                        pendingProtocolV2Frame = protocolFrame;
                        currentFrameIdx = (uint)Mathf.Max(0, protocolFrame.frameId);
                        hasNewProtocolV2Data = true;
                    }
                    lastReceivedFrameIdx = (uint)Mathf.Max(0, protocolFrame.frameId);
                    framesReceived++;
                    return;
                }

                if (data.Length < 644) return; // 最小封包大小 for SMPL/SMPJ
                
                if (header != "SMPL" && header != "SMPJ") return;

                uint frameIdx = reader.ReadUInt32();

                // Auto-clear cache on start of a new stream (even if frame 0 is dropped by UDP)
                if (frameIdx == 0 || (frameCache.frames.Count > 0 && frameIdx < lastReceivedFrameIdx - 10))
                {
                    lock(dataLock)
                    {
                        Debug.Log($"[RealtimePipelinePlayer] Detected stream restart (received {frameIdx} after {lastReceivedFrameIdx}), auto-clearing cache...");
                        ClearCache();
                    }
                }
                lastReceivedFrameIdx = frameIdx;
                
                // Read Translation (X, Y, Z in Unity Maya space convention)
                Vector3 trans = new Vector3(reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                
                float[] poses = new float[156];
                for (int i = 0; i < 156; i++)
                {
                    poses[i] = reader.ReadSingle();
                }

                bool hasJ = false;
                Vector3[] j3d = new Vector3[67];
                int receivedJoints = 0;

                if (header == "SMPJ" && data.Length >= 944)
                {
                    hasJ = true;
                    receivedJoints = data.Length >= 1448 ? 67 : 25;

                    for (int i = 0; i < receivedJoints; i++)
                    {
                        // Note: Our python script outputs standard coordinates (X=Right, Y=Up, Z=Forward)
                        j3d[i] = new Vector3(-reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                    }
                }

                // Push to thread-safe buffer
                lock (dataLock)
                {
                    currentFrameIdx = frameIdx;
                    
                    // Convert Python coordinates (X=Left, Y=Up, Z=Forward) to Unity (X=Right, Y=Up, Z=Forward)
                    currentTranslation = new Vector3(-trans.x, trans.y, trans.z);
                    
                    Array.Copy(poses, currentPoses, 156);
                    
                    hasJointsData = hasJ;
                    if (hasJ)
                    {
                        activeJointCount = receivedJoints;
                        Array.Copy(j3d, currentJoints, receivedJoints);
                        for (int index = 0; index < receivedJoints; index++) currentJointConfidence[index] = 1f;
                    }
                    hasNewData = true;
                }

                // Add to caching queue
                CachedFrame cf = new CachedFrame();
                cf.frameIdx = frameIdx;
                cf.trans = new Vector3(-trans.x, trans.y, trans.z);
                Array.Copy(poses, cf.poses, 156);
                cf.activeJointCount = hasJ ? receivedJoints : 0;
                if (hasJ) Array.Copy(j3d, cf.joints, receivedJoints);
                frameQueue.Enqueue(cf);

                framesReceived++;
            }
        }

        void Update()
        {
            // Always sync visibility based on toggles (handles Inspector changes)
            if (instantiatedCharacter != null && instantiatedCharacter.activeSelf != renderSMPL)
            {
                instantiatedCharacter.SetActive(renderSMPL);
            }
            ToggleSkeletonVisibility(renderJoints && hasJointsData);

            // FPS Calculation
            if (Time.time - lastFpsTime >= 1.0f)
            {
                FPS = framesReceived / (Time.time - lastFpsTime);
                framesReceived = 0;
                lastFpsTime = Time.time;
            }

            // Handle Video Path loading on main thread
            if (hasNewVideoPath)
            {
                hasNewVideoPath = false;
                Debug.Log($"[RealtimePipelinePlayer] Attempting to load video path: {currentVideoPath}");
                
                if (string.IsNullOrEmpty(currentVideoPath))
                {
                    Debug.LogError("[RealtimePipelinePlayer] Video path is empty!");
                }
                else if (!System.IO.File.Exists(currentVideoPath))
                {
                    Debug.LogError($"[RealtimePipelinePlayer] Video file does NOT exist at path: {currentVideoPath}");
                }
                else
                {
                    Debug.Log($"[RealtimePipelinePlayer] Video file exists. Assigning to VideoPlayer...");
                    videoPlayer.source = VideoSource.Url;
                    videoPlayer.url = currentVideoPath;
                    videoPlayer.prepareCompleted += (vp) => {
                        Debug.Log($"[RealtimePipelinePlayer] Video Prepared SUCCESSFULLY! Resolution: {vp.texture?.width}x{vp.texture?.height}");
                        vp.Play();
                    };
                    videoPlayer.Prepare();
                    Debug.Log($"[RealtimePipelinePlayer] Calling videoPlayer.Prepare() on: {currentVideoPath}");
                }
            }

            // Dequeue frames for cache
            while(frameQueue.TryDequeue(out CachedFrame cf))
            {
                frameCache.frames.Add(cf);
                if (!isPlaybackMode)
                {
                    playbackIndex = frameCache.frames.Count - 1;
                }
            }

            // If in playback mode, override the live data with cached data
            if (isPlaybackMode && frameCache.frames.Count > 0)
            {
                if (isPlaying)
                {
                    playbackTimer += Time.deltaTime * playbackSpeed;
                    float frameDuration = 1f / 32f; // Assuming 32 FPS default
                    if (playbackTimer >= frameDuration)
                    {
                        int framesToAdvance = Mathf.FloorToInt(playbackTimer / frameDuration);
                        playbackIndex += framesToAdvance;
                        playbackTimer -= framesToAdvance * frameDuration;
                        
                        if (playbackIndex >= frameCache.frames.Count - 1)
                        {
                            playbackIndex = frameCache.frames.Count - 1;
                            isPlaying = false;
                        }
                    }
                }

                playbackIndex = Mathf.Clamp(playbackIndex, 0, frameCache.frames.Count - 1);

                playbackIndex = Mathf.Clamp(playbackIndex, 0, frameCache.frames.Count - 1);

                CachedFrame f = frameCache.frames[playbackIndex];
                lock (dataLock)
                {
                    currentFrameIdx = f.frameIdx;
                    currentTranslation = f.trans;
                    Array.Copy(f.poses, currentPoses, 156);
                    if (f.activeJointCount > 0)
                    {
                        hasJointsData = true;
                        activeJointCount = f.activeJointCount;
                        Array.Copy(f.joints, currentJoints, f.activeJointCount);
                        for (int index = 0; index < f.activeJointCount; index++) currentJointConfidence[index] = 1f;
                    }
                    hasNewData = true;
                }
            }

            // Sync VideoPlayer (Avoid continuous seeking which breaks rendering)
            if (videoPlayer.isPrepared && showOriginalVideo)
            {
                if (isPlaybackMode)
                {
                    if (isPlaying)
                    {
                        if (!videoPlayer.isPlaying) videoPlayer.Play();
                        videoPlayer.playbackSpeed = playbackSpeed;
                        
                        if (videoPlayer.frameCount > 0 && Mathf.Abs(videoPlayer.frame - playbackIndex) > 3)
                        {
                            if (Time.time - lastSeekTime > 0.5f)
                            {
                                videoPlayer.frame = playbackIndex;
                                lastSeekTime = Time.time;
                            }
                        }
                    }
                    else
                    {
                        if (videoPlayer.isPlaying) videoPlayer.Pause();
                        if (videoPlayer.frame != playbackIndex)
                        {
                            if (Time.time - lastSeekTime > 0.1f) // Faster updates for scrubbing
                            {
                                videoPlayer.frame = playbackIndex;
                                lastSeekTime = Time.time;
                            }
                        }
                    }
                }
                else
                {
                    // Live Mode: Exact Frame Sync (Scrubbing)
                    if (videoPlayer.isPlaying) videoPlayer.Pause();
                    
                    if (videoPlayer.frameCount > 0 && videoPlayer.frame != playbackIndex)
                    {
                        // Limit scrub rate to prevent VideoPlayer from choking and turning black
                        if (Time.time - lastSeekTime > 0.1f)
                        {
                            videoPlayer.frame = playbackIndex;
                            lastSeekTime = Time.time;
                        }
                    }
                }
            }

            if (!IsConnected && !isPlaybackMode) return;

            // Apply data to Unity objects
            lock (dataLock)
            {
                if (hasNewProtocolV2Data)
                {
                    ProtocolV2Frame frame = pendingProtocolV2Frame;
                    pendingProtocolV2Frame = null;
                    hasNewProtocolV2Data = false;
                    ApplyProtocolV2Frame(frame);
                }
                if (hasNewData)
                {
                    LatestFrameIdx = currentFrameIdx;
                    
                    if (renderSMPL) ApplySMPL();
                    if (renderJoints && hasJointsData) ApplyJoints();

                    hasNewData = false;
                }
            }
        }

        /// <summary>
        /// Main-thread entry point for protocol-v2 offline playback. Root motion
        /// is applied to the outer player object, while the SMPL pelvis receives
        /// only pose rotation; raw 21-point hands are applied after body pose so
        /// the zeroed SMPL-H hand slots cannot overwrite the retargeted fingers.
        /// </summary>
        public void ApplyProtocolV2Frame(ProtocolV2Frame frame)
        {
            ApplyProtocolV2Frame(frame, true, true, true);
        }

        public void ApplyProtocolV2Frame(
            ProtocolV2Frame frame,
            bool applyRootMotion,
            bool driveHands,
            bool showSourceSkeleton)
        {
            if (frame == null || frame.body == null || frame.quality == null || !IsRuntimeReady) return;
            if (frame.protocolVersion != 2 || frame.body.pose == null || frame.body.pose.Length != 156)
            {
                Debug.LogError("[RealtimePipelinePlayer] Invalid protocol-v2 frame or pose length.");
                return;
            }

            currentFrameIdx = (uint)Mathf.Max(0, frame.frameId);
            LatestFrameIdx = currentFrameIdx;
            currentTranslation = Vector3.zero; // RootMotionDriver owns world translation in v2.
            Array.Copy(frame.body.pose, currentPoses, 156);
            ApplySMPL();

            if (applyRootMotion && rootMotionDriver != null)
            {
                rootMotionDriver.ApplyFrame(frame.body.rootPosition, frame.body.rootConfidence, frame.quality.inputValid);
            }
            if (driveHands && rawHandRetargeter != null && frame.hands != null)
            {
                rawHandRetargeter.ApplyHands(frame.hands);
            }
            if (trackingDebugPanel != null)
            {
                trackingDebugPanel.SetFrame(frame);
            }
            ApplyProtocolObservation(frame.observation, showSourceSkeleton);
        }

        private void ApplyProtocolObservation(ProtocolV2Observation observation, bool visible)
        {
            if (!visible || observation == null || observation.joints == null)
            {
                hasJointsData = false;
                ToggleSkeletonVisibility(false);
                return;
            }
            int count = Mathf.Clamp(observation.jointCount, 0, 67);
            if (observation.joints.Length < count * 3)
            {
                Debug.LogError("[RealtimePipelinePlayer] Offline observation joint array is too short.");
                hasJointsData = false;
                ToggleSkeletonVisibility(false);
                return;
            }
            for (int index = 0; index < count; index++)
            {
                int offset = index * 3;
                // Offline files use Python X=left. Mirror X to Unity X=right,
                // matching the previous SMPJ visualizer behavior.
                Vector3 converted = new Vector3(
                    -observation.joints[offset], observation.joints[offset + 1], observation.joints[offset + 2]
                );
                currentJoints[index] = Quaternion.Euler(sourceSkeletonEuler) * converted;
                currentJointConfidence[index] = observation.confidence != null && index < observation.confidence.Length
                    ? Mathf.Clamp01(observation.confidence[index])
                    : 1f;
            }
            for (int index = count; index < 67; index++) currentJointConfidence[index] = 0f;
            activeJointCount = count;
            hasJointsData = count > 0;
            ToggleSkeletonVisibility(renderJoints && hasJointsData);
            if (renderJoints && hasJointsData) ApplyJoints();
        }

        bool IsLowerBodyBone(string name)
        {
            return name == "L_Hip" || name == "R_Hip" || name == "L_Knee" || name == "R_Knee" ||
                   name == "L_Ankle" || name == "R_Ankle" || name == "L_Foot" || name == "R_Foot";
        }

        void ApplySMPL()
        {
            if (bones == null) return;

            for (int b = 0; b < bones.Length; b++)
            {
                Transform bone = bones[b];
                string boneName = bone.name;

                if (!Bones.NameToJointIndex.TryGetValue(boneName, out int poseIndex)) continue;
                if (poseIndex * 3 + 2 >= 156) continue;

                // Offline mode deliberately separates the two sources:
                // Learnable-SMPLify controls root/body/wrists (0..21), while
                // RawHandRetargeter exclusively controls all finger bones (22+).
                if (bodyPoseOnly && poseIndex >= 22) continue;

                if (freezeLowerBody && IsLowerBodyBone(boneName))
                {
                    bone.localEulerAngles = Vector3.zero;
                    continue;
                }

                bone.localEulerAngles = Vector3.zero;

                if (boneName == Bones.Pelvis)
                {
                    bone.Rotate(-90, 0, 0, Space.Self);
                    if (!freezePosition)
                    {
                        bone.localPosition = currentTranslation + positionOffset;
                    }
                }

                float x = currentPoses[poseIndex * 3];
                float y = currentPoses[poseIndex * 3 + 1];
                float z = currentPoses[poseIndex * 3 + 2];
                
                // Convert Axis-Angle to Quaternion, using scipy equivalent axis-angle length as magnitude
                float angle = Mathf.Sqrt(x * x + y * y + z * z);
                Quaternion rawRot = Quaternion.identity;
                
                if (angle > 1e-6f)
                {
                    Vector3 axis = new Vector3(x, y, z) / angle;
                    // Python sends Axis Angle, so convert to Quaternion (angle in radians)
                    rawRot = Quaternion.AngleAxis(angle * Mathf.Rad2Deg, axis);
                }

                // Apply Left-Handed conversion
                bone.localRotation = bone.localRotation * rawRot.ToLeftHanded();
            }
        }

        bool IsLowerBodyJoint(int index)
        {
            return (index >= 9 && index <= 14) || (index >= 19 && index <= 24);
        }

        void ApplyJoints()
        {
            if (jointSpheres == null || boneLines == null) return;

            for (int i = 0; i < activeJointCount; i++)
            {
                if (jointSpheres[i] != null)
                {
                    if (currentJointConfidence[i] < 0.5f)
                    {
                        if (jointSpheres[i].activeSelf) jointSpheres[i].SetActive(false);
                        continue;
                    }
                    if (freezeLowerBody && IsLowerBodyJoint(i))
                    {
                        if (jointSpheres[i].activeSelf) jointSpheres[i].SetActive(false);
                        continue;
                    }
                    else if (!jointSpheres[i].activeSelf && renderJoints)
                    {
                        jointSpheres[i].SetActive(true);
                    }

                    jointSpheres[i].transform.localPosition = currentJoints[i] + positionOffset;
                }
            }

            for (int i = 0; i < Body25Connections.Length; i++)
            {
                var conn = Body25Connections[i];
                if (boneLines[i] != null && jointSpheres[conn.jointA] != null && jointSpheres[conn.jointB] != null)
                {
                    if (conn.jointA >= activeJointCount || conn.jointB >= activeJointCount ||
                        currentJointConfidence[conn.jointA] < 0.5f || currentJointConfidence[conn.jointB] < 0.5f)
                    {
                        if (boneLines[i].gameObject.activeSelf) boneLines[i].gameObject.SetActive(false);
                        continue;
                    }

                    if (freezeLowerBody && (IsLowerBodyJoint(conn.jointA) || IsLowerBodyJoint(conn.jointB)))
                    {
                        if (boneLines[i].gameObject.activeSelf) boneLines[i].gameObject.SetActive(false);
                        continue;
                    }
                    else if (!boneLines[i].gameObject.activeSelf && renderJoints)
                    {
                        boneLines[i].gameObject.SetActive(true);
                    }

                    boneLines[i].SetPosition(0, jointSpheres[conn.jointA].transform.position);
                    boneLines[i].SetPosition(1, jointSpheres[conn.jointB].transform.position);
                }
            }
        }

        void ToggleSkeletonVisibility(bool visible)
        {
            if (jointSpheres != null)
            {
                for (int i = 0; i < jointSpheres.Length; i++)
                {
                    var sphere = jointSpheres[i];
                    if (sphere != null)
                    {
                        bool shouldBeVisible = visible && i < activeJointCount && currentJointConfidence[i] >= 0.5f &&
                            !(freezeLowerBody && IsLowerBodyJoint(i));
                        if (sphere.activeSelf != shouldBeVisible) sphere.SetActive(shouldBeVisible);
                    }
                }
            }
            if (boneLines != null)
            {
                for (int i = 0; i < boneLines.Length; i++)
                {
                    var line = boneLines[i];
                    if (line != null)
                    {
                        var conn = Body25Connections[i];
                        bool shouldBeVisible = visible && conn.jointA < activeJointCount && conn.jointB < activeJointCount &&
                            currentJointConfidence[conn.jointA] >= 0.5f && currentJointConfidence[conn.jointB] >= 0.5f &&
                            !(freezeLowerBody && (IsLowerBodyJoint(conn.jointA) || IsLowerBodyJoint(conn.jointB)));
                        if (line.gameObject.activeSelf != shouldBeVisible) line.gameObject.SetActive(shouldBeVisible);
                    }
                }
            }
        }

        public void Reconnect(int newPort)
        {
            if (listenPort == newPort && IsConnected) return;
            listenPort = newPort;
            
            isRunning = false;
            if (receiveThread != null && receiveThread.IsAlive)
            {
                receiveThread.Join(500);
            }
            if (udpClient != null)
            {
                udpClient.Close();
                udpClient = null;
            }

            StartUDP();
        }

        void OnApplicationQuit()
        {
            isRunning = false;
            if (receiveThread != null && receiveThread.IsAlive)
            {
                receiveThread.Join(500);
            }
            if (udpClient != null)
            {
                udpClient.Close();
            }
        }

        // --- Public API for UI ---
        public int GetCacheCount() => frameCache.frames.Count;

        public void ClearCache()
        {
            frameCache.frames.Clear();
            playbackIndex = 0;
            isPlaying = false;
            playbackTimer = 0f;
            lock(dataLock) { hasNewData = false; }
        }

        public void TogglePlayPause()
        {
            isPlaying = !isPlaying;
            if (isPlaying && playbackIndex >= frameCache.frames.Count - 1)
            {
                playbackIndex = 0; // Restart if at end
            }
        }

        public void SetPlaybackIndex(int idx)
        {
            playbackIndex = idx;
        }

        public void ExportToJson()
        {
            try
            {
                string json = JsonUtility.ToJson(frameCache, true);
                string path = "";

#if UNITY_EDITOR
                path = EditorUtility.SaveFilePanel(
                    "Save Recorded Animation",
                    Application.dataPath,
                    "recorded_animation.json",
                    "json");
                
                if (string.IsNullOrEmpty(path))
                {
                    return; // User canceled the dialog
                }
#else
                // Fallback for standalone game builds
                path = System.IO.Path.Combine(Application.dataPath, "recorded_animation.json");
#endif

                System.IO.File.WriteAllText(path, json);
                Debug.Log($"[RealtimePipelinePlayer] Exported {frameCache.frames.Count} frames to {path}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[RealtimePipelinePlayer] Failed to export JSON: {e.Message}");
            }
        }

        public void SetRenderSMPL(bool value)
        {
            renderSMPL = value;
            // The Update() method will now handle syncing all renderers immediately.
        }

        public void SetRenderJoints(bool value)
        {
            renderJoints = value;
            // The Update() method will now handle syncing the skeleton immediately.
        }

        public void SetFreezeLowerBody(bool value)
        {
            freezeLowerBody = value;
            if (!value)
            {
                // Re-enable spheres when turning off freeze
                ToggleSkeletonVisibility(renderJoints && hasJointsData);
            }
        }

        void OnDestroy()
        {
            isRunning = false;
            IsConnected = false;
            
            if (udpClient != null)
            {
                udpClient.Close();
                udpClient = null;
            }
            
            if (receiveThread != null && receiveThread.IsAlive)
            {
                receiveThread.Join(500);
            }
        }
    }
}
