#!/usr/bin/env python3
from flask import Flask, request
import base64
import logging

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
img = ''
audio_chunks = []

@app.route('/')
def index():
    return '''
    <html>
    <body style="margin:0;background:#000;color:#fff;text-align:center">
    <h3>Telemedicine Stream</h3>
    <img id="img" style="width:100%;max-width:640px">
    <div id="status"></div>
    <script>
    let audioContext = new (window.AudioContext || window.webkitAudioContext)();
    let nextTime = 0;
    
    // Click to start audio
    document.body.addEventListener('click', () => {
        if (audioContext.state === 'suspended') {
            audioContext.resume();
            document.getElementById('status').textContent = 'Audio enabled';
        }
    }, {once: true});
    
    function playAudioChunk(base64Data) {
        let binaryString = atob(base64Data);
        let len = binaryString.length;
        let bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }
        
        // Skip WAV header (44 bytes) and get raw PCM
        let pcmData = bytes.slice(44);
        let int16Array = new Int16Array(pcmData.buffer);
        let float32Array = new Float32Array(int16Array.length);
        
        for (let i = 0; i < int16Array.length; i++) {
            float32Array[i] = int16Array[i] / 32768.0;
        }
        
        let buffer = audioContext.createBuffer(1, float32Array.length, 48000);
        buffer.copyToChannel(float32Array, 0);
        
        let source = audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(audioContext.destination);
        
        if (nextTime < audioContext.currentTime) {
            nextTime = audioContext.currentTime;
        }
        source.start(nextTime);
        nextTime += buffer.duration;
    }
    
    setInterval(() => {
        fetch('/current').then(r => r.json()).then(data => {
            if(data.img) document.getElementById('img').src = 'data:image/jpeg;base64,' + data.img;
            if(data.audio) playAudioChunk(data.audio);
        });
    }, 50);
    
    document.getElementById('status').textContent = 'Click anywhere to enable audio';
    </script>
    </body>
    </html>
    '''

@app.route('/frame', methods=['POST'])
def frame():
    global img, audio_chunks
    data = request.json
    img = data['img']
    if data.get('audio'):
        audio_chunks.append(data['audio'])
        if len(audio_chunks) > 10:
            audio_chunks.pop(0)
    print(".", end="", flush=True)
    return 'ok'

@app.route('/current')
def get_current():
    audio = audio_chunks[-1] if audio_chunks else ''
    return {'img': img, 'audio': audio}

print("Server running at http://localhost:5000")
app.run(host='0.0.0.0', port=5000, debug=False)