import os
import time
import signal
import sys
import threading
import tkinter as tk
from datetime import datetime

import requests
import yfinance as yf
from dotenv import load_dotenv

import cv2
import mediapipe as mp
from pynput.mouse import Button, Controller as MouseController
mouse = MouseController()
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

load_dotenv()

# =========================
# API / DASHBOARD CONFIG
# =========================
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

CITY = "Syracuse"
STOCK_SYMBOLS = ["AAPL", "GOOGL", "SPY"]

WEATHER_REFRESH_MS = 10 * 60 * 1000
NEWS_REFRESH_MS = 15 * 60 * 1000
NEWS_CYCLE_MS = 7 * 1000
STOCK_REFRESH_MS = 5 * 60 * 1000
CLOCK_REFRESH_MS = 1000

BG_COLOR = "black"
BOX_COLOR = "#1c1c1e"
FG_COLOR = "white"
DIM_COLOR = "#888888"

FONT_TITLE = ("Arial", 14, "bold")
FONT_BODY = ("Arial", 13)
FONT_COMPACT = ("Arial", 12)

WIDGET_PAD = 10

# =========================
# HAND TRACKING CONFIG
# =========================
MODEL_PATH = "hand_landmarker.task"
CAMERA_ID = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
SMOOTHING_WINDOW = 4


running = True
DETECTION_RESULT = None
position_buffer = []
root = None

# =========================
# API CACHE
# =========================
_weather_cache = "Loading..."
_news_cache = [{"title": "Loading...", "source": "", "pub": ""}]
_stock_cache = ["Loading..." for _ in STOCK_SYMBOLS]


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
            info = ticker.fast_info
            price = info.last_price
            prev = info.previous_close

            if price is None or prev in (None, 0):
                raise ValueError("Stock data unavailable")

            change = price - prev
            pct = (change / prev) * 100
            arrow = "▲" if change >= 0 else "▼"
            results.append(f"{sym}  ${price:.2f}  {arrow}{abs(change):.2f} ({abs(pct):.2f}%)")
        except Exception:
            results.append(f"{sym}: N/A")

    _stock_cache = results


def bg(fn):
    threading.Thread(target=fn, daemon=True).start()


# =========================
# HAND HELPERS
# =========================
def smooth_position(x, y):
    position_buffer.append((x, y))
    if len(position_buffer) > SMOOTHING_WINDOW:
        position_buffer.pop(0)

    avg_x = int(sum(px for px, _ in position_buffer) / len(position_buffer))
    avg_y = int(sum(py for _, py in position_buffer) / len(position_buffer))
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


def run_hand_tracking():
    global running, DETECTION_RESULT
    
    screen_w, screen_h = get_screen_size()
    print(f"Screen size: {screen_w}x{screen_h}")
    

#    try:
#        screen_w, screen_h = pyautogui.size()
#        print(f"Screen size: {screen_w}x{screen_h}")
#    except Exception as e:
#        print(f"Unable to get screen size: {e}")
#        return

    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print("ERROR: Unable to open webcam.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    was_fist = False
    TRACKING_ENABLED = False
    ily_start_time = None
    ILY_HOLD_SECONDS = 3
    ily_cooldown_until = 0

    def save_result(result: vision.HandLandmarkerResult, unused_output_image: mp.Image, timestamp_ms: int):
        global DETECTION_RESULT
        DETECTION_RESULT = result

    try:
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.LIVE_STREAM,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            result_callback=save_result,
        )
        detector = vision.HandLandmarker.create_from_options(options)
    except Exception as e:
        print(f"Failed to load MediaPipe model: {e}")
        cap.release()
        return

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
                        mouse.release(Button.left)
                    except Exception:
                        pass
                    was_fist = False
                ily_start_time = None
                continue

            hand_landmarks = DETECTION_RESULT.hand_landmarks[0]

            # --- ILY detection ---
            # If ILY not triggering reliably, flip < to > on the thumb_out line
            thumb_out = hand_landmarks[4].x < hand_landmarks[3].x
            index_out = hand_landmarks[8].y  < hand_landmarks[6].y
            middle_in = hand_landmarks[12].y > hand_landmarks[10].y
            ring_in   = hand_landmarks[16].y > hand_landmarks[14].y
            pinky_out = hand_landmarks[20].y < hand_landmarks[18].y
            is_ily = thumb_out and index_out and middle_in and ring_in and pinky_out

            if is_ily and now >= ily_cooldown_until:  # <-- respect cooldown
                if ily_start_time is None:
                    ily_start_time = now
                elapsed = now - ily_start_time
                if elapsed >= ILY_HOLD_SECONDS:
                    TRACKING_ENABLED = not TRACKING_ENABLED
                    ily_start_time = None
                    ily_cooldown_until = now + 2.0  # <-- 2 second cooldown after toggle
                    print(f"Tracking {'ENABLED' if TRACKING_ENABLED else 'DISABLED'}")
                    if not TRACKING_ENABLED and was_fist:
                        try:
                            mouse.release(Button.left)
                        except Exception:
                            pass
                        was_fist = False
            else:
                ily_start_time = None
                
            # --- Only move/click if tracking is on ---
            if not TRACKING_ENABLED:
                continue

            palm = hand_landmarks[9]
            raw_x = int(palm.x * screen_w)
            raw_y = int(palm.y * screen_h)
            smooth_x, smooth_y = smooth_position(raw_x, raw_y)

            try:
                mouse.position = (smooth_x, smooth_y)
            except Exception as e:
                print(f"Mouse move error: {e}")

            fingertips = [8, 12, 16, 20]
            knuckles   = [6, 10, 14, 18]
            is_fist = all(
                hand_landmarks[tip].y > hand_landmarks[knuck].y
                for tip, knuck in zip(fingertips, knuckles)
            )

            try:
                if is_fist and not was_fist:
                    mouse.press(Button.left)
                elif not is_fist and was_fist:
                    mouse.release(Button.left)
            except Exception as e:
                print(f"Mouse click error: {e}")

            was_fist = is_fist

    except Exception as e:
        print(f"Hand tracking crashed: {e}")
    finally:
        try:
            mouse.release(Button.left)
        except Exception:
            pass
        try:
            detector.close()
        except Exception:
            pass
        cap.release()

# =========================
# ROUNDED RECTANGLE HELPER
# =========================
def rounded_rect_points(x1, y1, x2, y2, r=30):
    return [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1
    ]


# =========================
# DRAGGABLE CARD BASE
# =========================
class DraggableCard(tk.Canvas):
    _all_cards = []

    def __init__(self, parent, width, height, title, **kw):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=BG_COLOR,
            highlightthickness=0,
            bd=0,
            **kw
        )

        self.card_w = width
        self.card_h = height

        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width - 4, height - 4, r=28),
            smooth=True,
            splinesteps=36,
            fill=BOX_COLOR,
            outline="white",
            width=3
        )

        if title:
            self.create_text(
                20, 20,
                text=title,
                fill=DIM_COLOR,
                font=FONT_TITLE,
                anchor="nw"
            )

        self._drag_ox = 0
        self._drag_oy = 0
        self._is_dragging = False

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        DraggableCard._all_cards.append(self)

    def _on_press(self, e):
        self._drag_ox = e.x
        self._drag_oy = e.y
        self._is_dragging = True
        self.tk.call("raise", self._w)
        self.itemconfigure(self._bg_id, outline="#00ff00")

    def _on_drag(self, e):
        if not self._is_dragging:
            self._is_dragging = True
            self.itemconfigure(self._bg_id, outline="#00ff00")

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
        self._is_dragging = False
        self.itemconfigure(self._bg_id, outline="white")

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
                push_left = (nx + self.card_w + WIDGET_PAD) - ox
                push_right = (ox + ow + WIDGET_PAD) - nx
                push_up = (ny + self.card_h + WIDGET_PAD) - oy
                push_down = (oy + oh + WIDGET_PAD) - ny

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
            240, 40,
            text="...",
            fill=FG_COLOR,
            font=FONT_BODY,
            anchor="center"
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
# NEWS CARD
# =========================
class NewsCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0

        self._source_id = self.create_text(
            24, 48,
            text="",
            fill=DIM_COLOR,
            font=("Arial", 11),
            anchor="nw"
        )
        self._pub_id = self.create_text(
            24, 66,
            text="",
            fill=DIM_COLOR,
            font=("Arial", 11),
            anchor="nw"
        )
        self._headline_id = self.create_text(
            24, 90,
            text="Loading...",
            fill=FG_COLOR,
            font=("Arial", 14, "bold"),
            anchor="nw",
            width=440
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
            self.itemconfig(self._source_id, text=item["source"])
            self.itemconfig(self._pub_id, text=item["pub"])
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
                20, 48 + i * 34,
                text="Loading...",
                fill=FG_COLOR,
                font=FONT_COMPACT,
                anchor="nw",
                width=320
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


# =========================
# EXIT HANDLERS
# =========================
def close_app(event=None):
    global running, root
    running = False
    try:
        if root is not None:
            root.quit()
            root.destroy()
    except Exception:
        pass


def handle_exit(sig, frame):
    close_app()
    sys.exit(0)


# =========================
# MAIN WINDOW
# =========================
def main():
    global root

    root = tk.Tk()
    root.title("Smart Mirror Dashboard")
    root.configure(bg=BG_COLOR)

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    root.geometry(f"{screen_w}x{screen_h}+0+0")
    root.resizable(False, False)
    root.attributes("-fullscreen", True)

    root.bind("<Escape>", close_app)
    root.bind("q", close_app)
    root.protocol("WM_DELETE_WINDOW", close_app)

    signal.signal(signal.SIGINT, handle_exit)

    canvas = tk.Frame(root, bg=BG_COLOR)
    canvas.pack(fill="both", expand=True)

    dtw_card = DateTimeWeatherCard(canvas, x=10, y=10)
    NewsCard(canvas, x=1020, y=10)
    StocksCard(canvas, x=10, y=790)

    bg(fetch_weather)
    dtw_card.refresh_weather()

    hand_thread = threading.Thread(target=run_hand_tracking, daemon=True)
    hand_thread.start()

    root.mainloop()


if __name__ == "__main__":
    main()
