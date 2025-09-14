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
    // Create the audio context with a playback latency hint for smoother output.
    const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        latencyHint: 'playback',
        sampleRate: 48000
    });

    let nextTime = 0;                 // when the next buffer will start
    let lastAudioB64 = null;          // last audio chunk we've already played
    const audioQueue = [];            // small client-side queue for jitter

    // Click to start audio (required by browsers)
    document.body.addEventListener('click', () => {
        if (audioContext.state === 'suspended') {
            audioContext.resume();
            document.getElementById('status').textContent = 'Audio enabled';
        }
    }, {once: true});

    // Convert base64 WAV (48 kHz mono, 16-bit) -> Float32 samples
    function base64ToFloat32(base64Data) {
        const binaryString = atob(base64Data);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = binaryString.charCodeAt(i);

        // Skip 44-byte WAV header; remaining is little-endian PCM16
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

    // Schedule a Float32 mono buffer at 48 kHz
    function scheduleFloat32(float32Array) {
        const buffer = audioContext.createBuffer(1, float32Array.length, 48000);
        buffer.copyToChannel(float32Array, 0);

        const source = audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(audioContext.destination);

        const now = audioContext.currentTime;
        // Keep a small lead (50 ms) to avoid underruns
        if (nextTime < now + 0.05) nextTime = now + 0.05;

        source.start(nextTime);
        nextTime += buffer.duration;
    }

    // Only enqueue brand-new audio; drop duplicates
    function enqueueAudio(base64Data) {
        if (!base64Data || base64Data === lastAudioB64) return;
        lastAudioB64 = base64Data;
        audioQueue.push(base64Data);
        flushAudioQueue();
    }

    // Fill up to ~250 ms of scheduled audio to smooth over network jitter
    function flushAudioQueue() {
        const targetLead = 0.25; // seconds
        const now = audioContext.currentTime;
        while (audioQueue.length && (nextTime - now) < targetLead) {
            const b64 = audioQueue.shift();
            const f32 = base64ToFloat32(b64);
            scheduleFloat32(f32);
        }
    }

    // Poll the server frequently; de-dup + queue keeps this smooth
    setInterval(() => {
        fetch('/current')
            .then(r => r.json())
            .then(data => {
                if (data.img) {
                    document.getElementById('img').src = 'data:image/jpeg;base64,' + data.img;
                }
                if (data.audio) {
                    enqueueAudio(data.audio);
                }
                flushAudioQueue();
            })
            .catch(() => {});
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