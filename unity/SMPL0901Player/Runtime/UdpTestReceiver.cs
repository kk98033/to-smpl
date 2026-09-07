using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace SMPL0901Player.Runtime
{
    /// <summary>
    /// Standalone UDP Test Receiver for network connectivity debugging.
    /// Does not depend on character models or SMPL codecs.
    /// </summary>
    public sealed class UdpTestReceiver : MonoBehaviour
    {
        [Header("UDP Configuration")]
        public int listenPort = 9096;
        public bool listenOnStart = true;

        [Header("UI Display")]
        public bool showGui = true;
        public Vector2 screenPosition = new Vector2(20f, 20f);
        public Vector2 windowSize = new Vector2(520f, 380f);

        // Runtime diagnostics
        public bool IsListening { get; private set; }
        public long ReceivedPackets => Interlocked.Read(ref receivedPackets);
        public float ReceiveFps { get; private set; }
        public int LastPacketSize { get; private set; }
        public string LastSenderEndpoint { get; private set; } = string.Empty;
        public string LastPacketHex { get; private set; } = string.Empty;
        public string LastPacketAscii { get; private set; } = string.Empty;
        public string LastError { get; private set; } = string.Empty;
        public float SecondsSinceLastPacket => lastPacketRealtime < 0f
            ? float.PositiveInfinity
            : Time.realtimeSinceStartup - lastPacketRealtime;

        private UdpClient udpClient;
        private Thread receiveThread;
        private volatile bool isRunning;
        private long receivedPackets;
        private float lastPacketRealtime = -1f;
        private float fpsWindowStart;
        private long fpsWindowPackets;
        private string portInputText;
        private string localIpv4Text;
        private GUIStyle labelStyle;
        private GUIStyle boxStyle;

        private void Start()
        {
            portInputText = listenPort.ToString();
            localIpv4Text = FindLocalIpv4Addresses();
            if (listenOnStart) StartListening();
        }

        private void OnEnable()
        {
            if (listenOnStart && !IsListening) StartListening();
        }

        private void OnDisable()
        {
            StopListening();
        }

        private void OnDestroy()
        {
            StopListening();
        }

        public void StartListening()
        {
            if (IsListening) return;
            try
            {
                udpClient = new UdpClient();
                udpClient.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
                udpClient.Client.Bind(new IPEndPoint(IPAddress.Any, listenPort));

                isRunning = true;
                IsListening = true;
                LastError = string.Empty;
                fpsWindowStart = Time.realtimeSinceStartup;
                fpsWindowPackets = ReceivedPackets;

                receiveThread = new Thread(ReceiveLoop)
                {
                    IsBackground = true,
                    Name = $"UdpTestReceiver-{listenPort}"
                };
                receiveThread.Start();
                Debug.Log($"[UDP Test] Started listening on UDP 0.0.0.0:{listenPort}", this);
            }
            catch (Exception ex)
            {
                LastError = ex.Message;
                IsListening = false;
                Debug.LogError($"[UDP Test] Failed to bind port {listenPort}: {ex.Message}", this);
            }
        }

        public void StopListening()
        {
            isRunning = false;
            IsListening = false;
            try { udpClient?.Close(); } catch { }
            udpClient = null;
            if (receiveThread != null && receiveThread.IsAlive) receiveThread.Join(200);
            receiveThread = null;
        }

        public void Restart(int newPort)
        {
            listenPort = Mathf.Clamp(newPort, 1, 65535);
            portInputText = listenPort.ToString();
            StopListening();
            StartListening();
        }

        public void ClearStats()
        {
            Interlocked.Exchange(ref receivedPackets, 0);
            LastPacketSize = 0;
            LastSenderEndpoint = string.Empty;
            LastPacketHex = string.Empty;
            LastPacketAscii = string.Empty;
            lastPacketRealtime = -1f;
        }

        private void ReceiveLoop()
        {
            IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
            while (isRunning)
            {
                try
                {
                    byte[] data = udpClient.Receive(ref remote);
                    Interlocked.Increment(ref receivedPackets);

                    int size = data.Length;
                    string sender = remote.ToString();

                    // Hex preview of first up to 32 bytes
                    StringBuilder hex = new StringBuilder();
                    int previewLen = Mathf.Min(size, 32);
                    for (int i = 0; i < previewLen; i++)
                    {
                        hex.Append(data[i].ToString("X2"));
                        if (i < previewLen - 1) hex.Append(" ");
                    }
                    if (size > 32) hex.Append(" ...");

                    // ASCII preview (printable chars only)
                    StringBuilder ascii = new StringBuilder();
                    int asciiLen = Mathf.Min(size, 64);
                    for (int i = 0; i < asciiLen; i++)
                    {
                        byte b = data[i];
                        ascii.Append(b >= 32 && b <= 126 ? (char)b : '.');
                    }
                    if (size > 64) ascii.Append(" ...");

                    LastPacketSize = size;
                    LastSenderEndpoint = sender;
                    LastPacketHex = hex.ToString();
                    LastPacketAscii = ascii.ToString();
                    lastPacketRealtime = Time.realtimeSinceStartup;
                }
                catch (SocketException)
                {
                    if (isRunning) LastError = "Socket closed unexpectedly.";
                }
                catch (ObjectDisposedException) { }
                catch (Exception ex)
                {
                    LastError = ex.Message;
                }
            }
        }

        private void Update()
        {
            float elapsed = Time.realtimeSinceStartup - fpsWindowStart;
            if (elapsed >= 1f)
            {
                long count = ReceivedPackets;
                ReceiveFps = (count - fpsWindowPackets) / elapsed;
                fpsWindowPackets = count;
                fpsWindowStart = Time.realtimeSinceStartup;
            }
        }

        private void OnGUI()
        {
            if (!showGui) return;

            if (labelStyle == null)
            {
                labelStyle = new GUIStyle(GUI.skin.label)
                {
                    fontSize = 14,
                    richText = true
                };
            }

            Rect windowRect = new Rect(screenPosition.x, screenPosition.y, windowSize.x, windowSize.y);
            GUI.Box(windowRect, "UDP Test Receiver (Standalone)");

            float startX = windowRect.x + 15;
            float curY = windowRect.y + 30;

            // IP & Port Configuration row
            GUI.Label(new Rect(startX, curY, 80, 24), "Listen Port:");
            portInputText = GUI.TextField(new Rect(startX + 85, curY, 70, 24), portInputText ?? "19095");

            if (GUI.Button(new Rect(startX + 165, curY, 85, 24), "Apply / Bind"))
            {
                if (int.TryParse(portInputText, out int parsedPort))
                {
                    Restart(parsedPort);
                }
            }

            if (GUI.Button(new Rect(startX + 260, curY, 70, 24), IsListening ? "Stop" : "Start"))
            {
                if (IsListening) StopListening(); else StartListening();
            }

            if (GUI.Button(new Rect(startX + 340, curY, 80, 24), "Clear Stats"))
            {
                ClearStats();
            }

            curY += 32;

            // Status indicator
            string statusColor = IsListening ? "#43d17c" : "#ff6b6b";
            string statusText = IsListening ? "LISTENING" : "STOPPED";
            GUI.Label(new Rect(startX, curY, windowRect.width - 30, 24),
                $"Status: <color={statusColor}><b>{statusText}</b></color> on 0.0.0.0:{listenPort}", labelStyle);

            curY += 24;
            GUI.Label(new Rect(startX, curY, windowRect.width - 30, 24),
                $"Unity Local IPv4: <b>{localIpv4Text}</b>", labelStyle);

            curY += 28;
            string ageText = float.IsPositiveInfinity(SecondsSinceLastPacket) ? "--" : $"{SecondsSinceLastPacket:F2}s ago";
            string summary =
                $"<b>Packets Received:</b> <color=#43d17c>{ReceivedPackets}</color>\n" +
                $"<b>Receive Rate:</b> {ReceiveFps:F1} packets/sec\n" +
                $"<b>Last Sender:</b> {(string.IsNullOrEmpty(LastSenderEndpoint) ? "--" : LastSenderEndpoint)}\n" +
                $"<b>Last Packet Size:</b> {LastPacketSize} bytes (Age: {ageText})\n" +
                $"<b>ASCII Preview:</b> <color=#ffd166>{(string.IsNullOrEmpty(LastPacketAscii) ? "(none)" : LastPacketAscii)}</color>\n" +
                $"<b>HEX Dump:</b> {(string.IsNullOrEmpty(LastPacketHex) ? "(none)" : LastPacketHex)}";

            GUI.Label(new Rect(startX, curY, windowRect.width - 30, 160), summary, labelStyle);

            if (!string.IsNullOrEmpty(LastError))
            {
                GUI.Label(new Rect(startX, windowRect.y + windowRect.height - 35, windowRect.width - 30, 30),
                    $"<color=#ff6b6b>Error: {LastError}</color>", labelStyle);
            }
        }

        private static string FindLocalIpv4Addresses()
        {
            try
            {
                List<string> values = new List<string>();
                foreach (IPAddress address in Dns.GetHostAddresses(Dns.GetHostName()))
                {
                    if (address.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(address))
                        values.Add(address.ToString());
                }
                return values.Count > 0 ? string.Join(", ", values) : "none";
            }
            catch (Exception ex)
            {
                return "lookup failed: " + ex.Message;
            }
        }
    }
}
