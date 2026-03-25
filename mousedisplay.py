import os
import tkinter as tk
import requests
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv
import threading
import argparse
import sys
import time
import cv2
import mediapipe as mp
from pynput.mouse import Button, Controller as MouseController
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

CITY = "Syracuse"
STOCK_SYMBOLS = ["AAPL","GOOGL", "SPY"]

WEATHER_REFRESH_MS = 10 * 60 * 1000 # 10 minutes
NEWS_REFRESH_MS    = 15 * 60 * 1000 # 15 minutes
NEWS_CYCLE_MS      =  7 * 1000 # 7 seconds, rotates the widget to show next news
STOCK_REFRESH_MS   =  5 * 60 * 1000 # 5 minutes
CLOCK_REFRESH_MS   = 1000

BG_COLOR    = "black"
BOX_COLOR   = "#1c1c1e"
BOX_OUTLINE = "#2f2f2f"
FG_COLOR    = "white"
DIM_COLOR   = "#888888"

FONT_TITLE    = ("Arial", 14, "bold")
FONT_BODY     = ("Arial", 13)
FONT_COMPACT  = ("Arial", 12)
FONT_HEADLINE = ("Arial", 12)

WIDGET_PAD = 10

mouse = MouseController()
last_mouse_pos = None  # tracks previous position for relative movement

# Global variables
COUNTER, FPS = 0, 0
START_TIME = time.time()
DETECTION_RESULT = None

# Smoothing buffer — higher = smoother but slightly more lag
SMOOTHING_WINDOW = 6
position_buffer = []

# =========================
# API CACHE
# =========================
_weather_cache = "Loading..."
_news_cache    = []
_stock_cache   = ["Loading..." for _ in STOCK_SYMBOLS]

def fetch_weather():
    global _weather_cache
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": CITY, "appid": OPENWEATHER_API_KEY, "units": "imperial"}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        if "main" not in data:
            _weather_cache = "Weather N/A"
            return
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"].title()
        _weather_cache = f"{temp:.0f}°F  {desc}"
    except Exception:
        _weather_cache = "Weather N/A"

def fetch_news():
    global _news_cache
    try:
        url = "https://newsapi.org/v2/top-headlines"
        params = {"country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        articles = data.get("articles", [])
        results = []
        for a in articles:
            title = a.get("title", "No title")
            source = a.get("source", {}).get("name", "")
            published = a.get("publishedAt", "")
            try:
                dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
                pub_str = dt.strftime("%m.%d.%Y, %H:%M")
            except Exception:
                pub_str = ""
            results.append({"title": title, "source": source, "pub": pub_str})
        _news_cache = results if results else [{"title": "News unavailable", "source": "", "pub": ""}]
    except Exception:
        _news_cache = [{"title": "News unavailable", "source": "", "pub": ""}]

def fetch_stocks():
    global _stock_cache
    results = []
    for sym in STOCK_SYMBOLS:
        try:
            ticker = yf.Ticker(sym)
            info   = ticker.fast_info
            price  = info.last_price
            prev   = info.previous_close
            change = price - prev
            pct    = (change / prev) * 100
            arrow  = "▲" if change >= 0 else "▼"
            results.append(f"{sym}  ${price:.2f}  {arrow}{abs(change):.2f} ({abs(pct):.2f}%)")
            
            if price is None or prev in (None, 0):
                raise ValueError("Stock data unavailable")
        except Exception:
            results.append(f"{sym}: N/A")
    _stock_cache = results

def bg(fn):
    threading.Thread(target=fn, daemon=True).start()

# =========================
# ROUNDED RECTANGLE HELPER
# =========================
def rounded_rect_points(x1, y1, x2, y2, r=30):
    return [
        x1+r, y1,  x2-r, y1,
        x2,   y1,  x2,   y1+r,
        x2,   y2-r, x2,  y2,
        x2-r, y2,  x1+r, y2,
        x1,   y2,  x1,   y2-r,
        x1,   y1+r, x1,  y1
    ]

# =========================
# DRAGGABLE CARD BASE
# =========================
class DraggableCard(tk.Canvas):
    _all_cards = []

    def __init__(self, parent, width, height, title, **kw):
        super().__init__(
            parent,
            width=width, height=height,
            bg=BG_COLOR, highlightthickness=0, bd=0,
            **kw
        )
        self.card_w = width
        self.card_h = height

        # draw card background — white border by default
        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width-4, height-4, r=28),
            smooth=True,
            splinesteps=36,
            fill=BOX_COLOR,
            outline="white",
            width=3
        )

        if title:
            self.create_text(
                20, 20, text=title,
                fill=DIM_COLOR, font=FONT_TITLE, anchor="nw"
            )

        self._content_ids = []

        self._drag_ox = 0
        self._drag_oy = 0
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        DraggableCard._all_cards.append(self)

    # ---- drag handlers ----
    def _on_press(self, e):
        self._drag_ox = e.x
        self._drag_oy = e.y
        self.tk.call('raise', self._w)              # bring to front (safe on Canvas subclass)
        self.itemconfigure(self._bg_id, outline="#00ff00")  # green border while dragging
        self.update_idletasks()

    def _on_drag(self, e):
        parent = self.master
        pw = parent.winfo_width()
        ph = parent.winfo_height()

        nx = self.winfo_x() + e.x - self._drag_ox
        ny = self.winfo_y() + e.y - self._drag_oy

        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, nx))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, ny))

        nx, ny = self._resolve_collisions(nx, ny)
        self.place(x=nx, y=ny)

    def _on_release(self, e):
        self.itemconfigure(self._bg_id, outline="white")    # back to white on release
        self.update_idletasks()

    def _resolve_collisions(self, nx, ny):
        for other in DraggableCard._all_cards:
            if other is self:
                continue
            ox = other.winfo_x()
            oy = other.winfo_y()
            ow = other.card_w
            oh = other.card_h

            overlap_x = nx < ox + ow + WIDGET_PAD and nx + self.card_w + WIDGET_PAD > ox
            overlap_y = ny < oy + oh + WIDGET_PAD and ny + self.card_h + WIDGET_PAD > oy

            if overlap_x and overlap_y:
                push_left  = (nx + self.card_w + WIDGET_PAD) - ox
                push_right = (ox + ow + WIDGET_PAD) - nx
                push_up    = (ny + self.card_h + WIDGET_PAD) - oy
                push_down  = (oy + oh + WIDGET_PAD) - ny

                min_push = min(push_left, push_right, push_up, push_down)
                if min_push == push_left:
                    nx = ox - self.card_w - WIDGET_PAD
                elif min_push == push_right:
                    nx = ox + ow + WIDGET_PAD
                elif min_push == push_up:
                    ny = oy - self.card_h - WIDGET_PAD
                else:
                    ny = oy + oh + WIDGET_PAD

        parent = self.master
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, nx))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, ny))
        return nx, ny


# =========================
# DATE / TIME / WEATHER CARD
# =========================
class DateTimeWeatherCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=80, title="")
        self._line = self.create_text(
            240, 40, text="...",
            fill=FG_COLOR, font=FONT_BODY, anchor="center"
        )
        self.place(x=x, y=y)
        self._tick()

    def _tick(self):
        now = datetime.now()
        date_str = now.strftime("%a, %b %d")
        time_str = now.strftime("%I:%M:%S %p").lstrip("0")
        self.itemconfig(
            self._line,
            text=f"{date_str}   |   {time_str}   |   {_weather_cache}"
        )
        self.after(CLOCK_REFRESH_MS, self._tick)

    def refresh_weather(self):
        bg(fetch_weather)
        self.after(WEATHER_REFRESH_MS, self.refresh_weather)


# =========================
# NEWS CARD (Apple-style cycling)
# =========================
class NewsCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0

        self._source_id = self.create_text(
            24, 48, text="",
            fill=DIM_COLOR, font=("Arial", 11), anchor="nw"
        )
        self._pub_id = self.create_text(
            24, 66, text="",
            fill=DIM_COLOR, font=("Arial", 11), anchor="nw"
        )
        self._headline_id = self.create_text(
            24, 90, text="Loading...",
            fill=FG_COLOR, font=("Arial", 14, "bold"),
            anchor="nw", width=440
        )

        self.place(x=x, y=y)
        self._cycle()
        self.refresh_news()

    def refresh_news(self):
        bg(fetch_news)
        self.after(NEWS_REFRESH_MS, self.refresh_news)

    def _cycle(self):
        if _news_cache:
            n = len(_news_cache)
            self._idx = self._idx % n
            item = _news_cache[self._idx]
            self.itemconfig(self._source_id,   text=item["source"])
            self.itemconfig(self._pub_id,      text=item["pub"])
            self.itemconfig(self._headline_id, text=item["title"])
            self._idx += 1
        self.after(NEWS_CYCLE_MS, self._cycle)


# =========================
# STOCKS CARD
# =========================
class StocksCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=360, height=155, title="Stocks")
        self._line_ids = []
        for i in range(len(STOCK_SYMBOLS)):
            tid = self.create_text(
                20, 48 + i * 34, text="Loading...",
                fill=FG_COLOR, font=FONT_COMPACT,
                anchor="nw", width=320
            )
            self._line_ids.append(tid)
        self.place(x=x, y=y)
        self._refresh()

    def _refresh(self):
        bg(fetch_stocks)
        self.after(500, self._apply)
        self.after(STOCK_REFRESH_MS, self._refresh)

    def _apply(self):
        for i, tid in enumerate(self._line_ids):
            text = _stock_cache[i] if i < len(_stock_cache) else "N/A"
            color = FG_COLOR
            if "▲" in text:
                color = "#34c759"
            elif "▼" in text:
                color = "#ff453a"
            self.itemconfig(tid, text=text, fill=color)
        if any("Loading" in s for s in _stock_cache):
            self.after(2000, self._apply)
            
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

        #cv2.imshow('Hand Mouse', image)
        #if cv2.waitKey(1) == 27:
            #break

    # Clean up — always release mouse on exit
    if mouse_held:
        mouse.release(Button.left)
    detector.close()
    cap.release()
    #cv2.destroyAllWindows()


# =========================
# MAIN WINDOW
# =========================
root = tk.Tk()
root.title("Smart Mirror Dashboard")
root.configure(bg=BG_COLOR)
root.update_idletasks()
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
root.geometry(f"{screen_w}x{screen_h}+0+0")
root.resizable(False, False)
root.bind("<Escape>", lambda e: root.destroy())

canvas = tk.Frame(root, bg=BG_COLOR)
canvas.pack(fill="both", expand=True)

dtw_card   = DateTimeWeatherCard(canvas, x=10,  y=10)
news_card  = NewsCard(canvas,            x=1020,  y=10)
stock_card = StocksCard(canvas,          x=10,  y=790)

bg(fetch_weather)
dtw_card.refresh_weather()

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


root.mainloop()
