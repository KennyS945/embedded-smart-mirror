import time
import board
import neopixel
import RPi.GPIO as GPIO


PIR_PIN = 17                  # BCM numbering
LED_PIN = board.D18           # WS2812B data pin
NUM_PIXELS = 60               # Strip Length
BRIGHTNESS = 1.0              # 0.0 to 1.0
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

WHITE = (255, 255, 255)
OFF = (0, 0, 0)


GPIO.setmode(GPIO.BCM)
GPIO.setup(PIR_PIN, GPIO.IN)

pixels = neopixel.NeoPixel(
    LED_PIN,
    NUM_PIXELS,
    brightness=BRIGHTNESS,
    auto_write=False
)

def set_strip(color):
    pixels.fill(color)
    pixels.show()

def motion_detected():
    return GPIO.input(PIR_PIN) == GPIO.HIGH

try:
    print("System started. Waiting for motion...")

    # Make sure strip starts off
    set_strip(OFF)

    while True:
        # Wait until motion is first detected
        if motion_detected():
            print("Motion detected -> LEDs ON")
            set_strip(WHITE)

            # Keep lights on and check every 5 minutes
            while True:
                time.sleep(CHECK_INTERVAL_SECONDS)

                if motion_detected():
                    print("Still detecting motion -> keep LEDs ON for another 5 minutes")
                    set_strip(WHITE)
                else:
                    print("No motion detected -> LEDs OFF")
                    set_strip(OFF)
                    break

        time.sleep(0.2)

except KeyboardInterrupt:
    print("Stopping...")

finally:
    set_strip(OFF)
    GPIO.cleanup()