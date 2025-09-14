#!/usr/bin/env python3
from flask import Flask, request, Response, jsonify
import base64
import cv2
import numpy as np
import threading
import time

app = Flask(__name__)

# Global storage
current_frame = None
current_audio = None
frame_lock = threading.Lock()

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Stream</title>
        <style>
            body { margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; }
            img { max-width: 100%; height: auto; }
            .status { position: absolute; top: 10px; left: 10px; color: #0f0; font-family: monospace; }
        </style>
    </head>
    <body>
        <div class="status" id="status">Waiting for stream...</div>
        <img id="video" src="/video_feed">
        <script>
            let lastUpdate = Date.now();
            setInterval(() => {
                if (Date.now() - lastUpdate > 2000) {
                    document.getElementById('status').textContent = 'No signal';
                    document.getElementById('status').style.color = '#f00';
                }
            }, 1000);
            
            // Force refresh
            setInterval(() => {
                document.getElementById('video').src = '/video_feed?' + Date.now();
            }, 100);
        </script>
    </body>
    </html>
    '''

@app.route('/upload', methods=['POST'])
def upload():
    global current_frame, current_audio
    data = request.json
    if data.get('frame'):
        with frame_lock:
            current_frame = data['frame']
    if data.get('audio'):
        current_audio = data['audio']
    return jsonify({'status': 'ok'})

def generate():
    while True:
        with frame_lock:
            if current_frame:
                frame_data = base64.b64decode(current_frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
        time.sleep(0.03)

@app.route('/video_feed')
def video_feed():
    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    print("Server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)