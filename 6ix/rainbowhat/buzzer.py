"""Rainbow HAT Piezo Buzzer."""
from threading import Timer

try:
    import rpi_gpio as GPIO
except ImportError:
    raise ImportError("""This library requires the QNX rpi_gpio module.""")

BUZZER = 13

_timeout = None

_is_setup = False

pwm = None


def setup():
    """Set up the piezo buzzer."""
    global _is_setup, pwm

    if _is_setup:
        return

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUZZER, GPIO.OUT)

    pwm = GPIO.PWM(BUZZER, 50, mode = GPIO.PWM.MODE_PWM)
    pwm.start(1)
    _is_setup = True


def note(frequency, duration=1.0):
    """Play a single note.

    :param frequency: Musical frequency in hertz
    :param duration: Optional duration in seconds, use None to sustain note

    """
    global _timeout

    setup()

    if frequency is None:
        frequency = 100 #The library diesn't like low values here, aka 1

    if frequency <= 0:
        raise ValueError("Frequency must be > 0")

    if duration is not None and duration <= 0:
        raise ValueError("Duration must be > 0")

    clear_timeout()

    pwm.ChangeFrequency(frequency)

    if duration is not None and duration > 0:
        _timeout = Timer(duration, stop)
        _timeout.start()


def midi_note(note_number, duration=1.0):
    """Play a single note by MIDI note number.

    Converts a MIDI note number into a frequency and plays it. A5 is 69.

    :param note_number: MIDI note number of note
    :param duration: Optional duration in seconds, use None to sustain note

    """
    freq = (2 ** ((note_number - 69.0) / 12)) * 440

    note(freq, duration)


def clear_timeout():
    """Clear any note timeout set.

    Will cause any pending playing note to be sustained.

    """
    global _timeout

    if _timeout is not None:
        _timeout.cancel()
        _timeout = None


def stop():
    """Stop buzzer.

    Immediately silences the buzzer.

    """
    clear_timeout()

    GPIO.setup(BUZZER, GPIO.IN)

