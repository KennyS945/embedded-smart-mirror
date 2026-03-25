import threading
import time
import tkinter as tk
from tkinter import Canvas

import cv2
import mediapipe as mp
import pyautogui
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# =========================
# CONFIG
# =========================
MODEL_PATH = "hand_landmarker.task"
CAMERA_ID = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

SMOOTHING_WINDOW = 4
TRACKING_ENABLED_DEFAULT = True

BG_COLOR = "black"
WIDGET_BG = "#111111"
WIDGET_BORDER_IDLE = "white"
WIDGET_BORDER_DRAG = "lime"

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# =========================
# GLOBALS FOR HAND TRACKING
# =========================
COUNTER = 0
FPS = 0
START_TIME = time.time()
DETECTION_RESULT = None
position_buffer = []
running = True


def smooth_position(x, y):
    position_buffer.append((x, y))
    if len(position_buffer) > SMOOTHING_WINDOW:
        position_buffer.pop(0)

    avg_x = int(sum(p[0] for p in position_buffer) / len(position_buffer))
    avg_y = int(sum(p[1] for p in position_buffer) / len(position_buffer))
    return avg_x, avg_y


# =========================
# TKINTER DRAGGABLE WIDGET
# =========================
class DraggableWidget:
    def __init__(self, parent, x, y, w, h, title, value):
        self.parent = parent
        self.frame = tk.Frame(
            parent,
            bg=WIDGET_BG,
            highlightbackground=WIDGET_BORDER_IDLE,
            highlightcolor=WIDGET_BORDER_IDLE,
            highlightthickness=2,
            bd=0,
        )

        self.title_label = tk.Label(
            self.frame,
            text=title,
            bg=WIDGET_BG,
            fg="white",
            font=("Arial", 16, "bold"),
        )
        self.title_label.pack(pady=(10, 4))

        self.value_label = tk.Label(
            self.frame,
            text=value,
            bg=WIDGET_BG,
            fg="white",
            font=("Arial", 20),
        )
        self.value_label.pack(pady=(0, 10))

        self.window_id = parent.canvas.create_window(
            x, y, window=self.frame, anchor="nw", width=w, height=h
        )

        self.drag_data = {"x": 0, "y": 0}
        self.dragging = False

        for widget in (self.frame, self.title_label, self.value_label):
            widget.bind("<ButtonPress-1>", self.on_press)
            widget.bind("<B1-Motion>", self.on_drag)
            widget.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        self.dragging = True
        self.frame.config(
            highlightbackground=WIDGET_BORDER_DRAG,
            highlightcolor=WIDGET_BORDER_DRAG
        )
        self.drag_data["x"] = event.x_root
        self.drag_data["y"] = event.y_root

    def on_drag(self, event):
        dx = event.x_root - self.drag_data["x"]
        dy = event.y_root - self.drag_data["y"]

        self.parent.canvas.move(self.window_id, dx, dy)

        self.drag_data["x"] = event.x_root
        self.drag_data["y"] = event.y_root

    def on_release(self, event):
        self.dragging = False
        self.frame.config(
            highlightbackground=WIDGET_BORDER_IDLE,
            highlightcolor=WIDGET_BORDER_IDLE
        )

    def update_value(self, text):
        self.value_label.config(text=text)


# =========================
# MAIN MIRROR UI
# =========================
class SmartMirrorApp:
    def __init__(self, root):
        self.root = root
        self.root.configure(bg=BG_COLOR)
        self.root.attributes("-fullscreen", True)

        self.screen_w = root.winfo_screenwidth()
        self.screen_h = root.winfo_screenheight()

        self.canvas = Canvas(
            root,
            bg=BG_COLOR,
            highlightthickness=0,
            bd=0,
            width=self.screen_w,
            height=self.screen_h,
        )
        self.canvas.pack(fill="both", expand=True)

        self.widgets = []

        self.time_widget = DraggableWidget(
            self, 40, 40, 260, 120, "Time", "--:--:--"
        )
        self.weather_widget = DraggableWidget(
            self, self.screen_w - 320, 40, 280, 120, "Weather", "72°F"
        )
        self.news_widget = DraggableWidget(
            self, 40, self.screen_h - 180, 420, 120, "News", "Top headline here"
        )

        self.widgets.extend([
            self.time_widget,
            self.weather_widget,
            self.news_widget
        ])

        self.root.bind("<Escape>", self.exit_app)

        self.update_clock()

    def update_clock(self):
        current_time = time.strftime("%I:%M:%S %p")
        self.time_widget.update_value(current_time)
        self.root.after(1000, self.update_clock)

    def exit_app(self, event=None):
        global running
        running = False
        self.root.destroy()


# =========================
# HAND TRACKING THREAD
# =========================
def run_hand_tracking(
    model_path,
    num_hands=1,
    min_hand_detection_confidence=0.5,
    min_hand_presence_confidence=0.5,
    min_tracking_confidence=0.5,
    camera_id=0,
    width=640,
    height=480,
):
    global COUNTER, FPS, START_TIME, DETECTION_RESULT, running

    screen_w, screen_h = pyautogui.size()
    print(f"Screen size: {screen_w}x{screen_h}")

    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print("ERROR: Unable to open webcam.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    was_fist = False
    tracking_enabled = TRACKING_ENABLED_DEFAULT
    ily_start_time = None
    last_toggle_time = 0
    ily_hold_seconds = 3

    def save_result(result: vision.HandLandmarkerResult, unused_output_image, timestamp_ms):
        global COUNTER, FPS, START_TIME, DETECTION_RESULT
        if COUNTER % 10 == 0:
            elapsed = time.time() - START_TIME
            if elapsed > 0:
                FPS = 10 / elapsed
            START_TIME = time.time()
        DETECTION_RESULT = result
        COUNTER += 1

    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.LIVE_STREAM,
        num_hands=num_hands,
        min_hand_detection_confidence=min_hand_detection_confidence,
        min_hand_presence_confidence=min_hand_presence_confidence,
        min_tracking_confidence=min_tracking_confidence,
        result_callback=save_result,
    )

    detector = vision.HandLandmarker.create_from_options(options)

    try:
        while running and cap.isOpened():
            success, frame = cap.read()
            if not success:
                continue

            frame = cv2.flip(frame, 1)
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
            detector.detect_async(mp_image, time.time_ns() // 1_000_000)

            if DETECTION_RESULT is None or not DETECTION_RESULT.hand_landmarks:
                if was_fist:
                    try:
                        pyautogui.mouseUp()
                    except Exception:
                        pass
                    was_fist = False
                continue

            hand_landmarks = DETECTION_RESULT.hand_landmarks[0]

            # ILY gesture toggle
            thumb_out = hand_landmarks[4].x < hand_landmarks[3].x
            index_out = hand_landmarks[8].y < hand_landmarks[6].y
            middle_in = hand_landmarks[12].y > hand_landmarks[10].y
            ring_in = hand_landmarks[16].y > hand_landmarks[14].y
            pinky_out = hand_landmarks[20].y < hand_landmarks[18].y
            is_ily = thumb_out and index_out and middle_in and ring_in and pinky_out

            if is_ily:
                if ily_start_time is None:
                    ily_start_time = time.time()
                elif time.time() - ily_start_time >= ily_hold_seconds:
                    if time.time() - last_toggle_time > 1:
                        tracking_enabled = not tracking_enabled
                        last_toggle_time = time.time()
                        print(f"Tracking toggled: {tracking_enabled}")
                    ily_start_time = None
            else:
                ily_start_time = None

            if not tracking_enabled:
                if was_fist:
                    try:
                        pyautogui.mouseUp()
                    except Exception:
                        pass
                    was_fist = False
                continue

            # cursor movement from palm landmark
            palm = hand_landmarks[9]
            raw_x = int(palm.x * screen_w)
            raw_y = int(palm.y * screen_h)
            smooth_x, smooth_y = smooth_position(raw_x, raw_y)

            try:
                pyautogui.moveTo(smooth_x, smooth_y, duration=0, _pause=False)
            except Exception as e:
                print(f"Mouse move error: {e}")

            # fist = hold left click for dragging widget
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
                print(f"Mouse click error: {e}")

            was_fist = is_fist

    except Exception as e:
        print(f"Hand tracking crashed: {e}")

    finally:
        try:
            pyautogui.mouseUp()
        except Exception:
            pass
        detector.close()
        cap.release()


# =========================
# START APP
# =========================
def main():
    root = tk.Tk()
    app = SmartMirrorApp(root)

    tracking_thread = threading.Thread(
        target=run_hand_tracking,
        kwargs={
            "model_path": MODEL_PATH,
            "num_hands": 1,
            "min_hand_detection_confidence": 0.5,
            "min_hand_presence_confidence": 0.5,
            "min_tracking_confidence": 0.5,
            "camera_id": CAMERA_ID,
            "width": FRAME_WIDTH,
            "height": FRAME_HEIGHT,
        },
        daemon=True,
    )
    tracking_thread.start()

    root.mainloop()


if __name__ == "__main__":
    main()
