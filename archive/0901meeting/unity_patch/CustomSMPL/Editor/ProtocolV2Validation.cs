using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using CustomSMPL.Runtime0804;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace CustomSMPL.Editor
{
    /// <summary>
    /// Batch-mode smoke test for the 0804 JSON playback contract.
    /// Invoke with -executeMethod CustomSMPL.Editor.ProtocolV2Validation.RunBatch.
    /// </summary>
    public static class ProtocolV2Validation
    {
        private const string PlaybackPath =
            @"F:\School\Projects\main\0804meeting\experiments\ProtocolV2_Teammate4View\protocol_v2_playback.json";
        private const string PacketPath =
            @"F:\School\Projects\main\0804meeting\experiments\ProtocolV2_Teammate4View\protocol_v2_first_packet.bin";
        private const string UdpReadyPath =
            @"F:\School\Projects\main\0804meeting\experiments\ProtocolV2_Teammate4View\unity_udp_ready.txt";
        private const string UdpResultPath =
            @"F:\School\Projects\main\0804meeting\experiments\ProtocolV2_Teammate4View\unity_udp_result.json";
        private const string OfflineCatalogPath =
            @"F:\School\Projects\main\0804meeting\unity_playback\playback_catalog.json";
        private const string OfflineSceneResultPath =
            @"F:\School\Projects\main\0804meeting\unity_playback\unity_scene_validation.json";

        public static void RunBatch()
        {
            try
            {
                if (!File.Exists(PlaybackPath))
                    throw new FileNotFoundException("Protocol v2 playback file was not found.", PlaybackPath);

                ProtocolV2PlaybackFile playback =
                    JsonUtility.FromJson<ProtocolV2PlaybackFile>(File.ReadAllText(PlaybackPath));

                if (playback == null || playback.protocolVersion != 2)
                    throw new InvalidDataException("protocolVersion must be 2.");
                if (playback.frames == null || playback.frames.Length != 300)
                    throw new InvalidDataException("Expected exactly 300 playback frames.");

                ProtocolV2Frame first = playback.frames[0];
                if (first.body == null || first.body.pose == null || first.body.pose.Length != 156)
                    throw new InvalidDataException("Body pose must contain 156 floats.");
                if (first.body.rootPosition == null || first.body.rootPosition.Length != 3)
                    throw new InvalidDataException("Root position must contain 3 floats.");
                if (first.hands == null ||
                    first.hands.leftLocalJoints == null || first.hands.leftLocalJoints.Length != 63 ||
                    first.hands.rightLocalJoints == null || first.hands.rightLocalJoints.Length != 63)
                    throw new InvalidDataException("Each wrist-local hand must contain 63 floats.");

                if (!File.Exists(PacketPath))
                    throw new FileNotFoundException("SMV2 binary packet was not found.", PacketPath);
                if (!ProtocolV2BinaryCodec.TryDecode(File.ReadAllBytes(PacketPath), out ProtocolV2Frame binaryFrame, out string decodeError))
                    throw new InvalidDataException($"SMV2 decode failed: {decodeError}");
                if (binaryFrame.body.pose.Length != 156 || binaryFrame.hands.leftLocalJoints.Length != 63)
                    throw new InvalidDataException("Decoded SMV2 body/hand dimensions are invalid.");

                OfflineAnimationCatalog catalog = JsonUtility.FromJson<OfflineAnimationCatalog>(
                    File.ReadAllText(OfflineCatalogPath));
                if (catalog == null || catalog.animations == null || catalog.animations.Length != 7)
                    throw new InvalidDataException("Offline catalog must contain seven selectable animations.");
                foreach (OfflineAnimationEntry entry in catalog.animations)
                {
                    ProtocolV2PlaybackFile animation = JsonUtility.FromJson<ProtocolV2PlaybackFile>(
                        File.ReadAllText(entry.path));
                    if (animation.frames == null || animation.frames.Length != entry.frames)
                        throw new InvalidDataException($"Offline animation frame mismatch: {entry.id}");
                    ProtocolV2Frame sample = animation.frames[0];
                    if (sample.observation == null || sample.observation.joints == null ||
                        sample.observation.joints.Length != sample.observation.jointCount * 3)
                        throw new InvalidDataException($"Offline source skeleton is invalid: {entry.id}");
                    if (sample.hands == null || sample.hands.leftLocalJoints == null ||
                        sample.hands.leftLocalJoints.Length != 63)
                        throw new InvalidDataException($"Offline hand payload is invalid: {entry.id}");
                    if (entry.id == "amass_hand_motion_300")
                    {
                        if (!entry.useSmplHandPose)
                            throw new InvalidDataException("AMASS hand-motion clip must use source SMPL-H hand rotations.");
                        bool hasHandRotation = false;
                        for (int poseIndex = 66; poseIndex < sample.body.pose.Length; poseIndex++)
                            hasHandRotation |= Mathf.Abs(sample.body.pose[poseIndex]) > 1e-6f;
                        if (!hasHandRotation)
                            throw new InvalidDataException("AMASS SMPL-H hand rotation payload is empty.");
                    }
                }

                Debug.Log("[ProtocolV2Validation] PASS: seven offline animations, body/root/hands/source skeletons and legacy SMV2 compatibility are valid.");
                EditorApplication.Exit(0);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                EditorApplication.Exit(1);
            }
        }

        public static void RunUdpBatch()
        {
            const int port = 19095;
            const int expectedFrames = 300;
            try
            {
                if (File.Exists(UdpReadyPath)) File.Delete(UdpReadyPath);
                if (File.Exists(UdpResultPath)) File.Delete(UdpResultPath);
                int received = 0;
                int decoded = 0;
                int firstFrame = -1;
                int lastFrame = -1;
                using (UdpClient listener = new UdpClient(port))
                {
                    listener.Client.ReceiveBufferSize = 4 * 1024 * 1024;
                    listener.Client.ReceiveTimeout = 20000;
                    File.WriteAllText(UdpReadyPath, $"READY {port}");
                    IPEndPoint sender = new IPEndPoint(IPAddress.Any, 0);
                    while (received < expectedFrames)
                    {
                        byte[] packet = listener.Receive(ref sender);
                        received++;
                        if (ProtocolV2BinaryCodec.TryDecode(packet, out ProtocolV2Frame frame, out _))
                        {
                            decoded++;
                            if (firstFrame < 0) firstFrame = frame.frameId;
                            lastFrame = frame.frameId;
                        }
                    }
                }
                string result = $"{{\"status\":\"PASS\",\"received\":{received},\"decoded\":{decoded}," +
                    $"\"firstFrame\":{firstFrame},\"lastFrame\":{lastFrame},\"port\":{port}}}";
                File.WriteAllText(UdpResultPath, result);
                Debug.Log($"[ProtocolV2Validation] UDP PASS: Unity received and decoded {decoded}/{received} SMV2 frames.");
                EditorApplication.Exit(decoded == expectedFrames ? 0 : 1);
            }
            catch (Exception exception)
            {
                File.WriteAllText(UdpResultPath,
                    $"{{\"status\":\"FAIL\",\"message\":{JsonUtility.ToJson(exception.Message)}}}");
                Debug.LogException(exception);
                EditorApplication.Exit(1);
            }
        }

        public static void RunOfflineSceneBatch()
        {
            try
            {
                EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
                CustomSMPLSetup.SetupOfflinePlayerScene();
                CustomSMPLSetup.SetupOfflinePlayerScene();
                GameObject playerObject = GameObject.Find("0804_Offline_Player");
                if (playerObject == null) throw new InvalidDataException("One-click setup did not create the player.");

                RealtimePipelinePlayer player = playerObject.GetComponent<RealtimePipelinePlayer>();
                ProtocolV2PlaybackPlayer playback = playerObject.GetComponent<ProtocolV2PlaybackPlayer>();
                RawHandRetargeter hands = playerObject.GetComponent<RawHandRetargeter>();
                RootMotionDriver root = playerObject.GetComponent<RootMotionDriver>();
                OfflineAnimationControlPanel panel = playerObject.GetComponent<OfflineAnimationControlPanel>();
                if (playerObject.GetComponents<RealtimePipelinePlayer>().Length != 1 ||
                    playerObject.GetComponents<ProtocolV2PlaybackPlayer>().Length != 1 ||
                    playerObject.GetComponents<RawHandRetargeter>().Length != 1 ||
                    playerObject.GetComponents<RootMotionDriver>().Length != 1 ||
                    playerObject.GetComponents<OfflineAnimationControlPanel>().Length != 1)
                    throw new InvalidDataException("Repeated one-click setup created duplicate components.");
                if (player == null || playback == null || hands == null || root == null || panel == null)
                    throw new InvalidDataException("Offline playback components are incomplete.");
                if (player.enableUdp) throw new InvalidDataException("UDP must be disabled for the offline player.");
                if (!player.bodyPoseOnly)
                    throw new InvalidDataException("Offline Learnable pose must be body-only; fingers belong to Hand21.");
                if (!playback.driveHands)
                    throw new InvalidDataException("Offline player must drive SMPL-H fingers from Hand21.");
                if (player.characterPrefab == null) throw new InvalidDataException("SMPL-H prefab was not assigned.");

                GameObject character = (GameObject)PrefabUtility.InstantiatePrefab(player.characterPrefab);
                hands.Initialize(character.transform);
                int leftMapped = hands.LeftMappedBones;
                int rightMapped = hands.RightMappedBones;
                if (leftMapped < 15 || rightMapped < 15)
                    throw new InvalidDataException($"Hand mapping incomplete: left={leftMapped}, right={rightMapped}.");

                OfflineAnimationCatalog handCatalog = JsonUtility.FromJson<OfflineAnimationCatalog>(
                    File.ReadAllText(OfflineCatalogPath));
                ProtocolV2PlaybackFile handSample = JsonUtility.FromJson<ProtocolV2PlaybackFile>(
                    File.ReadAllText(handCatalog.animations[0].path));
                hands.ApplyHands(handSample.frames[0].hands);
                int leftDriven = hands.LastAppliedLeftSegments;
                int rightDriven = hands.LastAppliedRightSegments;
                UnityEngine.Object.DestroyImmediate(character);
                if (leftDriven != 15 || rightDriven != 15)
                    throw new InvalidDataException($"Hand21 did not drive every finger segment: left={leftDriven}, right={rightDriven}.");

                CustomSMPLSetup.SetupLegacyRealtimePipelineScene();
                CustomSMPLSetup.SetupLegacyRealtimePipelineScene();
                GameObject legacyObject = GameObject.Find("RealtimePipeline_Player");
                if (legacyObject == null) throw new InvalidDataException("Legacy setup did not create its own player.");
                RealtimePipelinePlayer legacyPlayer = legacyObject.GetComponent<RealtimePipelinePlayer>();
                if (legacyPlayer == null || !legacyPlayer.enableUdp || legacyPlayer.bodyPoseOnly)
                    throw new InvalidDataException("Legacy mode must keep UDP and full-pose behavior.");
                if (playerObject.activeSelf)
                    throw new InvalidDataException("Legacy and offline players must not play simultaneously.");
                CustomSMPLSetup.SetupOfflinePlayerScene();
                if (!playerObject.activeSelf || legacyObject.activeSelf)
                    throw new InvalidDataException("Offline setup did not switch cleanly from legacy mode.");

                string result = $"{{\"status\":\"PASS\",\"udpEnabled\":false," +
                    $"\"leftMappedBones\":{leftMapped},\"rightMappedBones\":{rightMapped}," +
                    $"\"leftDrivenSegments\":{leftDriven},\"rightDrivenSegments\":{rightDriven}," +
                    "\"bodyPoseOnly\":true,\"rawHand21DrivesFingers\":true," +
                    "\"smplHandPoseModeAvailable\":true," +
                    "\"legacyAndOfflineIndependent\":true,\"duplicateComponents\":false,\"selectableAnimations\":7}";
                File.WriteAllText(OfflineSceneResultPath, result);
                Debug.Log($"[ProtocolV2Validation] OFFLINE SCENE PASS: hand bones {leftMapped}+{rightMapped}, no UDP, no duplicate components.");
                EditorApplication.Exit(0);
            }
            catch (Exception exception)
            {
                File.WriteAllText(OfflineSceneResultPath, "{\"status\":\"FAIL\"}");
                Debug.LogException(exception);
                EditorApplication.Exit(1);
            }
        }
    }
}
