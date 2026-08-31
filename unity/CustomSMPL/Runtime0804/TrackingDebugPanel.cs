using UnityEngine;

namespace CustomSMPL.Runtime0804
{
    public class TrackingDebugPanel : MonoBehaviour
    {
        public bool visible = true;
        public Vector2 screenPosition = new Vector2(15f, 15f);
        public Vector2 panelSize = new Vector2(380f, 165f);

        private ProtocolV2Frame latest;
        private GUIStyle labelStyle;

        public void SetFrame(ProtocolV2Frame frame)
        {
            latest = frame;
        }

        void OnGUI()
        {
            if (!visible || latest == null || latest.quality == null) return;
            if (labelStyle == null)
            {
                labelStyle = new GUIStyle(GUI.skin.label) { fontSize = 15, richText = true };
            }
            Rect panel = new Rect(screenPosition.x, screenPosition.y, panelSize.x, panelSize.y);
            GUI.Box(panel, "Tracking Quality");
            ProtocolV2Quality quality = latest.quality;
            string color = quality.solverState == "TRACKING" || quality.solverState == "RECOVERED" ? "#43d17c" : "#ff6b6b";
            string text =
                $"Frame: {latest.frameId}\n" +
                $"State: <color={color}>{quality.solverState}</color>\n" +
                $"Input: {quality.inputValid} / {quality.inputScore:F2}\n" +
                $"Residual: {quality.fitResidualMm:F1} mm (worst {quality.worstJointResidualMm:F1})\n" +
                $"Torso: {quality.torsoOrientationDeg:F1} deg / Steps: {quality.stepsUsed}";
            GUI.Label(new Rect(panel.x + 12, panel.y + 25, panel.width - 24, panel.height - 30), text, labelStyle);
        }
    }
}
