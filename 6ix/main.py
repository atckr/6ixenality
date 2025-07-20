"""
Runs the Pi camera viewfinder by default, captures a screenshot on
button-A presses, logs button-B touches with pressure & timestamps, and
sends all collected context (environment + image + interaction log) to
a Gemini-api to predict MBTI when button C is pressed.

The Gemini response is expected in the format:
    "INTJ, D4 F4 A4 C5"
where the leading 4-letter code is the MBTI type and the trailing notes
form a chord.  The MBTI code is shown on the alphanumeric display and the
chord is played on the Rainbow HAT buzzer.
"""

import base64
import os
import signal
import subprocess
import threading
import time
import convertapi
from datetime import datetime
from typing import List, Tuple

import requests  # Needs to be available in your QNX Python build
from dotenv import load_dotenv

import rainbowhat  # QNX-adapted Rainbow HAT driver

try:
    import gpio_rpi.gpio as GPIO

    GPIO.cleanup()
except Exception as e:
    print("[WARN] Couldn't clean up GPIO:", e)

load_dotenv()  # Loads from .env by default

gemini_key = os.environ["GEMINI_API_KEY"]
convert_key = os.environ["CONVERT_API_KEY"]

# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
VIEWFINDER_CMD = "camera_example3_viewfinder"
SCREENSHOT_CMD = "screenshot"  # Should output screenshot.bmp in CWD
SCREENSHOT_FILE = "screenshot.bmp"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"  # adjust if needed
GEMINI_API_KEY_ENV = gemini_key

# Mapping from note names (C4, D#4, etc.) to frequencies (Hz)
NOTE_FREQ = {
    "A": 220.0,
    "A#": 233.08,
    "B": 246.94,
    "C": 261.63,
    "C#": 277.18,
    "D": 293.66,
    "D#": 311.13,
    "E": 329.63,
    "F": 349.23,
    "F#": 369.99,
    "G": 392.0,
    "G#": 415.3,
    "C4": 261,
    "C#4": 277,
    "D4": 294,
    "D#4": 311,
    "E4": 329,
    "F4": 349,
    "F#4": 370,
    "G4": 392,
    "G#4": 415,
    "A4": 440,
    "A#4": 466,
    "B4": 493,
    "C5": 523,
    "C#5": 554,
    "D5": 587,
    "D#5": 622,
    "E5": 659,
    "F5": 698,
    "F#5": 740,
    "G5": 784,
    "G#5": 830,
    "A5": 880,
    "A#5": 932,
    "B5": 988,
}
BUZZER_NOTE_MS = 666  # duration for each note in ms

# ──────────────────────────────────────────────────────────────────────────────
#  GLOBAL STATE
# ──────────────────────────────────────────────────────────────────────────────
viewfinder_proc: subprocess.Popen | None = None

current_temp: float | None = None
current_pressure_hpa: float | None = None
current_altitude_m: float | None = None

touch_log: List[Tuple[str, float]] = []  # list of (ISO8601 timestamp, pressure_hpa)

action_lock = threading.Lock()  # prevents overlapping C-button actions
loading_stop = threading.Event()  # signals the LED loading animation to stop


# ──────────────────────────────────────────────────────────────────────────────
#  UTILITIES
# ──────────────────────────────────────────────────────────────────────────────


def start_viewfinder():
    global viewfinder_proc
    if viewfinder_proc is None or viewfinder_proc.poll() is not None:
        try:
            viewfinder_proc = subprocess.Popen([VIEWFINDER_CMD])
            print("[INFO] Viewfinder started.")
        except FileNotFoundError:
            print(f"[ERROR] Viewfinder command not found: {VIEWFINDER_CMD}")
        except Exception as exc:
            print(f"[ERROR] Failed to start viewfinder: {exc}")


def start_screenshot():
    global screenshot_proc
    try:
        screenshot_proc = subprocess.Popen([SCREENSHOT_CMD])
        print(f"[INFO] Screenshot started: {SCREENSHOT_FILE}")
    except FileNotFoundError:
        print(f"[ERROR] Screenshot command not found: {SCREENSHOT_CMD}")
    except Exception as exc:
        print(f"[ERROR] Failed to start screenshot: {exc}")


def stop_process(proc, name, timeout=3):
    if proc and proc.poll() is None:
        try:
            proc.send_signal(signal.SIGTERM)
            threading.Timer(
                timeout, lambda: proc.kill() if proc.poll() is None else None
            ).start()
            print(
                f"[INFO] Sent SIGTERM to {name}. Will force-kill in {timeout}s if needed."
            )
        except Exception as e:
            print(f"[ERROR] Could not stop {name}: {e}")


def update_environment_readings() -> None:
    """Read temperature & pressure from Rainbow HAT and derive altitude."""
    global current_temp, current_pressure_hpa, current_altitude_m

    try:
        # Rainbow HAT sensor reads too high; divide by 2.5 as user discovered
        current_temp = rainbowhat.weather.temperature() / 2.5
        current_pressure_hpa = rainbowhat.weather.pressure() / 2.5

        # Altitude estimation via barometric formula (simplified ISA)
        # altitude = 44330 * (1 - (P / P0)^(1/5.255))
        P0 = 1013.25  # mean sea-level pressure in hPa
        current_altitude_m = 44330.0 * (
            1.0 - (current_pressure_hpa / P0) ** (1 / 5.255)
        )

        print(
            f"[ENV] T={current_temp:.1f}°C  P={current_pressure_hpa:.1f}hPa  Alt={current_altitude_m:.1f}m"
        )
    except Exception as exc:
        print(f"[ERROR] Failed to read environment sensors: {exc}")


def start_led_loading() -> None:
    """Animate LEDs in a rotating pattern until loading_stop is set."""

    def _worker():
        idx = 0
        while not loading_stop.is_set():
            for i in range(7):
                if i == idx:
                    rainbowhat.rainbow.set_pixel(i, 0, 0, 100)
                else:
                    rainbowhat.rainbow.set_pixel(i, 0, 0, 0)
            rainbowhat.rainbow.show()
            idx = (idx + 1) % 7
            time.sleep(0.1)
        rainbowhat.rainbow.set_all(0, 0, 0)
        rainbowhat.rainbow.show()

    loading_stop.clear()
    threading.Thread(target=_worker, daemon=True).start()


def stop_led_loading() -> None:
    loading_stop.set()


def play_chord(chord_str: str) -> None:
    """Play a 4-note chord on the buzzer sequentially."""
    notes = chord_str.replace(",", " ").split()
    for note in notes:
        freq = NOTE_FREQ.get(note.strip().upper())
        if freq:
            rainbowhat.buzzer.note(freq, BUZZER_NOTE_MS / 1000.0)
            time.sleep(0.6)  # tiny gap
    # rainbowhat.buzzer.note(0, 0)


def convert_bmp_to_jpg_online(bmp_path: str, jpg_path: str, secret: str) -> str:
    # convert_url = f"https://v2.convertapi.com/convert/bmp/to/jpg?Secret={secret}"
    convertapi.api_credentials = os.environ["CONVERT_API_KEY"]
    convertapi.convert("jpg", {"File": "screenshot.bmp"}, from_format="bmp").save_files(
        "screenshot.jpg"
    )

    print("[INFO] JPG saved to", jpg_path)
    return jpg_path


def send_jpg_to_gemini_with_prompt(jpg_path, temperature, altitude, pressure, touches):
    """Sends a JPEG + structured prompt to Gemini and returns MBTI + chord."""

    gemini_api_key = os.environ["GEMINI_API_KEY"]
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key}"

    # Base64 encode the JPEG
    with open(jpg_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Build the structured prompt
    touch_str = "\n".join([f"- Time: {t[0]} ms, Pressure: {t[1]} Pa" for t in touches])
    prompt_text = f"""
        Given temperature, altitude, pressure, list of touches (chosen number of touches, timing & pressure), and an embedded image of the user, answer the following in the exact format 'MBTI, note1 note2 note3 note4' where MBTI is exactly 4 characters of the predicted personality and note1 note2 note3 note4 makes up a chord that user will likely enjoy from the information we learn about how user interacted with the environment. This means, the output will be of a format "one string of 4 characters, 4 notes". Do NOT include any other extra information that might break the format. Extra information is of below and user's pose, style, expression can be learnt from the embedded image.
        Temperature: {temperature}°C
        Altitude: {altitude} m
        Pressure: {pressure} hPa
        Number of touches: {len(touches)}
        Touches: {touch_str}
Some suggested questions to determine personality: 1. When in a stimulating or chaotic environment (e.g., high altitude and cold), do you appear energized and expressive in your pose or gestures?
E – outward focus and energy
2. Does your button press pattern show immediate engagement with minimal hesitation?
E – impulsivity and outward initiative
3. In high-pressure settings, do you exhibit stillness, inward posture, or lack of engagement?
I – reserved nature under external demand
4. Is your response to the button task delayed but consistent, suggesting internal reflection before action?
I – inward processing
5. Is your clothing well-suited to environmental conditions (e.g., warm gear in cold settings), suggesting attention to concrete realities?
S – practicality and awareness
6. Do your touch timings show a consistent pattern, adapted to small sensory cues (e.g., temperature shifts)?
S – real-time sensory feedback
7. Does your outfit prioritize visual impact or style over practicality (e.g., light clothing in cold), suggesting abstract or conceptual focus?
N – symbolic thinking or future orientation
8. Do your button presses form a symbolic or patterned rhythm, not directly linked to environmental demands?
N – internal pattern generation or imaginative play
9. In high-pressure conditions, does your posture remain efficient or controlled, minimizing expressive movement?
T – focus on function and outcome
10. Is your button interaction steady and deliberate regardless of pressure, prioritizing task success?
T – logic-based consistency
11. Do you maintain expressive or open body language despite environmental discomfort?
F – value alignment or emotional expression
12. Does your button touch pattern change under discomfort (e.g., delayed or erratic presses when cold), suggesting emotional influence?
F – emotionally driven reactions
13. Is your outfit neat and coordinated, possibly indicating pre-planned self-presentation?
J – structure, preparedness
14. Do you exhibit an evenly spaced button press pattern with clear start and stop?
J – planned and organized execution
15. Does your clothing or hairstyle seem improvised or weather-inappropriate but expressive?
P – spontaneity or prioritizing comfort/flexibility
16. Is your touch behavior erratic or exploratory, with no clear pattern in timing or count?
P – openness to momentary choice
        """

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text.strip()},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                ]
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
    }
    response = requests.post(gemini_url, headers=headers, json=payload)
    response.raise_for_status()

    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


def screenshot_bmp_to_gemini_response(
    bmp_path, temperature, altitude, pressure, touches
):
    jpg_path = "screenshot.jpg"
    convert_bmp_to_jpg_online(bmp_path, jpg_path, convert_key)
    return send_jpg_to_gemini_with_prompt(
        jpg_path, temperature, altitude, pressure, touches
    )


def send_to_gemini() -> None:
    global current_temp, current_pressure_hpa, current_altitude_m, touch_log
    """Send collected data + image to Gemini asynchronously."""
    with action_lock:
        start_led_loading()
        result = screenshot_bmp_to_gemini_response(
            bmp_path="screenshot.bmp",
            temperature=current_temp,
            altitude=current_altitude_m,
            pressure=current_pressure_hpa,
            touches=touch_log,
        )
        stop_led_loading()
        time.sleep(0.6)  # tiny gap

        print(f"result = {result}")
        try:
            mbti, chord = result.split(",")
            mbti = mbti.strip().upper()[:4]
            chord = chord.strip()
        except ValueError:
            print("[ERROR] Gemini response not in expected format.")
            return

        # Display MBTI on 14-segment display
        rainbowhat.display.clear()
        rainbowhat.display.print_str(mbti[:4].ljust(4))
        rainbowhat.display.show()

        # Play chord on buzzer
        play_chord(chord)

        # Clear state
        touch_log.clear()
        print("[INFO] State cleared; system ready.")


# ──────────────────────────────────────────────────────────────────────────────
#  BUTTON EVENT HANDLERS
# ──────────────────────────────────────────────────────────────────────────────


@rainbowhat.touch.A.press()
def on_a_press(_):
    rainbowhat.display.clear()
    stop_led_loading()
    rainbowhat.lights.rgb(1, 0, 0)
    start_viewfinder()
    start_screenshot()


@rainbowhat.touch.A.release()
def on_a_release(_):
    rainbowhat.lights.rgb(0, 0, 0)
    stop_process(screenshot_proc, SCREENSHOT_CMD)
    stop_process(viewfinder_proc, VIEWFINDER_CMD)
    update_environment_readings()


@rainbowhat.touch.B.press()
def on_b_press(_):
    ts = datetime.utcnow().isoformat() + "Z"
    pressure = rainbowhat.weather.pressure() / 2.5  # immediate read
    touch_log.append((ts, pressure))
    rainbowhat.lights.rgb(0, 1, 0)


@rainbowhat.touch.B.release()
def on_b_release(_):
    rainbowhat.lights.rgb(0, 0, 0)


@rainbowhat.touch.C.press()
def on_c_press(_):
    rainbowhat.lights.rgb(0, 0, 1)
    threading.Thread(target=send_to_gemini, daemon=True).start()


@rainbowhat.touch.C.release()
def on_c_release(_):
    rainbowhat.lights.rgb(0, 0, 0)


# ──────────────────────────────────────────────────────────────────────────────
#  CLEANUP & MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────


def cleanup():
    try:
        if viewfinder_proc and viewfinder_proc.poll() is None:
            viewfinder_proc.terminate()
    except Exception:
        pass
    rainbowhat.touch.cleanup()
    rainbowhat.rainbow.set_all(0, 0, 0)
    rainbowhat.rainbow.show()
    rainbowhat.display.clear()
    rainbowhat.display.show()
    rainbowhat.buzzer.note(0, 0)
    print("[INFO] Clean exit.")


def main():
    signal.signal(signal.SIGINT, lambda *_: cleanup() or exit(0))
    signal.signal(signal.SIGTERM, lambda *_: cleanup() or exit(0))
    print("[INFO] System ready – press buttons on Rainbow HAT.")
    rainbowhat.display.clear()
    rainbowhat.display.print_str("6666")
    rainbowhat.display.show()
    signal.pause()


if __name__ == "__main__":
    main()
