import time
import board
import neopixel
from gpiozero import MotionSensor

# --- Configuration ---
PIR_PIN    = 2
LED_PIN    = board.D18
NUM_LEDS   = 30
COLOR      = (255, 200, 150)
TIMEOUT    = 10       # seconds of no motion before turning off
COOLDOWN   = 3        # seconds to ignore retriggering after strip turns off

# --- Setup ---
pir    = MotionSensor(PIR_PIN, threshold=0.5, queue_len=5)
pixels = neopixel.NeoPixel(LED_PIN, NUM_LEDS, brightness=1.0, auto_write=True)

def strip_on():
    pixels.fill(COLOR)
    print("[STRIP] On")

def strip_off():
    pixels.fill((0, 0, 0))
    print("[STRIP] Off")

# --- Main loop ---
last_motion   = 0
last_off_time = 0
strip_is_on   = False

try:
    strip_off()
    print("Waiting for motion...")

    while True:
        now = time.time()

        if pir.motion_detected:
            # ignore triggers during cooldown period
            if now - last_off_time > COOLDOWN:
                last_motion = now
                if not strip_is_on:
                    strip_on()
                    strip_is_on = True

        elif strip_is_on and now - last_motion > TIMEOUT:
            strip_off()
            strip_is_on  = False
            last_off_time = now

        time.sleep(0.3)

except KeyboardInterrupt:
    strip_off()
    print("Exiting cleanly")
