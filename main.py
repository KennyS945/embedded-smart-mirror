import os
import signal
import sys
import threading
import tkinter as tk

# Import all modules
import voicecontrol
import handcontrol
import widgets

def close_app(event=None):
    """Close the application."""
    voicecontrol._running = False
    handcontrol.set_running(False)
    if widgets._root_ref:
        try: widgets._root_ref.quit(); widgets._root_ref.destroy()
        except Exception: pass

def _handle_signal(sig, frame):
    """Handle SIGINT signal."""
    close_app()
    sys.exit(0)

def main():
    """Main entry point for the Smart Mirror application."""
    # Load todos on startup
    voicecontrol.load_todos()

    # Create root window
    root = tk.Tk()
    root.title("Smart Mirror")
    root.configure(bg=widgets.BG_COLOR)

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.attributes("-fullscreen", True)
    root.bind("<Escape>", close_app)
    root.bind("q",        close_app)
    root.protocol("WM_DELETE_WINDOW", close_app)
    signal.signal(signal.SIGINT, _handle_signal)

    # Set root references for widgets and hand control
    widgets.set_root_ref(root)

    # Create canvas frame
    canvas = tk.Frame(root, bg=widgets.BG_COLOR)
    canvas.pack(fill="both", expand=True)

    # Layout – sensible defaults for a 1920×1080 or similar Pi display
    todo_h = min(72 + widgets.TODO_MAX_VISIBLE * widgets.TODO_LINE_HEIGHT + 36, sh - 120)
    todo_y = max(widgets.WIDGET_PAD, (sh - int(todo_h)) // 2)

    # Create all widget cards
    dtw_card   = widgets.DateTimeWeatherCard(canvas, x=10,  y=10)
    news_card  = widgets.NewsCard(canvas,            x=510, y=10)
    stock_card = widgets.StocksCard(canvas,          x=10,  y=sh - 175)
    todo_card  = widgets.TodoCard(canvas,            x=widgets.WIDGET_PAD, y=todo_y, max_h=sh)
    ai_card    = widgets.AIResponseCard(canvas,      x=sw - 540,   y=sh - 240)

    # Set widget references
    widgets.set_stock_card_ref(stock_card)
    widgets.set_todo_card_ref(todo_card)
    widget_refs = {
        "datetime": dtw_card, "news": news_card,
        "stocks": stock_card, "ai": ai_card, "todo": todo_card,
    }
    widgets.set_widget_refs(widget_refs)

    # Start UI overlay loop (cursor + countdown)
    root.after(33, widgets.ui_overlay_loop)

    # Initial data fetch
    voicecontrol.bg(voicecontrol.fetch_weather)
    voicecontrol.bg(voicecontrol.fetch_news)

    # Background threads
    threading.Thread(target=voicecontrol.voice_loop,         daemon=True).start()
    threading.Thread(target=handcontrol.hand_tracking_loop, daemon=True).start()

    # Run main loop
    root.mainloop()


if __name__ == "__main__":
    main()
