import os
import tkinter as tk
import requests
import yfinance as yf
from datetime import datetime
import threading
import os

load_dotenv()  

# =========================
# CONFIG
# =========================
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")


CITY = "Syracuse"
STOCK_SYMBOLS = ["AAPL", "BA", "BAC"]

WEATHER_REFRESH_MS   = 10 * 60 * 1000
NEWS_REFRESH_MS      = 15 * 60 * 1000
NEWS_CYCLE_MS        = 6 * 1000        # rotate headline every 6 s
STOCK_REFRESH_MS     = 5  * 60 * 1000
CLOCK_REFRESH_MS     = 1000

BG_COLOR    = "black"
BOX_COLOR   = "#1c1c1e"
BOX_OUTLINE = "#2f2f2f"
FG_COLOR    = "white"
DIM_COLOR   = "#888888"

FONT_TITLE   = ("Arial", 14, "bold")
FONT_BODY    = ("Arial", 13)
FONT_COMPACT = ("Arial", 12)
FONT_HEADLINE= ("Arial", 12)

WIDGET_PAD = 10   # min gap between widgets / border

# =========================
# API FUNCTIONS (threaded)
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
            # format published: "2024-03-23T14:30:00Z" -> "03.23.2024, 14:30"
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
            price   = info.last_price
            prev    = info.previous_close
            change  = price - prev
            pct     = (change / prev) * 100
            arrow   = "▲" if change >= 0 else "▼"
            results.append(f"{sym}  ${price:.2f}  {arrow}{abs(change):.2f} ({abs(pct):.2f}%)")
        except Exception:
            results.append(f"{sym}: N/A")
    _stock_cache = results

# run fetch in background thread so GUI stays responsive
def bg(fn):
    threading.Thread(target=fn, daemon=True).start()

# =========================
# ROUNDED RECTANGLE HELPER
# =========================
def rounded_rect_points(x1, y1, x2, y2, r=30):
    return [
        x1+r, y1,  x2-r, y1,
        x2, y1,    x2, y1+r,
        x2, y2-r,  x2, y2,
        x2-r, y2,  x1+r, y2,
        x1, y2,    x1, y2-r,
        x1, y1+r,  x1, y1
    ]

# =========================
# DRAGGABLE CARD BASE
# =========================
class DraggableCard(tk.Canvas):
    """
    A rounded card widget that can be dragged.
    Collision is resolved against canvas borders and other DraggableCard instances.
    """
    _all_cards = []   # class-level registry for collision

    def __init__(self, parent, width, height, title, **kw):
        super().__init__(
            parent,
            width=width, height=height,
            bg=BG_COLOR, highlightthickness=0, bd=0,
            **kw
        )
        self.card_w = width
        self.card_h = height

        # draw card background
        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width-4, height-4, r=28),
            smooth=True, splinesteps=36,
            fill=BOX_COLOR, outline=BOX_OUTLINE, width=2
        )

        # title
        self.create_text(
            20, 20, text=title,
            fill=DIM_COLOR, font=FONT_TITLE, anchor="nw"
        )

        # content placeholder — subclasses fill this
        self._content_ids = []

        # drag state
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
        self.lift()

    def _on_drag(self, e):
        parent = self.master
        pw = parent.winfo_width()
        ph = parent.winfo_height()

        nx = self.winfo_x() + e.x - self._drag_ox
        ny = self.winfo_y() + e.y - self._drag_oy

        # clamp to canvas border
        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, nx))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, ny))

        # resolve collision with other cards
        nx, ny = self._resolve_collisions(nx, ny)

        self.place(x=nx, y=ny)

    def _on_release(self, e):
        pass

    def _resolve_collisions(self, nx, ny):
        """Push this card out of overlap with all others."""
        for other in DraggableCard._all_cards:
            if other is self:
                continue
            ox = other.winfo_x()
            oy = other.winfo_y()
            ow = other.card_w
            oh = other.card_h

            # AABB overlap?
            overlap_x = nx < ox + ow + WIDGET_PAD and nx + self.card_w + WIDGET_PAD > ox
            overlap_y = ny < oy + oh + WIDGET_PAD and ny + self.card_h + WIDGET_PAD > oy

            if overlap_x and overlap_y:
                # find smallest push direction
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

        # re-clamp after collision resolution
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
        # single-line compact layout
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
        # taller card so full headline is visible
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0

        # source name (dimmed, small)
        self._source_id = self.create_text(
            24, 48, text="",
            fill=DIM_COLOR, font=("Arial", 11),
            anchor="nw"
        )
        # published date (dimmed, small) — same line as source, right after
        self._pub_id = self.create_text(
            24, 66, text="",
            fill=DIM_COLOR, font=("Arial", 11),
            anchor="nw"
        )
        # bold headline
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
            self.itemconfig(self._source_id, text=item["source"])
            self.itemconfig(self._pub_id,    text=item["pub"])
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
        self.after(500, self._apply)   # small delay for thread to finish
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
        # re-check until populated
        if any("Loading" in s for s in _stock_cache):
            self.after(2000, self._apply)


# =========================
# MAIN WINDOW
# =========================
root = tk.Tk()
root.title("Smart Mirror Dashboard")
root.configure(bg=BG_COLOR)
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

canvas = tk.Frame(root, bg=BG_COLOR)
canvas.pack(fill="both", expand=True)

# initial positions (will be draggable)
dtw_card   = DateTimeWeatherCard(canvas, x=40,  y=30)
news_card  = NewsCard(canvas,            x=40,  y=130)
stock_card = StocksCard(canvas,          x=40,  y=260)

# kick off background weather fetch immediately
bg(fetch_weather)
dtw_card.refresh_weather()

root.mainloop()