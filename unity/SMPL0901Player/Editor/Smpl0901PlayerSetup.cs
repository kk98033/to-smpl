using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using SMPL0901Player.Runtime;

namespace SMPL0901Player.Editor
{
    public static class Smpl0901PlayerSetup
    {
        private const string ObjectName = "SMPL0901_LivePlayer";
        private const string TestReceiverName = "UDP_Test_Receiver";

        [MenuItem("SMPL 0901/Create UDP Test Receiver in Scene")]
        public static void CreateUdpTestReceiver()
        {
            GameObject target = GameObject.Find(TestReceiverName);
            if (target == null)
            {
                target = new GameObject(TestReceiverName);
                Undo.RegisterCreatedObjectUndo(target, "Create UDP Test Receiver");
            }

            UdpTestReceiver receiver = GetOrAdd<UdpTestReceiver>(target);
            receiver.listenPort = 19095;
            receiver.listenOnStart = true;
            receiver.showGui = true;

            EditorUtility.SetDirty(receiver);
            EditorSceneManager.MarkSceneDirty(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Selection.activeGameObject = target;
            Debug.Log("[SMPL0901] Standalone UDP Test Receiver created on UDP 19095.", target);
        }

        [MenuItem("SMPL 0901/Create Live Player in Scene")]
        public static void CreateOrRepairPlayer()
        {
            WarnAboutLegacyReceiver("RealtimePipeline_Player");
            WarnAboutLegacyReceiver("0818_Realtime_Player");
            GameObject target = GameObject.Find(ObjectName);
            if (target == null)
            {
                target = new GameObject(ObjectName);
                Undo.RegisterCreatedObjectUndo(target, "Create SMPL 0901 live player");
            }

            Smpl0901LivePlayer player = GetOrAdd<Smpl0901LivePlayer>(target);
            Smpl0901RootMotionDriver root = GetOrAdd<Smpl0901RootMotionDriver>(target);
            Smpl0901RawHandRetargeter hands = GetOrAdd<Smpl0901RawHandRetargeter>(target);
            Smpl0901TrackingPanel panel = GetOrAdd<Smpl0901TrackingPanel>(target);
            Smpl0901FittedSkeletonRenderer fitted =
                GetOrAdd<Smpl0901FittedSkeletonRenderer>(target);
            Rsv1RawSkeletonRenderer raw = GetOrAdd<Rsv1RawSkeletonRenderer>(target);

            player.listenPort = 9095;
            player.listenOnStart = false;
            player.requireManualStart = true;
            player.allowedServerIp = "192.168.1.250";
            player.supRigPelvisEuler = new Vector3(-90f, 0f, 0f);
            player.pelvisCorrectionEuler = Vector3.zero;
            player.livePoseEuler = new Vector3(0f, 0f, 90f);
            player.rootMotion = root;
            player.handRetargeter = hands;
            player.trackingPanel = panel;
            player.fittedSkeleton = fitted;
            player.rawSkeleton = raw;
            root.runtimeRoot = target.transform;
            root.useSmplCoordinateConversion = false;
            root.displayEuler = new Vector3(0f, 180f, 0f);
            root.SetDisplayEuler(root.displayEuler);
            root.invertSourceX = true;
            root.applyVertical = false;
            hands.snapToInput = false;
            hands.enableJointLimits = true;
            hands.enableAdaptiveSmoothing = true;
            hands.rotationSmoothing = 20f;
            panel.player = player;
            panel.fittedSkeleton = fitted;
            panel.rawSkeleton = raw;
            fitted.player = player;
            fitted.renderFittedSkeleton = false;
            raw.listenPort = 9096;
            raw.listenOnStart = false;
            raw.requireManualStart = true;
            raw.showTPoseBeforeFirstFrame = true;
            raw.allowedServerIp = "192.168.1.250";
            raw.useSmplCoordinateConversion = false;
            raw.invertX = true;
            raw.invertY = true;
            raw.invertZ = false;
            raw.rotationOffset = player.livePoseEuler;
            raw.player = player;
            raw.followSmplPelvis = true;
            raw.alignmentOffset = Vector3.zero;
            raw.renderRawSkeleton = true;
            panel.visible = true;
            panel.showDebugDetails = false;
            panel.panelSize = new Vector2(690f, 580f);

            if (player.characterPrefab == null)
                player.characterPrefab = FindSupCharacterPrefab();
            if (player.characterPrefab == null)
                Debug.LogWarning(
                    "[SMPL0901] SUP SMPL-H prefab was not found. Assign Character Prefab on the player.",
                    target);

            EditorUtility.SetDirty(player);
            EditorUtility.SetDirty(root);
            EditorUtility.SetDirty(hands);
            EditorUtility.SetDirty(panel);
            EditorUtility.SetDirty(fitted);
            EditorUtility.SetDirty(raw);
            EditorSceneManager.MarkSceneDirty(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Selection.activeGameObject = target;
            Debug.Log("[SMPL0901] Dedicated SMV2 hybrid player is ready on UDP 9095.", target);
        }

        private static GameObject FindSupCharacterPrefab()
        {
            string[] preferredPaths =
            {
                "Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Male New.prefab",
                "Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Female New.prefab"
            };
            foreach (string path in preferredPaths)
            {
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab != null) return prefab;
            }
            foreach (string guid in AssetDatabase.FindAssets("SMPLH Character t:Prefab"))
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab != null) return prefab;
            }
            return null;
        }

        private static T GetOrAdd<T>(GameObject target) where T : Component
        {
            T component = target.GetComponent<T>();
            return component != null ? component : Undo.AddComponent<T>(target);
        }

        private static void WarnAboutLegacyReceiver(string objectName)
        {
            GameObject legacy = GameObject.Find(objectName);
            if (legacy != null && legacy.activeInHierarchy)
                Debug.LogWarning(
                    $"[SMPL0901] Active legacy player '{objectName}' may already own UDP 9095. " +
                    "Disable that object before entering Play Mode; it was not modified automatically.",
                    legacy);
        }
    }
}
