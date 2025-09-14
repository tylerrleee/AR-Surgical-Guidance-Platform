#!/usr/bin/env python3
"""
Example client for consuming the telemedicine stream from another computer.
This shows how a US doctor's system could grab the video/audio feed.
"""
import requests
import base64
import cv2
import numpy as np
import time
import threading
import queue
from datetime import datetime

class TelemedicineStreamClient:
    def __init__(self, server_url, session_id=None):
        self.server_url = server_url.rstrip('/')
        self.session_id = session_id
        self.frame_queue = queue.Queue(maxsize=5)
        self.audio_queue = queue.Queue(maxsize=10)
        self.running = False
        
    def list_sessions(self):
        """Get list of active sessions"""
        try:
            resp = requests.get(f"{self.server_url}/api/sessions")
            return resp.json()
        except Exception as e:
            print(f"Error listing sessions: {e}")
            return []
    
    def get_session_info(self, session_id):
        """Get detailed info about a session"""
        try:
            resp = requests.get(f"{self.server_url}/api/session/{session_id}")
            return resp.json()
        except Exception as e:
            print(f"Error getting session info: {e}")
            return None
    
    def start_streaming(self, session_id=None):
        """Start streaming from a session"""
        self.session_id = session_id or self.session_id
        if not self.session_id:
            print("No session ID provided!")
            return False
        
        self.running = True
        threading.Thread(target=self._stream_worker, daemon=True).start()
        return True
    
    def _stream_worker(self):
        """Background worker to fetch stream data"""
        last_img = None
        last_audio = None
        
        while self.running:
            try:
                resp = requests.get(
                    f"{self.server_url}/api/stream/{self.session_id}",
                    timeout=0.5
                )
                data = resp.json()
                
                # Handle video frame
                if data.get('img') and data['img'] != last_img:
                    last_img = data['img']
                    try:
                        # Decode base64 to image
                        img_bytes = base64.b64decode(data['img'])
                        nparr = np.frombuffer(img_bytes, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        
                        # Add to queue (drop old frames if full)
                        if self.frame_queue.full():
                            self.frame_queue.get_nowait()
                        self.frame_queue.put(img)
                    except Exception as e:
                        print(f"Error decoding frame: {e}")
                
                # Handle audio
                if data.get('audio') and data['audio'] != last_audio:
                    last_audio = data['audio']
                    try:
                        audio_bytes = base64.b64decode(data['audio'])
                        if self.audio_queue.full():
                            self.audio_queue.get_nowait()
                        self.audio_queue.put(audio_bytes)
                    except Exception as e:
                        print(f"Error decoding audio: {e}")
                        
            except Exception as e:
                print(f"Stream error: {e}")
                time.sleep(0.1)
            
            time.sleep(0.05)  # 20 FPS max
    
    def get_frame(self, timeout=0.1):
        """Get latest video frame"""
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_audio(self, timeout=0.1):
        """Get latest audio chunk"""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def stop(self):
        """Stop streaming"""
        self.running = False

# Example usage with OpenCV display
def display_stream(server_url):
    """Example: Display the stream with OpenCV"""
    client = TelemedicineStreamClient(server_url)
    
    # List available sessions
    print("Available sessions:")
    sessions = client.list_sessions()
    for s in sessions:
        print(f"  {s['session_id']} - {s['patient_name']} ({s['severity']})")
    
    if not sessions:
        print("No active sessions found!")
        return
    
    # Use the most recent session
    session_id = sessions[-1]['session_id']
    print(f"\nConnecting to session: {session_id}")
    
    # Get session details
    info = client.get_session_info(session_id)
    if info:
        print(f"Patient: {info['patient_info']['name']}")
        print(f"Complaint: {info['patient_info']['complaint']}")
        print(f"Severity: {info['patient_info']['severity']}")
    
    # Start streaming
    client.start_streaming(session_id)
    
    print("\nPress 'q' to quit, 's' to save snapshot")
    
    while True:
        frame = client.get_frame()
        if frame is not None:
            # Add overlay information
            cv2.putText(frame, f"Session: {session_id}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"Live Feed - {datetime.now().strftime('%H:%M:%S')}", (10, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            cv2.imshow('Telemedicine Stream', frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            # Save snapshot
            filename = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(filename, frame)
            print(f"Saved: {filename}")
    
    cv2.destroyAllWindows()
    client.stop()

# Example: Process stream data programmatically
def process_stream(server_url, session_id):
    """Example: Process stream without display"""
    client = TelemedicineStreamClient(server_url, session_id)
    client.start_streaming()
    
    frame_count = 0
    audio_count = 0
    
    print("Processing stream for 10 seconds...")
    start_time = time.time()
    
    while time.time() - start_time < 10:
        # Process video frames
        frame = client.get_frame()
        if frame is not None:
            frame_count += 1
            # Your image processing here
            # e.g., detect surgical instruments, analyze scene, etc.
            
        # Process audio
        audio = client.get_audio()
        if audio is not None:
            audio_count += 1
            # Your audio processing here
            # e.g., transcribe, detect keywords, etc.
        
        time.sleep(0.01)
    
    client.stop()
    print(f"Processed {frame_count} frames and {audio_count} audio chunks")

if __name__ == "__main__":
    # Change this to your server URL (use ngrok URL when available)
    SERVER_URL = "http://localhost:5000"
    
    # For testing with OpenCV display
    display_stream(SERVER_URL)
    
    # Or for headless processing:
    # sessions = TelemedicineStreamClient(SERVER_URL).list_sessions()
    # if sessions:
    #     process_stream(SERVER_URL, sessions[-1]['session_id'])

    #hi