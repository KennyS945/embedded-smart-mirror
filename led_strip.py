pip install lgpio gpiozero rpi_ws281x adafruit-circuitpython-neopixel
import time
import board
import neopixel
from gpiozero import MotionSensor

# --- Configuration ---
PIR_PIN  = 2           # GPIO 2 for PIR signal
LED_PIN  = board.D18   # GPIO 18 required for WS2812B
NUM_LEDS = 30          # change to your actual LED count
COLOR    = (255, 200, 150)  # warm white — change to any RGB value
TIMEOUT  = 10          # seconds of no motion before strip turns off

# --- Setup ---
pir    = MotionSensor(PIR_PIN)
pixels = neopixel.NeoPixel(LED_PIN, NUM_LEDS, brightness=1.0, auto_write=True)

def strip_on():
    pixels.fill(COLOR)
    print("[STRIP] On")

def strip_off():
    pixels.fill((0, 0, 0))
    print("[STRIP] Off")

# --- Main loop ---
last_motion = 0
strip_is_on = False

try:
    strip_off()
    print("Waiting for motion...")

    while True:
        if pir.motion_detected:
            last_motion = time.time()
            if not strip_is_on:
                strip_on()
                strip_is_on = True

        elif strip_is_on and time.time() - last_motion > TIMEOUT:
            strip_off()
            strip_is_on = False

        time.sleep(0.3)

except KeyboardInterrupt:
    strip_off()
    print("Exiting cleanly")
