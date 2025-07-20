__version__ = '0.1.0q'

from . import apa102
from .bmp280 import bmp280
from .alphanum4 import AlphaNum4
from .touch import Buttons
from .lights import Lights
from . import buzzer
import rpi_gpio as GPIO
import smbus

bus = smbus.SMBus(1) # for Raspberry Pi 4 w/ QNX

display = AlphaNum4(i2c=bus)
touch = Buttons
lights = Lights
weather = bmp280(bus)
rainbow = apa102
