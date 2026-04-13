pip install rpi_ws281x adafruit-circuitpython-neopixel 

import time
import board
import neopixel

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    import Mock.GPIO as GPIO

# --- Configuration ---
PIR_PIN      = 2       # GPIO pin for PIR signal
LED_PIN      = board.D18  # GPIO 18 is required for WS2812B
NUM_LEDS     = 30      # change to however many LEDs your strip has
BRIGHTNESS   = 1.0     # full brightness (0.0 to 1.0)
DIM_LEVEL    = 0.1     # brightness after timeout
TIMEOUT      = 60      # seconds before dimming
COLOR        = (255, 200, 150)  # warm white — change as you like

# --- Setup ---
pixels = neopixel.NeoPixel(LED_PIN, NUM_LEDS, brightness=BRIGHTNESS, auto_write=True)

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIR_PIN, GPIO.IN)

def strip_on():
    pixels.brightness = BRIGHTNESS
    pixels.fill(COLOR)
    print("[STRIP] Full brightness")

def strip_dim():
    pixels.brightness = DIM_LEVEL
    pixels.fill(COLOR)
    print("[STRIP] Dimmed")

def strip_off():
    pixels.fill((0, 0, 0))
    print("[STRIP] Off")

# --- Main loop ---
last_motion = 0
dimmed = False

try:
    strip_off()  # start with strip off
    print("Waiting for motion...")

    while True:
        if GPIO.input(PIR_PIN):
            strip_on()
            last_motion = time.time()
            dimmed = False

        elif not dimmed and time.time() - last_motion > TIMEOUT:
            strip_dim()
            dimmed = True

        time.sleep(0.5)

except KeyboardInterrupt:
    strip_off()
    GPIO.cleanup()
