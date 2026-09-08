using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

namespace SMPL0901Player.Runtime
{
    /// <summary>
    /// Receives RSV1 on UDP 9096 and draws the original factory-59 prediction
    /// pelvis-relative under the SMPL player's root.
    /// </summary>
    public sealed class Rsv1RawSkeletonRenderer : MonoBehaviour
    {
        [Header("Alignment")]
        public Smpl0901LivePlayer player;
        [Tooltip("Keep raw pelvis on the rendered SMPL pelvis.")]
        public bool followSmplPelvis = true;
        [Tooltip("Fine alignment offset in the live-player coordinate frame.")]
        public Vector3 alignmentOffset = Vector3.zero;

        [Header("RSV1 UDP")]
        public int listenPort = 9096;
        public bool listenOnStart = false;
        [Tooltip("Open the socket only after Start Receiving is pressed.")]
        public bool requireManualStart = true;
        [Tooltip("Optional source-IP filter. Empty accepts RSV1 from any host.")]
        public string allowedServerIp = "192.168.1.250";

        [Header("Rendering")]
        public bool renderRawSkeleton = true;
        public bool showTPoseBeforeFirstFrame = true;
        [Range(0f, 1f)] public float minimumConfidence = 0.5f;
        public Color bodyColor = new Color(1f, 0.55f, 0.1f, 1f);
        public Color handColor = new Color(1f, 0.2f, 0.7f, 1f);
        public float bodyJointSize = 0.035f;
        public float handJointSize = 0.015f;
        public float bodyLineWidth = 0.015f;
        public float handLineWidth = 0.006f;

        [Header("Raw source to Unity")]
        [Tooltip("Use the same basis as bridge x,-y,z followed by SUP Maya/SMPL to Unity conversion: raw (x,y,z) -> Unity (-x,z,y).")]
        public bool useSmplCoordinateConversion = false;
        [Tooltip("Optional correction after the exact SMPL-to-Unity basis conversion.")]
        public Vector3 rotationOffset = Vector3.zero;
        [Tooltip("Matches bridge default axis x,-y,z plus Unity handedness conversion.")]
        public bool invertX = true;
        public bool invertY = true;
        public bool invertZ = false;
        [Tooltip("Scale used only when RSV1 unit=unknown (0).")]
        public float unknownUnitScale = 0.001f;

        public bool IsListening { get; private set; }
        public int LatestFrameId { get; private set; } = -1;
        public ulong LatestPtpEpochNs { get; private set; }
        public string LatestCoordinateFrame { get; private set; } = string.Empty;
        public float ReceiveFps { get; private set; }
        public string LastError { get; private set; } = string.Empty;
        public string LastObservedSenderIp { get; private set; } = string.Empty;
        public string LastAcceptedSenderIp { get; private set; } = string.Empty;
        public string BoundEndpoint => $"0.0.0.0:{listenPort}";
        public long ReceivedPackets => Interlocked.Read(ref receivedPackets);
        public long AcceptedPackets => Interlocked.Read(ref acceptedPackets);
        public long DecodeErrors => Interlocked.Read(ref decodeErrors);
        public long IgnoredPackets => Interlocked.Read(ref ignoredPackets);
        public float SecondsSinceLastPacket => lastPacketRealtime < 0f
            ? float.PositiveInfinity
            : Time.realtimeSinceStartup - lastPacketRealtime;
        public bool HasRenderableFrame => latestPelvisRelativePoints != null;

        private static readonly Vector2Int[] Connections = BuildConnections();
        private readonly object frameLock = new object();
        private Rsv1RawSkeletonFrame pendingFrame;
        private bool hasPendingFrame;
        private UdpClient udpClient;
        private Thread receiveThread;
        private volatile bool receiverRunning;
        private IPAddress allowedServerAddress;
        private long receivedPackets;
        private long acceptedPackets;
        private long decodeErrors;
        private long ignoredPackets;
        private float lastPacketRealtime = -1f;
        private float fpsWindowStart;
        private long fpsWindowPackets;
        private bool hasStarted;
        private Transform skeletonRoot;
        private GameObject[] jointObjects;
        private LineRenderer[] boneLines;
        private Material bodyMaterial;
        private Material handMaterial;
        private Vector3[] latestPelvisRelativePoints;
        private bool[] latestPointValidity;
        private int latestPoseRevision;

        /// <summary>
        /// Returns the latest body/hand points after the exact same unit, axis,
        /// whole-pose rotation and pelvis-centering conversion used by the raw
        /// renderer. The arrays are replaced (not mutated) on every new frame,
        /// so consumers on Unity's main thread may safely keep the references
        /// until the next call.
        /// </summary>
        public bool TryGetLatestPelvisRelativePose(
            out Vector3[] points, out bool[] valid, out int revision)
        {
            points = latestPelvisRelativePoints;
            valid = latestPointValidity;
            revision = latestPoseRevision;
            return points != null && valid != null;
        }

        private void Start()
        {
            hasStarted = true;
            if (player == null) player = GetComponent<Smpl0901LivePlayer>();
            if (player != null) rotationOffset = player.livePoseEuler;
            BuildVisuals();
            if (listenOnStart && !requireManualStart) StartListening();
        }

        private void OnEnable()
        {
            if (hasStarted && listenOnStart && !requireManualStart && !IsListening)
                StartListening();
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
                    Name = "SMPL0901-RSV1-Receiver"
                };
                receiveThread.Start();
                Debug.Log($"[SMPL0901] Listening for RSV1 on UDP {listenPort}.", this);
            }
            catch (Exception exception)
            {
                LastError = exception.Message;
                IsListening = false;
                Debug.LogError($"[SMPL0901] RSV1 UDP start failed: {exception.Message}", this);
            }
        }

        public void StopListening()
        {
            receiverRunning = false;
            IsListening = false;
            try { udpClient?.Close(); } catch { }
            udpClient = null;
            if (receiveThread != null && receiveThread.IsAlive) receiveThread.Join(250);
            receiveThread = null;
        }

        public void Reconnect(int port, string serverIp)
        {
            listenPort = Mathf.Clamp(port, 1, 65535);
            allowedServerIp = (serverIp ?? string.Empty).Trim();
            Interlocked.Exchange(ref decodeErrors, 0);
            Interlocked.Exchange(ref ignoredPackets, 0);
            LastError = string.Empty;
            StopListening();
            StartListening();
        }

        public void SetVisible(bool visible)
        {
            renderRawSkeleton = visible;
            if (skeletonRoot != null) skeletonRoot.gameObject.SetActive(visible);
        }

        public void SetAlignmentOffset(Vector3 value)
        {
            alignmentOffset = value;
        }

        public void ResetAlignmentOffset()
        {
            alignmentOffset = Vector3.zero;
        }

        public void ShowPreviewTPose()
        {
            if (skeletonRoot == null) BuildVisuals();
            if (jointObjects == null || boneLines == null) return;

            Vector3[] positions = new Vector3[Rsv1RawSkeletonCodec.JointCount];
            bool[] valid = new bool[Rsv1RawSkeletonCodec.JointCount];
            for (int index = 0; index < valid.Length; index++) valid[index] = true;

            positions[0] = new Vector3(0f, 0.78f, 0f);
            positions[1] = new Vector3(-0.035f, 0.81f, 0f);
            positions[2] = new Vector3(0.035f, 0.81f, 0f);
            positions[3] = new Vector3(-0.085f, 0.79f, 0f);
            positions[4] = new Vector3(0.085f, 0.79f, 0f);
            positions[5] = new Vector3(-0.22f, 0.55f, 0f);
            positions[6] = new Vector3(0.22f, 0.55f, 0f);
            positions[7] = new Vector3(-0.50f, 0.55f, 0f);
            positions[8] = new Vector3(0.50f, 0.55f, 0f);
            positions[9] = new Vector3(-0.78f, 0.55f, 0f);
            positions[10] = new Vector3(0.78f, 0.55f, 0f);
            positions[11] = new Vector3(-0.12f, 0f, 0f);
            positions[12] = new Vector3(0.12f, 0f, 0f);
            positions[13] = new Vector3(-0.12f, -0.45f, 0f);
            positions[14] = new Vector3(0.12f, -0.45f, 0f);
            positions[15] = new Vector3(-0.12f, -0.92f, 0f);
            positions[16] = new Vector3(0.12f, -0.92f, 0f);
            FillPreviewHand(positions, 17, positions[9], -1f);
            FillPreviewHand(positions, 38, positions[10], 1f);

            RenderPositions(positions, valid);
            LatestFrameId = -1;
            LastError = string.Empty;
        }

        private static void FillPreviewHand(
            Vector3[] positions, int offset, Vector3 wrist, float side)
        {
            positions[offset] = wrist;
            int[] starts = { 1, 5, 9, 13, 17 };
            float[] yOffsets = { -0.045f, 0.055f, 0.025f, -0.005f, -0.035f };
            for (int finger = 0; finger < starts.Length; finger++)
            {
                for (int joint = 0; joint < 4; joint++)
                {
                    float length = 0.035f + 0.045f * joint;
                    positions[offset + starts[finger] + joint] = wrist +
                        new Vector3(side * length, yOffsets[finger], 0f);
                }
            }
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
                    // Count immediately after Receive(). A localhost probe must
                    // be visible even when the 192.168.1.250 filter rejects it.
                    Interlocked.Increment(ref receivedPackets);
                    if (allowedServerAddress != null &&
                        !IsMatchingIp(remote.Address, allowedServerAddress))
                    {
                        Interlocked.Increment(ref ignoredPackets);
                        continue;
                    }
                    LastAcceptedSenderIp = remote.Address.ToString();
                    Interlocked.Increment(ref acceptedPackets);
                    if (!Rsv1RawSkeletonCodec.TryDecode(
                            packet, out Rsv1RawSkeletonFrame decoded, out string error))
                    {
                        Interlocked.Increment(ref decodeErrors);
                        LastError = error;
                        continue;
                    }
                    lock (frameLock)
                    {
                        pendingFrame = decoded;
                        hasPendingFrame = true;
                    }
                }
                catch (SocketException)
                {
                    if (receiverRunning) LastError = "RSV1 UDP socket closed unexpectedly.";
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
            if (skeletonRoot == null) BuildVisuals();

            Rsv1RawSkeletonFrame frame = null;
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
                // RSV1 is the direct inference stream and must remain live even
                // while the slower SMPL fit is processing or dropping a frame.
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
            if (!followSmplPelvis || skeletonRoot == null) return;
            if (player == null) player = GetComponent<Smpl0901LivePlayer>();
            if (player == null || player.RuntimePelvis == null) return;
            skeletonRoot.position = player.RuntimePelvis.position +
                transform.TransformVector(alignmentOffset);
            skeletonRoot.rotation = transform.rotation;
        }

        private void BuildVisuals()
        {
            if (skeletonRoot != null) return;
            GameObject rootObject = new GameObject("RSV1_Original_59pt_Skeleton");
            rootObject.transform.SetParent(transform, false);
            skeletonRoot = rootObject.transform;
            Shader shader = Shader.Find("Sprites/Default");
            bodyMaterial = new Material(shader) { color = bodyColor };
            handMaterial = new Material(shader) { color = handColor };

            jointObjects = new GameObject[Rsv1RawSkeletonCodec.JointCount];
            for (int index = 0; index < jointObjects.Length; index++)
            {
                GameObject joint = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                joint.name = $"RSV1_Joint_{index:D2}";
                joint.transform.SetParent(skeletonRoot, false);
                float size = index < 17 ? bodyJointSize : handJointSize;
                joint.transform.localScale = Vector3.one * size;
                Collider collider = joint.GetComponent<Collider>();
                if (collider != null) Destroy(collider);
                MeshRenderer renderer = joint.GetComponent<MeshRenderer>();
                renderer.sharedMaterial = index < 17 ? bodyMaterial : handMaterial;
                jointObjects[index] = joint;
            }

            boneLines = new LineRenderer[Connections.Length];
            for (int index = 0; index < Connections.Length; index++)
            {
                bool hand = Connections[index].x >= 17 || Connections[index].y >= 17;
                GameObject lineObject = new GameObject($"RSV1_Bone_{index:D2}");
                lineObject.transform.SetParent(skeletonRoot, false);
                LineRenderer line = lineObject.AddComponent<LineRenderer>();
                line.useWorldSpace = false;
                line.positionCount = 2;
                line.startWidth = line.endWidth = hand ? handLineWidth : bodyLineWidth;
                line.sharedMaterial = hand ? handMaterial : bodyMaterial;
                boneLines[index] = line;
            }
            if (showTPoseBeforeFirstFrame) ShowPreviewTPose();
            SetVisible(renderRawSkeleton);
        }

        private void ApplyFrame(Rsv1RawSkeletonFrame frame)
        {
            // Transport/decode metadata remains observable even when this is
            // a zero-confidence probe that cannot be rendered.
            LatestFrameId = unchecked((int)frame.frameId);
            LatestPtpEpochNs = frame.ptpEpochNs;
            LatestCoordinateFrame = frame.coordinateFrame;
            float scale = frame.unit == 1 ? 1f : frame.unit == 2 ? 0.001f : unknownUnitScale;
            Vector3[] positions = new Vector3[Rsv1RawSkeletonCodec.JointCount];
            bool[] valid = new bool[Rsv1RawSkeletonCodec.JointCount];
            Quaternion rotOffset = rotationOffset != Vector3.zero ? Quaternion.Euler(rotationOffset) : Quaternion.identity;

            for (int index = 0; index < positions.Length; index++)
            {
                int offset = index * 3;
                float x = frame.points[offset];
                float y = frame.points[offset + 1];
                float z = frame.points[offset + 2];
                valid[index] = frame.confidence[index] >= minimumConfidence &&
                    IsFinite(x) && IsFinite(y) && IsFinite(z);
                Vector3 pos;
                if (useSmplCoordinateConversion)
                {
                    // RSV1 contains original camera points. The bridge fits
                    // (x,-y,z); SUP renders that SMPL coordinate as (-x,z,-y),
                    // therefore the direct raw-to-Unity mapping is (-x,z,y).
                    pos = new Vector3(-x, z, y) * scale;
                }
                else
                {
                    pos = new Vector3(
                        invertX ? -x : x,
                        invertY ? -y : y,
                        invertZ ? -z : z) * scale;
                }
                if (rotationOffset != Vector3.zero)
                {
                    pos = rotOffset * pos;
                }
                positions[index] = pos;
            }
            if (!valid[11] || !valid[12])
            {
                LastError = "RSV1 pelvis joints 11/12 are invalid; holding raw skeleton.";
                return;
            }
            LastError = string.Empty;
            Vector3 pelvis = (positions[11] + positions[12]) * 0.5f;
            for (int index = 0; index < positions.Length; index++)
                positions[index] -= pelvis;
            latestPelvisRelativePoints = positions;
            latestPointValidity = valid;
            latestPoseRevision++;
            RenderPositions(positions, valid);
        }

        private void RenderPositions(Vector3[] positions, bool[] valid)
        {
            for (int index = 0; index < positions.Length; index++)
            {
                jointObjects[index].SetActive(renderRawSkeleton && valid[index]);
                if (valid[index]) jointObjects[index].transform.localPosition = positions[index];
            }
            for (int index = 0; index < Connections.Length; index++)
            {
                int a = Connections[index].x;
                int b = Connections[index].y;
                bool show = renderRawSkeleton && valid[a] && valid[b];
                boneLines[index].enabled = show;
                if (!show) continue;
                boneLines[index].SetPosition(0, positions[a]);
                boneLines[index].SetPosition(1, positions[b]);
            }
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private static Vector2Int[] BuildConnections()
        {
            List<Vector2Int> result = new List<Vector2Int>
            {
                new Vector2Int(0,1), new Vector2Int(0,2), new Vector2Int(1,3),
                new Vector2Int(2,4), new Vector2Int(5,6), new Vector2Int(5,7),
                new Vector2Int(7,9), new Vector2Int(6,8), new Vector2Int(8,10),
                new Vector2Int(5,11), new Vector2Int(6,12), new Vector2Int(11,12),
                new Vector2Int(11,13), new Vector2Int(13,15),
                new Vector2Int(12,14), new Vector2Int(14,16),
                new Vector2Int(9,17), new Vector2Int(10,38)
            };
            AddHand(result, 17);
            AddHand(result, 38);
            return result.ToArray();
        }

        private static void AddHand(List<Vector2Int> result, int offset)
        {
            int[] starts = { 1, 5, 9, 13, 17 };
            foreach (int start in starts)
            {
                result.Add(new Vector2Int(offset, offset + start));
                result.Add(new Vector2Int(offset + start, offset + start + 1));
                result.Add(new Vector2Int(offset + start + 1, offset + start + 2));
                result.Add(new Vector2Int(offset + start + 2, offset + start + 3));
            }
        }

        private void OnDisable() { StopListening(); }

        private void OnDestroy()
        {
            StopListening();
            if (bodyMaterial != null) Destroy(bodyMaterial);
            if (handMaterial != null) Destroy(handMaterial);
        }
    }
}
