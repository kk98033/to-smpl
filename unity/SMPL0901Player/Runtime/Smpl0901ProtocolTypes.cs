using System;

namespace SMPL0901Player.Runtime
{
    [Serializable]
    public class ProtocolV2Frame
    {
        public int protocolVersion;
        public int frameId;
        public ProtocolV2Body body;
        public ProtocolV2Hands hands;
        public ProtocolV2Quality quality;
    }

    [Serializable]
    public class ProtocolV2Body
    {
        public float[] rootPosition;
        public float[] pelvisWorld;
        public float[] rootRotation;
        public float rootConfidence;
        public float[] pose;
    }

    [Serializable]
    public class ProtocolV2Hands
    {
        // Flattened 21 x 3 arrays. JsonUtility does not reliably parse jagged arrays.
        public float[] leftLocalJoints;
        public float[] leftConfidence;
        public float[] rightLocalJoints;
        public float[] rightConfidence;
    }

    [Serializable]
    public class ProtocolV2Quality
    {
        public bool inputValid;
        public float inputScore;
        public float fitResidualMm;
        public float worstJointResidualMm;
        public float torsoOrientationDeg;
        public string solverState;
        public int stepsUsed;
        public string[] reasons;
    }

}
