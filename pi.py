#!/usr/bin/env python3
import subprocess
import requests
import base64
import time
import threading
import queue

SERVER_IP = "172.20.10.2"
frame_queue = queue.Queue(maxsize=2)

def capture_images():
    """Continuous image capture in background"""
    while True:
        subprocess.run(['libcamera-still', '-o', '/tmp/pic.jpg', '--width', '640', '--height', '480', '-n', '-t', '1'], capture_output=True)
        try:
            with open('/tmp/pic.jpg', 'rb') as f:
                frame_queue.put_nowait(base64.b64encode(f.read()).decode())
        except:
            pass

threading.Thread(target=capture_images, daemon=True).start()

print("Starting high-speed streamer...")

while True:
    # Get latest frame
    img = None
    try:
        img = frame_queue.get_nowait()
    except:
        pass
    
    # Record shorter audio chunk (0.2 seconds for faster updates)
    audio_result = subprocess.run(['arecord', '-D', 'plughw:3,0', '-f', 'S16_LE', '-r', '48000', '-c', '1', '-d', '0.2', '-t', 'wav'], 
                                capture_output=True)
    
    if img:
        try:
            audio_b64 = base64.b64encode(audio_result.stdout).decode() if audio_result.stdout else None
            requests.post(f'http://{SERVER_IP}:5000/frame', 
                         json={'img': img, 'audio': audio_b64}, 
                         timeout=0.5)
            print(".", end="", flush=True)
        except:
            pass
    
    time.sleep(0.05)  # 20 FPS