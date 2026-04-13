import tkinter as tk
from datetime import datetime

# Constants
BG_COLOR    = "black"
BOX_COLOR   = "#1c1c1e"
FG_COLOR    = "white"
DIM_COLOR   = "#888888"

# Fonts
FONT_TITLE   = ("Arial", 14, "bold")
FONT_BODY    = ("Arial", 13)
FONT_COMPACT = ("Arial", 12)

WIDGET_PAD = 10

# TODO
TODO_LINE_HEIGHT      = 30
TODO_MAX_VISIBLE      = 14
TODO_CARD_WIDTH       = 340

# Refresh intervals (ms)
WEATHER_REFRESH_MS = 10 * 60 * 1000
NEWS_REFRESH_MS    = 15 * 60 * 1000
NEWS_CYCLE_MS      =  7 * 1000
CLOCK_REFRESH_MS   = 1000
STOCK_REFRESH_MS   =  5 * 60 * 1000

# Import voice control functions
from voicecontrol import (
    _weather_cache, _news_cache, _stock_cache, _ui_queue, _todo_tasks,
    fetch_weather, fetch_news, fetch_stocks, _redraw_stocks, bg
)

# Import hand control
import handcontrol

# Global references
_root_ref = None
_stock_card_ref = None
_todo_card_ref = None
_ily_label = None

# ─────────────────────────────────────────────
# ROUNDED RECTANGLE HELPER
# ─────────────────────────────────────────────
def rounded_rect_points(x1, y1, x2, y2, r=28):
    return [
        x1+r, y1,   x2-r, y1,
        x2,   y1,   x2,   y1+r,
        x2,   y2-r, x2,   y2,
        x2-r, y2,   x1+r, y2,
        x1,   y2,   x1,   y2-r,
        x1,   y1+r, x1,   y1,
    ]

# ─────────────────────────────────────────────
# DRAGGABLE CARD BASE
# ─────────────────────────────────────────────
class DraggableCard(tk.Canvas):
    _all_cards = []

    def __init__(self, parent, width, height, title, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=BG_COLOR, highlightthickness=0, bd=0, **kw)
        self.card_w = width
        self.card_h = height
        self._mirror_place = None

        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width-4, height-4),
            smooth=True, splinesteps=36, fill=BOX_COLOR, outline="white", width=3,
        )
        if title:
            self.create_text(20, 20, text=title, fill=DIM_COLOR, font=FONT_TITLE, anchor="nw")

        self._drag_ox = self._drag_oy = 0
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        DraggableCard._all_cards.append(self)

    def place(self, cnf={}, **kw):
        tk.Canvas.place(self, cnf, **kw)
        x = kw.get("x") or (cnf.get("x") if isinstance(cnf, dict) else None)
        y = kw.get("y") or (cnf.get("y") if isinstance(cnf, dict) else None)
        if x is not None and y is not None:
            try:
                self._mirror_place = (int(float(x)), int(float(y)))
            except (TypeError, ValueError):
                pass

    def mirror_set_visible(self, visible):
        if visible:
            if self._mirror_place:
                self.place(x=self._mirror_place[0], y=self._mirror_place[1])
        else:
            try:
                if self.winfo_manager():
                    self._mirror_place = (self.winfo_x(), self.winfo_y())
            except tk.TclError:
                pass
            self.place_forget()

    def _on_press(self, e):
        self._drag_ox, self._drag_oy = e.x, e.y
        self.tk.call("raise", self._w)
        self.itemconfigure(self._bg_id, outline="#00ff00")

    def _on_drag(self, e):
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, self.winfo_x() + e.x - self._drag_ox))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, self.winfo_y() + e.y - self._drag_oy))
        nx, ny = self._resolve_collisions(nx, ny)
        self.place(x=nx, y=ny)

    def _on_release(self, e):
        self.itemconfigure(self._bg_id, outline="white")
        try:
            if self.winfo_manager():
                self._mirror_place = (self.winfo_x(), self.winfo_y())
        except tk.TclError:
            pass

    def _resolve_collisions(self, nx, ny):
        for other in DraggableCard._all_cards:
            if other is self:
                continue
            try:
                if not other.winfo_manager():
                    continue
            except tk.TclError:
                continue
            ox, oy, ow, oh = other.winfo_x(), other.winfo_y(), other.card_w, other.card_h
            if (nx < ox+ow+WIDGET_PAD and nx+self.card_w+WIDGET_PAD > ox and
                    ny < oy+oh+WIDGET_PAD and ny+self.card_h+WIDGET_PAD > oy):
                pl = (nx+self.card_w+WIDGET_PAD) - ox
                pr = (ox+ow+WIDGET_PAD) - nx
                pu = (ny+self.card_h+WIDGET_PAD) - oy
                pd = (oy+oh+WIDGET_PAD) - ny
                m  = min(pl, pr, pu, pd)
                if m == pl: nx = ox - self.card_w - WIDGET_PAD
                elif m == pr: nx = ox + ow + WIDGET_PAD
                elif m == pu: ny = oy - self.card_h - WIDGET_PAD
                else:         ny = oy + oh + WIDGET_PAD
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        return (max(WIDGET_PAD, min(pw-self.card_w-WIDGET_PAD, nx)),
                max(WIDGET_PAD, min(ph-self.card_h-WIDGET_PAD, ny)))

# ─────────────────────────────────────────────
# WIDGETS
# ─────────────────────────────────────────────
class DateTimeWeatherCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=80, title="")
        self._line = self.create_text(240, 40, text="...", fill=FG_COLOR,
                                      font=FONT_BODY, anchor="center")
        self.place(x=x, y=y)
        self._tick()
        self._sched_weather()

    def _tick(self):
        now = datetime.now()
        self.itemconfig(self._line, text=(
            f"{now.strftime('%a, %b %d')}   |   "
            f"{now.strftime('%I:%M:%S %p').lstrip('0')}   |   {_weather_cache}"
        ))
        self.after(CLOCK_REFRESH_MS, self._tick)

    def _sched_weather(self):
        bg(fetch_weather)
        self.after(WEATHER_REFRESH_MS, self._sched_weather)


class NewsCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0
        self._src_id = self.create_text(24, 48,  text="", fill=DIM_COLOR, font=("Arial",11), anchor="nw")
        self._pub_id = self.create_text(24, 66,  text="", fill=DIM_COLOR, font=("Arial",11), anchor="nw")
        self._hdl_id = self.create_text(24, 90,  text="Loading...", fill=FG_COLOR,
                                        font=("Arial",14,"bold"), anchor="nw", width=440)
        self.place(x=x, y=y)
        self._cycle()
        self._sched_news()

    def _sched_news(self):
        bg(fetch_news)
        self.after(NEWS_REFRESH_MS, self._sched_news)

    def _cycle(self):
        if _news_cache:
            self._idx %= len(_news_cache)
            item = _news_cache[self._idx]
            self.itemconfig(self._src_id, text=item["source"])
            self.itemconfig(self._pub_id, text=item["pub"])
            self.itemconfig(self._hdl_id, text=item["title"])
            self._idx += 1
        self.after(NEWS_CYCLE_MS, self._cycle)


class StocksCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=360, height=155, title="Stocks")
        self._line_ids = []
        for i in range(len(_stock_cache)):
            tid = self.create_text(20, 48 + i*34, text="Loading...",
                                   fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=320)
            self._line_ids.append(tid)
        self.place(x=x, y=y)
        self._sched_stocks()

    def _sched_stocks(self):
        bg(fetch_stocks)
        self.after(500, self._apply)
        self.after(STOCK_REFRESH_MS, self._sched_stocks)

    def apply_cache_to_canvas(self):
        self._apply()

    def _apply(self):
        for i, tid in enumerate(self._line_ids):
            txt = _stock_cache[i] if i < len(_stock_cache) else "N/A"
            color = "#34c759" if "▲" in txt else ("#ff453a" if "▼" in txt else FG_COLOR)
            self.itemconfig(tid, text=txt, fill=color)
        if any("Loading" in s for s in _stock_cache):
            self.after(2000, self._apply)

    def resync_lines(self):
        from voicecontrol import STOCK_SYMBOLS
        n = len(STOCK_SYMBOLS)
        while len(self._line_ids) < n:
            tid = self.create_text(20, 48 + len(self._line_ids)*34, text="Loading...",
                                   fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=320)
            self._line_ids.append(tid)
        while len(self._line_ids) > n:
            self.delete(self._line_ids.pop())
        for i, tid in enumerate(self._line_ids):
            self.coords(tid, 20, 48 + i*34)


class TodoCard(DraggableCard):
    def __init__(self, parent, x, y, max_h):
        h = min(72 + TODO_MAX_VISIBLE * TODO_LINE_HEIGHT + 36, max_h - 120)
        super().__init__(parent, width=TODO_CARD_WIDTH, height=int(h), title="To-do")
        self._row_ids = []
        self.place(x=x, y=y)
        self.refresh_list()

    def refresh_list(self):
        for rid in self._row_ids:
            try: self.delete(rid)
            except tk.TclError: pass
        self._row_ids.clear()
        y0    = 48
        tasks = _todo_tasks[:TODO_MAX_VISIBLE]
        if not tasks:
            self._row_ids.append(self.create_text(
                24, y0, text="No tasks – ask the mirror to add one",
                fill=DIM_COLOR, font=FONT_COMPACT, anchor="nw", width=TODO_CARD_WIDTH-40))
        else:
            for t in tasks:
                self._row_ids.append(self.create_text(
                    24, y0, text=f"• {t['text']}",
                    fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=TODO_CARD_WIDTH-40))
                y0 += TODO_LINE_HEIGHT
            ov = len(_todo_tasks) - TODO_MAX_VISIBLE
            if ov > 0:
                self._row_ids.append(self.create_text(
                    24, y0, text=f"+ {ov} more",
                    fill=DIM_COLOR, font=("Arial",11), anchor="nw"))


class AIResponseCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=520, height=220, title="AI")
        self._text_id = self.create_text(260, 110, text="", fill=FG_COLOR,
                                         font=FONT_BODY, anchor="center", width=470, justify="center")
        self.place(x=x, y=y)
        self._poll()

    def _poll(self):
        from voicecontrol import _ai_state, _ai_text
        while not _ui_queue.empty():
            state, text = _ui_queue.get_nowait()
            # Update the module-level state
            import voicecontrol
            voicecontrol._ai_state = state
            voicecontrol._ai_text = text
            
        if _ai_state == "idle":
            self.coords(self._text_id, 260, 110)
            self.itemconfig(self._text_id, text="", anchor="center", justify="center")
        elif _ai_state in ("listening", "thinking"):
            self.coords(self._text_id, 260, 110)
            self.itemconfig(self._text_id, text=_ai_text, anchor="center", justify="center")
        else:  # response / error
            self.coords(self._text_id, 20, 52)
            self.itemconfig(self._text_id, text=_ai_text, anchor="nw", justify="left")
        self.after(150, self._poll)

# ─────────────────────────────────────────────
# UI OVERLAY LOOP
# ─────────────────────────────────────────────
def ui_overlay_loop():
    """Main-thread loop: renders countdown without flooding Tk."""
    global _ily_label
    if _root_ref is None:
        return
    
    ily_remaining = handcontrol.get_ily_remaining()
        
    if ily_remaining <= 0: 
        if _ily_label is not None: 
            #remove label from screen completely 
            _ily_label.destroy()
            #reset to none so it can be recreated fresh next time
            _ily_label = None
    else:
        # ILY countdown label
        if _ily_label is None:
            _ily_label = tk.Label(
                _root_ref, text="", fg="white", bg="#1c1c1e",
                font=("Arial", 14, "bold"), padx=12, pady=8,
            )
            y = 10
            widget_refs = _get_widget_refs()
            dtw = widget_refs.get("datetime")
            if dtw is not None:
                try:
                    y = dtw.winfo_y() + dtw.card_h + 10
                except Exception:
                    y = 95
            _ily_label.place(x=10, y=y)
        
        action = "off" if handcontrol.is_tracking_enabled() else "on"
        _ily_label.config(text=f"Cursor {action} in {ily_remaining:.1f}s")
     
    # ~10 FPS UI overlay updates (lightweight)
    _root_ref.after(33, ui_overlay_loop)

def set_root_ref(root):
    """Set reference to root window."""
    global _root_ref
    _root_ref = root
    handcontrol.set_root_ref(root)

def set_widget_refs(refs):
    """Set reference to widget dictionary."""
    # Import here to avoid circular import at module level
    import voicecontrol
    voicecontrol._widget_refs = refs

def _get_widget_refs():
    """Get reference to widget dictionary."""
    import voicecontrol
    return voicecontrol._widget_refs

def set_stock_card_ref(card):
    """Set reference to stock card."""
    global _stock_card_ref
    _stock_card_ref = card
    import voicecontrol
    voicecontrol._stock_card_ref = card

def set_todo_card_ref(card):
    """Set reference to todo card."""
    global _todo_card_ref
    _todo_card_ref = card
    import voicecontrol
    voicecontrol._todo_card_ref = card
