import time
import board
import neopixel
from gpiozero import MotionSensor

# -----------------------------
# Configuration
# -----------------------------
PIR_PIN = 17                  # BCM numbering; PIR OUT -> GPIO17
LED_PIN = board.D18           # NeoPixel data pin
NUM_LEDS = 30                 # change to your strip length
BRIGHTNESS = 1.0
CHECK_INTERVAL = 300          # 5 minutes = 300 seconds

WHITE = (255, 255, 255)
OFF = (0, 0, 0)

# -----------------------------
# Setup
# -----------------------------
pir = MotionSensor(PIR_PIN)
pixels = neopixel.NeoPixel(
    LED_PIN,
    NUM_LEDS,
    brightness=BRIGHTNESS,
    auto_write=False
)

def strip_on():
    pixels.fill(WHITE)
    pixels.show()
    print("[STRIP] White ON")

def strip_off():
    pixels.fill(OFF)
    pixels.show()
    print("[STRIP] OFF")

try:
    strip_off()
    print("Waiting for motion...")

    while True:
        # Wait until motion is first detected
        pir.wait_for_motion()
        print("[PIR] Motion detected")
        strip_on()

        # Keep checking every 5 minutes
        while True:
            time.sleep(CHECK_INTERVAL)

            if pir.motion_detected:
                print("[PIR] Motion still present -> keep lights ON for another 5 minutes")
                strip_on()
            else:
                print("[PIR] No motion -> lights OFF")
                strip_off()
                break

except KeyboardInterrupt:
    print("Exiting...")

finally:
    strip_off()
