import time
from gpiozero import MotionSensor, LED

# --- Configuration ---
PIR_PIN = 2
LED_PIN = 17
TIMEOUT = 10
COOLDOWN = 3

# --- Setup ---
pir = MotionSensor(PIR_PIN, threshold=0.5, queue_len=5)
led = LED(LED_PIN)

last_motion   = 0
last_off_time = 0
led_is_on     = False

try:
    led.off()
    print("Waiting for motion... stand still or leave the room")

    while True:
        now        = time.time()
        motion     = pir.motion_detected
        time_since = round(now - last_motion, 1)

        print(f"  motion_detected={motion} | led_on={led_is_on} | time_since_motion={time_since}s")

        if motion:
            if now - last_off_time > COOLDOWN:
                last_motion = now
                if not led_is_on:
                    led.on()
                    led_is_on = True
                    print("[LED] On")

        elif led_is_on and time_since > TIMEOUT:
            led.off()
            led_is_on     = False
            last_off_time = now
            print("[LED] Off")

        time.sleep(0.3)

except KeyboardInterrupt:
    led.off()
    print("Exiting cleanly")



Traceback (most recent call last):
  File "/home/group6/hand_mouse/led_strip.py", line 11, in <module>
    pir = MotionSensor(PIR_PIN, threshold=0.5, queue_len=5)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/devices.py", line 108, in __call__
    self = super().__call__(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/input_devices.py", line 588, in __init__
    super().__init__(
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/input_devices.py", line 257, in __init__
    super().__init__(
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/mixins.py", line 243, in __init__
    super().__init__(*args, **kwargs)
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/input_devices.py", line 84, in __init__
    self.pin.pull = pull
    ^^^^^^^^^^^^^
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/pins/__init__.py", line 357, in <lambda>
    lambda self, value: self._set_pull(value),
                        ^^^^^^^^^^^^^^^^^^^^^
  File "/home/group6/myenv311/lib/python3.11/site-packages/gpiozero/pins/lgpio.py", line 186, in _set_pull
    raise PinFixedPull(
gpiozero.exc.PinFixedPull: GPIO2 has a physical pull-up resistor

