using UnityEngine;

namespace SMPL0901Player.Runtime
{
    public class Smpl0901RootMotionDriver : MonoBehaviour
    {
        [Header("Target")]
        public Transform runtimeRoot;

        [Header("Source to Unity calibration")]
        public bool invertSourceX = true;
        public bool applyVertical = false;
        public float sourceScale = 1f;
        public Vector3 calibrationEuler = Vector3.zero;

        [Header("Stability")]
        [Range(0f, 1f)] public float minimumConfidence = 0.5f;
        public float deadZoneMeters = 0.01f;
        public float smoothingSpeed = 12f;

        public Vector3 LatestAppliedPosition { get; private set; }

        private Vector3 unityAnchor;
        private bool initialized;

        void Awake()
        {
            InitializeIfNeeded();
        }

        public void ResetAnchor()
        {
            initialized = false;
            InitializeIfNeeded();
        }

        public void ResetAnchor(Vector3 worldAnchor)
        {
            if (runtimeRoot == null) runtimeRoot = transform;
            runtimeRoot.position = worldAnchor;
            unityAnchor = worldAnchor;
            LatestAppliedPosition = worldAnchor;
            initialized = true;
        }

        private void InitializeIfNeeded()
        {
            if (runtimeRoot == null) runtimeRoot = transform;
            if (initialized || runtimeRoot == null) return;
            unityAnchor = runtimeRoot.position;
            LatestAppliedPosition = unityAnchor;
            initialized = true;
        }

        public void ApplyFrame(float[] anchoredRootPosition, float confidence, bool inputValid)
        {
            InitializeIfNeeded();
            if (!initialized || anchoredRootPosition == null || anchoredRootPosition.Length < 3) return;
            if (!inputValid || confidence < minimumConfidence) return;

            Vector3 source = new Vector3(anchoredRootPosition[0], anchoredRootPosition[1], anchoredRootPosition[2]);
            if (invertSourceX) source.x = -source.x;
            if (!applyVertical) source.y = 0f;
            if (Mathf.Abs(source.x) < deadZoneMeters) source.x = 0f;
            if (Mathf.Abs(source.y) < deadZoneMeters) source.y = 0f;
            if (Mathf.Abs(source.z) < deadZoneMeters) source.z = 0f;

            Vector3 calibrated = Quaternion.Euler(calibrationEuler) * (source * sourceScale);
            Vector3 target = unityAnchor + calibrated;
            float blend = 1f - Mathf.Exp(-Mathf.Max(0.01f, smoothingSpeed) * Time.deltaTime);
            runtimeRoot.position = Vector3.Lerp(runtimeRoot.position, target, blend);
            LatestAppliedPosition = runtimeRoot.position;
        }
    }
}
