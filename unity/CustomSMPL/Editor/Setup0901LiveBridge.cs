using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using CustomSMPL.Runtime0804;
using CustomSMPL.UI;

namespace CustomSMPL.Editor
{
    public static class Setup0901LiveBridge
    {
        [MenuItem("CustomSMPL/Setup 0901 Live Bridge Player")]
        public static void SetupScene()
        {
            GameObject playerObject = GameObject.Find("0901_Live_SMPL_Player");
            if (playerObject == null)
            {
                playerObject = new GameObject("0901_Live_SMPL_Player");
                Undo.RegisterCreatedObjectUndo(playerObject, "Create 0901 live SMPL player");
            }

            RealtimePipelinePlayer player = GetOrAdd<RealtimePipelinePlayer>(playerObject);
            RootMotionDriver rootMotion = GetOrAdd<RootMotionDriver>(playerObject);
            RawHandRetargeter hands = GetOrAdd<RawHandRetargeter>(playerObject);
            TrackingDebugPanel debugPanel = GetOrAdd<TrackingDebugPanel>(playerObject);

            player.listenPort = 9095;
            player.enableUdp = true;
            player.bodyPoseOnly = true;
            player.sourceSkeletonEuler = Vector3.zero;
            player.rootMotionDriver = rootMotion;
            player.rawHandRetargeter = hands;
            player.trackingDebugPanel = debugPanel;
            rootMotion.runtimeRoot = playerObject.transform;

            hands.snapToInput = false;
            hands.enableJointLimits = true;
            hands.enableAdaptiveSmoothing = true;
            hands.rotationSmoothing = 20f;

            if (player.characterPrefab == null)
            {
                const string prefabPath =
                    "Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Male New.prefab";
                player.characterPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (player.characterPrefab == null)
                    Debug.LogWarning("[0901] SUP character prefab not found; assign it in the Inspector.");
            }

            GameObject uiObject = GameObject.Find("0901_Live_SMPL_UI");
            if (uiObject == null)
            {
                uiObject = new GameObject("0901_Live_SMPL_UI");
                Undo.RegisterCreatedObjectUndo(uiObject, "Create 0901 live SMPL UI");
            }
            RealtimePipeline_UIManager ui = GetOrAdd<RealtimePipeline_UIManager>(uiObject);
            ui.player = player;

            EditorUtility.SetDirty(player);
            EditorUtility.SetDirty(rootMotion);
            EditorUtility.SetDirty(hands);
            EditorUtility.SetDirty(debugPanel);
            EditorUtility.SetDirty(ui);
            EditorSceneManager.MarkSceneDirty(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Selection.activeGameObject = playerObject;
            Debug.Log("[0901] Live hybrid SMPL player ready on UDP port 9095.");
        }

        private static T GetOrAdd<T>(GameObject target) where T : Component
        {
            T component = target.GetComponent<T>();
            return component != null ? component : target.AddComponent<T>();
        }
    }
}
