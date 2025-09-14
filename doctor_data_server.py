#!/usr/bin/env python3
"""
Doctor Data Server - Receives annotations and audio from doctor's UI
and exposes them via API for ngrok forwarding to other systems.
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import time
from datetime import datetime
import threading
import queue

app = Flask(__name__)
CORS(app)

# Storage for doctor's data
doctor_annotations = {}  # session_id -> list of annotations
doctor_audio_queue = queue.Queue(maxsize=50)  # Recent audio chunks
session_data = {}  # session_id -> metadata

class DoctorDataStore:
    def __init__(self):
        self.annotations = {}
        self.audio_chunks = {}
        self.lock = threading.Lock()
    
    def add_annotations(self, session_id, annotations):
        with self.lock:
            if session_id not in self.annotations:
                self.annotations[session_id] = []
            
            # Update existing or add new annotations
            for new_ann in annotations:
                # Remove old annotation with same ID
                self.annotations[session_id] = [
                    ann for ann in self.annotations[session_id] 
                    if ann.get('id') != new_ann.get('id')
                ]
                # Add new annotation
                self.annotations[session_id].append(new_ann)
            
            # Clean up old annotations (older than 15 seconds)
            now = time.time() * 1000  # Convert to milliseconds
            self.annotations[session_id] = [
                ann for ann in self.annotations[session_id]
                if now - ann.get('timestamp', 0) < 15000
            ]
    
    def get_annotations(self, session_id):
        with self.lock:
            return self.annotations.get(session_id, [])
    
    def add_audio(self, session_id, audio_data, doctor_id):
        with self.lock:
            if session_id not in self.audio_chunks:
                self.audio_chunks[session_id] = []
            
            audio_entry = {
                'audio': audio_data,
                'doctor_id': doctor_id,
                'timestamp': time.time() * 1000
            }
            
            self.audio_chunks[session_id].append(audio_entry)
            
            # Keep only last 10 audio chunks per session
            if len(self.audio_chunks[session_id]) > 10:
                self.audio_chunks[session_id].pop(0)
    
    def get_latest_audio(self, session_id):
        with self.lock:
            chunks = self.audio_chunks.get(session_id, [])
            return chunks[-1] if chunks else None

# Global data store
data_store = DoctorDataStore()

@app.route('/')
def index():
    return '''
    <html>
    <head><title>Doctor Data Server</title></head>
    <body style="font-family: Arial, sans-serif; margin: 2rem; background: #1a1a1a; color: #fff;">
        <h1>🩺 Doctor Data Server</h1>
        <p>This server receives annotations and audio from the doctor's UI.</p>
        <p>Expose this via ngrok for other systems to consume doctor's input.</p>
        
        <h2>Available Endpoints:</h2>
        <ul>
            <li><code>POST /doctor_annotations</code> - Receive annotations from doctor</li>
            <li><code>POST /doctor_audio</code> - Receive audio from doctor</li>
            <li><code>GET /annotations/{session_id}</code> - Get current annotations for session</li>
            <li><code>GET /doctor_audio/{session_id}</code> - Get latest doctor audio for session</li>
            <li><code>GET /sessions</code> - List sessions with doctor data</li>
        </ul>
        
        <h2>Current Status:</h2>
        <p>Sessions with annotations: <span id="ann-count">0</span></p>
        <p>Sessions with audio: <span id="audio-count">0</span></p>
        
        <script>
            setInterval(async () => {
                try {
                    const resp = await fetch('/sessions');
                    const data = await resp.json();
                    document.getElementById('ann-count').textContent = 
                        Object.keys(data.annotations || {}).length;
                    document.getElementById('audio-count').textContent = 
                        Object.keys(data.audio || {}).length;
                } catch (err) {
                    console.error('Status update failed:', err);
                }
            }, 2000);
        </script>
    </body>
    </html>
    '''

@app.route('/doctor_annotations', methods=['POST'])
def receive_annotations():
    """Receive annotations from doctor's UI"""
    try:
        data = request.json
        session_id = data.get('session_id')
        annotations = data.get('annotations', [])
        
        if not session_id:
            return jsonify({'error': 'Missing session_id'}), 400
        
        data_store.add_annotations(session_id, annotations)
        
        print(f"Received {len(annotations)} annotations for session {session_id}")
        return jsonify({'status': 'received', 'count': len(annotations)})
        
    except Exception as e:
        print(f"Error receiving annotations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/doctor_audio', methods=['POST'])
def receive_doctor_audio():
    """Receive audio from doctor's microphone"""
    try:
        data = request.json
        session_id = data.get('session_id')
        audio_b64 = data.get('audio')
        doctor_id = data.get('doctor_id', 'unknown')
        
        if not session_id or not audio_b64:
            return jsonify({'error': 'Missing session_id or audio data'}), 400
        
        data_store.add_audio(session_id, audio_b64, doctor_id)
        
        print(f"Received audio from Dr. {doctor_id} for session {session_id}")
        return jsonify({'status': 'received'})
        
    except Exception as e:
        print(f"Error receiving doctor audio: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/annotations/<session_id>')
def get_annotations(session_id):
    """Get current annotations for a session"""
    try:
        annotations = data_store.get_annotations(session_id)
        return jsonify({
            'session_id': session_id,
            'annotations': annotations,
            'timestamp': time.time() * 1000
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/doctor_audio/<session_id>')
def get_doctor_audio(session_id):
    """Get latest doctor audio for a session"""
    try:
        audio_data = data_store.get_latest_audio(session_id)
        if audio_data:
            return jsonify({
                'session_id': session_id,
                'audio': audio_data['audio'],
                'doctor_id': audio_data['doctor_id'],
                'timestamp': audio_data['timestamp']
            })
        else:
            return jsonify({
                'session_id': session_id,
                'audio': None,
                'message': 'No audio data available'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/sessions')
def list_sessions():
    """List all sessions with doctor data"""
    try:
        with data_store.lock:
            return jsonify({
                'annotations': {
                    sid: len(anns) for sid, anns in data_store.annotations.items()
                },
                'audio': {
                    sid: len(chunks) for sid, chunks in data_store.audio_chunks.items()
                },
                'timestamp': time.time() * 1000
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/combined/<session_id>')
def get_combined_data(session_id):
    """Get both annotations and latest audio for a session"""
    try:
        annotations = data_store.get_annotations(session_id)
        audio_data = data_store.get_latest_audio(session_id)
        
        return jsonify({
            'session_id': session_id,
            'annotations': annotations,
            'doctor_audio': audio_data,
            'timestamp': time.time() * 1000
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Cleanup old data periodically
def cleanup_old_data():
    """Remove old annotations and audio chunks"""
    while True:
        try:
            time.sleep(30)  # Run every 30 seconds
            now = time.time() * 1000
            
            with data_store.lock:
                # Clean annotations older than 15 seconds
                for session_id in list(data_store.annotations.keys()):
                    data_store.annotations[session_id] = [
                        ann for ann in data_store.annotations[session_id]
                        if now - ann.get('timestamp', 0) < 15000
                    ]
                    # Remove empty sessions
                    if not data_store.annotations[session_id]:
                        del data_store.annotations[session_id]
                
                # Clean audio older than 2 minutes
                for session_id in list(data_store.audio_chunks.keys()):
                    data_store.audio_chunks[session_id] = [
                        chunk for chunk in data_store.audio_chunks[session_id]
                        if now - chunk.get('timestamp', 0) < 120000
                    ]
                    # Remove empty sessions
                    if not data_store.audio_chunks[session_id]:
                        del data_store.audio_chunks[session_id]
                        
        except Exception as e:
            print(f"Cleanup error: {e}")

# Start cleanup thread
threading.Thread(target=cleanup_old_data, daemon=True).start()

if __name__ == '__main__':
    print("Doctor Data Server")
    print("Running on: http://localhost:5001")
    print("\nExpose this via ngrok with:")
    print("  ngrok http 5001")
    print("\nEndpoints:")
    print("  POST /doctor_annotations - Receive annotations")
    print("  POST /doctor_audio - Receive doctor audio")
    print("  GET  /annotations/{session_id} - Get annotations")
    print("  GET  /doctor_audio/{session_id} - Get doctor audio")
    print("  GET  /combined/{session_id} - Get both")
    
    app.run(host='0.0.0.0', port=5001, debug=False) 