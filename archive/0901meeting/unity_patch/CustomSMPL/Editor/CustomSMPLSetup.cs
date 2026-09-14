using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using CustomSMPL.UI;
using CustomSMPL.H36M;
using CustomSMPL.H36M.UI;
using CustomSMPL.Runtime0804;

namespace CustomSMPL.Editor
{
    /// <summary>
    /// Editor utility to automatically set up the Custom SMPL Animation Player in the active scene.
    /// Provides a menu command under CustomSMPL/Setup Player Scene.
    /// </summary>
    public static class CustomSMPLSetup
    {
        [MenuItem("CustomSMPL/Setup Player Scene")]
        public static void SetupScene()
        {
            // 1. Find or create CustomSMPL_Player GameObject
            GameObject playerObj = GameObject.Find("CustomSMPL_Player");
            if (playerObj == null)
            {
                playerObj = new GameObject("CustomSMPL_Player");
                Undo.RegisterCreatedObjectUndo(playerObj, "Create CustomSMPL_Player");
                Debug.Log("[CustomSMPLSetup] Created 'CustomSMPL_Player' GameObject.");
            }

            CustomAnimationPlayer player = playerObj.GetComponent<CustomAnimationPlayer>();
            if (player == null)
            {
                player = playerObj.AddComponent<CustomAnimationPlayer>();
                Undo.RegisterCreatedObjectUndo(playerObj, "Add CustomAnimationPlayer");
                Debug.Log("[CustomSMPLSetup] Added 'CustomAnimationPlayer' component.");
            }

            // 2. Load character prefab from package and assign it if empty
            if (player.characterPrefab == null)
            {
                string prefabPath = "Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Female New.prefab";
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (prefab != null)
                {
                    player.characterPrefab = prefab;
                    EditorUtility.SetDirty(player);
                    Debug.Log($"[CustomSMPLSetup] Linked character prefab: '{prefabPath}'");
                }
                else
                {
                    Debug.LogWarning($"[CustomSMPLSetup] Could not find prefab at: '{prefabPath}'. Please link a character prefab manually in the Inspector.");
                }
            }

            // 3. Find or create AnimationUI GameObject
            GameObject uiObj = GameObject.Find("AnimationUI");
            if (uiObj == null)
            {
                uiObj = new GameObject("AnimationUI");
                Undo.RegisterCreatedObjectUndo(uiObj, "Create AnimationUI");
                Debug.Log("[CustomSMPLSetup] Created 'AnimationUI' GameObject.");
            }

            AnimationUIManager uiManager = uiObj.GetComponent<AnimationUIManager>();
            if (uiManager == null)
            {
                uiManager = uiObj.AddComponent<AnimationUIManager>();
                Undo.RegisterCreatedObjectUndo(uiObj, "Add AnimationUIManager");
                Debug.Log("[CustomSMPLSetup] Added 'AnimationUIManager' component.");
            }

            // Link player to UI manager
            if (uiManager.animationPlayer == null)
            {
                uiManager.animationPlayer = player;
                EditorUtility.SetDirty(uiManager);
                Debug.Log("[CustomSMPLSetup] Linked 'AnimationUIManager' to 'CustomAnimationPlayer'.");
            }

            // Mark active scene as dirty to prompt saving
            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] Scene setup completed successfully!");
        }

        [MenuItem("CustomSMPL/Setup H36M Player Scene")]
        public static void SetupH36MScene()
        {
            // 1. Find or create H36M_Player GameObject
            GameObject playerObj = GameObject.Find("H36M_Player");
            if (playerObj == null)
            {
                playerObj = new GameObject("H36M_Player");
                Undo.RegisterCreatedObjectUndo(playerObj, "Create H36M_Player");
                Debug.Log("[CustomSMPLSetup] Created 'H36M_Player' GameObject.");
            }

            H36MAnimationPlayer player = playerObj.GetComponent<H36MAnimationPlayer>();
            if (player == null)
            {
                player = playerObj.AddComponent<H36MAnimationPlayer>();
                Undo.RegisterCreatedObjectUndo(playerObj, "Add H36MAnimationPlayer");
                Debug.Log("[CustomSMPLSetup] Added 'H36MAnimationPlayer' component.");
            }

            // 2. Find or create H36M_UI GameObject
            GameObject uiObj = GameObject.Find("H36M_UI");
            if (uiObj == null)
            {
                uiObj = new GameObject("H36M_UI");
                Undo.RegisterCreatedObjectUndo(uiObj, "Create H36M_UI");
                Debug.Log("[CustomSMPLSetup] Created 'H36M_UI' GameObject.");
            }

            H36M_UIManager uiManager = uiObj.GetComponent<H36M_UIManager>();
            if (uiManager == null)
            {
                uiManager = uiObj.AddComponent<H36M_UIManager>();
                Undo.RegisterCreatedObjectUndo(uiObj, "Add H36M_UIManager");
                Debug.Log("[CustomSMPLSetup] Added 'H36M_UIManager' component.");
            }

            // Link player to UI manager
            if (uiManager.player == null)
            {
                uiManager.player = player;
                EditorUtility.SetDirty(uiManager);
                Debug.Log("[CustomSMPLSetup] Linked 'H36M_UIManager' to 'H36MAnimationPlayer'.");
            }

            // Mark active scene as dirty to prompt saving
            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] H36M Scene setup completed successfully!");
        }

        [MenuItem("CustomSMPL/Legacy Realtime UDP Player")]
        public static void SetupLegacyRealtimePipelineScene()
        {
            SetSceneObjectActive("0818_Realtime_Player", false);
            SetSceneObjectActive("0804_Offline_Player", false);
            SetSceneObjectActive("0804_AMASS_TwoModel_Comparison", false);
            GameObject playerObj = FindOrCreateSceneObject("RealtimePipeline_Player");
            playerObj.SetActive(true);

            RealtimePipelinePlayer player = playerObj.GetComponent<RealtimePipelinePlayer>();
            if (player == null)
            {
                player = playerObj.AddComponent<RealtimePipelinePlayer>();
            }
            AssignCharacterPrefab(player);
            player.enableUdp = true;
            player.bodyPoseOnly = false;
            player.sourceSkeletonEuler = Vector3.zero;

            // A scene previously configured by the interim 0804 version may
            // still contain offline components on this legacy object. Keep
            // them for recovery but disable them in UDP mode.
            SetComponentEnabled<ProtocolV2PlaybackPlayer>(playerObj, false);
            SetComponentEnabled<OfflineAnimationControlPanel>(playerObj, false);
            SetComponentEnabled<TrackingDebugPanel>(playerObj, false);

            GameObject uiObj = FindOrCreateSceneObject("RealtimePipeline_UI");
            uiObj.SetActive(true);
            CustomSMPL.UI.RealtimePipeline_UIManager uiManager =
                uiObj.GetComponent<CustomSMPL.UI.RealtimePipeline_UIManager>();
            if (uiManager == null)
            {
                uiManager = uiObj.AddComponent<CustomSMPL.UI.RealtimePipeline_UIManager>();
            }
            uiManager.enabled = true;
            uiManager.player = player;
            EditorUtility.SetDirty(player);
            EditorUtility.SetDirty(uiManager);

            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] Legacy realtime UDP player ready on port 9095.");
        }

        [MenuItem("CustomSMPL/0818 Realtime Protocol V2 UDP Player")]
        public static void Setup0818RealtimeProtocolV2Scene()
        {
            SetSceneObjectActive("RealtimePipeline_Player", false);
            SetSceneObjectActive("RealtimePipeline_UI", false);
            SetSceneObjectActive("0804_Offline_Player", false);
            SetSceneObjectActive("0804_AMASS_TwoModel_Comparison", false);

            GameObject playerObj = FindOrCreateSceneObject("0818_Realtime_Player");
            playerObj.SetActive(true);

            RealtimePipelinePlayer player = playerObj.GetComponent<RealtimePipelinePlayer>();
            if (player == null) player = playerObj.AddComponent<RealtimePipelinePlayer>();
            AssignCharacterPrefab(player);

            RootMotionDriver rootMotion = GetOrAdd<RootMotionDriver>(playerObj);
            RawHandRetargeter handRetargeter = GetOrAdd<RawHandRetargeter>(playerObj);
            handRetargeter.snapToInput = false; // Enable adaptive smoothing for live UDP input
            handRetargeter.enableJointLimits = true;
            handRetargeter.enableAdaptiveSmoothing = true;
            handRetargeter.rotationSmoothing = 20f;

            TrackingDebugPanel debugPanel = GetOrAdd<TrackingDebugPanel>(playerObj);

            // Disable offline file playback when live UDP is active
            SetComponentEnabled<ProtocolV2PlaybackPlayer>(playerObj, false);
            SetComponentEnabled<OfflineAnimationControlPanel>(playerObj, false);

            rootMotion.enabled = true;
            handRetargeter.enabled = true;
            debugPanel.enabled = true;

            player.enableUdp = true;
            player.listenPort = 9095;
            player.bodyPoseOnly = true;
            player.sourceSkeletonEuler = Vector3.zero;
            player.rootMotionDriver = rootMotion;
            player.rawHandRetargeter = handRetargeter;
            player.trackingDebugPanel = debugPanel;
            rootMotion.runtimeRoot = playerObj.transform;

            GameObject uiObj = FindOrCreateSceneObject("RealtimePipeline_UI");
            uiObj.SetActive(true);
            CustomSMPL.UI.RealtimePipeline_UIManager uiManager =
                uiObj.GetComponent<CustomSMPL.UI.RealtimePipeline_UIManager>();
            if (uiManager == null)
            {
                uiManager = uiObj.AddComponent<CustomSMPL.UI.RealtimePipeline_UIManager>();
            }
            uiManager.enabled = true;
            uiManager.player = player;

            EditorUtility.SetDirty(player);
            EditorUtility.SetDirty(rootMotion);
            EditorUtility.SetDirty(handRetargeter);
            EditorUtility.SetDirty(debugPanel);
            EditorUtility.SetDirty(uiManager);

            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] 0818 Realtime Protocol V2 UDP Player ready on port 9095 with Body + Hand ROM + Root Motion + Quality Gate.");
        }

        [MenuItem("CustomSMPL/0804 Offline Player (Latest)")]
        public static void SetupOfflinePlayerScene()
        {
            SetSceneObjectActive("0818_Realtime_Player", false);
            SetSceneObjectActive("RealtimePipeline_Player", false);
            SetSceneObjectActive("RealtimePipeline_UI", false);
            SetSceneObjectActive("0804_AMASS_TwoModel_Comparison", false);
            GameObject playerObj = FindOrCreateSceneObject("0804_Offline_Player");
            playerObj.SetActive(true);

            RealtimePipelinePlayer player = playerObj.GetComponent<RealtimePipelinePlayer>();
            if (player == null) player = playerObj.AddComponent<RealtimePipelinePlayer>();
            AssignCharacterPrefab(player);

            RootMotionDriver rootMotion = GetOrAdd<RootMotionDriver>(playerObj);
            RawHandRetargeter handRetargeter = GetOrAdd<RawHandRetargeter>(playerObj);
            handRetargeter.snapToInput = true;
            TrackingDebugPanel debugPanel = GetOrAdd<TrackingDebugPanel>(playerObj);
            ProtocolV2PlaybackPlayer playbackV2 = GetOrAdd<ProtocolV2PlaybackPlayer>(playerObj);
            OfflineAnimationControlPanel offlinePanel = GetOrAdd<OfflineAnimationControlPanel>(playerObj);

            rootMotion.enabled = true;
            handRetargeter.enabled = true;
            debugPanel.enabled = true;
            playbackV2.enabled = true;
            offlinePanel.enabled = true;
            player.enableUdp = false;
            player.bodyPoseOnly = true;
            player.sourceSkeletonEuler = Vector3.zero;
            player.rootMotionDriver = rootMotion;
            player.rawHandRetargeter = handRetargeter;
            player.trackingDebugPanel = debugPanel;
            rootMotion.runtimeRoot = playerObj.transform;
            playbackV2.targetPlayer = player;
            playbackV2.driveHands = true;
            string offlineCatalog = @"F:\School\Projects\main\0804meeting\unity_playback\playback_catalog.json";
            if (System.IO.File.Exists(offlineCatalog)) playbackV2.catalogJsonPath = offlineCatalog;
            offlinePanel.playback = playbackV2;
            offlinePanel.player = player;

            EditorUtility.SetDirty(player);
            EditorUtility.SetDirty(rootMotion);
            EditorUtility.SetDirty(handRetargeter);
            EditorUtility.SetDirty(playbackV2);
            EditorUtility.SetDirty(offlinePanel);

            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] 0804 offline player ready: Learnable body + raw Hand21 fingers, no UDP.");
        }

        [MenuItem("CustomSMPL/0804 AMASS Two-Model Comparison")]
        public static void SetupAmassTwoModelComparison()
        {
            SetSceneObjectActive("0818_Realtime_Player", false);
            SetSceneObjectActive("RealtimePipeline_Player", false);
            SetSceneObjectActive("RealtimePipeline_UI", false);
            SetSceneObjectActive("0804_Offline_Player", false);

            GameObject comparisonRoot = FindOrCreateSceneObject("0804_AMASS_TwoModel_Comparison");
            comparisonRoot.SetActive(true);
            GameObject previousObject = FindOrCreateSceneObject("AMASS_Previous_Method_LEFT");
            GameObject jointSmplObject = FindOrCreateSceneObject("AMASS_Joint_SMPL_Method_RIGHT");
            previousObject.transform.SetParent(comparisonRoot.transform, false);
            jointSmplObject.transform.SetParent(comparisonRoot.transform, false);
            previousObject.transform.localPosition = new Vector3(-1.25f, 0f, 0f);
            jointSmplObject.transform.localPosition = new Vector3(1.25f, 0f, 0f);

            ProtocolV2PlaybackPlayer previous = ConfigureComparisonSide(previousObject, true);
            ProtocolV2PlaybackPlayer jointSmpl = ConfigureComparisonSide(jointSmplObject, false);
            JointPositionSmplTwistDriver directDriver = GetOrAdd<JointPositionSmplTwistDriver>(jointSmplObject);
            directDriver.enabled = true;
            directDriver.pullBonePositions = true;
            jointSmpl.jointTwistDriver = directDriver;
            jointSmpl.useReferenceSmplPose = true;

            AmassTwoMethodComparisonController controller =
                GetOrAdd<AmassTwoMethodComparisonController>(comparisonRoot);
            controller.enabled = true;
            controller.previousMethod = previous;
            controller.jointSmplMethod = jointSmpl;
            controller.catalogPath = @"F:\School\Projects\main\0804meeting\unity_playback\playback_catalog.json";
            controller.animationId = "amass_hand_motion_300";
            controller.showBothSourceSkeletons = true;

            EditorUtility.SetDirty(previousObject);
            EditorUtility.SetDirty(jointSmplObject);
            EditorUtility.SetDirty(previous);
            EditorUtility.SetDirty(jointSmpl);
            EditorUtility.SetDirty(directDriver);
            EditorUtility.SetDirty(controller);
            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] AMASS two-model comparison ready: LEFT previous, RIGHT joint + SMPL rotation.");
        }

        private static ProtocolV2PlaybackPlayer ConfigureComparisonSide(GameObject playerObject, bool previousMethod)
        {
            RealtimePipelinePlayer player = GetOrAdd<RealtimePipelinePlayer>(playerObject);
            AssignCharacterPrefab(player);
            player.enableUdp = false;
            player.renderSMPL = true;
            player.renderJoints = true;
            player.bodyPoseOnly = previousMethod;

            RawHandRetargeter hands = GetOrAdd<RawHandRetargeter>(playerObject);
            hands.enabled = true;
            hands.snapToInput = true;
            player.rawHandRetargeter = hands;

            ProtocolV2PlaybackPlayer playback = GetOrAdd<ProtocolV2PlaybackPlayer>(playerObject);
            playback.enabled = false; // The comparison controller owns the shared clock.
            playback.targetPlayer = player;
            playback.applyRootMotion = false;
            playback.showSourceSkeleton = true;
            playback.forceRawHand21 = previousMethod;
            playback.useReferenceSmplPose = !previousMethod;
            playback.driveHands = previousMethod;
            playback.catalogJsonPath = @"F:\School\Projects\main\0804meeting\unity_playback\playback_catalog.json";
            return playback;
        }

        // Backward-compatible entry point used by validation scripts. It has no
        // menu item, so users see only the two explicit modes above.
        public static void SetupRealtimePipelineScene()
        {
            SetupOfflinePlayerScene();
        }

        private static GameObject FindSceneObject(string objectName)
        {
            foreach (GameObject candidate in Resources.FindObjectsOfTypeAll<GameObject>())
            {
                if (candidate.name == objectName && candidate.scene.IsValid()) return candidate;
            }
            return null;
        }

        private static GameObject FindOrCreateSceneObject(string objectName)
        {
            GameObject result = FindSceneObject(objectName);
            if (result != null) return result;
            result = new GameObject(objectName);
            Undo.RegisterCreatedObjectUndo(result, $"Create {objectName}");
            return result;
        }

        private static void SetSceneObjectActive(string objectName, bool active)
        {
            GameObject target = FindSceneObject(objectName);
            if (target != null) target.SetActive(active);
        }

        private static T GetOrAdd<T>(GameObject target) where T : Component
        {
            T result = target.GetComponent<T>();
            return result != null ? result : target.AddComponent<T>();
        }

        private static void SetComponentEnabled<T>(GameObject target, bool enabled) where T : Behaviour
        {
            T component = target.GetComponent<T>();
            if (component != null) component.enabled = enabled;
        }

        private static void AssignCharacterPrefab(RealtimePipelinePlayer player)
        {
            if (player.characterPrefab != null) return;
            const string prefabPath = "Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Female New.prefab";
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (prefab != null) player.characterPrefab = prefab;
            else Debug.LogWarning($"[CustomSMPLSetup] Could not find prefab at: {prefabPath}");
        }

        [MenuItem("CustomSMPL/Setup Direct Joint Experiment Scene")]
        public static void SetupDirectJointExperimentScene()
        {
            // 1. Find or create DirectJointExperiment GameObject
            GameObject playerObj = GameObject.Find("DirectJointExperiment");
            if (playerObj == null)
            {
                playerObj = new GameObject("DirectJointExperiment");
                Undo.RegisterCreatedObjectUndo(playerObj, "Create DirectJointExperiment");
                Debug.Log("[CustomSMPLSetup] Created 'DirectJointExperiment' GameObject.");
            }

            CustomSMPL.Experiment.DirectJointPlayer player = playerObj.GetComponent<CustomSMPL.Experiment.DirectJointPlayer>();
            if (player == null)
            {
                player = playerObj.AddComponent<CustomSMPL.Experiment.DirectJointPlayer>();
                Undo.RegisterCreatedObjectUndo(playerObj, "Add DirectJointPlayer");
                Debug.Log("[CustomSMPLSetup] Added 'DirectJointPlayer' component.");
            }

            // 2. Load character prefab from package and assign it if empty
            if (player.characterPrefab == null)
            {
                string prefabPath = "Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Female New.prefab";
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                if (prefab != null)
                {
                    player.characterPrefab = prefab;
                    EditorUtility.SetDirty(player);
                    Debug.Log($"[CustomSMPLSetup] Linked character prefab: '{prefabPath}'");
                }
                else
                {
                    Debug.LogWarning($"[CustomSMPLSetup] Could not find prefab at: '{prefabPath}'. Please link a character prefab manually in the Inspector.");
                }
            }

            // Mark active scene as dirty to prompt saving
            EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Debug.Log("[CustomSMPLSetup] Direct Joint Experiment Scene setup completed successfully!");
        }
    }
}
