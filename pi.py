#!/usr/bin/env python3
import subprocess
import requests
import base64
import time
import threading
import queue
import sys
import io, wave

# ====== CONFIG ======
SERVER_IP = "192.168.2.1"
WIDTH, HEIGHT = "640", "480"          # try 640x480 first; drop to 480x360 if needed
FPS = "30"                             # request rate; camera/CPU will cap it
AUDIO_DUR_SEC = "0.10"                 # shorter audio chunks to keep latency low
AUDIO_FRESH_WINDOW_S = 0.12            # only attach audio this recent
HTTP_TIMEOUT = (0.1, 0.15)             # (connect, read) seconds
CHUNK_SIZE = 65536                     # bytes to read from camera pipe each iteration
# ====================

session = requests.Session()

# Keep newest frame only.
frame_queue = queue.Queue(maxsize=1)

# Latest audio base64 + timestamp
latest_audio_b64 = None
latest_audio_ts = 0.0

def put_latest(q: queue.Queue, item):
    """Keep only the most recent item in the queue."""
    try:
        while q.full():
            q.get_nowait()
    except queue.Empty:
        pass
    q.put_nowait(item)

def start_camera():
    """
    Start a continuous MJPEG stream to stdout.
    This avoids spawning a process per frame (your old bottleneck).
    """
    cmd = [
        "libcamera-vid",
        "-t", "0",                  # run forever
        "-n",                       # no preview
        "--codec", "mjpeg",         # MJPEG = individual JPEGs
        "--width", WIDTH,
        "--height", HEIGHT,
        "--framerate", FPS,
        "-o", "-"                   # write to stdout
    ]
    # Use Popen so we can read stdout as the stream flows
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0
    )

def mjpeg_reader_proc():
    """
    Read bytes from libcamera-vid stdout, carve out JPEGs by SOI/EOI markers,
    and push the newest frame (base64) to frame_queue.
    """
    proc = start_camera()
    buf = bytearray()
    SOI = b"\xff\xd8"  # Start Of Image
    EOI = b"\xff\xd9"  # End Of Image

    while True:
        chunk = proc.stdout.read(CHUNK_SIZE)
        if not chunk:
            # camera process died; restart
            try:
                proc.kill()
            except Exception:
                pass
            proc = start_camera()
            continue

        buf.extend(chunk)

        # Find complete JPEGs in the buffer
        while True:
            start = buf.find(SOI)
            if start < 0:
                # No JPEG start yet; keep reading
                if len(buf) > 2 * CHUNK_SIZE:
                    # Trim pathological garbage
                    del buf[:-2]
                break

            end = buf.find(EOI, start + 2)
            if end < 0:
                # Incomplete JPEG; need more bytes
                # Discard bytes before SOI to keep buffer bounded
                if start > 0:
                    del buf[:start]
                break

            # Got a full JPEG [start : end+2)
            jpg = bytes(buf[start:end + 2])
            # Drop everything up to the end of this JPEG
            del buf[:end + 2]

            # Push newest frame only
            try:
                img_b64 = base64.b64encode(jpg).decode()
                put_latest(frame_queue, img_b64)
            except Exception:
                # ignore bad frame and continue
                pass

def pcm_to_wav(pcm_bytes: bytes, sample_rate=48000, channels=1, sampwidth_bytes=2) -> bytes:
    """Wrap raw PCM bytes in a minimal WAV header."""
    with io.BytesIO() as bio:
        with wave.open(bio, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sampwidth_bytes)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return bio.getvalue()

def audio_worker():
    """
    Stream mono 16-bit PCM from arecord and emit ~100ms WAV chunks continuously.
    """
    global latest_audio_b64, latest_audio_ts

    SR = 48000
    CH = 1
    BYTES_PER_SAMPLE = 2  # S16_LE
    CHUNK_MS = 100
    CHUNK_BYTES = int(SR * CH * BYTES_PER_SAMPLE * CHUNK_MS / 1000)

    def start_proc():
        return subprocess.Popen(
            ["arecord",
             "-D", "plughw:3,0",
             "-f", "S16_LE",
             "-r", str(SR),
             "-c", str(CH),
             "-t", "raw"],                 # raw PCM stream
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=CHUNK_BYTES * 4
        )

    proc = start_proc()
    buf = bytearray()

    while True:
        try:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                # device hiccup; restart
                try: proc.kill()
                except Exception: pass
                proc = start_proc()
                continue

            buf.extend(chunk)

            # emit fixed-size chunks
            while len(buf) >= CHUNK_BYTES:
                pcm = bytes(buf[:CHUNK_BYTES])
                del buf[:CHUNK_BYTES]

                wav_bytes = pcm_to_wav(pcm, sample_rate=SR, channels=CH, sampwidth_bytes=BYTES_PER_SAMPLE)
                try:
                    latest_audio_b64 = base64.b64encode(wav_bytes).decode()
                    latest_audio_ts = time.time()
                except Exception:
                    pass
        except Exception:
            # restart on any read error
            try: proc.kill()
            except Exception: pass
            proc = start_proc()

def sender():
    """
    Send frames as fast as they’re available.
    Attach audio only if it’s fresh.
    """
    dots = 0
    while True:
        try:
            img_b64 = frame_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        audio_b64 = None
        now = time.time()
        if latest_audio_b64 and (now - latest_audio_ts) <= AUDIO_FRESH_WINDOW_S:
            audio_b64 = latest_audio_b64

        try:
            session.post(
                f"http://{SERVER_IP}:5000/frame",
                json={"img": img_b64, "audio": audio_b64},
                timeout=HTTP_TIMEOUT,
            )
            dots += 1
            if dots % 50 == 0:
                # Simple heartbeat without spamming stdout
                print(".", end="", flush=True)
        except Exception:
            # Drop on network issues to avoid blocking camera
            pass

def main():
    print("Starting split-stream MJPEG sender (low-latency).")
    threading.Thread(target=mjpeg_reader_proc, daemon=True).start()
    threading.Thread(target=audio_worker, daemon=True).start()
    threading.Thread(target=sender, daemon=True).start()
    while True:
        time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
