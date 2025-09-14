#!/usr/bin/env python3
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import base64
import logging
import json
from datetime import datetime
import threading
import time

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)  # Enable CORS for external access

# Session data
sessions = {}
current_session_id = None

class Session:
    def __init__(self, session_id, patient_info):
        self.id = session_id
        self.patient_info = patient_info
        self.start_time = datetime.now()
        self.img = ''
        self.audio_chunks = []
        self.annotations = []  # For future drawing overlay
        self.active = True
        
    def add_frame(self, img, audio=None):
        self.img = img
        if audio:
            self.audio_chunks.append(audio)
            # Keep last 10 chunks (~1 second)
            if len(self.audio_chunks) > 10:
                self.audio_chunks.pop(0)
    
    def get_latest(self):
        return {
            'img': self.img,
            'audio': self.audio_chunks[-1] if self.audio_chunks else '',
            'annotations': self.annotations,
            'session_id': self.id,
            'patient_info': self.patient_info
        }

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Emergency Telemedicine Portal</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #fff;
            height: 100vh;
            overflow: hidden;
        }
        .container { height: 100vh; display: flex; flex-direction: column; }
        
        /* Intake Form */
        #intake-form {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.95);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .form-content {
            background: #1a1a1a;
            padding: 2rem;
            border-radius: 12px;
            max-width: 500px;
            width: 90%;
            box-shadow: 0 10px 50px rgba(0,0,0,0.5);
        }
        .form-content h2 {
            color: #ff3333;
            margin-bottom: 1.5rem;
            text-align: center;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: #ccc;
            font-size: 0.9rem;
        }
        .form-group input, .form-group textarea, .form-group select {
            width: 100%;
            padding: 0.75rem;
            background: #2a2a2a;
            border: 1px solid #444;
            border-radius: 6px;
            color: #fff;
            font-size: 1rem;
        }
        .form-group textarea {
            min-height: 100px;
            resize: vertical;
        }
        .severity-options {
            display: flex;
            gap: 1rem;
            margin-top: 0.5rem;
        }
        .severity-option {
            flex: 1;
            padding: 1rem;
            background: #2a2a2a;
            border: 2px solid #444;
            border-radius: 6px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
        }
        .severity-option:hover {
            border-color: #666;
        }
        .severity-option.selected {
            border-color: #ff3333;
            background: #3a2020;
        }
        .start-btn {
            width: 100%;
            padding: 1rem;
            background: #ff3333;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            margin-top: 1.5rem;
            transition: background 0.2s;
        }
        .start-btn:hover {
            background: #e62929;
        }
        
        /* Stream View */
        .header {
            background: #1a1a1a;
            padding: 1rem;
            border-bottom: 1px solid #333;
            display: none;
        }
        .patient-info {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .info-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .info-label {
            color: #888;
            font-size: 0.9rem;
        }
        .severity-critical { color: #ff3333; font-weight: 600; }
        .severity-urgent { color: #ff9933; font-weight: 600; }
        .severity-stable { color: #33ff33; font-weight: 600; }
        
        .stream-container {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            background: #000;
        }
        #stream-img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }
        .no-signal {
            text-align: center;
            color: #666;
        }
        .status-bar {
            position: absolute;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.8);
            padding: 0.75rem 1.5rem;
            border-radius: 30px;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #33ff33;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .audio-status {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        /* API Info */
        .api-info {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(0,0,0,0.8);
            padding: 1rem;
            border-radius: 8px;
            font-size: 0.8rem;
            display: none;
        }
        .api-info code {
            background: #2a2a2a;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Patient Intake Form -->
        <div id="intake-form">
            <div class="form-content">
                <h2>🚨 Emergency Medical Stream</h2>
                <form id="patient-form">
                    <div class="form-group">
                        <label>Patient Name/ID</label>
                        <input type="text" id="patient-name" required placeholder="Enter patient identifier">
                    </div>
                    
                    <div class="form-group">
                        <label>Age</label>
                        <input type="number" id="patient-age" required placeholder="Patient age">
                    </div>
                    
                    <div class="form-group">
                        <label>Chief Complaint</label>
                        <textarea id="complaint" required placeholder="Describe the medical issue briefly..."></textarea>
                    </div>
                    
                    <div class="form-group">
                        <label>Severity</label>
                        <div class="severity-options">
                            <div class="severity-option" data-severity="critical">
                                <strong>Critical</strong>
                                <div style="font-size: 0.8rem; color: #888; margin-top: 0.25rem;">Life-threatening</div>
                            </div>
                            <div class="severity-option" data-severity="urgent">
                                <strong>Urgent</strong>
                                <div style="font-size: 0.8rem; color: #888; margin-top: 0.25rem;">Needs immediate care</div>
                            </div>
                            <div class="severity-option" data-severity="stable">
                                <strong>Stable</strong>
                                <div style="font-size: 0.8rem; color: #888; margin-top: 0.25rem;">Can wait briefly</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label>Additional Notes (Optional)</label>
                        <textarea id="notes" placeholder="Allergies, medications, relevant history..."></textarea>
                    </div>
                    
                    <button type="submit" class="start-btn">Start Emergency Stream</button>
                </form>
            </div>
        </div>
        
        <!-- Stream Header -->
        <div class="header">
            <div class="patient-info">
                <div class="info-item">
                    <span class="info-label">Patient:</span>
                    <span id="display-name"></span>
                </div>
                <div class="info-item">
                    <span class="info-label">Age:</span>
                    <span id="display-age"></span>
                </div>
                <div class="info-item">
                    <span class="info-label">Severity:</span>
                    <span id="display-severity"></span>
                </div>
                <div class="info-item">
                    <span class="info-label">Session:</span>
                    <span id="display-session" style="font-family: monospace; font-size: 0.9rem;"></span>
                </div>
            </div>
        </div>
        
        <!-- Video Stream -->
        <div class="stream-container">
            <div class="no-signal" id="no-signal">
                <h3>Waiting for video signal...</h3>
                <p style="margin-top: 1rem; color: #666;">Camera feed will appear here</p>
            </div>
            <img id="stream-img" style="display: none;">
            
            <div class="status-bar" id="status-bar" style="display: none;">
                <div class="status-indicator"></div>
                <span>LIVE</span>
                <div class="audio-status">
                    <span id="audio-indicator">🔇</span>
                    <span id="audio-text">Click to enable audio</span>
                </div>
            </div>
        </div>
        
        <!-- API Info (for developers) -->
        <div class="api-info" id="api-info">
            <strong>API Endpoints:</strong><br>
            Stream: <code id="stream-endpoint">/api/stream/{session_id}</code><br>
            Info: <code id="info-endpoint">/api/session/{session_id}</code>
        </div>
    </div>
    
    <script>
    let sessionId = null;
    let selectedSeverity = null;
    const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        latencyHint: 'playback',
        sampleRate: 48000
    });
    let nextTime = 0;
    let lastAudioB64 = null;
    const audioQueue = [];
    
    // Severity selection
    document.querySelectorAll('.severity-option').forEach(opt => {
        opt.addEventListener('click', () => {
            document.querySelectorAll('.severity-option').forEach(o => o.classList.remove('selected'));
            opt.classList.add('selected');
            selectedSeverity = opt.dataset.severity;
        });
    });
    
    // Form submission
    document.getElementById('patient-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (!selectedSeverity) {
            alert('Please select severity level');
            return;
        }
        
        const patientInfo = {
            name: document.getElementById('patient-name').value,
            age: document.getElementById('patient-age').value,
            complaint: document.getElementById('complaint').value,
            severity: selectedSeverity,
            notes: document.getElementById('notes').value
        };
        
        // Start session
        try {
            const response = await fetch('/api/start_session', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({patient_info: patientInfo})
            });
            const data = await response.json();
            sessionId = data.session_id;
            
            // Update UI
            document.getElementById('intake-form').style.display = 'none';
            document.querySelector('.header').style.display = 'block';
            document.getElementById('display-name').textContent = patientInfo.name;
            document.getElementById('display-age').textContent = patientInfo.age;
            document.getElementById('display-severity').textContent = patientInfo.severity.toUpperCase();
            document.getElementById('display-severity').className = 'severity-' + patientInfo.severity;
            document.getElementById('display-session').textContent = sessionId;
            
            // Show API info
            document.getElementById('api-info').style.display = 'block';
            document.getElementById('stream-endpoint').textContent = '/api/stream/' + sessionId;
            document.getElementById('info-endpoint').textContent = '/api/session/' + sessionId;
            
            // Start polling
            startStreaming();
        } catch (err) {
            alert('Failed to start session: ' + err.message);
        }
    });
    
    // Audio handling
    document.body.addEventListener('click', () => {
        if (audioContext.state === 'suspended') {
            audioContext.resume();
            document.getElementById('audio-indicator').textContent = '🔊';
            document.getElementById('audio-text').textContent = 'Audio enabled';
        }
    }, {once: true});
    
    function base64ToFloat32(base64Data) {
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
        return float32Array;
    }
    
    function scheduleFloat32(float32Array) {
        const buffer = audioContext.createBuffer(1, float32Array.length, 48000);
        buffer.copyToChannel(float32Array, 0);
        
        const source = audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(audioContext.destination);
        
        const now = audioContext.currentTime;
        if (nextTime < now + 0.05) nextTime = now + 0.05;
        
        source.start(nextTime);
        nextTime += buffer.duration;
    }
    
    function enqueueAudio(base64Data) {
        if (!base64Data || base64Data === lastAudioB64) return;
        lastAudioB64 = base64Data;
        audioQueue.push(base64Data);
        flushAudioQueue();
    }
    
    function flushAudioQueue() {
        const targetLead = 0.25;
        const now = audioContext.currentTime;
        while (audioQueue.length && (nextTime - now) < targetLead) {
            const b64 = audioQueue.shift();
            const f32 = base64ToFloat32(b64);
            scheduleFloat32(f32);
        }
    }
    
    // Streaming
    function startStreaming() {
        setInterval(async () => {
            if (!sessionId) return;
            
            try {
                const response = await fetch('/api/stream/' + sessionId);
                const data = await response.json();
                
                if (data.img) {
                    document.getElementById('no-signal').style.display = 'none';
                    document.getElementById('stream-img').style.display = 'block';
                    document.getElementById('status-bar').style.display = 'flex';
                    document.getElementById('stream-img').src = 'data:image/jpeg;base64,' + data.img;
                }
                
                if (data.audio) {
                    enqueueAudio(data.audio);
                }
                
                flushAudioQueue();
            } catch (err) {
                console.error('Stream error:', err);
            }
        }, 50);
    }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/start_session', methods=['POST'])
def start_session():
    global current_session_id
    data = request.json
    session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    session = Session(session_id, data['patient_info'])
    sessions[session_id] = session
    current_session_id = session_id
    
    return jsonify({
        'session_id': session_id,
        'status': 'active'
    })

@app.route('/api/session/<session_id>')
def get_session_info(session_id):
    """Get session information for external consumers"""
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session = sessions[session_id]
    return jsonify({
        'session_id': session.id,
        'patient_info': session.patient_info,
        'start_time': session.start_time.isoformat(),
        'active': session.active
    })

@app.route('/api/stream/<session_id>')
def get_stream(session_id):
    """Get current frame and audio for external consumers"""
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify(sessions[session_id].get_latest())

@app.route('/api/sessions')
def list_sessions():
    """List all sessions"""
    return jsonify([{
        'session_id': s.id,
        'patient_name': s.patient_info.get('name'),
        'severity': s.patient_info.get('severity'),
        'start_time': s.start_time.isoformat(),
        'active': s.active
    } for s in sessions.values()])

# Legacy endpoints for compatibility with your sender
@app.route('/frame', methods=['POST'])
def frame():
    """Receive frame from Raspberry Pi"""
    global current_session_id
    
    if not current_session_id or current_session_id not in sessions:
        # Auto-create session if none exists
        current_session_id = 'auto_' + datetime.now().strftime('%Y%m%d_%H%M%S')
        sessions[current_session_id] = Session(current_session_id, {
            'name': 'Auto Session',
            'severity': 'unknown'
        })
    
    data = request.json
    session = sessions[current_session_id]
    session.add_frame(data.get('img'), data.get('audio'))
    
    print(".", end="", flush=True)
    return 'ok'

@app.route('/current')
def get_current():
    """Legacy endpoint"""
    if current_session_id and current_session_id in sessions:
        return jsonify(sessions[current_session_id].get_latest())
    return jsonify({'img': '', 'audio': ''})

# Cleanup old sessions periodically
def cleanup_sessions():
    while True:
        time.sleep(300)  # Every 5 minutes
        cutoff = datetime.now().timestamp() - 3600  # 1 hour
        to_remove = []
        for sid, session in sessions.items():
            if session.start_time.timestamp() < cutoff and not session.active:
                to_remove.append(sid)
        for sid in to_remove:
            del sessions[sid]

threading.Thread(target=cleanup_sessions, daemon=True).start()

if __name__ == '__main__':
    print("Enhanced Telemedicine Server")
    print("Access at: http://localhost:5000")
    print("\nAPI Endpoints:")
    print("  POST /api/start_session - Start new session")
    print("  GET  /api/session/{id} - Get session info")
    print("  GET  /api/stream/{id} - Get live stream data")
    print("  GET  /api/sessions - List all sessions")
    app.run(host='0.0.0.0', port=5000, debug=False)