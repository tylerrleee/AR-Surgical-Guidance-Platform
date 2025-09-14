#!/usr/bin/env python3
"""
Doctor's UI for telemedicine system - handles login, patient data display,
live video streaming with annotations, and bidirectional audio.
"""
from flask import Flask, render_template_string, request, jsonify, session as flask_session
from flask_cors import CORS
import requests
import base64
import cv2
import numpy as np
import time
import threading
import queue
import json
import secrets
from datetime import datetime
import io
import wave

# Import the client from doctor.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from doctor import TelemedicineStreamClient

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

# Global state
current_client = None
active_sessions = {}
doctor_audio_queue = queue.Queue(maxsize=10)
annotation_queue = queue.Queue(maxsize=50)

# Configuration
NGROK_URL = ""  # Will be set after login
LOCALHOST_URL = "http://localhost:5001"  # For sending doctor's data

class DoctorSession:
    def __init__(self, doctor_id, ngrok_url):
        self.doctor_id = doctor_id
        self.ngrok_url = ngrok_url
        self.client = TelemedicineStreamClient(ngrok_url)
        self.current_session_id = None
        self.patient_info = None
        self.annotations = []
        self.last_frame = None

# HTML Template for Doctor's UI
DOCTOR_UI_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doctor's Telemedicine Console</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a1a;
            color: #fff;
            height: 100vh;
            overflow: hidden;
        }
        
        /* Login Form */
        #login-screen {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 2000;
        }
        .login-form {
            background: #2a2a2a;
            padding: 3rem;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            max-width: 400px;
            width: 90%;
        }
        .login-form h1 {
            text-align: center;
            margin-bottom: 2rem;
            color: #4CAF50;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: #ccc;
        }
        .form-group input {
            width: 100%;
            padding: 1rem;
            background: #1a1a1a;
            border: 1px solid #444;
            border-radius: 8px;
            color: #fff;
            font-size: 1rem;
        }
        .login-btn {
            width: 100%;
            padding: 1rem;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            cursor: pointer;
            transition: background 0.2s;
        }
        .login-btn:hover { background: #45a049; }
        
        /* Main Interface */
        .main-container {
            display: none;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        /* Header */
        .header {
            background: #2a2a2a;
            padding: 1rem 2rem;
            border-bottom: 1px solid #444;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .doctor-info {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .session-selector {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .session-selector select {
            background: #1a1a1a;
            color: #fff;
            border: 1px solid #444;
            padding: 0.5rem;
            border-radius: 4px;
        }
        
        /* Content Area */
        .content {
            flex: 1;
            display: flex;
            height: calc(100vh - 80px);
        }
        
        /* Patient Info Sidebar */
        .patient-sidebar {
            width: 300px;
            background: #2a2a2a;
            border-right: 1px solid #444;
            padding: 1.5rem;
            overflow-y: auto;
        }
        .patient-card {
            background: #1a1a1a;
            padding: 1.5rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
        }
        .patient-name {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        .patient-detail {
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
        }
        .severity-critical { color: #ff4444; }
        .severity-urgent { color: #ff9944; }
        .severity-stable { color: #44ff44; }
        
        /* Video Area */
        .video-container {
            flex: 1;
            position: relative;
            background: #000;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        #video-canvas {
            max-width: 100%;
            max-height: 100%;
            cursor: crosshair;
        }
        .no-stream {
            text-align: center;
            color: #666;
        }
        
        /* Drawing Tools */
        .drawing-tools {
            position: absolute;
            top: 20px;
            left: 20px;
            background: rgba(0,0,0,0.8);
            padding: 1rem;
            border-radius: 12px;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        .tool-btn {
            background: #444;
            color: #fff;
            border: none;
            padding: 0.5rem;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .tool-btn:hover { background: #555; }
        .tool-btn.active { background: #4CAF50; }
        
        /* Audio Controls */
        .audio-controls {
            position: absolute;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.8);
            padding: 1rem 2rem;
            border-radius: 30px;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .mic-btn {
            background: #ff4444;
            color: white;
            border: none;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            cursor: pointer;
            transition: all 0.2s;
        }
        .mic-btn:hover { transform: scale(1.1); }
        .mic-btn.recording { background: #44ff44; animation: pulse 1s infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        /* Status Indicators */
        .status-bar {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(0,0,0,0.8);
            padding: 0.75rem 1.5rem;
            border-radius: 20px;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #44ff44;
            animation: pulse 2s infinite;
        }
    </style>
</head>
<body>
    <!-- Login Screen -->
    <div id="login-screen">
        <div class="login-form">
            <h1>🩺 Doctor Login</h1>
            <form id="login-form">
                <div class="form-group">
                    <label>Doctor ID</label>
                    <input type="text" id="doctor-id" required placeholder="Enter your doctor ID">
                </div>
                <div class="form-group">
                    <label>Ngrok URL</label>
                    <input type="url" id="ngrok-url" required placeholder="https://xxxx-xx-xx-xxx-xxx.ngrok-free.app">
                </div>
                <button type="submit" class="login-btn">Connect to System</button>
            </form>
        </div>
    </div>
    
    <!-- Main Interface -->
    <div class="main-container" id="main-interface">
        <!-- Header -->
        <div class="header">
            <div class="doctor-info">
                <span>👨‍⚕️ Dr. <span id="current-doctor"></span></span>
                <span id="connection-status">Connected</span>
            </div>
            <div class="session-selector">
                <label>Active Sessions:</label>
                <select id="session-select">
                    <option value="">Select a session...</option>
                </select>
                <button onclick="refreshSessions()" style="background: #4CAF50; color: white; border: none; padding: 0.5rem; border-radius: 4px;">Refresh</button>
            </div>
        </div>
        
        <!-- Content -->
        <div class="content">
            <!-- Patient Sidebar -->
            <div class="patient-sidebar">
                <div id="patient-info" style="display: none;">
                    <div class="patient-card">
                        <div class="patient-name" id="patient-name">-</div>
                        <div class="patient-detail">
                            <span>Age:</span>
                            <span id="patient-age">-</span>
                        </div>
                        <div class="patient-detail">
                            <span>Severity:</span>
                            <span id="patient-severity">-</span>
                        </div>
                        <div class="patient-detail">
                            <span>Session:</span>
                            <span id="session-id" style="font-family: monospace;">-</span>
                        </div>
                    </div>
                    <div class="patient-card">
                        <h3 style="margin-bottom: 1rem;">Chief Complaint</h3>
                        <p id="patient-complaint">-</p>
                    </div>
                    <div class="patient-card" id="patient-notes-card" style="display: none;">
                        <h3 style="margin-bottom: 1rem;">Additional Notes</h3>
                        <p id="patient-notes">-</p>
                    </div>
                </div>
                <div id="no-session" style="text-align: center; color: #666; margin-top: 2rem;">
                    <h3>No Session Selected</h3>
                    <p>Please select an active session above</p>
                </div>
            </div>
            
            <!-- Video Area -->
            <div class="video-container">
                <div class="no-stream" id="no-stream">
                    <h3>🎥 Waiting for video stream...</h3>
                    <p>Video feed will appear here once connected</p>
                </div>
                <canvas id="video-canvas" style="display: none;"></canvas>
                
                <!-- Drawing Tools -->
                <div class="drawing-tools">
                    <h4 style="margin-bottom: 0.5rem;">Tools</h4>
                    <button class="tool-btn active" data-tool="free" onclick="selectTool('free')">✏️ Draw</button>
                    <button class="tool-btn" data-tool="circle" onclick="selectTool('circle')">⭕ Circle</button>
                    <button class="tool-btn" data-tool="arrow" onclick="selectTool('arrow')">↗️ Arrow</button>
                    <button class="tool-btn" onclick="clearAnnotations()">🗑️ Clear</button>
                </div>
                
                <!-- Audio Controls -->
                <div class="audio-controls">
                    <button class="mic-btn" id="mic-btn" onclick="toggleMic()">🎤</button>
                    <span id="audio-status">Click to start speaking</span>
                    <span id="patient-audio">🔊 Patient Audio</span>
                </div>
                
                <!-- Status Bar -->
                <div class="status-bar">
                    <div class="status-dot"></div>
                    <span>LIVE</span>
                    <span id="fps-counter">0 FPS</span>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Global state
        let doctorId = '';
        let ngrokUrl = '';
        let currentSessionId = '';
        let canvas, ctx;
        let isDrawing = false;
        let currentTool = 'free';
        let annotations = [];
        let isRecording = false;
        let mediaRecorder = null;
        let audioContext = null;
        let nextTime = 0;
        let frameCount = 0;
        let lastFpsUpdate = Date.now();
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            canvas = document.getElementById('video-canvas');
            ctx = canvas.getContext('2d');
            setupDrawingEvents();
            setupAudio();
        });
        
        // Login handling
        document.getElementById('login-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            doctorId = document.getElementById('doctor-id').value;
            ngrokUrl = document.getElementById('ngrok-url').value.replace(/\/$/, '');
            
            try {
                // Test connection
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({doctor_id: doctorId, ngrok_url: ngrokUrl})
                });
                
                if (response.ok) {
                    document.getElementById('login-screen').style.display = 'none';
                    document.getElementById('main-interface').style.display = 'flex';
                    document.getElementById('current-doctor').textContent = doctorId;
                    refreshSessions();
                    startStreamLoop();
                } else {
                    alert('Failed to connect. Please check your credentials and ngrok URL.');
                }
            } catch (err) {
                alert('Connection failed: ' + err.message);
            }
        });
        
        // Session management
        async function refreshSessions() {
            try {
                const response = await fetch('/api/sessions');
                const sessions = await response.json();
                
                const select = document.getElementById('session-select');
                select.innerHTML = '<option value="">Select a session...</option>';
                
                sessions.forEach(session => {
                    const option = document.createElement('option');
                    option.value = session.session_id;
                    option.textContent = `${session.patient_name} (${session.severity})`;
                    select.appendChild(option);
                });
            } catch (err) {
                console.error('Failed to refresh sessions:', err);
            }
        }
        
        document.getElementById('session-select').addEventListener('change', function() {
            const sessionId = this.value;
            if (sessionId) {
                connectToSession(sessionId);
            }
        });
        
        async function connectToSession(sessionId) {
            try {
                const response = await fetch(`/api/session/${sessionId}`);
                const sessionData = await response.json();
                
                currentSessionId = sessionId;
                displayPatientInfo(sessionData);
                
                // Show patient info, hide no-session message
                document.getElementById('patient-info').style.display = 'block';
                document.getElementById('no-session').style.display = 'none';
                
            } catch (err) {
                console.error('Failed to connect to session:', err);
            }
        }
        
        function displayPatientInfo(sessionData) {
            const info = sessionData.patient_info;
            document.getElementById('patient-name').textContent = info.name || 'Unknown';
            document.getElementById('patient-age').textContent = info.age || 'Unknown';
            document.getElementById('patient-severity').textContent = (info.severity || 'unknown').toUpperCase();
            document.getElementById('patient-severity').className = 'severity-' + (info.severity || 'unknown');
            document.getElementById('session-id').textContent = sessionData.session_id;
            document.getElementById('patient-complaint').textContent = info.complaint || 'No complaint recorded';
            
            if (info.notes) {
                document.getElementById('patient-notes').textContent = info.notes;
                document.getElementById('patient-notes-card').style.display = 'block';
            } else {
                document.getElementById('patient-notes-card').style.display = 'none';
            }
        }
        
        // Video streaming
        async function startStreamLoop() {
            setInterval(async () => {
                if (!currentSessionId) return;
                
                try {
                    const response = await fetch(`/api/stream/${currentSessionId}`);
                    const data = await response.json();
                    
                    if (data.img) {
                        displayFrame(data.img);
                        updateFPS();
                    }
                    
                    if (data.audio) {
                        playAudio(data.audio);
                    }
                } catch (err) {
                    console.error('Stream error:', err);
                }
            }, 50); // 20 FPS
        }
        
        function displayFrame(base64Image) {
            const img = new Image();
            img.onload = function() {
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);
                
                // Draw annotations
                drawAnnotations();
                
                // Show canvas, hide no-stream
                document.getElementById('no-stream').style.display = 'none';
                canvas.style.display = 'block';
            };
            img.src = 'data:image/jpeg;base64,' + base64Image;
        }
        
        function updateFPS() {
            frameCount++;
            const now = Date.now();
            if (now - lastFpsUpdate >= 1000) {
                document.getElementById('fps-counter').textContent = frameCount + ' FPS';
                frameCount = 0;
                lastFpsUpdate = now;
            }
        }
        
        // Drawing functionality
        function setupDrawingEvents() {
            let startX, startY;
            
            canvas.addEventListener('mousedown', function(e) {
                if (!currentSessionId) return;
                
                const rect = canvas.getBoundingClientRect();
                startX = e.clientX - rect.left;
                startY = e.clientY - rect.top;
                isDrawing = true;
                
                if (currentTool === 'free') {
                    const annotation = {
                        type: 'path',
                        points: [{x: startX, y: startY}],
                        timestamp: Date.now(),
                        id: Math.random().toString(36).substr(2, 9)
                    };
                    annotations.push(annotation);
                }
            });
            
            canvas.addEventListener('mousemove', function(e) {
                if (!isDrawing || !currentSessionId) return;
                
                const rect = canvas.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                
                if (currentTool === 'free') {
                    const lastAnnotation = annotations[annotations.length - 1];
                    lastAnnotation.points.push({x, y});
                }
            });
            
            canvas.addEventListener('mouseup', function(e) {
                if (!isDrawing || !currentSessionId) return;
                
                const rect = canvas.getBoundingClientRect();
                const endX = e.clientX - rect.left;
                const endY = e.clientY - rect.top;
                
                if (currentTool === 'circle') {
                    const radius = Math.sqrt(Math.pow(endX - startX, 2) + Math.pow(endY - startY, 2));
                    annotations.push({
                        type: 'circle',
                        x: startX,
                        y: startY,
                        radius: radius,
                        timestamp: Date.now(),
                        id: Math.random().toString(36).substr(2, 9)
                    });
                } else if (currentTool === 'arrow') {
                    annotations.push({
                        type: 'arrow',
                        startX: startX,
                        startY: startY,
                        endX: endX,
                        endY: endY,
                        timestamp: Date.now(),
                        id: Math.random().toString(36).substr(2, 9)
                    });
                }
                
                isDrawing = false;
                sendAnnotations();
            });
        }
        
        function selectTool(tool) {
            currentTool = tool;
            document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelector(`[data-tool="${tool}"]`).classList.add('active');
        }
        
        function drawAnnotations() {
            const now = Date.now();
            annotations = annotations.filter(ann => now - ann.timestamp < 10000); // Keep for 10 seconds
            
            annotations.forEach(ann => {
                const age = now - ann.timestamp;
                const opacity = Math.max(0, 1 - age / 10000); // Fade over 10 seconds
                
                ctx.strokeStyle = `rgba(255, 0, 0, ${opacity})`;
                ctx.lineWidth = 3;
                ctx.lineCap = 'round';
                
                if (ann.type === 'path') {
                    if (ann.points.length > 1) {
                        ctx.beginPath();
                        ctx.moveTo(ann.points[0].x, ann.points[0].y);
                        for (let i = 1; i < ann.points.length; i++) {
                            ctx.lineTo(ann.points[i].x, ann.points[i].y);
                        }
                        ctx.stroke();
                    }
                } else if (ann.type === 'circle') {
                    ctx.beginPath();
                    ctx.arc(ann.x, ann.y, ann.radius, 0, 2 * Math.PI);
                    ctx.stroke();
                } else if (ann.type === 'arrow') {
                    drawArrow(ann.startX, ann.startY, ann.endX, ann.endY);
                }
            });
        }
        
        function drawArrow(startX, startY, endX, endY) {
            const headlen = 15;
            const angle = Math.atan2(endY - startY, endX - startX);
            
            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.lineTo(endX, endY);
            ctx.stroke();
            
            ctx.beginPath();
            ctx.moveTo(endX, endY);
            ctx.lineTo(endX - headlen * Math.cos(angle - Math.PI / 6), endY - headlen * Math.sin(angle - Math.PI / 6));
            ctx.moveTo(endX, endY);
            ctx.lineTo(endX - headlen * Math.cos(angle + Math.PI / 6), endY - headlen * Math.sin(angle + Math.PI / 6));
            ctx.stroke();
        }
        
        function clearAnnotations() {
            annotations = [];
            sendAnnotations();
        }
        
        async function sendAnnotations() {
            try {
                await fetch('/api/annotations', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        session_id: currentSessionId,
                        annotations: annotations
                    })
                });
            } catch (err) {
                console.error('Failed to send annotations:', err);
            }
        }
        
        // Audio functionality
        async function setupAudio() {
            try {
                audioContext = new (window.AudioContext || window.webkitAudioContext)({
                    latencyHint: 'playback',
                    sampleRate: 48000
                });
            } catch (err) {
                console.error('Failed to setup audio:', err);
            }
        }
        
        function playAudio(base64Data) {
            if (!audioContext || !base64Data) return;
            
            try {
                const binaryString = atob(base64Data);
                const len = binaryString.length;
                const bytes = new Uint8Array(len);
                for (let i = 0; i < len; i++) bytes[i] = binaryString.charCodeAt(i);
                
                const pcmData = bytes.slice(44);
                const int16Array = new Int16Array(
                    pcmData.buffer,
                    pcmData.byteOffset,
                    Math.floor(pcmData.byteLength / 2)
                );
                const float32Array = new Float32Array(int16Array.length);
                for (let i = 0; i < int16Array.length; i++) {
                    float32Array[i] = int16Array[i] / 32768.0;
                }
                
                const buffer = audioContext.createBuffer(1, float32Array.length, 48000);
                buffer.copyToChannel(float32Array, 0);
                
                const source = audioContext.createBufferSource();
                source.buffer = buffer;
                source.connect(audioContext.destination);
                
                const now = audioContext.currentTime;
                if (nextTime < now + 0.05) nextTime = now + 0.05;
                
                source.start(nextTime);
                nextTime += buffer.duration;
            } catch (err) {
                console.error('Audio playback error:', err);
            }
        }
        
        async function toggleMic() {
            if (isRecording) {
                stopRecording();
            } else {
                startRecording();
            }
        }
        
        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                
                mediaRecorder.ondataavailable = function(event) {
                    if (event.data.size > 0) {
                        sendAudioData(event.data);
                    }
                };
                
                mediaRecorder.start(100); // 100ms chunks
                isRecording = true;
                
                document.getElementById('mic-btn').classList.add('recording');
                document.getElementById('audio-status').textContent = 'Recording...';
            } catch (err) {
                console.error('Failed to start recording:', err);
                alert('Microphone access denied or not available');
            }
        }
        
        function stopRecording() {
            if (mediaRecorder) {
                mediaRecorder.stop();
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
                mediaRecorder = null;
            }
            
            isRecording = false;
            document.getElementById('mic-btn').classList.remove('recording');
            document.getElementById('audio-status').textContent = 'Click to start speaking';
        }
        
        async function sendAudioData(audioBlob) {
            try {
                const formData = new FormData();
                formData.append('audio', audioBlob);
                formData.append('session_id', currentSessionId);
                
                await fetch('/api/doctor_audio', {
                    method: 'POST',
                    body: formData
                });
            } catch (err) {
                console.error('Failed to send audio:', err);
            }
        }
        
        // Auto-refresh sessions every 30 seconds
        setInterval(refreshSessions, 30000);
    </script>
</body>
</html>
'''

# API Routes
@app.route('/')
def index():
    return render_template_string(DOCTOR_UI_TEMPLATE)

@app.route('/api/login', methods=['POST'])
def login():
    global current_client, NGROK_URL
    data = request.json
    doctor_id = data['doctor_id']
    ngrok_url = data['ngrok_url']
    
    try:
        # Test connection to ngrok URL
        test_client = TelemedicineStreamClient(ngrok_url)
        sessions = test_client.list_sessions()
        
        # Store in session
        flask_session['doctor_id'] = doctor_id
        flask_session['ngrok_url'] = ngrok_url
        
        # Set global state
        NGROK_URL = ngrok_url
        current_client = test_client
        
        return jsonify({'status': 'success', 'doctor_id': doctor_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/sessions')
def get_sessions():
    if not current_client:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        sessions = current_client.list_sessions()
        return jsonify(sessions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/session/<session_id>')
def get_session_info(session_id):
    if not current_client:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        info = current_client.get_session_info(session_id)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stream/<session_id>')
def get_stream_data(session_id):
    if not current_client:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        # Get stream data from ngrok server
        response = requests.get(f"{NGROK_URL}/api/stream/{session_id}", timeout=1)
        return response.json()
    except Exception as e:
        return jsonify({'img': '', 'audio': '', 'error': str(e)})

@app.route('/api/annotations', methods=['POST'])
def send_annotations():
    """Send annotations to localhost for ngrok forwarding"""
    data = request.json
    
    try:
        # Send to localhost server (which will be exposed via ngrok)
        requests.post(f"{LOCALHOST_URL}/doctor_annotations", 
                     json=data, 
                     timeout=0.5)
    except Exception as e:
        print(f"Failed to send annotations: {e}")
    
    return jsonify({'status': 'ok'})

@app.route('/api/doctor_audio', methods=['POST'])
def send_doctor_audio():
    """Send doctor's audio to localhost for ngrok forwarding"""
    try:
        audio_file = request.files['audio']
        session_id = request.form['session_id']
        
        # Convert to base64 for transmission
        audio_data = audio_file.read()
        audio_b64 = base64.b64encode(audio_data).decode()
        
        # Send to localhost server
        requests.post(f"{LOCALHOST_URL}/doctor_audio", 
                     json={
                         'session_id': session_id,
                         'audio': audio_b64,
                         'doctor_id': flask_session.get('doctor_id', 'unknown')
                     }, 
                     timeout=0.5)
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        print(f"Failed to send doctor audio: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Doctor's Telemedicine UI")
    print("Access at: http://localhost:5002")
    print("\nThis will connect to your ngrok-exposed patient stream")
    print("and send doctor's annotations/audio to localhost:5001 for ngrok forwarding")
    app.run(host='0.0.0.0', port=5002, debug=False) 