using System.Collections.Generic;
using UnityEngine;
using Utilities;
using SMPLModel;

namespace SMPL0901Player.Runtime
{
    /// <summary>Draws the body bones resulting from the fitted SMPL pose.</summary>
    public sealed class Smpl0901FittedSkeletonRenderer : MonoBehaviour
    {
        public Smpl0901LivePlayer player;
        public bool renderFittedSkeleton = false;
        public Color color = new Color(0.1f, 0.9f, 1f, 1f);
        public float jointSize = 0.035f;
        public float lineWidth = 0.014f;

        private sealed class BoneVisual
        {
            public Transform bone;
            public Transform parent;
            public GameObject joint;
            public LineRenderer line;
        }

        private readonly List<BoneVisual> visuals = new List<BoneVisual>();
        private Transform visualRoot;
        private Material material;

        public void SetVisible(bool visible)
        {
            renderFittedSkeleton = visible;
            if (visualRoot != null) visualRoot.gameObject.SetActive(visible);
        }

        private void LateUpdate()
        {
            if (player == null) player = GetComponent<Smpl0901LivePlayer>();
            if (visuals.Count == 0 && player != null && player.IsRuntimeReady) BuildVisuals();
            if (!renderFittedSkeleton || visuals.Count == 0) return;
            foreach (BoneVisual visual in visuals)
            {
                if (visual.bone == null) continue;
                visual.joint.transform.position = visual.bone.position;
                if (visual.line == null || visual.parent == null) continue;
                visual.line.SetPosition(0, visual.parent.position);
                visual.line.SetPosition(1, visual.bone.position);
            }
        }

        private void BuildVisuals()
        {
            Transform[] runtimeBones = player.RuntimeBones;
            if (runtimeBones == null) return;
            GameObject rootObject = new GameObject("SMPL_Fitted_Body_Skeleton");
            rootObject.transform.SetParent(transform, false);
            visualRoot = rootObject.transform;
            material = new Material(Shader.Find("Sprites/Default")) { color = color };

            HashSet<Transform> bodyBones = new HashSet<Transform>();
            foreach (Transform bone in runtimeBones)
            {
                if (bone != null && Bones.NameToJointIndex.TryGetValue(bone.name, out int index) &&
                    index >= 0 && index < 22)
                    bodyBones.Add(bone);
            }
            foreach (Transform bone in bodyBones)
            {
                Transform parent = bone.parent;
                while (parent != null && !bodyBones.Contains(parent)) parent = parent.parent;

                GameObject joint = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                joint.name = "SMPL_Fitted_" + bone.name;
                joint.transform.SetParent(visualRoot, true);
                joint.transform.localScale = Vector3.one * jointSize;
                Collider collider = joint.GetComponent<Collider>();
                if (collider != null) Destroy(collider);
                joint.GetComponent<MeshRenderer>().sharedMaterial = material;

                LineRenderer line = null;
                if (parent != null)
                {
                    GameObject lineObject = new GameObject("SMPL_Fitted_Bone_" + bone.name);
                    lineObject.transform.SetParent(visualRoot, false);
                    line = lineObject.AddComponent<LineRenderer>();
                    line.useWorldSpace = true;
                    line.positionCount = 2;
                    line.startWidth = line.endWidth = lineWidth;
                    line.sharedMaterial = material;
                }
                visuals.Add(new BoneVisual { bone = bone, parent = parent, joint = joint, line = line });
            }
            SetVisible(renderFittedSkeleton);
        }

        private void OnDestroy()
        {
            if (material != null) Destroy(material);
        }
    }
}
