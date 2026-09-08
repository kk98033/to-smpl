using UnityEngine;

namespace SMPL0901Player.Runtime
{
    public class Smpl0901RootMotionDriver : MonoBehaviour
    {
        [Header("Target")]
        public Transform runtimeRoot;

        [Header("Source to Unity calibration")]
        [Tooltip("Convert fitted SMPL (x,y,z) to the SUP Unity basis (-x,z,-y).")]
        public bool useSmplCoordinateConversion = false;
        public bool invertSourceX = true;
        public bool applyVertical = false;
        public float sourceScale = 1f;
        public Vector3 calibrationEuler = Vector3.zero;

        [Header("Manual placement")]
        [Tooltip("User-controlled Unity world offset, applied after tracked root motion.")]
        public Vector3 manualOffset = Vector3.zero;
        [Tooltip("Whole-player orientation. Y=180 faces the camera and also applies to the preview T-pose.")]
        public Vector3 displayEuler = new Vector3(0f, 180f, 0f);

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
            ApplyDisplayRotation();
        }

        public void ResetAnchor()
        {
            if (runtimeRoot == null) runtimeRoot = transform;
            unityAnchor = runtimeRoot.position - manualOffset;
            LatestAppliedPosition = runtimeRoot.position;
            initialized = true;
        }

        public void ResetAnchor(Vector3 worldAnchor)
        {
            if (runtimeRoot == null) runtimeRoot = transform;
            runtimeRoot.position = worldAnchor + manualOffset;
            unityAnchor = worldAnchor;
            LatestAppliedPosition = runtimeRoot.position;
            initialized = true;
        }

        public void SetManualOffset(Vector3 value)
        {
            if (runtimeRoot == null) runtimeRoot = transform;
            Vector3 delta = value - manualOffset;
            manualOffset = value;
            if (runtimeRoot != null) runtimeRoot.position += delta;
            LatestAppliedPosition = runtimeRoot != null ? runtimeRoot.position : value;
        }

        public void ResetManualOffset()
        {
            SetManualOffset(Vector3.zero);
        }

        public void SetDisplayEuler(Vector3 value)
        {
            displayEuler = value;
            ApplyDisplayRotation();
        }

        public void ResetDisplayEuler()
        {
            SetDisplayEuler(new Vector3(0f, 180f, 0f));
        }

        private void ApplyDisplayRotation()
        {
            if (runtimeRoot == null) runtimeRoot = transform;
            if (runtimeRoot != null) runtimeRoot.rotation = Quaternion.Euler(displayEuler);
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

            Vector3 source = useSmplCoordinateConversion
                ? new Vector3(-anchoredRootPosition[0], anchoredRootPosition[2], -anchoredRootPosition[1])
                : new Vector3(anchoredRootPosition[0], anchoredRootPosition[1], anchoredRootPosition[2]);
            if (!useSmplCoordinateConversion && invertSourceX) source.x = -source.x;
            if (!applyVertical) source.y = 0f;
            if (Mathf.Abs(source.x) < deadZoneMeters) source.x = 0f;
            if (Mathf.Abs(source.y) < deadZoneMeters) source.y = 0f;
            if (Mathf.Abs(source.z) < deadZoneMeters) source.z = 0f;

            Vector3 calibrated = Quaternion.Euler(calibrationEuler) * (source * sourceScale);
            Vector3 target = unityAnchor + calibrated + manualOffset;
            float blend = 1f - Mathf.Exp(-Mathf.Max(0.01f, smoothingSpeed) * Time.deltaTime);
            runtimeRoot.position = Vector3.Lerp(runtimeRoot.position, target, blend);
            LatestAppliedPosition = runtimeRoot.position;
        }
    }
}
