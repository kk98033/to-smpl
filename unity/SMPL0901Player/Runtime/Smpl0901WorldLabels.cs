using UnityEngine;

namespace SMPL0901Player.Runtime
{
    /// <summary>
    /// Display-only world labels for the two comparison avatars. The labels
    /// follow pelvis positions and billboard toward the active camera.
    /// </summary>
    public sealed class Smpl0901WorldLabels : MonoBehaviour
    {
        public Smpl0901LivePlayer player;
        public Smpl0901DirectJointBaseline rawAvatar;
        public string smplLabel = "SMPL FITTED AVATAR";
        public string rawLabel = "RAW 59PT AVATAR";
        public Vector3 labelOffset = new Vector3(0f, 1.25f, 0f);
        public Color smplColor = new Color(0.20f, 0.88f, 1f, 1f);
        public Color rawColor = new Color(1f, 0.64f, 0.18f, 1f);

        private TextMesh smplText;
        private TextMesh rawText;

        private void Start()
        {
            ResolveSources();
            smplText = CreateLabel("SMPL0901_Label_SMPL", smplLabel, smplColor);
            rawText = CreateLabel("SMPL0901_Label_RawAvatar", rawLabel, rawColor);
        }

        private void LateUpdate()
        {
            ResolveSources();
            Camera camera = Camera.main;
            UpdateLabel(
                smplText,
                player != null ? player.RuntimePelvis : null,
                player != null && player.renderCharacter,
                camera);
            UpdateLabel(
                rawText,
                rawAvatar != null ? rawAvatar.RuntimePelvis : null,
                rawAvatar != null && rawAvatar.renderBaseline,
                camera);
        }

        private void ResolveSources()
        {
            if (player == null) player = GetComponent<Smpl0901LivePlayer>();
            if (rawAvatar == null)
                rawAvatar = GetComponent<Smpl0901DirectJointBaseline>();
        }

        private TextMesh CreateLabel(string objectName, string content, Color color)
        {
            GameObject labelObject = new GameObject(objectName);
            labelObject.transform.SetParent(transform, false);
            TextMesh text = labelObject.AddComponent<TextMesh>();
            text.text = content;
            text.anchor = TextAnchor.MiddleCenter;
            text.alignment = TextAlignment.Center;
            text.fontSize = 64;
            text.characterSize = 0.018f;
            text.color = color;
            return text;
        }

        private void UpdateLabel(
            TextMesh label, Transform anchor, bool requestedVisible, Camera camera)
        {
            if (label == null) return;
            bool show = requestedVisible && anchor != null;
            label.gameObject.SetActive(show);
            if (!show) return;
            label.transform.position = anchor.position + labelOffset;
            if (camera != null)
                label.transform.rotation = camera.transform.rotation;
        }
    }
}
