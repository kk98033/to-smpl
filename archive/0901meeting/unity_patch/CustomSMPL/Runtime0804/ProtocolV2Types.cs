using System;

namespace CustomSMPL.Runtime0804
{
    [Serializable]
    public class ProtocolV2PlaybackFile
    {
        public int protocolVersion;
        public string datasetName;
        public string displayName;
        public string source;
        public string coordinateConvention;
        public bool gtAvailable;
        public bool hasHands;
        public bool hasRootMotion;
        public string fingerDriveMode;
        public ProtocolV2Frame[] frames;
    }

    [Serializable]
    public class ProtocolV2Frame
    {
        public int protocolVersion;
        public int frameId;
        public double timestamp;
        public string units;
        public string calibrationId;
        public ProtocolV2Body body;
        public ProtocolV2Hands hands;
        public ProtocolV2Observation observation;
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
        // Optional original/source SMPL-H pose. Used by the controlled AMASS
        // joint-position + SMPL-twist comparison, never by production inputs.
        public float[] referencePose;
        public float[] betas;
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

    [Serializable]
    public class ProtocolV2Observation
    {
        public int jointCount;
        // Flattened Body25 or Body25 + 2 x Hand21 source joints.
        public float[] joints;
        public float[] confidence;
        public string label;
        public bool gtAvailable;
    }

    [Serializable]
    public class OfflineAnimationCatalog
    {
        public int version;
        public int defaultIndex;
        public OfflineAnimationEntry[] animations;
    }

    [Serializable]
    public class OfflineAnimationEntry
    {
        public string id;
        public string displayName;
        public string path;
        public float fps;
        public float[] rootEuler;
        public bool gtAvailable;
        public bool hasHands;
        public bool useSmplHandPose;
        public int frames;
        public int validLeftHandFrames;
        public int validRightHandFrames;
        public float[] rootRangeM;
    }
}
