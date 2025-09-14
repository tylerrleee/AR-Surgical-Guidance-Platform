#!/usr/bin/env python3
"""
Mac server that receives stream from Pi and hosts doctor interface
"""

from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import asyncio
import websockets
import json
import threading
import base64
import logging
import time  # <-- required for /api/annotated_stream

# Disable Flask development server warning noise
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'telemedicine-hackathon'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global variables for stream data
current_frame = None
current_audio = None
current_annotations = []

# HTML template for doctor interface
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Telemedicine AR - Doctor Interface</title>
    <style>
        body { margin: 0; padding: 20px; font-family: Arial, sans-serif; background: #1a1a1a; color: white; }
        .container { max-width: 1200px; margin: 0 auto; }
        .video-container { position: relative; display: inline-block; border: 2px solid #333; }
        #videoCanvas { display: block; background: #000; }
        #drawingCanvas { position: absolute; top: 0; left: 0; cursor: crosshair; }
        .controls { margin-top: 20px; padding: 20px; background: #2a2a2a; border-radius: 8px; }
        .tool-btn { margin: 5px; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        .tool-btn.active { background: #007bff; color: white; }
        .color-picker { width: 50px; height: 40px; margin: 5px; vertical-align: middle; }
        .clear-btn { background: #dc3545; color: white; }
        .status { padding: 10px; margin-bottom: 20px; border-radius: 4px; }
        .status.connected { background: #28a745; }
        .status.disconnected { background: #dc3545; }
        h1 { text-align: center; color: #007bff; }
    </style>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
</head>
<body>
    <div class="container">
        <h1>Telemedicine AR System - Doctor Interface</h1>
        <div id="status" class="status disconnected">Connecting...</div>

        <div class="video-container">
            <canvas id="videoCanvas" width="640" height="480"></canvas>
            <canvas id="drawingCanvas" width="640" height="480"></canvas>
        </div>

        <div class="controls">
            <h3>Drawing Tools</h3>
            <button class="tool-btn active" onclick="setTool('pen')">✏️ Pen</button>
            <button class="tool-btn" onclick="setTool('arrow')">➡️ Arrow</button>
            <button class="tool-btn" onclick="setTool('circle')">⭕ Circle</button>
            <button class="tool-btn" onclick="setTool('rectangle')">⬜ Rectangle</button>
            <button class="tool-btn" onclick="setTool('text')">📝 Text</button>

            <input type="color" id="colorPicker" class="color-picker" value="#ff0000">
            <input type="range" id="lineWidth" min="1" max="10" value="3">
            <span id="widthDisplay">3px</span>

            <button class="tool-btn clear-btn" onclick="clearDrawing()">🗑️ Clear All</button>
        </div>
    </div>

    <script>
        const socket = io();
        // WebAudio setup
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        const audioCtx = new AudioContext();
        const resumeAudio = () => { if (audioCtx.state === 'suspended') audioCtx.resume(); };
        document.body.addEventListener('click', resumeAudio, { once: true });

        const videoCanvas = document.getElementById('videoCanvas');
        const videoCtx = videoCanvas.getContext('2d');
        const drawingCanvas = document.getElementById('drawingCanvas');
        const drawingCtx = drawingCanvas.getContext('2d');

        let isDrawing = false;
        let currentTool = 'pen';
        let startX, startY;

        socket.on('connect', () => {
            document.getElementById('status').className = 'status connected';
            document.getElementById('status').textContent = 'Connected to server';
        });

        socket.on('disconnect', () => {
            document.getElementById('status').className = 'status disconnected';
            document.getElementById('status').textContent = 'Disconnected from server';
        });

        socket.on('video_frame', (data) => {
            const img = new Image();
            img.onload = () => { videoCtx.drawImage(img, 0, 0, 640, 480); };
            img.src = 'data:image/jpeg;base64,' + data.frame;
        });

        socket.on('audio_chunk', (data) => {
            try {
                playInt16MonoPCM(data.chunk, data.rate || 16000);
            } catch (e) {
                console.error('Audio play error:', e);
            }
        });

        function playInt16MonoPCM(base64Data, sampleRate) {
            const binary = atob(base64Data);
            const len = binary.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
            const pcm16 = new Int16Array(bytes.buffer);
            const pcmFloat = new Float32Array(pcm16.length);
            for (let i = 0; i < pcm16.length; i++) {
                pcmFloat[i] = Math.max(-1, Math.min(1, pcm16[i] / 32768));
            }
            const buffer = audioCtx.createBuffer(1, pcmFloat.length, sampleRate);
            buffer.copyToChannel(pcmFloat, 0);
            const src = audioCtx.createBufferSource();
            src.buffer = buffer;
            src.connect(audioCtx.destination);
            src.start();
        }

        function setTool(tool) {
            currentTool = tool;
            document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        }

        function getMousePos(e) {
            const rect = drawingCanvas.getBoundingClientRect();
            return { x: e.clientX - rect.left, y: e.clientY - rect.top };
        }

        drawingCanvas.addEventListener('mousedown', (e) => {
            isDrawing = true;
            const pos = getMousePos(e);
            startX = pos.x; startY = pos.y;
            if (currentTool === 'pen') { drawingCtx.beginPath(); drawingCtx.moveTo(startX, startY); }
        });

        drawingCanvas.addEventListener('mousemove', (e) => {
            if (!isDrawing) return;
            const pos = getMousePos(e);
            const color = document.getElementById('colorPicker').value;
            const lineWidth = document.getElementById('lineWidth').value;
            drawingCtx.strokeStyle = color; drawingCtx.lineWidth = lineWidth;

            if (currentTool === 'pen') {
                drawingCtx.lineTo(pos.x, pos.y);
                drawingCtx.stroke();
                socket.emit('annotation', {
                    tool: 'pen', startX: startX, startY: startY,
                    endX: pos.x, endY: pos.y, color, lineWidth
                });
                startX = pos.x; startY = pos.y;
            }
        });

        drawingCanvas.addEventListener('mouseup', (e) => {
            if (!isDrawing) return;
            isDrawing = false;
            const pos = getMousePos(e);
            const color = document.getElementById('colorPicker').value;
            const lineWidth = document.getElementById('lineWidth').value;
            drawingCtx.strokeStyle = color; drawingCtx.lineWidth = lineWidth;

            let annotation = null;

            switch (currentTool) {
                case 'arrow':
                    drawArrow(startX, startY, pos.x, pos.y);
                    annotation = { tool: 'arrow', startX, startY, endX: pos.x, endY: pos.y, color, lineWidth };
                    break;
                case 'circle':
                    const radius = Math.hypot(pos.x - startX, pos.y - startY);
                    drawingCtx.beginPath(); drawingCtx.arc(startX, startY, radius, 0, 2 * Math.PI); drawingCtx.stroke();
                    annotation = { tool: 'circle', centerX: startX, centerY: startY, radius, color, lineWidth };
                    break;
                case 'rectangle':
                    drawingCtx.beginPath(); drawingCtx.rect(startX, startY, pos.x - startX, pos.y - startY); drawingCtx.stroke();
                    annotation = { tool: 'rectangle', startX, startY, width: pos.x - startX, height: pos.y - startY, color, lineWidth };
                    break;
                case 'text':
                    const text = prompt('Enter text:');
                    if (text) {
                        drawingCtx.font = '20px Arial';
                        drawingCtx.fillStyle = color;
                        drawingCtx.fillText(text, pos.x, pos.y);
                        annotation = { tool: 'text', text, x: pos.x, y: pos.y, color };
                    }
                    break;
            }
            if (annotation) { socket.emit('annotation', annotation); }
        });

        function drawArrow(fromX, fromY, toX, toY) {
            const headLength = 15;
            const angle = Math.atan2(toY - fromY, toX - fromX);
            drawingCtx.beginPath();
            drawingCtx.moveTo(fromX, fromY);
            drawingCtx.lineTo(toX, toY);
            drawingCtx.lineTo(toX - headLength * Math.cos(angle - Math.PI / 6), toY - headLength * Math.sin(angle - Math.PI / 6));
            drawingCtx.moveTo(toX, toY);
            drawingCtx.lineTo(toX - headLength * Math.cos(angle + Math.PI / 6), toY - headLength * Math.sin(angle + Math.PI / 6));
            drawingCtx.stroke();
        }

        function clearDrawing() {
            drawingCtx.clearRect(0, 0, drawingCanvas.width, drawingCanvas.height);
            socket.emit('clear_annotations');
        }

        document.getElementById('lineWidth').addEventListener('input', (e) => {
            document.getElementById('widthDisplay').textContent = e.target.value + 'px';
        });
    </script>
</body>
</html>
'''

# --- WebSocket server for Pi connection ---
async def pi_websocket_handler(websocket, path=None):
    """Handle incoming stream from Raspberry Pi (compatible with websockets >=10)."""
    global current_frame, current_audio
    frame_count = 0
    try:
        peer = getattr(websocket, "remote_address", None)
        print(f"Raspberry Pi connected from {peer}")

        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception as e:
                print(f"[WS] JSON parse error: {e}")
                continue

            if data.get("type") == "stream":
                # Update latest frame/audio in memory for the web UI
                current_frame = data.get("video")
                current_audio = data.get("audio")

                # Debug logging every ~30 frames to avoid spam
                if current_frame:
                    frame_count += 1
                    if frame_count % 30 == 0:
                        print(f"[DEBUG] Received {frame_count} frames")

                # Emit to clients
                if current_audio is not None:
                    socketio.emit("audio_chunk", {
                        "chunk": current_audio,
                        "rate": data.get("audio_rate", 16000),
                    })
                if current_frame is not None:
                    socketio.emit("video_frame", {"frame": current_frame})

    except Exception as e:
        print(f"Pi connection error: {e}")
    finally:
        print("Raspberry Pi disconnected")

def start_pi_websocket():
    """Start WebSocket server for Pi in a dedicated asyncio loop inside this thread."""
    async def main():
        # Increase max_size and add ping settings for stability
        async with websockets.serve(
            pi_websocket_handler,
            host="0.0.0.0",
            port=8765,
            max_size=4 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=10,
        ):
            print("[WS] Listening on ws://0.0.0.0:8765")
            # Run forever
            await asyncio.Future()
    asyncio.run(main())

# --- Flask routes ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# SocketIO handlers
@socketio.on('connect')
def handle_connect():
    print('Doctor interface connected')
    emit('connection_status', {'status': 'connected'})

@socketio.on('annotation')
def handle_annotation(data):
    """Handle drawing annotations from doctor"""
    global current_annotations
    current_annotations.append(data)
    socketio.emit('new_annotation', data, include_self=False)

@socketio.on('clear_annotations')
def handle_clear():
    """Clear all annotations"""
    global current_annotations
    current_annotations = []
    socketio.emit('annotations_cleared')

# API endpoint for AR glasses
@app.route('/api/annotated_stream')
def get_annotated_stream():
    """Get current frame with annotations for AR glasses"""
    return {
        'frame': current_frame,
        'annotations': current_annotations,
        'timestamp': time.time()
    }

if __name__ == '__main__':
    print("Starting Telemedicine Server...")
    print("1. Set SERVER_IP in pi_streamer.py to this Mac's IP for your chosen network setup.")
    print("2. Web UI: http://<MAC_IP>:5000 (or http://localhost:5000 on the Mac).")
    print("3. Expose with ngrok if needed: ngrok http 5000")

    # Start Pi WebSocket server in background thread
    pi_thread = threading.Thread(target=start_pi_websocket, daemon=True)
    pi_thread.start()

    # Start Flask/SocketIO server (no reloader; binds to all interfaces)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
