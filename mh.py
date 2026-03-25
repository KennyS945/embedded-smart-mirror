"""Hand landmarker with mouse cursor control — Raspberry Pi version.
   Uses pynput instead of pyautogui for fast, low-latency cursor control on Linux.
   Run with: python3 hand_mouse.py --cameraId 1
"""

import argparse
import sys
import time

import cv2
import mediapipe as mp
from pynput.mouse import Button, Controller as MouseController

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Mouse controller (pynput — much faster than pyautogui on Linux)
mouse = MouseController()
last_mouse_pos = None  # tracks previous position for relative movement

# Global variables
COUNTER, FPS = 0, 0
START_TIME = time.time()
DETECTION_RESULT = None

# Smoothing buffer — higher = smoother but slightly more lag
SMOOTHING_WINDOW = 6
position_buffer = []


def smooth_position(x, y):
    position_buffer.append((x, y))
    if len(position_buffer) > SMOOTHING_WINDOW:
        position_buffer.pop(0)
    avg_x = int(sum(p[0] for p in position_buffer) / len(position_buffer))
    avg_y = int(sum(p[1] for p in position_buffer) / len(position_buffer))
    return avg_x, avg_y


def get_screen_size():
    """Get screen size on Linux without pyautogui."""
    try:
        import subprocess
        out = subprocess.check_output(
            "xrandr | grep '*' | awk '{print $1}'", shell=True
        ).decode().strip().split('\n')[0]
        w, h = out.split('x')
        return int(w), int(h)
    except Exception:
        return 1920, 1080  # safe fallback


def run(model: str, num_hands: int,
        min_hand_detection_confidence: float,
        min_hand_presence_confidence: float,
        min_tracking_confidence: float,
        camera_id: int, width: int, height: int) -> None:

    screen_w, screen_h = get_screen_size()
    print(f"Screen size: {screen_w}x{screen_h}")

    # Open Logitech camera — try V4L2 backend first for better Pi performance
    cap = cv2.VideoCapture(camera_id, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_id)  # fallback
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    # Reduce internal buffer to 1 frame — prevents lag buildup on Pi
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    row_size = 50
    left_margin = 24
    text_color = (0, 0, 0)
    font_size = 1
    font_thickness = 1
    fps_avg_frame_count = 10

    # State
    was_fist = False
    mouse_held = False
    global last_mouse_pos
    ily_start_time = None
    TRACKING_ENABLED = False
    ILY_HOLD_SECONDS = 3

    # Hand connections
    HAND_CONNECTIONS = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (0,9),(9,10),(10,11),(11,12),
        (0,13),(13,14),(14,15),(15,16),
        (0,17),(17,18),(18,19),(19,20),
        (5,9),(9,13),(13,17)
    ]

    def save_result(result: vision.HandLandmarkerResult,
                    unused_output_image: mp.Image, timestamp_ms: int):
        global FPS, COUNTER, START_TIME, DETECTION_RESULT
        if COUNTER % fps_avg_frame_count == 0:
            FPS = fps_avg_frame_count / (time.time() - START_TIME)
            START_TIME = time.time()
        DETECTION_RESULT = result
        COUNTER += 1

    base_options = python.BaseOptions(model_asset_path=model)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.LIVE_STREAM,
        num_hands=num_hands,
        min_hand_detection_confidence=min_hand_detection_confidence,
        min_hand_presence_confidence=min_hand_presence_confidence,
        min_tracking_confidence=min_tracking_confidence,
        result_callback=save_result)
    detector = vision.HandLandmarker.create_from_options(options)

    print("Starting — show ILY sign for 3 seconds to enable tracking.")
    print("Press ESC in the video window to quit.")

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            sys.exit('ERROR: Unable to read from webcam. Please verify your webcam settings.')

        image = cv2.flip(image, 1)
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        detector.detect_async(mp_image, time.time_ns() // 1_000_000)

        # FPS display
        fps_text = 'FPS = {:.1f}'.format(FPS)
        cv2.putText(image, fps_text, (left_margin, row_size),
                    cv2.FONT_HERSHEY_DUPLEX, font_size, text_color,
                    font_thickness, cv2.LINE_AA)

        MARGIN = 10
        FONT_SIZE = 1
        FONT_THICKNESS = 1
        HANDEDNESS_TEXT_COLOR = (88, 205, 54)
        frame_h, frame_w, _ = image.shape

        if DETECTION_RESULT:
            for idx in range(len(DETECTION_RESULT.hand_landmarks)):
                hand_landmarks = DETECTION_RESULT.hand_landmarks[idx]
                handedness = DETECTION_RESULT.handedness[idx]

                # Draw skeleton
                pts = [(int(lm.x * frame_w), int(lm.y * frame_h))
                       for lm in hand_landmarks]
                for conn in HAND_CONNECTIONS:
                    cv2.line(image, pts[conn[0]], pts[conn[1]], (200, 200, 200), 2)
                for pt in pts:
                    cv2.circle(image, pt, 5, (0, 128, 255), -1)

                # Handedness label
                x_coords = [lm.x for lm in hand_landmarks]
                y_coords = [lm.y for lm in hand_landmarks]
                text_x = int(min(x_coords) * frame_w)
                text_y = int(min(y_coords) * frame_h) - MARGIN
                cv2.putText(image, f"{handedness[0].category_name}",
                            (text_x, text_y), cv2.FONT_HERSHEY_DUPLEX,
                            FONT_SIZE, HANDEDNESS_TEXT_COLOR, FONT_THICKNESS,
                            cv2.LINE_AA)

                # --- ILY detection ---
                # Thumb out + index up + middle curled + ring curled + pinky up
                # If ILY not triggering, flip < to > on thumb_out line
                thumb_out = hand_landmarks[4].x < hand_landmarks[3].x
                index_out = hand_landmarks[8].y  < hand_landmarks[6].y
                middle_in = hand_landmarks[12].y > hand_landmarks[10].y
                ring_in   = hand_landmarks[16].y > hand_landmarks[14].y
                pinky_out = hand_landmarks[20].y < hand_landmarks[18].y
                is_ily = thumb_out and index_out and middle_in and ring_in and pinky_out

                if is_ily:
                    if ily_start_time is None:
                        ily_start_time = time.time()
                    elapsed = time.time() - ily_start_time
                    remaining = ILY_HOLD_SECONDS - elapsed
                    if elapsed >= ILY_HOLD_SECONDS:
                        TRACKING_ENABLED = not TRACKING_ENABLED
                        ily_start_time = None
                        if TRACKING_ENABLED:
                            # Snap cursor to palm position the moment tracking turns on
                            palm = hand_landmarks[9]
                            snap_x = int(palm.x * 1920)
                            snap_y = int(palm.y * 1080)
                            mouse.position = (snap_x, snap_y)
                            last_mouse_pos = (snap_x, snap_y)
                        else:
                            # Safety: release mouse if tracking turned off mid-drag
                            if mouse_held:
                                mouse.release(Button.left)
                                mouse_held = False
                    else:
                        cv2.putText(image, f"ILY: {remaining:.1f}s",
                                    (left_margin, row_size * 3),
                                    cv2.FONT_HERSHEY_DUPLEX, font_size,
                                    (255, 100, 255), font_thickness, cv2.LINE_AA)
                else:
                    ily_start_time = None

                # Tracking status
                state_text = "TRACKING ON" if TRACKING_ENABLED else "TRACKING OFF - show ILY 3s"
                state_color = (0, 255, 0) if TRACKING_ENABLED else (0, 0, 255)
                cv2.putText(image, state_text, (left_margin, row_size * 4),
                            cv2.FONT_HERSHEY_DUPLEX, font_size, state_color,
                            font_thickness, cv2.LINE_AA)

                if not TRACKING_ENABLED:
                    continue

                # --- Palm cursor (landmark 9) ---
                palm = hand_landmarks[9]
                raw_x = int(palm.x * screen_w)
                raw_y = int(palm.y * screen_h)
                smooth_x, smooth_y = smooth_position(raw_x, raw_y)

                # Move cursor using relative movement (fixes Linux/Pi absolute position bug)
                if last_mouse_pos is None:
                    last_mouse_pos = (smooth_x, smooth_y)
                dx = smooth_x - last_mouse_pos[0]
                dy = smooth_y - last_mouse_pos[1]
                if dx != 0 or dy != 0:
                    mouse.move(dx, dy)
                last_mouse_pos = (smooth_x, smooth_y)

                cursor_x = int(palm.x * frame_w)
                cursor_y = int(palm.y * frame_h)

                # --- Fist detection ---
                fingertips = [8, 12, 16, 20]
                knuckles   = [6, 10, 14, 18]
                is_fist = all(
                    hand_landmarks[tip].y > hand_landmarks[knuck].y
                    for tip, knuck in zip(fingertips, knuckles)
                )

                if is_fist:
                    cv2.circle(image, (cursor_x, cursor_y), 20, (0, 0, 255), -1)
                    cv2.circle(image, (cursor_x, cursor_y), 20, (0, 0, 180), 2)
                    if not mouse_held:
                        mouse.press(Button.left)
                        mouse_held = True
                else:
                    cv2.circle(image, (cursor_x, cursor_y), 15, (0, 255, 255), -1)
                    cv2.circle(image, (cursor_x, cursor_y), 15, (0, 180, 180), 2)
                    if mouse_held:
                        mouse.release(Button.left)
                        mouse_held = False

                was_fist = is_fist

                status = "DRAGGING" if is_fist else "Move"
                cv2.putText(image, status, (left_margin, row_size * 2),
                            cv2.FONT_HERSHEY_DUPLEX, font_size,
                            (0, 0, 255) if is_fist else (0, 200, 0),
                            font_thickness, cv2.LINE_AA)

        cv2.imshow('Hand Mouse', image)
        if cv2.waitKey(1) == 27:
            break

    # Clean up — always release mouse on exit
    if mouse_held:
        mouse.release(Button.left)
    detector.close()
    cap.release()
    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--model', required=False, type=str,
                        default='hand_landmarker.task')
    parser.add_argument('--numHands', required=False, type=int, default=1)
    parser.add_argument('--minHandDetectionConfidence',
                        required=False, type=float, default=0.5)
    parser.add_argument('--minHandPresenceConfidence',
                        required=False, type=float, default=0.5)
    parser.add_argument('--minTrackingConfidence',
                        required=False, type=float, default=0.5)
    # Change this default to 1 or 2 if Logitech cam isn't found on 0
    parser.add_argument('--cameraId', required=False, type=int, default=1)
    parser.add_argument('--frameWidth', required=False, type=int, default=640)
    parser.add_argument('--frameHeight', required=False, type=int, default=480)
    args = parser.parse_args()

    run(args.model, args.numHands, args.minHandDetectionConfidence,
        args.minHandPresenceConfidence, args.minTrackingConfidence,
        args.cameraId, args.frameWidth, args.frameHeight)


if __name__ == '__main__':
    main()
