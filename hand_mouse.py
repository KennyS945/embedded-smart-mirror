import argparse
import sys
import time

import cv2
import mediapipe as mp
import pyautogui

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0

COUNTER, FPS = 0, 0
START_TIME = time.time()
DETECTION_RESULT = None

SMOOTHING_WINDOW = 6
position_buffer = []


def smooth_position(x, y):
    position_buffer.append((x, y))
    if len(position_buffer) > SMOOTHING_WINDOW:
        position_buffer.pop(0)
    avg_x = int(sum(p[0] for p in position_buffer) / len(position_buffer))
    avg_y = int(sum(p[1] for p in position_buffer) / len(position_buffer))
    return avg_x, avg_y


def run(model: str, num_hands: int,
        min_hand_detection_confidence: float,
        min_hand_presence_confidence: float,
        min_tracking_confidence: float,
        camera_id: int, width: int, height: int) -> None:

    global FPS, COUNTER, START_TIME, DETECTION_RESULT

    screen_w, screen_h = pyautogui.size()

    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        sys.exit("ERROR: Unable to open webcam.")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    was_fist = False
    ily_start_time = None
    TRACKING_ENABLED = True   # start enabled for easier testing on Pi
    ILY_HOLD_SECONDS = 3
    last_toggle_time = 0

    def save_result(result: vision.HandLandmarkerResult,
                    unused_output_image: mp.Image, timestamp_ms: int):
        global FPS, COUNTER, START_TIME, DETECTION_RESULT
        if COUNTER % 10 == 0:
            elapsed = time.time() - START_TIME
            if elapsed > 0:
                FPS = 10 / elapsed
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
        result_callback=save_result
    )
    detector = vision.HandLandmarker.create_from_options(options)

    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                print("WARNING: Failed to read frame from webcam.")
                continue

            frame = cv2.flip(frame, 1)
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
            detector.detect_async(mp_image, time.time_ns() // 1_000_000)

            if DETECTION_RESULT is None or not DETECTION_RESULT.hand_landmarks:
                continue

            for idx in range(len(DETECTION_RESULT.hand_landmarks)):
                hand_landmarks = DETECTION_RESULT.hand_landmarks[idx]

                # ILY gesture detection
                thumb_out = hand_landmarks[4].x < hand_landmarks[3].x
                index_out = hand_landmarks[8].y < hand_landmarks[6].y
                middle_in = hand_landmarks[12].y > hand_landmarks[10].y
                ring_in = hand_landmarks[16].y > hand_landmarks[14].y
                pinky_out = hand_landmarks[20].y < hand_landmarks[18].y
                is_ily = thumb_out and index_out and middle_in and ring_in and pinky_out

                if is_ily:
                    if ily_start_time is None:
                        ily_start_time = time.time()
                    elif time.time() - ily_start_time >= ILY_HOLD_SECONDS:
                        if time.time() - last_toggle_time > 1:
                            TRACKING_ENABLED = not TRACKING_ENABLED
                            last_toggle_time = time.time()
                        ily_start_time = None
                else:
                    ily_start_time = None

                if not TRACKING_ENABLED:
                    continue

                # Cursor movement using palm landmark
                palm = hand_landmarks[9]
                raw_x = int(palm.x * screen_w)
                raw_y = int(palm.y * screen_h)
                smooth_x, smooth_y = smooth_position(raw_x, raw_y)

                try:
                    pyautogui.moveTo(smooth_x, smooth_y, duration=0, _pause=False)
                except Exception as e:
                    print(f"Mouse move error: {e}")

                # Fist detection for drag
                fingertips = [8, 12, 16, 20]
                knuckles = [6, 10, 14, 18]
                is_fist = all(
                    hand_landmarks[tip].y > hand_landmarks[knuck].y
                    for tip, knuck in zip(fingertips, knuckles)
                )

                try:
                    if is_fist and not was_fist:
                        pyautogui.mouseDown()
                    elif not is_fist and was_fist:
                        pyautogui.mouseUp()
                except Exception as e:
                    print(f"Mouse click/drag error: {e}")

                was_fist = is_fist

    except KeyboardInterrupt:
        print("Stopping hand tracking...")

    finally:
        try:
            pyautogui.mouseUp()
        except Exception:
            pass
        detector.close()
        cap.release()


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--model', required=False, type=str, default='hand_landmarker.task')
    parser.add_argument('--numHands', required=False, type=int, default=1)
    parser.add_argument('--minHandDetectionConfidence', required=False, type=float, default=0.5)
    parser.add_argument('--minHandPresenceConfidence', required=False, type=float, default=0.5)
    parser.add_argument('--minTrackingConfidence', required=False, type=float, default=0.5)
    parser.add_argument('--cameraId', required=False, type=int, default=0)
    parser.add_argument('--frameWidth', required=False, type=int, default=640)
    parser.add_argument('--frameHeight', required=False, type=int, default=480)
    args = parser.parse_args()

    run(
        args.model,
        args.numHands,
        args.minHandDetectionConfidence,
        args.minHandPresenceConfidence,
        args.minTrackingConfidence,
        args.cameraId,
        args.frameWidth,
        args.frameHeight
    )


if __name__ == '__main__':
    main()
