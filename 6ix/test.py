import rainbowhat
import time
import atexit
import signal

TIMEOUT = 5 # Timeout in seconds, for the final loop

d = 294
e = 329
f = 349
g = 392
a = 440
b = 493
c = 523

colors = [
    [100,0,0, "Red"],
    [0,100,0, "Green"],
    [0,0,100, "Blue"],
    [100,100,100, "White"],
    [0,0,0, "Off"]
]

# Set up button event handlers, for A/B/C touch pads
# this section links a press on button A
# to what to do when it happens
@rainbowhat.touch.A.press()
def touch_a(channel):
    rainbowhat.lights.rgb(1, 0, 0)

@rainbowhat.touch.B.press()
def touch_b(channel):
    rainbowhat.lights.rgb(0, 1, 0)

@rainbowhat.touch.C.press()
def touch_c(channel):
    rainbowhat.lights.rgb(0, 0, 1)

# this section links a letting go of any button
# to what to do when it happens
@rainbowhat.touch.release()
def release(channel):
    rainbowhat.lights.rgb(0, 0, 0)

# waits until a signal is received
signal.pause()

# Helper function to simplify alphanum text display
def showString(text):
   rainbowhat.display.clear()
   rainbowhat.display.print_str(text)
   rainbowhat.display.show()

# Display a string, a number, and scrolling text on the 14-char alphanum display
print("---- Testing 14-segment display!")
showString("Test")
time.sleep(1.0)
rainbowhat.display.print_float(-1.23)
rainbowhat.display.show()
time.sleep(1.0)

msg = "    Hello, world    "
offset = 0
for x in range(len(msg)-4 + 1):
   showString(msg[offset:offset+4])
   offset += 1
   if offset > len(msg) - 4:
      offset = 0
   time.sleep(0.25)


# Play notes on the buzzer. For some reason this doesn't work well.. PWM issue?
print("---- Testing buzzer output!")
showString("Buzz")
for note in [d,e,f,g,a,b,c,None]:
   rainbowhat.buzzer.note(note,1.0)
   time.sleep(0.2)

# Testing BPM280 sensor!
temp = round(rainbowhat.weather.temperature() / 2.5, 1) # Values appear to be 2.5 times bigger, not sure why yet
pres = round(rainbowhat.weather.pressure() / 2.5, 0)
showString("TEMP")
time.sleep(0.75)
rainbowhat.display.clear()
rainbowhat.display.print_number_str(str(temp))
rainbowhat.display.show()
time.sleep(0.75)
showString("PRES")
time.sleep(0.75)
showString(str(pres)[0:4])
time.sleep(0.75)

# Toggle the RGB LEDS
# Note LED 0 is on the right, oddly, like the board printing shows
print("---- Testing the RGB LEDs together!")
showString("RGBs")
rainbowhat.rainbow.set_all(100, 100, 100)
rainbowhat.rainbow.show()
time.sleep(0.5)
rainbowhat.rainbow.set_all(0, 0, 0)
rainbowhat.rainbow.show()

print("---- Testing the RGB LEDs individually!")
for i in range(0, 7):
   showString("RGB" + str(i))
   for color in colors:
      r, g, b, colorname = color
      rainbowhat.rainbow.set_pixel(i, r, g, b)
      rainbowhat.rainbow.show()
      time.sleep(0.1)

# Toggle the lights ON then OFF
# print("---- Testing the three LEDs!")
# showString("LED1")
# rainbowhat.lights.rgb(1, 0, 0)
# time.sleep(0.8)
# showString("LED2")
# rainbowhat.lights.rgb(1, 1, 0)
# time.sleep(0.8)
# showString("LED3")
# rainbowhat.lights.rgb(1, 1, 1)
# time.sleep(0.8)
# rainbowhat.lights.rgb(0, 0, 0)


print("---- Starting main loop for button testing...")
showString("BUT-")

start = time.time()
while True:
   if time.time() - start > TIMEOUT:
      print("---- Timeout! Exiting!")
      showString("BYE ")
      time.sleep(1.0)
      showString("")
      break

