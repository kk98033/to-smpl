using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;
using Utilities;
using SMPLModel;

namespace SMPL0901Player.Runtime
{
    /// <summary>
    /// Dedicated receiver/player for the 1389-byte SMV2 datagram emitted by
    /// smpl-0901-bridge. It intentionally contains no legacy SMPL/SMPJ,
    /// video-cache, or offline-playback path.
    /// </summary>
    public sealed class Smpl0901LivePlayer : MonoBehaviour
    {
        [Header("Character")]
        public GameObject characterPrefab;
        public Vector3 pelvisLocalOffset = Vector3.zero;
        [Tooltip("SUP's authored SMPL-H rig correction. Keep this separate from display/source controls.")]
        public Vector3 supRigPelvisEuler = new Vector3(-90f, 0f, 0f);
        [Tooltip("Internal pelvis-only correction. Normally leave at zero.")]
        public Vector3 pelvisCorrectionEuler = Vector3.zero;
        [Tooltip("Whole received pose orientation. Applied to the character root, never to an individual bone.")]
        public Vector3 livePoseEuler = new Vector3(0f, 0f, 90f);
        public bool renderCharacter = true;

        [Header("SMV2 UDP")]
        public int listenPort = 9095;
        public bool listenOnStart = false;
        [Tooltip("Open the socket only after Start Receiving is pressed.")]
        public bool requireManualStart = true;
        [Tooltip("Optional source-IP filter. Empty accepts SMV2 from any host.")]
        public string allowedServerIp = "192.168.1.250";

        [Header("Rejected fit preview")]
        [Tooltip("Apply inputValid=false SMV2 candidates so Unity mirrors the Dashboard debug mesh. Disable for strict production hold behavior.")]
        public bool applyRejectedCandidates = true;

        [Header("Hybrid drivers")]
        public Smpl0901RootMotionDriver rootMotion;
        public Smpl0901RawHandRetargeter handRetargeter;
        public Smpl0901TrackingPanel trackingPanel;
        public Smpl0901FittedSkeletonRenderer fittedSkeleton;
        public Rsv1RawSkeletonRenderer rawSkeleton;
        public Smpl0901DirectJointBaseline directJointBaseline;

        public bool IsListening { get; private set; }
        public bool IsRuntimeReady => runtimeCharacter != null && bones != null;
        public int LatestFrameId { get; private set; } = -1;
        public long ReceivedPackets => Interlocked.Read(ref receivedPackets);
        public long AcceptedPackets => Interlocked.Read(ref acceptedPackets);
        public long DecodeErrors => Interlocked.Read(ref decodeErrors);
        public long IgnoredPackets => Interlocked.Read(ref ignoredPackets);
        public long AppliedPoseFrames { get; private set; }
        public long HeldInputFrames { get; private set; }
        public long AppliedRejectedPoseFrames { get; private set; }
        public string PoseApplyStatus { get; private set; } = "waiting for SMV2";
        public float ReceiveFps { get; private set; }
        public string LastError { get; private set; } = string.Empty;
        public string LastObservedSenderIp { get; private set; } = string.Empty;
        public string LastAcceptedSenderIp { get; private set; } = string.Empty;
        public string BoundEndpoint => $"0.0.0.0:{listenPort}";
        public float SecondsSinceLastPacket => lastPacketRealtime < 0f
            ? float.PositiveInfinity
            : Time.realtimeSinceStartup - lastPacketRealtime;
        public float SecondsSinceLastAppliedPose => lastAppliedPoseRealtime < 0f
            ? float.PositiveInfinity
            : Time.realtimeSinceStartup - lastAppliedPoseRealtime;
        public Transform[] RuntimeBones => bones;
        public Transform RuntimePelvis => pelvisBone;
        public string BindingStatus { get; private set; } = "not built";
        public bool BoneDebugMode { get; private set; }
        public bool DebugUseReceivedRotation { get; private set; }
        public bool DebugApplyReceivedThroughSelected { get; private set; }
        public int DebugBoneIndex { get; private set; }
        public Vector3 DebugBoneEuler { get; private set; }
        public string DebugBoneName
        {
            get
            {
                Transform bone = GetBodyBone(DebugBoneIndex);
                return bone != null ? bone.name : "unmapped";
            }
        }
        public Vector3 DebugReceivedRotvec
        {
            get
            {
                if (latestPose == null || latestPose.Length < (DebugBoneIndex + 1) * 3)
                    return Vector3.zero;
                int offset = DebugBoneIndex * 3;
                return new Vector3(latestPose[offset], latestPose[offset + 1], latestPose[offset + 2]);
            }
        }
        public float DebugReceivedAngleDeg => DebugReceivedRotvec.magnitude * Mathf.Rad2Deg;

        private readonly object frameLock = new object();
        private ProtocolV2Frame pendingFrame;
        private bool hasPendingFrame;
        private GameObject runtimeCharacter;
        private Transform livePoseRoot;
        private SkinnedMeshRenderer skinnedMesh;
        private SkinnedMeshRenderer[] characterRenderers;
        private Transform[] bones;
        private Quaternion[] bindLocalRotations;
        private Vector3[] bindLocalPositions;
        private Transform pelvisBone;
        private int[] bodyBoneIndices;
        private float[] latestPose;
        private UdpClient udpClient;
        private Thread receiveThread;
        private volatile bool receiverRunning;
        private float lastPacketRealtime = -1f;
        private float lastAppliedPoseRealtime = -1f;
        private float fpsWindowStart;
        private long fpsWindowPackets;
        private long receivedPackets;
        private long acceptedPackets;
        private long decodeErrors;
        private long ignoredPackets;
        private bool hasStarted;
        private IPAddress allowedServerAddress;

        private void Awake()
        {
            // Migrate the two revisions that mixed source/display correction
            // into the SUP rig's own pelvis basis conversion.
            if (Mathf.Abs(pelvisCorrectionEuler.x) < 0.01f &&
                Mathf.Abs(pelvisCorrectionEuler.y) < 0.01f &&
                Mathf.Abs(Mathf.Abs(pelvisCorrectionEuler.z) - 90f) < 0.01f)
                pelvisCorrectionEuler = Vector3.zero;

            // Existing scenes may have been generated before RSV1/fitted
            // skeleton support was added. Repair the dedicated 0901 object at
            // runtime instead of leaving the UI in "receiver missing" state.
            if (rootMotion == null) rootMotion = GetOrAdd<Smpl0901RootMotionDriver>();
            if (handRetargeter == null)
                handRetargeter = GetOrAdd<Smpl0901RawHandRetargeter>();
            if (trackingPanel == null) trackingPanel = GetOrAdd<Smpl0901TrackingPanel>();
            if (fittedSkeleton == null)
                fittedSkeleton = GetOrAdd<Smpl0901FittedSkeletonRenderer>();
            if (rawSkeleton == null) rawSkeleton = GetOrAdd<Rsv1RawSkeletonRenderer>();
            if (directJointBaseline == null)
                directJointBaseline = GetOrAdd<Smpl0901DirectJointBaseline>();

            rootMotion.runtimeRoot = transform;
            rootMotion.SetDisplayEuler(rootMotion.displayEuler);
            fittedSkeleton.player = this;
            trackingPanel.player = this;
            trackingPanel.fittedSkeleton = fittedSkeleton;
            trackingPanel.rawSkeleton = rawSkeleton;
            trackingPanel.directJointBaseline = directJointBaseline;
            rawSkeleton.player = this;
            // Current to-smpl uses the proper right-handed x,-y,-z input map.
            // RSV1 is deliberately pre-map, so its Unity renderer must apply
            // the matching proper-map/SUP point basis rather than the legacy
            // reflected x,-y,z fallback.
            rawSkeleton.useSmplCoordinateConversion = true;
            directJointBaseline.player = this;
            directJointBaseline.rawSkeleton = rawSkeleton;
            if (string.IsNullOrWhiteSpace(rawSkeleton.allowedServerIp))
                rawSkeleton.allowedServerIp = allowedServerIp;
        }

        private void Start()
        {
            hasStarted = true;
            BuildCharacter();
            if (listenOnStart && !requireManualStart) StartListening();
        }

        private void OnEnable()
        {
            if (hasStarted && listenOnStart && !requireManualStart && !IsListening)
                StartListening();
        }

        public void BuildCharacter()
        {
            if (runtimeCharacter != null) return;
            if (characterPrefab == null)
            {
                LastError = "Character prefab is not assigned.";
                Debug.LogError($"[SMPL0901] {LastError}", this);
                return;
            }

            GameObject orientationObject = new GameObject("SMPL0901_LivePoseRoot");
            orientationObject.transform.SetParent(transform, false);
            livePoseRoot = orientationObject.transform;
            runtimeCharacter = Instantiate(
                characterPrefab, livePoseRoot.position, Quaternion.identity, livePoseRoot);
            runtimeCharacter.name = characterPrefab.name + "_0901_Runtime";
            // The Instantiate overload preserves world rotation. Force the
            // character to inherit the outer player's display orientation.
            runtimeCharacter.transform.localRotation = Quaternion.identity;

            CharacterPoser poser = runtimeCharacter.GetComponentInChildren<CharacterPoser>(true);
            if (poser != null) poser.enabled = false;
            CharacterComponent character =
                runtimeCharacter.GetComponentInChildren<CharacterComponent>(true);
            if (character != null) character.enabled = false;
            foreach (CharacterTranslater translator in
                     runtimeCharacter.GetComponentsInChildren<CharacterTranslater>(true))
                translator.enabled = false;

            foreach (SkinnedMeshRenderer candidate in
                     runtimeCharacter.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (candidate.bones != null && candidate.bones.Length > 0)
                {
                    skinnedMesh = candidate;
                    bones = candidate.bones;
                    break;
                }
            }
            if (bones == null)
            {
                LastError = "No SkinnedMeshRenderer with bones was found in the prefab.";
                Debug.LogError($"[SMPL0901] {LastError}", this);
                return;
            }
            characterRenderers = runtimeCharacter.GetComponentsInChildren<SkinnedMeshRenderer>(true);

            bindLocalRotations = new Quaternion[bones.Length];
            bindLocalPositions = new Vector3[bones.Length];
            bodyBoneIndices = new int[22];
            for (int index = 0; index < bodyBoneIndices.Length; index++)
                bodyBoneIndices[index] = -1;
            for (int index = 0; index < bones.Length; index++)
            {
                Transform bone = bones[index];
                if (bone == null) continue;
                bindLocalRotations[index] = bone.localRotation;
                bindLocalPositions[index] = bone.localPosition;
                if (bone.name == Bones.Pelvis) pelvisBone = bone;
                if (Bones.NameToJointIndex.TryGetValue(bone.name, out int poseIndex) &&
                    poseIndex >= 0 && poseIndex < bodyBoneIndices.Length)
                {
                    if (bodyBoneIndices[poseIndex] >= 0)
                        Debug.LogWarning($"[SMPL0901] Duplicate body binding for pose {poseIndex}: {bone.name}.", this);
                    else
                        bodyBoneIndices[poseIndex] = index;
                }
            }

            int mappedBodyBones = 0;
            string missing = string.Empty;
            for (int poseIndex = 0; poseIndex < bodyBoneIndices.Length; poseIndex++)
            {
                if (bodyBoneIndices[poseIndex] >= 0) mappedBodyBones++;
                else missing += (missing.Length == 0 ? string.Empty : ",") + poseIndex;
            }
            BindingStatus = missing.Length == 0
                ? "22/22 SMPL body joints mapped"
                : $"{mappedBodyBones}/22 mapped; missing pose indices: {missing}";
            if (missing.Length > 0)
                Debug.LogError($"[SMPL0901] Bone binding incomplete: {BindingStatus}", this);

            // Some SUP "New" prefabs contain a large authored child offset.
            // Move the instantiated prefab once so its bind-pose pelvis is at
            // this player's origin. Root motion then moves the outer player,
            // and raw RSV1 can share the exact same pelvis anchor.
            if (pelvisBone != null)
                runtimeCharacter.transform.position += livePoseRoot.position - pelvisBone.position;

            if (rootMotion != null) rootMotion.runtimeRoot = transform;
            if (handRetargeter != null)
                handRetargeter.Initialize(runtimeCharacter.transform);
            ShowTPose();
            SetCharacterVisible(renderCharacter);
            Debug.Log($"[SMPL0901] Character ready with {bones.Length} bones; {BindingStatus}.", this);
        }

        public void StartListening()
        {
            if (IsListening) return;
            try
            {
                allowedServerAddress = null;
                string filter = (allowedServerIp ?? string.Empty).Trim();
                if (filter.Length > 0 && !IPAddress.TryParse(filter, out allowedServerAddress))
                    throw new ArgumentException($"Invalid server IP: {filter}");
                udpClient = new UdpClient();
                udpClient.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
                udpClient.Client.Bind(new IPEndPoint(IPAddress.Any, listenPort));
                receiverRunning = true;
                IsListening = true;
                LastError = string.Empty;
                fpsWindowStart = Time.realtimeSinceStartup;
                fpsWindowPackets = ReceivedPackets;
                receiveThread = new Thread(ReceiveLoop)
                {
                    IsBackground = true,
                    Name = "SMPL0901-SMV2-Receiver"
                };
                receiveThread.Start();
                Debug.Log($"[SMPL0901] Listening for SMV2 on UDP {listenPort}.", this);
            }
            catch (Exception exception)
            {
                LastError = exception.Message;
                IsListening = false;
                Debug.LogError($"[SMPL0901] UDP start failed: {exception.Message}", this);
            }
        }

        public void StopListening()
        {
            receiverRunning = false;
            IsListening = false;
            try { udpClient?.Close(); } catch { }
            udpClient = null;
            if (receiveThread != null && receiveThread.IsAlive)
                receiveThread.Join(250);
            receiveThread = null;
        }

        public void Reconnect(int port)
        {
            listenPort = Mathf.Clamp(port, 1, 65535);
            Interlocked.Exchange(ref decodeErrors, 0);
            Interlocked.Exchange(ref ignoredPackets, 0);
            LastError = string.Empty;
            StopListening();
            StartListening();
        }

        public void Reconnect(int port, string serverIp)
        {
            allowedServerIp = (serverIp ?? string.Empty).Trim();
            Reconnect(port);
        }

        public void ResetRootAnchor()
        {
            if (rootMotion != null) rootMotion.ResetAnchor();
        }

        public void SetCharacterVisible(bool visible)
        {
            renderCharacter = visible;
            if (characterRenderers == null && runtimeCharacter != null)
                characterRenderers = runtimeCharacter.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            if (characterRenderers == null) return;
            foreach (SkinnedMeshRenderer renderer in characterRenderers)
            {
                if (renderer != null) renderer.enabled = visible;
            }
        }

        public void SetBoneDebugMode(bool enabled)
        {
            BoneDebugMode = enabled;
            if (enabled)
            {
                if (livePoseRoot != null)
                    livePoseRoot.localRotation = Quaternion.Euler(livePoseEuler);
                ApplyIsolatedBoneDebugPose();
            }
            else if (latestPose != null)
            {
                if (livePoseRoot != null)
                    livePoseRoot.localRotation = Quaternion.Euler(livePoseEuler);
                ApplyBodyPose(latestPose);
            }
            else
            {
                ShowTPose();
            }
        }

        public void StepDebugBone(int delta)
        {
            DebugBoneIndex = (DebugBoneIndex + delta) % 22;
            if (DebugBoneIndex < 0) DebugBoneIndex += 22;
            DebugBoneEuler = Vector3.zero;
            ApplyIsolatedBoneDebugPose();
        }

        public void SetDebugBoneEuler(Vector3 value)
        {
            DebugBoneEuler = value;
            ApplyIsolatedBoneDebugPose();
        }

        public void SetDebugUseReceivedRotation(bool value)
        {
            DebugUseReceivedRotation = value;
            ApplyIsolatedBoneDebugPose();
        }

        public void SetDebugApplyReceivedThroughSelected(bool value)
        {
            DebugApplyReceivedThroughSelected = value;
            ApplyIsolatedBoneDebugPose();
        }

        public void ResetDebugBoneRotation()
        {
            DebugBoneEuler = Vector3.zero;
            DebugUseReceivedRotation = false;
            DebugApplyReceivedThroughSelected = false;
            ApplyIsolatedBoneDebugPose();
        }

        public void ShowTPose()
        {
            if (bones == null || bindLocalRotations == null || bindLocalPositions == null)
                return;
            // Preview orientation uses only the outer Display Rot. The live
            // source correction is applied only after a received pose arrives.
            if (livePoseRoot != null)
                livePoseRoot.localRotation = Quaternion.identity;
            for (int index = 0; index < bones.Length; index++)
            {
                Transform bone = bones[index];
                if (bone == null) continue;
                bone.localRotation = bindLocalRotations[index];
                bone.localPosition = bindLocalPositions[index];
                if (bone.name == Bones.Pelvis)
                {
                    bone.localPosition = bindLocalPositions[index] + pelvisLocalOffset;
                }
            }
            if (handRetargeter != null) handRetargeter.ResetToBindPose();
        }

        private static bool IsMatchingIp(IPAddress remote, IPAddress allowed)
        {
            if (allowed == null) return true;
            if (remote == null) return false;
            if (remote.Equals(allowed)) return true;
            try
            {
                IPAddress r4 = remote.IsIPv4MappedToIPv6 ? remote.MapToIPv4() : remote;
                IPAddress a4 = allowed.IsIPv4MappedToIPv6 ? allowed.MapToIPv4() : allowed;
                return r4.Equals(a4);
            }
            catch
            {
                return false;
            }
        }

        private void ReceiveLoop()
        {
            IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
            while (receiverRunning)
            {
                try
                {
                    byte[] packet = udpClient.Receive(ref remote);
                    LastObservedSenderIp = remote.Address.ToString();
                    // Count at the socket boundary, before source filtering and
                    // decoding, so debug can distinguish network from protocol.
                    Interlocked.Increment(ref receivedPackets);
                    if (allowedServerAddress != null &&
                        !IsMatchingIp(remote.Address, allowedServerAddress))
                    {
                        Interlocked.Increment(ref ignoredPackets);
                        continue;
                    }
                    LastAcceptedSenderIp = remote.Address.ToString();
                    Interlocked.Increment(ref acceptedPackets);
                    if (!Smpl0901BinaryCodec.TryDecode(
                            packet, out ProtocolV2Frame decoded, out string error))
                    {
                        Interlocked.Increment(ref decodeErrors);
                        LastError = error;
                        continue;
                    }
                    lock (frameLock)
                    {
                        // Latest-wins buffer: SMPL fitting may be slower than the
                        // source camera, so stale queued poses are never replayed.
                        pendingFrame = decoded;
                        hasPendingFrame = true;
                    }
                }
                catch (SocketException)
                {
                    if (receiverRunning) LastError = "UDP socket closed unexpectedly.";
                }
                catch (ObjectDisposedException) { }
                catch (Exception exception)
                {
                    LastError = exception.Message;
                    Interlocked.Increment(ref decodeErrors);
                }
            }
        }

        private void Update()
        {
            ProtocolV2Frame frame = null;
            lock (frameLock)
            {
                if (hasPendingFrame)
                {
                    frame = pendingFrame;
                    pendingFrame = null;
                    hasPendingFrame = false;
                }
            }
            if (frame != null)
            {
                lastPacketRealtime = Time.realtimeSinceStartup;
                ApplyFrame(frame);
            }

            float elapsed = Time.realtimeSinceStartup - fpsWindowStart;
            if (elapsed >= 1f)
            {
                long count = ReceivedPackets;
                ReceiveFps = (count - fpsWindowPackets) / elapsed;
                fpsWindowPackets = count;
                fpsWindowStart = Time.realtimeSinceStartup;
            }
        }

        private void LateUpdate()
        {
            // SUP's MeshDisplay may restore renderer.enabled during Update.
            // Enforce the runtime UI choice after all regular Update calls.
            if (!renderCharacter) SetCharacterVisible(false);
        }

        private void ApplyFrame(ProtocolV2Frame frame)
        {
            if (frame == null || frame.body == null ||
                frame.quality == null || frame.protocolVersion != 2)
            {
                PoseApplyStatus = "decoded frame is incomplete";
                return;
            }

            LatestFrameId = frame.frameId;
            if (trackingPanel != null) trackingPanel.SetFrame(frame);

            bool rejectedCandidate = !frame.quality.inputValid;
            if (rejectedCandidate)
            {
                HeldInputFrames++;
                if (!applyRejectedCandidates)
                {
                    PoseApplyStatus = "SMV2 rejected candidate; strict hold enabled";
                    return;
                }
            }
            if (!IsRuntimeReady)
            {
                if (characterPrefab == null)
                    LastError = "Character prefab is not assigned on Smpl0901LivePlayer.";
                PoseApplyStatus = "character rig is not ready";
                return;
            }
            if (frame.body.pose == null || frame.body.pose.Length != 156)
            {
                LastError = "Decoded pose does not contain 156 values.";
                PoseApplyStatus = LastError;
                return;
            }

            latestPose = (float[])frame.body.pose.Clone();
            if (BoneDebugMode)
            {
                ApplyIsolatedBoneDebugPose();
                PoseApplyStatus = "BONE ISOLATION active; full pose paused";
                return;
            }

            // This is a whole-pose coordinate correction. Keeping it on the
            // instantiated character root prevents it from contaminating the
            // SMPL pelvis/local skinning rotations.
            if (livePoseRoot != null)
                livePoseRoot.localRotation = Quaternion.Euler(livePoseEuler);
            ApplyBodyPose(frame.body.pose);
            if (rootMotion != null)
                rootMotion.ApplyFrame(
                    frame.body.rootPosition,
                    frame.body.rootConfidence,
                    !rejectedCandidate || applyRejectedCandidates);
            if (handRetargeter != null && frame.hands != null)
                handRetargeter.ApplyHands(frame.hands);
            AppliedPoseFrames++;
            if (rejectedCandidate) AppliedRejectedPoseFrames++;
            lastAppliedPoseRealtime = Time.realtimeSinceStartup;
            PoseApplyStatus = rejectedCandidate
                ? $"applied Dashboard candidate {frame.frameId} (safety rejected)"
                : $"applied accepted frame {frame.frameId}";
        }

        private void ApplyBodyPose(float[] pose)
        {
            if (bodyBoneIndices == null || bodyBoneIndices.Length != 22) return;
            for (int poseIndex = 0; poseIndex < bodyBoneIndices.Length; poseIndex++)
            {
                int boneIndex = bodyBoneIndices[poseIndex];
                if (boneIndex < 0 || boneIndex >= bones.Length) continue;
                Transform bone = bones[boneIndex];
                if (bone == null || poseIndex * 3 + 2 >= pose.Length) continue;

                // Match the legacy RealtimePipelinePlayer exactly. SUP's
                // runtime rig expects an identity local pose every frame;
                // authored bind rotations must not be accumulated here.
                bone.localRotation = Quaternion.identity;
                if (bone.name == Bones.Pelvis)
                {
                    // Match SUP CharacterPoser exactly: its exported SMPL-H
                    // pelvis requires -90 degrees around X before the converted
                    // SMPL root rotation. User/source correction is a separate
                    // output-space rotation and must not replace this step.
                    bone.localRotation = Quaternion.Euler(pelvisCorrectionEuler) *
                        Quaternion.Euler(supRigPelvisEuler);
                    Vector3 bindPosition = bindLocalPositions != null &&
                        boneIndex < bindLocalPositions.Length
                        ? bindLocalPositions[boneIndex] : Vector3.zero;
                    bone.localPosition = bindPosition + pelvisLocalOffset;
                }

                int offset = poseIndex * 3;
                float x = pose[offset];
                float y = pose[offset + 1];
                float z = pose[offset + 2];
                float radians = Mathf.Sqrt(x * x + y * y + z * z);
                if (radians <= 1e-6f) continue;
                Quaternion axisAngle = Quaternion.AngleAxis(
                    radians * Mathf.Rad2Deg,
                    new Vector3(x, y, z) / radians);
                bone.localRotation *= axisAngle.ToLeftHanded();
            }
        }

        private Transform GetBodyBone(int poseIndex)
        {
            if (bones == null || bodyBoneIndices == null ||
                poseIndex < 0 || poseIndex >= bodyBoneIndices.Length)
                return null;
            int boneIndex = bodyBoneIndices[poseIndex];
            return boneIndex >= 0 && boneIndex < bones.Length ? bones[boneIndex] : null;
        }

        private void ApplyIsolatedBoneDebugPose()
        {
            if (!IsRuntimeReady || bodyBoneIndices == null) return;
            if (livePoseRoot != null)
                livePoseRoot.localRotation = Quaternion.Euler(livePoseEuler);

            for (int poseIndex = 0; poseIndex < bodyBoneIndices.Length; poseIndex++)
            {
                Transform bone = GetBodyBone(poseIndex);
                if (bone == null) continue;
                bone.localRotation = poseIndex == 0
                    ? Quaternion.Euler(supRigPelvisEuler)
                    : Quaternion.identity;
                int boneIndex = bodyBoneIndices[poseIndex];
                if (poseIndex == 0 && bindLocalPositions != null && boneIndex < bindLocalPositions.Length)
                    bone.localPosition = bindLocalPositions[boneIndex] + pelvisLocalOffset;
            }
            if (handRetargeter != null) handRetargeter.ResetToBindPose();

            if (DebugApplyReceivedThroughSelected && latestPose != null)
            {
                // SMPL body indices are parent-before-child. Applying the
                // received prefix progressively reveals the first joint whose
                // local rotation makes the combined hierarchy diverge.
                for (int poseIndex = 0; poseIndex <= DebugBoneIndex; poseIndex++)
                {
                    Transform bone = GetBodyBone(poseIndex);
                    if (bone != null) bone.localRotation *= RotationFromPose(latestPose, poseIndex);
                }
                return;
            }

            Transform selected = GetBodyBone(DebugBoneIndex);
            if (selected == null) return;
            Quaternion testRotation = DebugUseReceivedRotation && latestPose != null
                ? RotationFromPose(latestPose, DebugBoneIndex)
                : Quaternion.Euler(DebugBoneEuler);
            selected.localRotation *= testRotation;
        }

        private static Quaternion RotationFromPose(float[] pose, int poseIndex)
        {
            int offset = poseIndex * 3;
            if (pose == null || offset < 0 || offset + 2 >= pose.Length)
                return Quaternion.identity;
            Vector3 rotvec = new Vector3(pose[offset], pose[offset + 1], pose[offset + 2]);
            float radians = rotvec.magnitude;
            return radians > 1e-6f
                ? Quaternion.AngleAxis(radians * Mathf.Rad2Deg, rotvec / radians).ToLeftHanded()
                : Quaternion.identity;
        }

        private void OnDisable()
        {
            StopListening();
        }

        private void OnDestroy()
        {
            StopListening();
        }

        private T GetOrAdd<T>() where T : Component
        {
            T component = GetComponent<T>();
            return component != null ? component : gameObject.AddComponent<T>();
        }
    }
}
