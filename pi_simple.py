#!/usr/bin/env python3
import cv2
import requests
import base64
import time
import threading
import pyaudio
import queue

# CONFIG
SERVER_URL = "http://10.189.65.41:5000"
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FPS = 15

# Video setup
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
cap.set(cv2.CAP_PROP_FPS, FPS)

# Audio setup
audio_queue = queue.Queue(maxsize=10)
try:
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=1024,
                    input_device_index=1)  # Your USB mic
    audio_enabled = True
except:
    audio_enabled = False
    print("Audio disabled")

def capture_audio():
    while audio_enabled:
        try:
            data = stream.read(1024, exception_on_overflow=False)
            audio_queue.put_nowait(base64.b64encode(data).decode())
        except:
            pass

if audio_enabled:
    threading.Thread(target=capture_audio, daemon=True).start()

print(f"Streaming to {SERVER_URL}")
frame_count = 0

while True:
    ret, frame = cap.read()
    if ret:
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        
        audio_data = None
        try:
            audio_data = audio_queue.get_nowait()
        except:
            pass
        
        try:
            requests.post(f"{SERVER_URL}/upload", json={
                'frame': jpg_as_text,
                'audio': audio_data
            }, timeout=0.5)
            frame_count += 1
            if frame_count % 30 == 0:
                print(f"Sent {frame_count} frames")
        except:
            pass
    
    time.sleep(1.0/FPS)