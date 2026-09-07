using System;
using System.IO;
using System.Text;

namespace SMPL0901Player.Runtime
{
    public sealed class Rsv1RawSkeletonFrame
    {
        public ushort protocolVersion;
        public ushort flags;
        public uint frameId;
        public ulong ptpEpochNs;
        public byte unit;
        public string coordinateFrame;
        public float[] points;
        public float[] confidence;

        public bool HasPreciseSourcePtp => (flags & 1) != 0;
    }

    /// <summary>Decoder for &lt;4sHHIQB3x64s177f59f (1032 bytes).</summary>
    public static class Rsv1RawSkeletonCodec
    {
        public const int PacketSize = 1032;
        public const int JointCount = 59;

        public static bool TryDecode(
            byte[] packet, out Rsv1RawSkeletonFrame frame, out string error)
        {
            frame = null;
            error = string.Empty;
            if (packet == null || packet.Length != PacketSize)
            {
                error = $"RSV1 packet must contain {PacketSize} bytes; received {packet?.Length ?? 0}.";
                return false;
            }
            try
            {
                using (MemoryStream stream = new MemoryStream(packet, false))
                using (BinaryReader reader = new BinaryReader(stream, Encoding.UTF8))
                {
                    string magic = Encoding.ASCII.GetString(reader.ReadBytes(4));
                    if (magic != "RSV1")
                    {
                        error = $"Unexpected raw-skeleton magic: {magic}";
                        return false;
                    }
                    Rsv1RawSkeletonFrame result = new Rsv1RawSkeletonFrame
                    {
                        protocolVersion = reader.ReadUInt16(),
                        flags = reader.ReadUInt16(),
                        frameId = reader.ReadUInt32(),
                        ptpEpochNs = reader.ReadUInt64(),
                        unit = reader.ReadByte()
                    };
                    reader.ReadBytes(3);
                    byte[] coordinateBytes = reader.ReadBytes(64);
                    int nul = Array.IndexOf(coordinateBytes, (byte)0);
                    int textLength = nul >= 0 ? nul : coordinateBytes.Length;
                    result.coordinateFrame = Encoding.UTF8.GetString(coordinateBytes, 0, textLength);
                    result.points = ReadFloats(reader, JointCount * 3);
                    result.confidence = ReadFloats(reader, JointCount);
                    if (result.protocolVersion != 1)
                    {
                        error = $"Unsupported RSV1 protocol version {result.protocolVersion}.";
                        return false;
                    }
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
    }
}
