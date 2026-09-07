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
        public bool visible = true;
        public Vector2 screenPosition = new Vector2(15f, 15f);
        public Vector2 panelSize = new Vector2(500f, 390f);

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
            if (serverIpText == null)
                serverIpText = player != null ? player.allowedServerIp : string.Empty;
            if (smv2PortText == null && player != null)
                smv2PortText = player.listenPort.ToString();
            if (rsv1PortText == null && rawSkeleton != null)
                rsv1PortText = rawSkeleton.listenPort.ToString();
            if (localIpv4Text == null) localIpv4Text = FindLocalIpv4Addresses();

            float width = Mathf.Max(580f, panelSize.x);
            float height = Mathf.Max(445f, panelSize.y);
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
            if (GUI.Button(new Rect(panel.x + 14, buttonY, 145, 26), "Reconnect Both") &&
                player != null && rawSkeleton != null &&
                int.TryParse(smv2PortText, out int smv2Port) &&
                int.TryParse(rsv1PortText, out int rsv1Port))
            {
                player.Reconnect(smv2Port, serverIpText);
                rawSkeleton.Reconnect(rsv1Port, serverIpText);
            }
            if (GUI.Button(new Rect(panel.x + 170, buttonY, 145, 26), "Reset Root Anchor") &&
                player != null)
                player.ResetRootAnchor();
            if (GUI.Button(new Rect(panel.x + 326, buttonY, 130, 26), "Accept Any IP"))
            {
                serverIpText = string.Empty;
                if (player != null && rawSkeleton != null &&
                    int.TryParse(smv2PortText, out int anySmv2Port) &&
                    int.TryParse(rsv1PortText, out int anyRsv1Port))
                {
                    player.Reconnect(anySmv2Port, string.Empty);
                    rawSkeleton.Reconnect(anyRsv1Port, string.Empty);
                }
            }

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

            float statusY = buttonY + 36f;
            GUI.Label(
                new Rect(panel.x + 14, statusY, panel.width - 28, 220f),
                $"Unity local IPv4: {localIpv4Text}\n" +
                $"Filter: {(string.IsNullOrWhiteSpace(serverIpText) ? "ANY" : serverIpText)}\n" +
                smv2Transport + "\n" + rawTransport + "\n" + qualityText,
                labelStyle);

            string debug = BuildDebugMessage();
            GUI.Label(
                new Rect(panel.x + 14, panel.y + panel.height - 62f, panel.width - 28, 52f),
                debug, labelStyle);
        }

        private string BuildDebugMessage()
        {
            if (player == null || rawSkeleton == null)
                return "<color=#ff6b6b>DEBUG: Re-run SMPL 0901/Create Live Player in Scene.</color>";
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
