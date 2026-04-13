import os
import time
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pynput.mouse import Button, Controller as MouseController

# Hand tracking (Pi-friendly settings - optimized for speed)
HAND_MODEL_PATH       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models/hand_landmarker.task")
CAMERA_ID             = 0
FRAME_WIDTH           = 320     # lower res → less CPU
FRAME_HEIGHT          = 240
SMOOTHING_WINDOW      = 3       # reduced for faster response
HAND_SKIP_FRAMES      = 1       # process every Nth frame (1 = every frame)
ILY_HOLD_SECONDS      = 3.0
HAND_MAX_FPS          = 30.0    # increased for responsiveness

# Global state
_mouse           = MouseController()
_tracking_enabled = False
_running          = True
_position_buffer  = []
_detection_result = None

_ily_remaining  = 0.0
_root_ref       = None

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────
def _get_screen_size():
    try:
        import subprocess
        out = subprocess.check_output(
            "xrandr | grep '*' | awk '{print $1}'", shell=True
        ).decode().strip().split("\n")[0]
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080

def _smooth(x, y):
    """Optimized smoothing with weighted average for faster response"""
    _position_buffer.append((x, y))
    if len(_position_buffer) > SMOOTHING_WINDOW:
        _position_buffer.pop(0)
    
    if len(_position_buffer) == 1:
        return x, y
    
    # Weighted moving average - recent positions get more weight
    weights = [i + 1 for i in range(len(_position_buffer))]
    total_weight = sum(weights)
    ax = int(sum(px * w for (px, _), w in zip(_position_buffer, weights)) / total_weight)
    ay = int(sum(py * w for (_, py), w in zip(_position_buffer, weights)) / total_weight)
    return ax, ay

def _set_ily_remaining(remaining):
    """Thread-safe-ish: hand thread writes, UI loop reads."""
    global _ily_remaining
    try:
        _ily_remaining = float(remaining)
    except (TypeError, ValueError):
        _ily_remaining = 0.0

def get_ily_remaining():
    """Get current ILY countdown remaining."""
    return _ily_remaining

def set_root_ref(root):
    """Set reference to root window."""
    global _root_ref
    _root_ref = root

def set_tracking_enabled(enabled):
    """Set tracking enabled state."""
    global _tracking_enabled
    _tracking_enabled = enabled

def is_tracking_enabled():
    """Check if hand tracking is enabled."""
    return _tracking_enabled

def set_running(running):
    """Set running state."""
    global _running
    _running = running

# ─────────────────────────────────────────────
# HAND TRACKING LOOP
# ─────────────────────────────────────────────
def hand_tracking_loop():
    global _tracking_enabled, _running

    if not os.path.exists(HAND_MODEL_PATH):
        print(f"[Hand] Model not found: {HAND_MODEL_PATH}"); return

    screen_w, screen_h = _get_screen_size()
    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print("[Hand] Unable to open webcam."); return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    # Pi: request MJPEG for lower USB bandwidth
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    try:
        detector = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.3,   # optimized for Pi
                min_hand_presence_confidence=0.3,
                min_tracking_confidence=0.3,
            )
        )
    except Exception as e:
        print(f"[Hand] Failed to load model: {e}"); cap.release(); return

    was_fist    = False
    ily_start   = None
    frame_count = 0
    last_tick   = 0.0

    try:
        while _running and cap.isOpened():
            # Cap processing FPS (prevents pegging CPU on Pi)
            now = time.time()
            min_dt = 1.0 / max(HAND_MAX_FPS, 1.0)
            if last_tick and (now - last_tick) < min_dt:
                time.sleep(max(0.0, min_dt - (now - last_tick)))
            last_tick = time.time()

            # Cheap skip: grab (no decode) on skipped frames
            frame_count += 1
            if HAND_SKIP_FRAMES > 1 and (frame_count % HAND_SKIP_FRAMES) != 0:
                cap.grab()
                continue

            ok, frame = cap.read()
            if not ok:
                continue

            frame    = cv2.flip(frame, 1)
            rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img   = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = detector.detect(mp_img)

            if not result or not result.hand_landmarks:
                if was_fist:
                    try: _mouse.release(Button.left)
                    except Exception: pass
                    was_fist = False
                ily_start = None
                continue

            lm = result.hand_landmarks[0]

            # ILY gesture: thumb + index + pinky out; middle + ring folded
            is_ily = (
                lm[4].x < lm[3].x       and   # thumb out (mirrored)
                lm[8].y  < lm[6].y       and   # index out
                lm[12].y > lm[10].y      and   # middle in
                lm[16].y > lm[14].y      and   # ring in
                lm[20].y < lm[18].y            # pinky out
            )

            if is_ily:
                if ily_start is None:
                    ily_start = time.time()
                elapsed   = time.time() - ily_start
                remaining = ILY_HOLD_SECONDS - elapsed
                if elapsed >= ILY_HOLD_SECONDS:
                    _tracking_enabled = not _tracking_enabled
                    ily_start = None
                    _set_ily_remaining(0)
                    print(f"[Hand] Tracking {'ON' if _tracking_enabled else 'OFF'}")
                    if not _tracking_enabled and was_fist:
                        try: 
                            _mouse.release(Button.left)
                        except Exception: 
                            pass
                        was_fist = False
                else:
                    _set_ily_remaining(remaining)
            else:
                ily_start = None
                _set_ily_remaining(0)

            if not _tracking_enabled:
                continue

            palm    = lm[9]
            sx, sy  = int(palm.x * screen_w), int(palm.y * screen_h)
            mx, my  = _smooth(sx, sy)
            try:
                _mouse.position = (mx, my)
            except Exception:
                pass

            tips    = [8, 12, 16, 20]
            knucks  = [6, 10, 14, 18]
            is_fist = all(lm[t].y > lm[k].y for t, k in zip(tips, knucks))
            try:
                if is_fist and not was_fist:
                    _mouse.press(Button.left)
                elif not is_fist and was_fist:
                    _mouse.release(Button.left)
            except Exception:
                pass
            was_fist = is_fist

    except Exception as e:
        print(f"[Hand] Crash: {e}")
    finally:
        try: _mouse.release(Button.left)
        except Exception: pass
        _set_ily_remaining(0)
        try: detector.close()
        except Exception: pass
        cap.release()
