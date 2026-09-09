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
            Smpl0901DirectJointBaseline baseline =
                GetOrAdd<Smpl0901DirectJointBaseline>(target);
            Smpl0901WorldLabels labels = GetOrAdd<Smpl0901WorldLabels>(target);

            player.listenPort = 9095;
            player.listenOnStart = false;
            player.requireManualStart = true;
            player.allowedServerIp = "192.168.1.250";
            player.applyRejectedCandidates = true;
            player.supRigPelvisEuler = new Vector3(-90f, 0f, 0f);
            player.pelvisCorrectionEuler = Vector3.zero;
            player.livePoseEuler = new Vector3(0f, 0f, 90f);
            player.applyPoseRelativeToBind = true;
            player.bindRelativeDisplayEuler = new Vector3(0f, 180f, 0f);
            player.rawMatchedDisplayEuler = new Vector3(0f, -90f, 0f);
            player.rootMotion = root;
            player.handRetargeter = hands;
            player.trackingPanel = panel;
            player.fittedSkeleton = fitted;
            player.rawSkeleton = raw;
            player.directJointBaseline = baseline;
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
            hands.applyFingerDeltasFromBind = true;
            panel.player = player;
            panel.fittedSkeleton = fitted;
            panel.rawSkeleton = raw;
            panel.directJointBaseline = baseline;
            fitted.player = player;
            fitted.renderFittedSkeleton = false;
            raw.listenPort = 9096;
            raw.listenOnStart = false;
            raw.requireManualStart = true;
            raw.showTPoseBeforeFirstFrame = true;
            raw.allowedServerIp = "192.168.1.250";
            raw.useSmplCoordinateConversion = true;
            raw.invertX = true;
            raw.invertY = true;
            raw.invertZ = false;
            raw.rotationOffset = player.livePoseEuler;
            raw.displayEuler = new Vector3(0f, -90f, 0f);
            raw.player = player;
            raw.followSmplPelvis = true;
            raw.alignmentOffset = Vector3.zero;
            raw.renderRawSkeleton = true;
            baseline.player = player;
            baseline.rawSkeleton = raw;
            baseline.renderBaseline = true;
            baseline.baselineOffset = new Vector3(-2f, 0f, 0f);
            baseline.displayEuler = raw.displayEuler;
            baseline.matchSmplCharacterScale = true;
            baseline.autoScaleToRaw = false;
            labels.player = player;
            labels.rawAvatar = baseline;
            panel.visible = true;
            panel.showDebugDetails = false;
            panel.panelExpanded = true;
            panel.panelSize = new Vector2(840f, 680f);

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
            EditorUtility.SetDirty(baseline);
            EditorUtility.SetDirty(labels);
            EditorSceneManager.MarkSceneDirty(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Selection.activeGameObject = target;
            Debug.Log("[SMPL0901] Dedicated SMV2 hybrid player is ready on UDP 9095.", target);
        }

        [MenuItem("SMPL 0901/Create Demo Room + Camera + Live Player")]
        public static void CreateDemoRoomWithPlayer()
        {
            GameObject sceneRoot = FindOrCreateRoot("SMPL0901_DemoScene");
            GameObject environment = FindOrCreateChild(sceneRoot.transform, "Environment");
            GameObject actors = FindOrCreateChild(sceneRoot.transform, "Actors");
            GameObject cameras = FindOrCreateChild(sceneRoot.transform, "Cameras");
            GameObject lighting = FindOrCreateChild(sceneRoot.transform, "Lighting");

            ConfigureRoomPart(environment.transform, "Floor",
                new Vector3(0f, -0.05f, 0f), new Vector3(10f, 0.1f, 10f));
            ConfigureRoomPart(environment.transform, "Back Wall",
                new Vector3(0f, 1.5f, 4.95f), new Vector3(10f, 3f, 0.1f));
            ConfigureRoomPart(environment.transform, "Left Wall",
                new Vector3(-4.95f, 1.5f, 0f), new Vector3(0.1f, 3f, 10f));
            ConfigureRoomPart(environment.transform, "Right Wall",
                new Vector3(4.95f, 1.5f, 0f), new Vector3(0.1f, 3f, 10f));

            CreateOrRepairPlayer();
            GameObject playerObject = GameObject.Find(ObjectName);
            if (playerObject != null)
            {
                Undo.SetTransformParent(playerObject.transform, actors.transform, "Group SMPL player");
                playerObject.transform.localPosition = new Vector3(0f, 1f, 0f);
                playerObject.transform.localRotation = Quaternion.identity;
            }

            Camera sceneCamera = Camera.main;
            if (sceneCamera == null)
            {
                GameObject cameraObject = FindOrCreateChild(cameras.transform, "SMPL0901_Camera");
                sceneCamera = GetOrAdd<Camera>(cameraObject);
                cameraObject.tag = "MainCamera";
            }
            else
            {
                Undo.SetTransformParent(sceneCamera.transform, cameras.transform, "Group SMPL camera");
            }
            sceneCamera.transform.position = new Vector3(0f, 1.6f, -4.2f);
            sceneCamera.transform.rotation = Quaternion.LookRotation(
                new Vector3(0f, 1f, 0f) - sceneCamera.transform.position,
                Vector3.up);
            sceneCamera.fieldOfView = 50f;

            GameObject lightObject = FindOrCreateChild(lighting.transform, "Key Light");
            Light keyLight = GetOrAdd<Light>(lightObject);
            keyLight.type = LightType.Directional;
            keyLight.intensity = 1.1f;
            lightObject.transform.rotation = Quaternion.Euler(48f, -32f, 0f);

            EditorSceneManager.MarkSceneDirty(
                UnityEngine.SceneManagement.SceneManager.GetActiveScene());
            Selection.activeGameObject = sceneRoot;
            Debug.Log(
                "[SMPL0901] Demo room, grouped player, camera and light are ready. " +
                "The player pelvis starts at Y=1 so the preview feet sit on the floor.",
                sceneRoot);
        }

        private static GameObject FindOrCreateRoot(string name)
        {
            GameObject existing = GameObject.Find(name);
            if (existing != null) return existing;
            GameObject created = new GameObject(name);
            Undo.RegisterCreatedObjectUndo(created, "Create " + name);
            return created;
        }

        private static GameObject FindOrCreateChild(Transform parent, string name)
        {
            Transform existing = parent.Find(name);
            if (existing != null) return existing.gameObject;
            GameObject created = new GameObject(name);
            Undo.RegisterCreatedObjectUndo(created, "Create " + name);
            created.transform.SetParent(parent, false);
            return created;
        }

        private static void ConfigureRoomPart(
            Transform parent, string name, Vector3 localPosition, Vector3 localScale)
        {
            Transform existing = parent.Find(name);
            GameObject part;
            if (existing != null)
            {
                part = existing.gameObject;
            }
            else
            {
                part = GameObject.CreatePrimitive(PrimitiveType.Cube);
                part.name = name;
                Undo.RegisterCreatedObjectUndo(part, "Create " + name);
                part.transform.SetParent(parent, false);
            }
            part.transform.localPosition = localPosition;
            part.transform.localRotation = Quaternion.identity;
            part.transform.localScale = localScale;
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
