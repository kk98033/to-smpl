using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using UnityEngine;

namespace SMPL0901Player.Runtime
{
    public class Smpl0901TrackingPanel : MonoBehaviour
    {
        public Smpl0901LivePlayer player;
        public Rsv1RawSkeletonRenderer rawSkeleton;
        public Smpl0901FittedSkeletonRenderer fittedSkeleton;
        public Smpl0901DirectJointBaseline directJointBaseline;
        public bool visible = true;
        public bool showDebugDetails = false;
        public Vector2 screenPosition = new Vector2(15f, 15f);
        public Vector2 panelSize = new Vector2(690f, 580f);

        private ProtocolV2Frame latest;
        private GUIStyle labelStyle;
        private string serverIpText;
        private string smv2PortText;
        private string rsv1PortText;
        private string localIpv4Text;

        public void SetFrame(ProtocolV2Frame frame)
        {
            latest = frame;
        }

        void OnGUI()
        {
            if (!visible) return;
            if (labelStyle == null)
            {
                labelStyle = new GUIStyle(GUI.skin.label) { fontSize = 15, richText = true };
            }
            if (player == null) player = GetComponent<Smpl0901LivePlayer>();
            if (rawSkeleton == null) rawSkeleton = GetComponent<Rsv1RawSkeletonRenderer>();
            if (fittedSkeleton == null)
                fittedSkeleton = GetComponent<Smpl0901FittedSkeletonRenderer>();
            if (directJointBaseline == null)
                directJointBaseline = GetComponent<Smpl0901DirectJointBaseline>();
            if (serverIpText == null)
                serverIpText = player != null ? player.allowedServerIp : string.Empty;
            if (smv2PortText == null && player != null)
                smv2PortText = player.listenPort.ToString();
            if (rsv1PortText == null && rawSkeleton != null)
                rsv1PortText = rawSkeleton.listenPort.ToString();
            if (localIpv4Text == null) localIpv4Text = FindLocalIpv4Addresses();

            float width = Mathf.Max(690f, panelSize.x);
            float height = showDebugDetails ? Mathf.Max(614f, panelSize.y) : 304f;
            Rect panel = new Rect(screenPosition.x, screenPosition.y, width, height);
            GUI.Box(panel, "SMPL 0901 Live Player");

            // Keep the three requested rendering choices at the very top so
            // an older serialized panel size cannot hide them.
            float toggleY = panel.y + 27f;
            if (player != null)
            {
                bool showMesh = GUI.Toggle(
                    new Rect(panel.x + 14, toggleY, 150, 24),
                    player.renderCharacter, "Show SMPL Mesh");
                if (showMesh != player.renderCharacter) player.SetCharacterVisible(showMesh);
            }
            if (fittedSkeleton != null)
            {
                bool showFitted = GUI.Toggle(
                    new Rect(panel.x + 180, toggleY, 180, 24),
                    fittedSkeleton.renderFittedSkeleton, "Show Fitted Skeleton");
                if (showFitted != fittedSkeleton.renderFittedSkeleton)
                    fittedSkeleton.SetVisible(showFitted);
            }
            if (rawSkeleton != null)
            {
                bool showRaw = GUI.Toggle(
                    new Rect(panel.x + 375, toggleY, 190, 24),
                    rawSkeleton.renderRawSkeleton, "Show Raw 59pt Skeleton");
                if (showRaw != rawSkeleton.renderRawSkeleton) rawSkeleton.SetVisible(showRaw);
            }
            showDebugDetails = GUI.Toggle(
                new Rect(panel.x + 580, toggleY, 100, 24),
                showDebugDetails, "Show Debug");

            float configY = panel.y + 58f;
            GUI.Label(new Rect(panel.x + 14, configY, 82, 24), "Server IP");
            serverIpText = GUI.TextField(
                new Rect(panel.x + 92, configY, 165, 24),
                serverIpText ?? "192.168.1.250");
            GUI.Label(new Rect(panel.x + 270, configY, 78, 24), "SMV2 port");
            smv2PortText = GUI.TextField(
                new Rect(panel.x + 345, configY, 65, 24), smv2PortText ?? "9095");
            GUI.Label(new Rect(panel.x + 420, configY, 72, 24), "RSV1 port");
            rsv1PortText = GUI.TextField(
                new Rect(panel.x + 490, configY, 65, 24), rsv1PortText ?? "9096");

            float buttonY = configY + 31f;
            if (GUI.Button(new Rect(panel.x + 14, buttonY, 145, 26), "Start Receiving") &&
                player != null && rawSkeleton != null &&
                int.TryParse(smv2PortText, out int smv2Port) &&
                int.TryParse(rsv1PortText, out int rsv1Port))
            {
                player.Reconnect(smv2Port, serverIpText);
                rawSkeleton.Reconnect(rsv1Port, serverIpText);
            }
            if (GUI.Button(new Rect(panel.x + 170, buttonY, 105, 26), "Stop Receiving"))
            {
                if (player != null)
                {
                    player.StopListening();
                    player.ShowTPose();
                }
                if (rawSkeleton != null)
                {
                    rawSkeleton.StopListening();
                    rawSkeleton.ShowPreviewTPose();
                }
                if (directJointBaseline != null) directJointBaseline.ShowBindPose();
                latest = null;
            }
            if (GUI.Button(new Rect(panel.x + 286, buttonY, 140, 26), "Reset Root Anchor") &&
                player != null)
                player.ResetRootAnchor();
            if (GUI.Button(new Rect(panel.x + 437, buttonY, 120, 26), "Accept Any IP"))
            {
                serverIpText = string.Empty;
            }
            if (directJointBaseline != null)
            {
                bool showBaseline = GUI.Toggle(
                    new Rect(panel.x + 568, buttonY, 112, 26),
                    directJointBaseline.renderBaseline, "XYZ Baseline");
                if (showBaseline != directJointBaseline.renderBaseline)
                    directJointBaseline.SetVisible(showBaseline);
            }

            float placementY = buttonY + 34f;
            GUI.Label(new Rect(panel.x + 14, placementY, 72, 24), "Player Pos");
            if (player != null && player.rootMotion != null)
            {
                Vector3 offset = player.rootMotion.manualOffset;
                Vector3 adjusted = new Vector3(
                    DrawOffsetSlider(new Rect(panel.x + 84, placementY, 145, 24), "X", offset.x),
                    DrawOffsetSlider(new Rect(panel.x + 238, placementY, 145, 24), "Y", offset.y),
                    DrawOffsetSlider(new Rect(panel.x + 392, placementY, 145, 24), "Z", offset.z));
                if ((adjusted - offset).sqrMagnitude > 1e-8f)
                    player.rootMotion.SetManualOffset(adjusted);
                if (GUI.Button(new Rect(panel.x + 548, placementY - 1f, 126, 25), "Reset Position"))
                    player.rootMotion.ResetManualOffset();
            }

            float rawPlacementY = placementY + 34f;
            GUI.Label(new Rect(panel.x + 14, rawPlacementY, 72, 24), "Raw Offset");
            if (rawSkeleton != null)
            {
                Vector3 rawOffset = rawSkeleton.alignmentOffset;
                Vector3 adjustedRaw = new Vector3(
                    DrawOffsetSlider(new Rect(panel.x + 84, rawPlacementY, 145, 24), "X", rawOffset.x),
                    DrawOffsetSlider(new Rect(panel.x + 238, rawPlacementY, 145, 24), "Y", rawOffset.y),
                    DrawOffsetSlider(new Rect(panel.x + 392, rawPlacementY, 145, 24), "Z", rawOffset.z));
                if ((adjustedRaw - rawOffset).sqrMagnitude > 1e-8f)
                    rawSkeleton.SetAlignmentOffset(adjustedRaw);
                if (GUI.Button(new Rect(panel.x + 548, rawPlacementY - 1f, 126, 25), "Reset Raw Offset"))
                    rawSkeleton.ResetAlignmentOffset();
            }

            float baselinePlacementY = rawPlacementY + 34f;
            GUI.Label(new Rect(panel.x + 14, baselinePlacementY, 72, 24), "Base Offset");
            if (directJointBaseline != null)
            {
                Vector3 baselineOffset = directJointBaseline.baselineOffset;
                Vector3 adjustedBaseline = new Vector3(
                    DrawOffsetSlider(new Rect(panel.x + 84, baselinePlacementY, 145, 24), "X", baselineOffset.x),
                    DrawOffsetSlider(new Rect(panel.x + 238, baselinePlacementY, 145, 24), "Y", baselineOffset.y),
                    DrawOffsetSlider(new Rect(panel.x + 392, baselinePlacementY, 145, 24), "Z", baselineOffset.z));
                if ((adjustedBaseline - baselineOffset).sqrMagnitude > 1e-8f)
                    directJointBaseline.SetBaselineOffset(adjustedBaseline);
                if (GUI.Button(new Rect(panel.x + 548, baselinePlacementY - 1f, 126, 25), "Reset Baseline"))
                    directJointBaseline.ResetBaselineOffset();
            }

            float rotationY = baselinePlacementY + 34f;
            GUI.Label(new Rect(panel.x + 14, rotationY, 72, 24), "Live Pose Rot");
            if (player != null && rawSkeleton != null)
            {
                Vector3 sourceEuler = player.livePoseEuler;
                Vector3 adjustedEuler = new Vector3(
                    DrawAngleSlider(new Rect(panel.x + 84, rotationY, 145, 24), "X", sourceEuler.x),
                    DrawAngleSlider(new Rect(panel.x + 238, rotationY, 145, 24), "Y", sourceEuler.y),
                    DrawAngleSlider(new Rect(panel.x + 392, rotationY, 145, 24), "Z", sourceEuler.z));
                if ((adjustedEuler - sourceEuler).sqrMagnitude > 1e-6f)
                {
                    player.livePoseEuler = adjustedEuler;
                    rawSkeleton.rotationOffset = adjustedEuler;
                }
                if (GUI.Button(new Rect(panel.x + 548, rotationY - 1f, 126, 25), "Reset Rotation"))
                {
                    Vector3 defaultEuler = new Vector3(0f, 0f, 90f);
                    player.livePoseEuler = defaultEuler;
                    rawSkeleton.rotationOffset = defaultEuler;
                }
            }

            float displayRotationY = rotationY + 34f;
            GUI.Label(new Rect(panel.x + 14, displayRotationY, 72, 24), "Display Rot");
            if (player != null && player.rootMotion != null)
            {
                Vector3 displayEuler = player.rootMotion.displayEuler;
                Vector3 adjustedDisplayEuler = new Vector3(
                    DrawAngleSlider(new Rect(panel.x + 84, displayRotationY, 145, 24), "X", displayEuler.x),
                    DrawAngleSlider(new Rect(panel.x + 238, displayRotationY, 145, 24), "Y", displayEuler.y),
                    DrawAngleSlider(new Rect(panel.x + 392, displayRotationY, 145, 24), "Z", displayEuler.z));
                if ((adjustedDisplayEuler - displayEuler).sqrMagnitude > 1e-6f)
                    player.rootMotion.SetDisplayEuler(adjustedDisplayEuler);
                if (GUI.Button(new Rect(panel.x + 548, displayRotationY - 1f, 126, 25), "Face Camera"))
                    player.rootMotion.ResetDisplayEuler();
            }

            if (!showDebugDetails) return;

            string smv2Connection = player != null && player.IsListening ? "LISTENING" : "STOPPED";
            string smv2Age = player == null || float.IsPositiveInfinity(player.SecondsSinceLastPacket)
                ? "--" : $"{player.SecondsSinceLastPacket:F2}s";
            string rawConnection = rawSkeleton != null && rawSkeleton.IsListening
                ? "LISTENING" : "STOPPED";
            string rawAge = rawSkeleton == null ||
                float.IsPositiveInfinity(rawSkeleton.SecondsSinceLastPacket)
                ? "--" : $"{rawSkeleton.SecondsSinceLastPacket:F2}s";
            string qualityText = "Waiting for first SMV2 frame...";
            if (latest != null && latest.quality != null)
            {
                ProtocolV2Quality quality = latest.quality;
                string color = quality.solverState == "TRACKING" || quality.solverState == "RECOVERED"
                    ? "#43d17c" : "#ff6b6b";
                qualityText =
                    $"Frame: {latest.frameId} / State: <color={color}>{quality.solverState}</color>\n" +
                    $"Input: {quality.inputValid} / {quality.inputScore:F2}\n" +
                    $"Residual: {quality.fitResidualMm:F1} mm (worst {quality.worstJointResidualMm:F1})\n" +
                    $"Torso: {quality.torsoOrientationDeg:F1} deg / Steps: {quality.stepsUsed}";
            }
            string smv2Transport = player == null ? "SMV2 player missing" :
                $"SMV2 {player.BoundEndpoint}  {smv2Connection}  {player.ReceiveFps:F1} FPS  age {smv2Age}\n" +
                $"  observed={DisplayIp(player.LastObservedSenderIp)}, " +
                $"acceptedFrom={DisplayIp(player.LastAcceptedSenderIp)}, received={player.ReceivedPackets}, " +
                $"accepted={player.AcceptedPackets}, " +
                $"ignored={player.IgnoredPackets}, decodeErrors={player.DecodeErrors}";
            string rawTransport = rawSkeleton == null ? "RSV1 receiver missing" :
                $"RSV1 {rawSkeleton.BoundEndpoint}  {rawConnection}  {rawSkeleton.ReceiveFps:F1} FPS  age {rawAge}\n" +
                $"  observed={DisplayIp(rawSkeleton.LastObservedSenderIp)}, " +
                $"acceptedFrom={DisplayIp(rawSkeleton.LastAcceptedSenderIp)}, frame={rawSkeleton.LatestFrameId}, " +
                $"received={rawSkeleton.ReceivedPackets}, accepted={rawSkeleton.AcceptedPackets}, " +
                $"ignored={rawSkeleton.IgnoredPackets}, " +
                $"decodeErrors={rawSkeleton.DecodeErrors}";

            float statusY = displayRotationY + 34f;
            GUI.Label(
                new Rect(panel.x + 14, statusY, panel.width - 28, 220f),
                $"Unity local IPv4: {localIpv4Text}\n" +
                $"Filter: {(string.IsNullOrWhiteSpace(serverIpText) ? "ANY" : serverIpText)}\n" +
                smv2Transport + "\n" + rawTransport + "\n" + qualityText + "\n" +
                $"Binding: {(player != null ? player.BindingStatus : "--")}\n" +
                $"Player offset: {FormatVector(player != null && player.rootMotion != null ? player.rootMotion.manualOffset : Vector3.zero)}  " +
                $"Live pose rot: {FormatVector(player != null ? player.livePoseEuler : Vector3.zero)}  " +
                $"Display rot: {FormatVector(player != null && player.rootMotion != null ? player.rootMotion.displayEuler : Vector3.zero)}  " +
                $"Raw offset: {FormatVector(rawSkeleton != null ? rawSkeleton.alignmentOffset : Vector3.zero)}",
                labelStyle);

            string debug = BuildDebugMessage();
            GUI.Label(
                new Rect(panel.x + 14, panel.y + panel.height - 62f, panel.width - 28, 52f),
                debug, labelStyle);
            DrawBoneDebugPanel(panel);
        }

        private void DrawBoneDebugPanel(Rect parentPanel)
        {
            if (player == null) return;
            Rect panel = new Rect(
                parentPanel.x, parentPanel.y + parentPanel.height + 8f,
                parentPanel.width, 218f);
            GUI.Box(panel, "SMPL Bone Isolation Debug");

            bool enabled = GUI.Toggle(
                new Rect(panel.x + 14, panel.y + 27f, 260f, 24f),
                player.BoneDebugMode,
                "Isolate one body bone (pause full pose)");
            if (enabled != player.BoneDebugMode)
                player.SetBoneDebugMode(enabled);
            if (!player.BoneDebugMode)
            {
                GUI.Label(
                    new Rect(panel.x + 285f, panel.y + 27f, 385f, 24f),
                    "Enable this to test the SUP rig one joint at a time.");
                return;
            }

            float jointY = panel.y + 57f;
            if (GUI.Button(new Rect(panel.x + 14f, jointY, 80f, 26f), "< Prev"))
                player.StepDebugBone(-1);
            GUI.Label(
                new Rect(panel.x + 105f, jointY + 2f, 310f, 24f),
                $"Joint {player.DebugBoneIndex:D2}: {player.DebugBoneName}", labelStyle);
            if (GUI.Button(new Rect(panel.x + 425f, jointY, 80f, 26f), "Next >"))
                player.StepDebugBone(1);

            Vector3 received = player.DebugReceivedRotvec;
            GUI.Label(
                new Rect(panel.x + 14f, panel.y + 88f, 655f, 24f),
                $"Latest server rotvec rad: ({received.x:F3}, {received.y:F3}, {received.z:F3})  " +
                $"magnitude: {player.DebugReceivedAngleDeg:F1} deg");

            bool useReceived = GUI.Toggle(
                new Rect(panel.x + 14f, panel.y + 116f, 300f, 24f),
                player.DebugUseReceivedRotation,
                "Use latest received rotvec for this bone");
            if (useReceived != player.DebugUseReceivedRotation)
                player.SetDebugUseReceivedRotation(useReceived);
            bool usePrefix = GUI.Toggle(
                new Rect(panel.x + 335f, panel.y + 116f, 335f, 24f),
                player.DebugApplyReceivedThroughSelected,
                "Apply received joints 0..selected");
            if (usePrefix != player.DebugApplyReceivedThroughSelected)
                player.SetDebugApplyReceivedThroughSelected(usePrefix);

            float rotationY = panel.y + 145f;
            GUI.Label(new Rect(panel.x + 14f, rotationY, 72f, 24f), "Manual Rot");
            Vector3 current = player.DebugBoneEuler;
            Vector3 adjusted = new Vector3(
                DrawDebugAngleSlider(new Rect(panel.x + 84f, rotationY, 145f, 24f), "X", current.x),
                DrawDebugAngleSlider(new Rect(panel.x + 238f, rotationY, 145f, 24f), "Y", current.y),
                DrawDebugAngleSlider(new Rect(panel.x + 392f, rotationY, 145f, 24f), "Z", current.z));
            if (!player.DebugUseReceivedRotation &&
                !player.DebugApplyReceivedThroughSelected &&
                (adjusted - current).sqrMagnitude > 1e-6f)
                player.SetDebugBoneEuler(adjusted);

            if (GUI.Button(
                    new Rect(panel.x + 548f, rotationY - 1f, 126f, 25f),
                    "Reset Joint"))
                player.ResetDebugBoneRotation();

            GUI.Label(
                new Rect(panel.x + 14f, panel.y + 180f, 660f, 28f),
                "Use 0..selected and press Next: the first step that distorts identifies the failing joint/parent chain.");
        }

        private static float DrawOffsetSlider(Rect rect, string axis, float value)
        {
            GUI.Label(new Rect(rect.x, rect.y, 18f, rect.height), axis);
            float result = GUI.HorizontalSlider(
                new Rect(rect.x + 18f, rect.y + 6f, 82f, 16f), value, -5f, 5f);
            GUI.Label(new Rect(rect.x + 104f, rect.y, 45f, rect.height), result.ToString("F2"));
            return result;
        }

        private static float DrawAngleSlider(Rect rect, string axis, float value)
        {
            GUI.Label(new Rect(rect.x, rect.y, 18f, rect.height), axis);
            float result = GUI.HorizontalSlider(
                new Rect(rect.x + 18f, rect.y + 6f, 82f, 16f), value, -180f, 180f);
            GUI.Label(new Rect(rect.x + 104f, rect.y, 45f, rect.height), result.ToString("F0"));
            return result;
        }

        private static float DrawDebugAngleSlider(Rect rect, string axis, float value)
        {
            GUI.Label(new Rect(rect.x, rect.y, 18f, rect.height), axis);
            float result = GUI.HorizontalSlider(
                new Rect(rect.x + 18f, rect.y + 6f, 82f, 16f), value, -60f, 60f);
            GUI.Label(new Rect(rect.x + 104f, rect.y, 45f, rect.height), result.ToString("F0"));
            return result;
        }

        private static string FormatVector(Vector3 value)
        {
            return $"({value.x:F2}, {value.y:F2}, {value.z:F2})";
        }

        private string BuildDebugMessage()
        {
            if (player == null || rawSkeleton == null)
                return "<color=#ff6b6b>DEBUG: Re-run SMPL 0901/Create Live Player in Scene.</color>";
            if (!player.IsListening && !rawSkeleton.IsListening)
                return "<color=#7dd3fc>READY: T-pose preview. Adjust position/rotation, then press Start Receiving.</color>";
            if (!player.IsListening || !rawSkeleton.IsListening)
            {
                string error = !string.IsNullOrEmpty(player.LastError)
                    ? player.LastError : rawSkeleton.LastError;
                return $"<color=#ff6b6b>DEBUG: receiver stopped. {error}</color>";
            }
            if (player.IgnoredPackets > 0 || rawSkeleton.IgnoredPackets > 0)
                return "<color=#ffb347>DEBUG: packets observed but rejected by Server IP filter. Check 192.168.1.250 or press Accept Any IP.</color>";
            if (player.DecodeErrors > 0 || rawSkeleton.DecodeErrors > 0)
                return "<color=#ff6b6b>DEBUG: packet reached Unity but binary format/length was rejected. Check SMV2=1389 and RSV1=1032.</color>";
            if (player.ReceivedPackets == 0 && rawSkeleton.ReceivedPackets == 0)
                return "<color=#ffb347>DEBUG: no UDP seen. Server must send to a Unity local IPv4 above; allow inbound UDP 9095/9096 in Windows Firewall.</color>";
            if (player.ReceivedPackets == 0)
                return "<color=#ffb347>DEBUG: RSV1 arrives, but no SMV2 on 9095. Check bridge --unity-host and --unity-port.</color>";
            if (rawSkeleton.ReceivedPackets == 0)
                return "<color=#ffb347>DEBUG: SMV2 arrives, but no RSV1 on 9096. Check the raw-skeleton sender destination.</color>";
            if (!string.IsNullOrEmpty(rawSkeleton.LastError))
                return $"<color=#ffb347>DEBUG: RSV1 transport/decode works, but renderer held the frame: {rawSkeleton.LastError}</color>";
            return "<color=#43d17c>DEBUG: both SMV2 and RSV1 are receiving.</color>";
        }

        private static string DisplayIp(string value)
        {
            return string.IsNullOrEmpty(value) ? "--" : value;
        }

        private static string FindLocalIpv4Addresses()
        {
            try
            {
                List<string> values = new List<string>();
                foreach (IPAddress address in Dns.GetHostAddresses(Dns.GetHostName()))
                {
                    if (address.AddressFamily == AddressFamily.InterNetwork &&
                        !IPAddress.IsLoopback(address))
                        values.Add(address.ToString());
                }
                return values.Count > 0 ? string.Join(", ", values) : "none";
            }
            catch (System.Exception exception)
            {
                return "lookup failed: " + exception.Message;
            }
        }
    }
}
