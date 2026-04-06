import json
import os
import threading
import time
import tkinter as tk
from datetime import datetime

import cv2
import mediapipe as mp
import requests
import yfinance as yf
from dotenv import load_dotenv
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pynput.mouse import Button, Controller as MouseController

load_dotenv()

# =========================
# CONFIG
# =========================
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

CITY = "Syracuse"
STOCK_SYMBOLS = ["AAPL", "BA", "BAC"]

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

TODO_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_todos.json")
TODO_LINE_HEIGHT = 30
TODO_MAX_VISIBLE = 14
TODO_CARD_WIDTH = 340

# Hand tracking
HAND_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
CAMERA_ID = 0
FRAME_WIDTH = 320
FRAME_HEIGHT = 240
SMOOTHING_WINDOW = 5
HAND_SKIP_FRAMES = 1
HAND_MAX_FPS = 20.0

# =========================
# STATE
# =========================
_weather_cache = "Loading..."
_news_cache = []
_stock_cache = ["Loading..." for _ in STOCK_SYMBOLS]
_todo_tasks = []

_running = True
_mouse = MouseController()
_position_buffer = []


def bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def load_todos():
    global _todo_tasks
    try:
        with open(TODO_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tasks", [])
        out = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, str) and item.strip():
                out.append({"text": item.strip()})
            elif isinstance(item, dict):
                txt = (item.get("text") or "").strip()
                if txt:
                    out.append({"text": txt})
        _todo_tasks = out
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        _todo_tasks = []


def fetch_weather():
    global _weather_cache
    try:
        if not OPENWEATHER_API_KEY:
            _weather_cache = "Weather key missing"
            return
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": CITY, "appid": OPENWEATHER_API_KEY, "units": "imperial"}
        data = requests.get(url, params=params, timeout=5).json()
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
        if not NEWS_API_KEY:
            _news_cache = [{"title": "News key missing", "source": "", "pub": ""}]
            return
        url = "https://newsapi.org/v2/top-headlines"
        params = {"country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY}
        data = requests.get(url, params=params, timeout=5).json()
        out = []
        for a in data.get("articles", []):
            title = a.get("title", "No title")
            source = a.get("source", {}).get("name", "")
            pub = a.get("publishedAt", "")
            try:
                dt = datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ")
                pub = dt.strftime("%m.%d.%Y, %H:%M")
            except Exception:
                pub = ""
            out.append({"title": title, "source": source, "pub": pub})
        _news_cache = out if out else [{"title": "News unavailable", "source": "", "pub": ""}]
    except Exception:
        _news_cache = [{"title": "News unavailable", "source": "", "pub": ""}]


def fetch_stocks():
    global _stock_cache
    out = []
    for sym in STOCK_SYMBOLS:
        try:
            info = yf.Ticker(sym).fast_info
            price = info.last_price
            prev = info.previous_close
            change = price - prev
            pct = (change / prev) * 100
            arrow = "▲" if change >= 0 else "▼"
            out.append(f"{sym}  ${price:.2f}  {arrow}{abs(change):.2f} ({abs(pct):.2f}%)")
        except Exception:
            out.append(f"{sym}: N/A")
    _stock_cache = out


def rounded_rect_points(x1, y1, x2, y2, r=28):
    return [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]


class DraggableCard(tk.Canvas):
    _all_cards = []

    def __init__(self, parent, width, height, title):
        super().__init__(parent, width=width, height=height, bg=BG_COLOR, highlightthickness=0, bd=0)
        self.card_w = width
        self.card_h = height

        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width - 4, height - 4),
            smooth=True, splinesteps=36, fill=BOX_COLOR, outline="white", width=3
        )
        if title:
            self.create_text(20, 20, text=title, fill=DIM_COLOR, font=FONT_TITLE, anchor="nw")

        self._drag_ox = 0
        self._drag_oy = 0
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        DraggableCard._all_cards.append(self)

    def _on_press(self, e):
        self._drag_ox, self._drag_oy = e.x, e.y
        self.tk.call("raise", self._w)
        self.itemconfigure(self._bg_id, outline="#00ff00")

    def _on_drag(self, e):
        parent = self.master
        pw, ph = parent.winfo_width(), parent.winfo_height()
        nx = self.winfo_x() + e.x - self._drag_ox
        ny = self.winfo_y() + e.y - self._drag_oy
        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, nx))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, ny))
        nx, ny = self._resolve_collisions(nx, ny)
        self.place(x=nx, y=ny)

    def _on_release(self, _e):
        self.itemconfigure(self._bg_id, outline="white")

    def _resolve_collisions(self, nx, ny):
        for other in DraggableCard._all_cards:
            if other is self:
                continue
            ox, oy, ow, oh = other.winfo_x(), other.winfo_y(), other.card_w, other.card_h
            overlap_x = nx < ox + ow + WIDGET_PAD and nx + self.card_w + WIDGET_PAD > ox
            overlap_y = ny < oy + oh + WIDGET_PAD and ny + self.card_h + WIDGET_PAD > oy
            if overlap_x and overlap_y:
                push_left = (nx + self.card_w + WIDGET_PAD) - ox
                push_right = (ox + ow + WIDGET_PAD) - nx
                push_up = (ny + self.card_h + WIDGET_PAD) - oy
                push_down = (oy + oh + WIDGET_PAD) - ny
                m = min(push_left, push_right, push_up, push_down)
                if m == push_left:
                    nx = ox - self.card_w - WIDGET_PAD
                elif m == push_right:
                    nx = ox + ow + WIDGET_PAD
                elif m == push_up:
                    ny = oy - self.card_h - WIDGET_PAD
                else:
                    ny = oy + oh + WIDGET_PAD
        return nx, ny


class DateTimeWeatherCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=80, title="")
        self._line = self.create_text(240, 40, text="...", fill=FG_COLOR, font=FONT_BODY, anchor="center")
        self.place(x=x, y=y)
        self._tick()
        self.refresh_weather()

    def _tick(self):
        now = datetime.now()
        date_str = now.strftime("%a, %b %d")
        time_str = now.strftime("%I:%M:%S %p").lstrip("0")
        self.itemconfig(self._line, text=f"{date_str}   |   {time_str}   |   {_weather_cache}")
        self.after(CLOCK_REFRESH_MS, self._tick)

    def refresh_weather(self):
        bg(fetch_weather)
        self.after(WEATHER_REFRESH_MS, self.refresh_weather)


class NewsCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0
        self._source_id = self.create_text(24, 48, text="", fill=DIM_COLOR, font=("Arial", 11), anchor="nw")
        self._pub_id = self.create_text(24, 66, text="", fill=DIM_COLOR, font=("Arial", 11), anchor="nw")
        self._headline_id = self.create_text(
            24, 90, text="Loading...", fill=FG_COLOR, font=("Arial", 14, "bold"), anchor="nw", width=440
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
            self._idx %= n
            item = _news_cache[self._idx]
            self.itemconfig(self._source_id, text=item["source"])
            self.itemconfig(self._pub_id, text=item["pub"])
            self.itemconfig(self._headline_id, text=item["title"])
            self._idx += 1
        self.after(NEWS_CYCLE_MS, self._cycle)


class StocksCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=360, height=155, title="Stocks")
        self._line_ids = []
        for i in range(len(STOCK_SYMBOLS)):
            tid = self.create_text(
                20, 48 + i * 34, text="Loading...", fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=320
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


class TodoCard(DraggableCard):
    def __init__(self, parent, x, y, max_h):
        h = min(72 + TODO_MAX_VISIBLE * TODO_LINE_HEIGHT + 36, max_h - 120)
        super().__init__(parent, width=TODO_CARD_WIDTH, height=int(h), title="To-do")
        self._row_ids = []
        self.place(x=x, y=y)
        self.refresh_list()

    def refresh_list(self):
        for rid in self._row_ids:
            self.delete(rid)
        self._row_ids.clear()
        y0 = 48
        tasks = _todo_tasks[:TODO_MAX_VISIBLE]
        if not tasks:
            self._row_ids.append(self.create_text(
                24, y0, text="No tasks in mirror_todos.json", fill=DIM_COLOR,
                font=FONT_COMPACT, anchor="nw", width=TODO_CARD_WIDTH - 40
            ))
        else:
            for t in tasks:
                self._row_ids.append(self.create_text(
                    24, y0, text=f"• {t['text']}", fill=FG_COLOR,
                    font=FONT_COMPACT, anchor="nw", width=TODO_CARD_WIDTH - 40
                ))
                y0 += TODO_LINE_HEIGHT
            ov = len(_todo_tasks) - TODO_MAX_VISIBLE
            if ov > 0:
                self._row_ids.append(self.create_text(
                    24, y0, text=f"+ {ov} more", fill=DIM_COLOR, font=("Arial", 11), anchor="nw"
                ))


def _get_screen_size():
    try:
        import subprocess
        out = subprocess.check_output("xrandr | grep '*' | awk '{print $1}'", shell=True).decode().strip()
        line = out.split("\n")[0]
        w, h = line.split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920


def _smooth(x, y):
    _position_buffer.append((x, y))
    if len(_position_buffer) > SMOOTHING_WINDOW:
        _position_buffer.pop(0)
    ax = int(sum(px for px, _ in _position_buffer) / len(_position_buffer))
    ay = int(sum(py for _, py in _position_buffer) / len(_position_buffer))
    return ax, ay


def hand_tracking_loop():
    global _running
    if not os.path.exists(HAND_MODEL_PATH):
        print(f"[Hand] Model not found: {HAND_MODEL_PATH}")
        return

    sw, sh = _get_screen_size()
    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print("[Hand] Unable to open webcam.")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    try:
        detector = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.45,
                min_hand_presence_confidence=0.45,
                min_tracking_confidence=0.45,
            )
        )
    except Exception as e:
        print(f"[Hand] Failed to load model: {e}")
        cap.release()
        return

    was_fist = False
    frame_count = 0
    last_tick = 0.0

    try:
        while _running and cap.isOpened():
            now = time.time()
            min_dt = 1.0 / max(HAND_MAX_FPS, 1.0)
            if last_tick and (now - last_tick) < min_dt:
                time.sleep(max(0.0, min_dt - (now - last_tick)))
            last_tick = time.time()

            frame_count += 1
            if HAND_SKIP_FRAMES > 1 and (frame_count % HAND_SKIP_FRAMES) != 0:
                cap.grab()
                continue

            ok, frame = cap.read()
            if not ok:
                continue

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not result or not result.hand_landmarks:
                if was_fist:
                    try:
                        _mouse.release(Button.left)
                    except Exception:
                        pass
                    was_fist = False
                continue

            lm = result.hand_landmarks[0]
            palm = lm[9]
            sx, sy = int(palm.x * sw), int(palm.y * sh)
            mx, my = _smooth(sx, sy)
            try:
                _mouse.position = (mx, my)
            except Exception:
                pass

            tips = [8, 12, 16, 20]
            knucks = [6, 10, 14, 18]
            is_fist = all(lm[t].y > lm[k].y for t, k in zip(tips, knucks))
            try:
                if is_fist and not was_fist:
                    _mouse.press(Button.left)
                elif not is_fist and was_fist:
                    _mouse.release(Button.left)
            except Exception:
                pass
            was_fist = is_fist
    finally:
        try:
            _mouse.release(Button.left)
        except Exception:
            pass
        try:
            detector.close()
        except Exception:
            pass
        cap.release()


def close_app(root):
    global _running
    _running = False
    try:
        root.quit()
        root.destroy()
    except Exception:
        pass


def main():
    load_todos()

    root = tk.Tk()
    root.title("Vertical Mirror Widgets + Hand Control")
    root.configure(bg=BG_COLOR)
    root.attributes("-fullscreen", True)
    root.bind("<Escape>", lambda _e: close_app(root))

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    canvas = tk.Frame(root, bg=BG_COLOR)
    canvas.pack(fill="both", expand=True)

    todo_h = min(72 + TODO_MAX_VISIBLE * TODO_LINE_HEIGHT + 36, sh - 120)
    todo_y = max(WIDGET_PAD, (sh - int(todo_h)) // 2)

    DateTimeWeatherCard(canvas, x=10, y=10)
    NewsCard(canvas, x=510, y=10)
    StocksCard(canvas, x=10, y=max(WIDGET_PAD, sh - 175))
    TodoCard(canvas, x=WIDGET_PAD, y=todo_y, max_h=sh)

    bg(fetch_weather)
    bg(fetch_news)
    bg(fetch_stocks)
    threading.Thread(target=hand_tracking_loop, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
