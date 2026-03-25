"""Hand landmarker with mouse cursor control — Windows version."""

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

# Global variables
COUNTER, FPS = 0, 0
START_TIME = time.time()
DETECTION_RESULT = None

# Smoothing buffer
SMOOTHING_WINDOW = 10
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

    screen_w, screen_h = pyautogui.size()

    cap = cv2.VideoCapture(camera_id)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    row_size = 50
    left_margin = 24
    text_color = (0, 0, 0)
    font_size = 1
    font_thickness = 1
    fps_avg_frame_count = 10

    # State
    was_fist = False
    ily_start_time = None
    TRACKING_ENABLED = False
    ILY_HOLD_SECONDS = 3

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

    # Hand connections hardcoded (replaces mp.solutions.hands.HAND_CONNECTIONS)
    HAND_CONNECTIONS = [
        (0,1),(1,2),(2,3),(3,4),        # thumb
        (0,5),(5,6),(6,7),(7,8),        # index
        (0,9),(9,10),(10,11),(11,12),   # middle
        (0,13),(13,14),(14,15),(15,16), # ring
        (0,17),(17,18),(18,19),(19,20), # pinky
        (5,9),(9,13),(13,17)            # palm
    ]

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            sys.exit('ERROR: Unable to read from webcam. Please verify your webcam settings.')

        image = cv2.flip(image, 1)
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
        detector.detect_async(mp_image, time.time_ns() // 1_000_000)

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

                # --- Draw landmarks using cv2 directly (no protobuf needed) ---
                h, w, _ = image.shape
                pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks]

                # Draw connections
                connections = HAND_CONNECTIONS
                for conn in connections:
                    cv2.line(image, pts[conn[0]], pts[conn[1]], (200, 200, 200), 2)

                # Draw landmark dots
                for pt in pts:
                    cv2.circle(image, pt, 5, (0, 128, 255), -1)

                # --- Handedness label ---
                x_coords = [lm.x for lm in hand_landmarks]
                y_coords = [lm.y for lm in hand_landmarks]
                text_x = int(min(x_coords) * frame_w)
                text_y = int(min(y_coords) * frame_h) - MARGIN
                cv2.putText(image, f"{handedness[0].category_name}",
                            (text_x, text_y), cv2.FONT_HERSHEY_DUPLEX,
                            FONT_SIZE, HANDEDNESS_TEXT_COLOR, FONT_THICKNESS,
                            cv2.LINE_AA)

                # --- ILY detection ---
                # NOTE: if ILY isn't detected, flip thumb_out comparison (< to >)
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
                    else:
                        cv2.putText(image, f"ILY: {remaining:.1f}s",
                                    (left_margin, row_size * 3),
                                    cv2.FONT_HERSHEY_DUPLEX, font_size,
                                    (255, 100, 255), font_thickness, cv2.LINE_AA)
                else:
                    ily_start_time = None

                # --- Tracking status ---
                state_text = "TRACKING ON" if TRACKING_ENABLED else "TRACKING OFF - show ILY for 3s"
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
                pyautogui.moveTo(smooth_x, smooth_y, duration=0, _pause=False)

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
                    if not was_fist:
                        pyautogui.mouseDown()
                else:
                    cv2.circle(image, (cursor_x, cursor_y), 15, (0, 255, 255), -1)
                    cv2.circle(image, (cursor_x, cursor_y), 15, (0, 180, 180), 2)
                    if was_fist:
                        pyautogui.mouseUp()

                was_fist = is_fist

                status = "DRAGGING" if is_fist else "Move"
                cv2.putText(image, status, (left_margin, row_size * 2),
                            cv2.FONT_HERSHEY_DUPLEX, font_size,
                            (0, 0, 255) if is_fist else (0, 200, 0),
                            font_thickness, cv2.LINE_AA)

        cv2.imshow('Hand Mouse', image)
        if cv2.waitKey(1) == 27:
            break

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
    parser.add_argument('--cameraId', required=False, type=int, default=0)
    parser.add_argument('--frameWidth', required=False, type=int, default=1280)
    parser.add_argument('--frameHeight', required=False, type=int, default=960)
    args = parser.parse_args()

    run(args.model, args.numHands, args.minHandDetectionConfidence,
        args.minHandPresenceConfidence, args.minTrackingConfidence,
        args.cameraId, args.frameWidth, args.frameHeight)


if __name__ == '__main__':
    main()
