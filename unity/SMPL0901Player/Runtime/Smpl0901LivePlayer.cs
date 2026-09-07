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
        public bool renderCharacter = true;

        [Header("SMV2 UDP")]
        public int listenPort = 9095;
        public bool listenOnStart = true;
        [Tooltip("Optional source-IP filter. Empty accepts SMV2 from any host.")]
        public string allowedServerIp = "192.168.1.250";

        [Header("Hybrid drivers")]
        public Smpl0901RootMotionDriver rootMotion;
        public Smpl0901RawHandRetargeter handRetargeter;
        public Smpl0901TrackingPanel trackingPanel;
        public Smpl0901FittedSkeletonRenderer fittedSkeleton;
        public Rsv1RawSkeletonRenderer rawSkeleton;

        public bool IsListening { get; private set; }
        public bool IsRuntimeReady => runtimeCharacter != null && bones != null;
        public int LatestFrameId { get; private set; } = -1;
        public long ReceivedPackets => Interlocked.Read(ref receivedPackets);
        public long AcceptedPackets => Interlocked.Read(ref acceptedPackets);
        public long DecodeErrors => Interlocked.Read(ref decodeErrors);
        public long IgnoredPackets => Interlocked.Read(ref ignoredPackets);
        public float ReceiveFps { get; private set; }
        public string LastError { get; private set; } = string.Empty;
        public string LastObservedSenderIp { get; private set; } = string.Empty;
        public string LastAcceptedSenderIp { get; private set; } = string.Empty;
        public string BoundEndpoint => $"0.0.0.0:{listenPort}";
        public float SecondsSinceLastPacket => lastPacketRealtime < 0f
            ? float.PositiveInfinity
            : Time.realtimeSinceStartup - lastPacketRealtime;
        public Transform[] RuntimeBones => bones;

        private readonly object frameLock = new object();
        private ProtocolV2Frame pendingFrame;
        private bool hasPendingFrame;
        private GameObject runtimeCharacter;
        private SkinnedMeshRenderer skinnedMesh;
        private Transform[] bones;
        private UdpClient udpClient;
        private Thread receiveThread;
        private volatile bool receiverRunning;
        private float lastPacketRealtime = -1f;
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

            rootMotion.runtimeRoot = transform;
            fittedSkeleton.player = this;
            trackingPanel.player = this;
            trackingPanel.fittedSkeleton = fittedSkeleton;
            trackingPanel.rawSkeleton = rawSkeleton;
            if (string.IsNullOrWhiteSpace(rawSkeleton.allowedServerIp))
                rawSkeleton.allowedServerIp = allowedServerIp;
        }

        private void Start()
        {
            hasStarted = true;
            BuildCharacter();
            if (listenOnStart) StartListening();
        }

        private void OnEnable()
        {
            if (hasStarted && listenOnStart && !IsListening) StartListening();
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

            runtimeCharacter = Instantiate(
                characterPrefab, transform.position, Quaternion.identity, transform);
            runtimeCharacter.name = characterPrefab.name + "_0901_Runtime";

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

            if (rootMotion != null) rootMotion.runtimeRoot = transform;
            if (handRetargeter != null)
                handRetargeter.Initialize(runtimeCharacter.transform);
            SetCharacterVisible(renderCharacter);
            Debug.Log($"[SMPL0901] Character ready with {bones.Length} bones.", this);
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
            if (skinnedMesh != null) skinnedMesh.enabled = visible;
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

        private void ApplyFrame(ProtocolV2Frame frame)
        {
            if (frame == null || frame.body == null ||
                frame.quality == null || frame.protocolVersion != 2)
                return;

            LatestFrameId = frame.frameId;
            if (trackingPanel != null) trackingPanel.SetFrame(frame);

            if (!frame.quality.inputValid) return; // Hold the last valid pose.
            if (!IsRuntimeReady)
            {
                if (characterPrefab == null)
                    LastError = "Character prefab is not assigned on Smpl0901LivePlayer.";
                return;
            }
            if (frame.body.pose == null || frame.body.pose.Length != 156)
            {
                LastError = "Decoded pose does not contain 156 values.";
                return;
            }

            ApplyBodyPose(frame.body.pose);
            if (rootMotion != null)
                rootMotion.ApplyFrame(
                    frame.body.rootPosition,
                    frame.body.rootConfidence,
                    frame.quality.inputValid);
            if (handRetargeter != null && frame.hands != null)
                handRetargeter.ApplyHands(frame.hands);
        }

        private void ApplyBodyPose(float[] pose)
        {
            foreach (Transform bone in bones)
            {
                if (bone == null ||
                    !Bones.NameToJointIndex.TryGetValue(bone.name, out int poseIndex) ||
                    poseIndex * 3 + 2 >= pose.Length)
                    continue;

                // The server sends zero SMPL-H finger slots. Finger bones are
                // exclusively driven from wrist-local Hand21 after this pass.
                if (poseIndex >= 22) continue;

                bone.localEulerAngles = Vector3.zero;
                if (bone.name == Bones.Pelvis)
                {
                    bone.Rotate(-90f, 0f, 0f, Space.Self);
                    bone.localPosition = pelvisLocalOffset;
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
                bone.localRotation = bone.localRotation * axisAngle.ToLeftHanded();
            }
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
