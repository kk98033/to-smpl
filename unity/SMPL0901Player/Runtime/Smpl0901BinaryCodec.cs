using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace SMPL0901Player.Runtime
{
    /// <summary>
    /// Decoder for the main Python pipeline's SMV2 UDP datagram. The first
    /// 644 bytes preserve the legacy SMPL frame/trans/pose layout.
    /// </summary>
    public static class Smpl0901BinaryCodec
    {
        public const int PacketSize = 1389;

        private static readonly string[] SolverStates =
        {
            "TRACKING", "RECOVERED", "ADAPTIVE_100", "KAMA_REINITIALIZE",
            "HOLD_INPUT_INVALID", "TRACKING_LOST", "FAILED_HOLD"
        };

        private static readonly string[] ReasonNames =
        {
            "non_finite", "coordinate_range", "torso_length", "left_right_asymmetry",
            "bone_length_outlier", "joint_speed", "joint_residual",
            "max_joint_residual", "torso_orientation", "twist", "delta",
            "facing_mismatch", "fit_residual"
        };

        public static bool TryDecode(byte[] data, out ProtocolV2Frame frame, out string error)
        {
            frame = null;
            error = string.Empty;
            if (data == null || data.Length != PacketSize)
            {
                error = $"SMV2 packet must contain {PacketSize} bytes; received {data?.Length ?? 0}.";
                return false;
            }

            try
            {
                using (MemoryStream stream = new MemoryStream(data, false))
                using (BinaryReader reader = new BinaryReader(stream, Encoding.ASCII))
                {
                    string header = Encoding.ASCII.GetString(reader.ReadBytes(4));
                    if (header != "SMV2")
                    {
                        error = $"Unexpected protocol-v2 header: {header}";
                        return false;
                    }

                    ProtocolV2Frame result = new ProtocolV2Frame
                    {
                        protocolVersion = 2,
                        frameId = unchecked((int)reader.ReadUInt32()),
                        body = new ProtocolV2Body(),
                        hands = new ProtocolV2Hands(),
                        quality = new ProtocolV2Quality()
                    };

                    ReadFloats(reader, 3); // Legacy translation prefix; rootPosition below owns v2 motion.
                    result.body.pose = ReadFloats(reader, 156);
                    result.body.rootPosition = ReadFloats(reader, 3);
                    result.body.pelvisWorld = ReadFloats(reader, 3);
                    result.body.rootRotation = ReadFloats(reader, 4);
                    result.body.rootConfidence = reader.ReadSingle();
                    result.hands.leftLocalJoints = ReadFloats(reader, 63);
                    result.hands.leftConfidence = ReadFloats(reader, 21);
                    result.hands.rightLocalJoints = ReadFloats(reader, 63);
                    result.hands.rightConfidence = ReadFloats(reader, 21);

                    result.quality.inputValid = reader.ReadByte() != 0;
                    result.quality.inputScore = reader.ReadSingle();
                    result.quality.fitResidualMm = reader.ReadSingle();
                    result.quality.worstJointResidualMm = reader.ReadSingle();
                    result.quality.torsoOrientationDeg = reader.ReadSingle();
                    int stateCode = reader.ReadInt32();
                    result.quality.solverState = stateCode >= 0 && stateCode < SolverStates.Length
                        ? SolverStates[stateCode]
                        : "FAILED_HOLD";
                    result.quality.stepsUsed = reader.ReadInt32();
                    result.quality.reasons = DecodeReasons(reader.ReadUInt32());
                    frame = result;
                    return true;
                }
            }
            catch (Exception exception)
            {
                error = exception.Message;
                return false;
            }
        }

        private static float[] ReadFloats(BinaryReader reader, int count)
        {
            float[] values = new float[count];
            for (int index = 0; index < count; index++) values[index] = reader.ReadSingle();
            return values;
        }

        private static string[] DecodeReasons(uint mask)
        {
            List<string> reasons = new List<string>();
            for (int index = 0; index < ReasonNames.Length; index++)
            {
                if ((mask & (1u << index)) != 0) reasons.Add(ReasonNames[index]);
            }
            return reasons.ToArray();
        }
    }
}
