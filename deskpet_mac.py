"""
DESKPET for macOS  -  generated from deskpet.py by make_mac.py, do not hand-edit.

UNTESTED ON REAL HARDWARE. The game logic is shared with the Windows build and
is well exercised; the platform layer is not. Two things to expect:

  * Click-through. On Windows the colour key makes transparent areas pass
    clicks to whatever is underneath. macOS transparency does not, so the
    window may swallow clicks across its whole rectangle even where nothing
    is drawn.
  * Tk version. -transparent needs a reasonably modern Tk. Apple's bundled
    Python ships an old one and may show a grey box instead; install Python
    from python.org if so.

X notifications are deliberately absent from this build.
"""


import array
import colorsys
import hashlib
import json
import subprocess
import math
import os
import random
import sys
import threading
import time
import traceback
import wave
import webbrowser
import tkinter as tk
from tkinter import simpledialog, messagebox

# ----------------------------------------------------------------------------
# palette  -  jade creature, warm accents, ink face. everything else stays quiet
# ----------------------------------------------------------------------------
TRANS      = "#FF00FE"      # colour key -> becomes fully transparent + click-through
BODY       = "#7FD1B9"
BODY_DARK  = "#57B49B"
BELLY      = "#DCF4EC"
INK        = "#1E3A34"
BLUSH      = "#F09C9C"
ACCENT     = "#FFD166"      # hearts, zzz, sparkle
EGG        = "#F3EDE2"
EGG_SPOT   = "#CFE6DC"
FOOD       = "#F2845C"

W, H          = 380, 420    # window size
FLOOR_C       = 386         # y inside the canvas where the pet's feet sit
FPS_MS        = 33

# decay: hours for a full 100 -> 0 slide
HUNGER_HOURS  = 5.0
HAPPY_HOURS   = 7.0
ENERGY_HOURS  = 10.0
SLEEP_RESTORE = 0.75        # hours of sleep for a full energy refill
OFFLINE_CAP_H = 12.0        # never punish more than this for being away

HATCH_SECONDS = 90.0
HYGIENE_HOURS = 5.0         # how fast a dirty desktop drags hygiene down
GRIME_TO_SICK = 600.0       # seconds at low hygiene before it falls ill
MAX_MESSES    = 6
STAY_DAYS     = 3.0         # then it announces it has somewhere to be
REVEAL_MAX    = 2.6         # a line is always fully typed out within this
EVO_FLICKER   = 2.6         # seconds of form-flicker before the whiteout
EVO_TOTAL     = 5.6


# ----------------------------------------------------------------------------
def set_dpi_aware():
    """Nothing to do here. macOS handles Retina scaling itself and Tk reports
    points, so canvas coordinates already line up with the screen. On Windows
    this had to negotiate per-monitor DPI awareness."""
    return


_SCREEN = [0, 25, 1440, 860]        # replaced once Tk is up


def measure_screen(root):
    """Usable area with the menu bar and Dock excluded. wm_maxsize is what the
    window manager will actually allow, which is exactly the work area."""
    try:
        mw, mh = root.wm_maxsize()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        mw, mh = min(mw, sw), min(mh, sh)
        top = sh - mh if mh < sh else 25
        _SCREEN[:] = [0, top, mw, top + mh]
    except Exception:
        _SCREEN[:] = [0, 25, root.winfo_screenwidth(),
                      root.winfo_screenheight() - 70]
    return tuple(_SCREEN)


def work_area():
    return tuple(_SCREEN)


def work_area_at(x, y):
    """One screen only. Per-monitor work areas would need pyobjc, and this
    stays dependency-free."""
    return tuple(_SCREEN)


def virtual_screen():
    return tuple(_SCREEN)


def save_path():
    d = os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                     "DeskPet")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "pet.json")


def pick_font(root, names, size):
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
        for n in names:
            if n in fams:
                return (n, size)
    except Exception:
        pass
    return ("Menlo", size)


def clamp(v, a=0.0, b=100.0):
    return max(a, min(b, v))


def ease_out(t):
    return 1 - (1 - t) ** 3


class Spring:
    """Lag + overshoot, so the antenna trails the body instead of welding to it."""
    def __init__(self, k=0.20, damp=0.80):
        self.x = 0.0
        self.v = 0.0
        self.k = k
        self.damp = damp

    def push(self, force):
        self.v += force

    def step(self):
        self.v += -self.k * self.x
        self.v *= self.damp
        self.x += self.v
        return self.x



# X's page title is always "<page> / X", but browsers bolt their own name on
# the end ("- Google Chrome", "and 2 more pages - Microsoft Edge"), so match
# the "/ X" segment anywhere rather than at the end of the string.





# (host, port, use_ssl). Verified August 2026 - providers do change these.
#
# NOT LISTED ON PURPOSE: Outlook.com / Hotmail / Live. Microsoft finished
# switching off basic authentication in March 2026, and app passwords went with
# it, so IMAP there needs a full OAuth flow that this little program has no
# business doing. Forward X's mail to any account below instead.



DEFAULT_CFG = {
    "muted": False,
    "volume": 0.7,
}



def config_dir():
    return os.path.dirname(save_path())


def cfg_path():
    return os.path.join(config_dir(), "config.json")




def load_config():
    c = dict(DEFAULT_CFG)
    try:
        with open(cfg_path(), encoding="utf-8") as f:
            c.update(json.load(f))
    except Exception:
        pass
    return c


def store_config(c):
    try:
        with open(cfg_path(), "w", encoding="utf-8") as f:
            json.dump(c, f, indent=1)
    except Exception:
        pass








# digests, marketing and account mail - not real notifications, so ignored







# ----------------------------------------------------------------------------
# Game Boy style voice
#
# The DMG had two pulse channels (duty 12.5/25/50/75%), a 4-bit wave channel
# and an LFSR noise channel, with stepped 4-bit volume envelopes. Everything
# below is synthesised from scratch to those constraints and written out as
# small WAVs - no samples, no assets, stdlib only.
#
# The cry is seeded from your pet's name, so it's uniquely its own, and the
# stage variants are the same base cry re-pitched and re-timed - which is how
# the Game Boy squeezed a whole bestiary out of a few kilobytes.
# ----------------------------------------------------------------------------
SR = 22050
SFX_VERSION = 3

# macOS ships afplay, so nothing needs installing. Unlike winsound it will
# mix several sounds at once, so speech never has to queue behind a cry.
def afplay(path):
    try:
        return subprocess.Popen(["afplay", path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except Exception:
        return None


def _env(shape, t):
    if shape == "decay":
        a = math.exp(-3.4 * t)
    elif shape == "pluck":
        a = math.exp(-9.0 * t)
    elif shape == "swell":
        a = math.sin(math.pi * t) ** 0.6
    elif shape == "hold":
        a = 1.0 if t < 0.82 else (1.0 - t) / 0.18
    else:
        a = 1.0 - t
    a *= min(1.0, t / 0.02) if t < 0.02 else 1.0     # de-click the attack
    return math.floor(max(0.0, a) * 15) / 15.0        # 4-bit stepped envelope


def tone(dur, f0, f1=None, duty=0.5, shape="decay", noise=0.0,
         nfreq=1800.0, vib=0.0, vrate=18.0, gain=1.0):
    """One pulse-channel segment with an exponential pitch sweep."""
    n = max(1, int(SR * dur))
    f1 = f0 if f1 is None else f1
    out = array.array("f", [0.0]) * n
    phase = 0.0
    npha = 0.0
    lfsr = 0x7FFF
    nval = 1.0
    for i in range(n):
        t = i / n
        f = f0 * (f1 / f0) ** t
        if vib:
            f *= 1.0 + vib * math.sin(2 * math.pi * vrate * i / SR)
        phase = (phase + f / SR) % 1.0
        v = 1.0 if phase < duty else -1.0
        if noise > 0.0:
            npha += nfreq / SR
            while npha >= 1.0:
                npha -= 1.0
                bit = (lfsr ^ (lfsr >> 1)) & 1
                lfsr = (lfsr >> 1) | (bit << 14)
                nval = -1.0 if (lfsr & 1) else 1.0
            v = v * (1.0 - noise) + nval * noise
        out[i] = v * _env(shape, t) * gain
    return out


def silence(dur):
    return array.array("f", [0.0]) * max(1, int(SR * dur))


def render(segments, vol=1.0):
    buf = array.array("f")
    for seg in segments:
        buf.extend(seg)
    pcm = array.array("h", [0]) * len(buf)
    for i, v in enumerate(buf):
        q = round(max(-1.0, min(1.0, v)) * 7) / 7.0   # 4-bit DAC crunch
        pcm[i] = int(q * vol * 0.62 * 32767)          # volume after, so it
    return pcm                                        # stays crunchy when quiet


def write_wav(path, pcm):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def build_cry(seed, pitch=1.0, length=1.0):
    """An original cry: 2-4 swept pulse segments with a noise growl."""
    rng = random.Random(seed)
    duties = [0.125, 0.25, 0.5, 0.75]
    base = rng.uniform(300, 560) * pitch
    segs = []
    for k in range(rng.randint(2, 4)):
        d = rng.uniform(0.07, 0.17) * length
        up = rng.random() < 0.55
        a = base * rng.uniform(0.75, 1.45)
        b = a * (rng.uniform(1.25, 2.3) if up else rng.uniform(0.42, 0.8))
        segs.append(tone(d, a, b,
                         duty=rng.choice(duties),
                         shape=rng.choice(["hold", "decay", "swell"]),
                         noise=rng.choice([0.0, 0.0, 0.18, 0.32]),
                         nfreq=rng.uniform(900, 5200),
                         vib=rng.choice([0.0, 0.05, 0.11]),
                         gain=0.95))
        if rng.random() < 0.35:
            segs.append(silence(rng.uniform(0.012, 0.035)))
        base *= rng.uniform(0.82, 1.18)
    segs.append(tone(0.09 * length, base * 0.9, base * 0.45, duty=0.125,
                     shape="decay", gain=0.7))
    return segs


def build_bank(seed):
    """name -> list of segments, for every sound the pet makes."""
    b = {}
    b["cry"]     = build_cry(seed)
    b["cry_hi"]  = build_cry(seed, pitch=1.32, length=0.85)
    b["cry_low"] = build_cry(seed, pitch=0.78, length=1.18)
    b["chirp"]   = [tone(0.05, 780, 1180, duty=0.25, shape="hold"),
                    tone(0.07, 1180, 1560, duty=0.5, shape="decay")]
    b["happy"]   = [tone(0.06, 660, 660, duty=0.5, shape="hold"),
                    tone(0.06, 880, 880, duty=0.5, shape="hold"),
                    tone(0.14, 1320, 1320, duty=0.25, shape="decay")]
    b["eat"]     = [tone(0.05, 190, 120, duty=0.5, shape="pluck", noise=0.85, nfreq=3200),
                    silence(0.05),
                    tone(0.05, 210, 130, duty=0.5, shape="pluck", noise=0.85, nfreq=2600),
                    silence(0.05),
                    tone(0.07, 170, 100, duty=0.5, shape="pluck", noise=0.8, nfreq=2100)]
    b["hop"]     = [tone(0.08, 520, 1040, duty=0.25, shape="decay")]
    b["sad"]     = [tone(0.30, 420, 165, duty=0.5, shape="decay", vib=0.06, vrate=9)]
    b["yawn"]    = [tone(0.34, 300, 190, duty=0.125, shape="swell", vib=0.04, vrate=6, gain=0.6)]
    b["wake"]    = [tone(0.09, 400, 700, duty=0.25, shape="swell"),
                    tone(0.10, 700, 990, duty=0.5, shape="decay")]
    b["land"]    = [tone(0.11, 150, 70, duty=0.5, shape="pluck", noise=0.65, nfreq=900)]
    b["crack"]   = [tone(0.04, 900, 500, duty=0.125, shape="pluck", noise=0.55, nfreq=6000)]
    b["ping"]    = [tone(0.055, 990, 990, duty=0.25, shape="hold"),
                    tone(0.11, 1480, 1480, duty=0.25, shape="decay")]
    b["splash"]  = [tone(0.18, 260, 900, duty=0.5, shape="swell", noise=0.55,
                         nfreq=2600, gain=0.8),
                    tone(0.16, 900, 420, duty=0.25, shape="decay", noise=0.35,
                         nfreq=4200, gain=0.6)]
    b["sparkle"] = [tone(0.05, 1320, 1320, duty=0.125, shape="pluck"),
                    tone(0.05, 1760, 1760, duty=0.125, shape="pluck"),
                    tone(0.05, 2100, 2100, duty=0.125, shape="pluck"),
                    tone(0.20, 2640, 2640, duty=0.125, shape="decay")]
    b["evolve"]  = [tone(0.10, 330, 495, duty=0.25, shape="hold"),
                    tone(0.10, 440, 660, duty=0.25, shape="hold"),
                    tone(0.10, 550, 825, duty=0.25, shape="hold"),
                    tone(0.10, 660, 990, duty=0.25, shape="hold"),
                    tone(0.55, 880, 1760, duty=0.125, shape="swell",
                         vib=0.05, vrate=16)]
    b["arrival"]  = song_arrival()
    b["farewell"] = song_farewell()
    b["fanfare"] = [tone(0.06, 660, 660, duty=0.25, shape="hold"),
                    tone(0.06, 880, 880, duty=0.25, shape="hold"),
                    tone(0.06, 1100, 1100, duty=0.25, shape="hold"),
                    tone(0.22, 1320, 1320, duty=0.5, shape="decay", vib=0.03, vrate=14)]
    return b



# ----------------------------------------------------------------------------
# Speech
#
# One blip per letter, pitched deterministically from the letter itself plus
# the pet's voice seed - so the same word always sounds the same, which is what
# makes it read as a voice rather than as noise. Vowels are held longer,
# punctuation becomes a pause. The whole utterance is rendered as ONE wav and
# played once - simpler than firing one process per blip.
# ----------------------------------------------------------------------------
VOWELS = "aeiouy"

VOICE_OF = {
    "dreamer":    dict(base=545, duty=0.50, dur=0.055, gap=0.028, slide=1.06, jit=0.18),
    "stoic":      dict(base=380, duty=0.50, dur=0.060, gap=0.032, slide=0.97, jit=0.08),
    "rascal":     dict(base=640, duty=0.25, dur=0.040, gap=0.018, slide=1.10, jit=0.24),
    "melancholy": dict(base=430, duty=0.50, dur=0.065, gap=0.036, slide=0.92, jit=0.12),
    "curious":    dict(base=620, duty=0.25, dur=0.042, gap=0.020, slide=1.14, jit=0.22),
    "gentle":     dict(base=500, duty=0.50, dur=0.055, gap=0.028, slide=1.00, jit=0.12),
    "fierce":     dict(base=340, duty=0.125, dur=0.045, gap=0.018, slide=0.90, jit=0.16),
    "wanderer":   dict(base=480, duty=0.25, dur=0.050, gap=0.024, slide=1.04, jit=0.16),
}

MAX_BLIPS = 46          # long quotes stop blipping rather than droning on


def build_speech(text, seed, personality, tier):
    """Turn a line of text into a babble track. Returns (segments, seconds)."""
    v = VOICE_OF.get(personality, VOICE_OF["gentle"])
    pitch = {0: 1.34, 1: 1.10, 2: 0.94}.get(tier, 1.0)
    segs, secs, blips = [], 0.0, 0
    for ch in text:
        if ch == " ":
            segs.append(silence(0.034))
            secs += 0.034
            continue
        if ch in ".!?":
            segs.append(silence(0.11))
            secs += 0.11
            continue
        if ch in ",;:-\u2014":
            segs.append(silence(0.062))
            secs += 0.062
            continue
        if not ch.isalnum() or blips >= MAX_BLIPS:
            continue
        low = ch.lower()
        h = (ord(low) * 31 + seed) % 13                  # same letter, same note
        f = v["base"] * pitch * (1.0 + v["jit"] * (h - 6) / 6.0)
        vowel = low in VOWELS
        dur = v["dur"] * (1.3 if vowel else 1.0)
        segs.append(tone(dur, f, f * v["slide"], duty=v["duty"],
                         shape="hold" if vowel else "pluck", gain=0.72))
        segs.append(silence(v["gap"]))
        secs += dur + v["gap"]
        blips += 1
    return segs, secs



SEMITONES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
             "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def freq(name):
    """'A4' -> 440.0"""
    step = SEMITONES[name[:-1]] + (int(name[-1]) - 4) * 12 - 9
    return 440.0 * (2.0 ** (step / 12.0))


def melody(seq, beat, duty=0.5, shape="hold", gain=0.7):
    """seq is [(note or None, beats), ...]. None is a rest."""
    segs = []
    for name, beats in seq:
        d = beat * beats
        if name is None:
            segs.append(silence(d))
            continue
        f = freq(name)
        segs.append(tone(d * 0.90, f, f, duty=duty, shape=shape, gain=gain))
        segs.append(silence(d * 0.10))            # a little air between notes
    return segs


def mix(*tracks):
    """Sum several tracks into one. Returns a single segment."""
    arrs = []
    for t in tracks:
        a = array.array("f")
        for seg in t:
            a.extend(seg)
        arrs.append(a)
    n = max(len(a) for a in arrs) if arrs else 0
    out = array.array("f", [0.0]) * n
    for a in arrs:
        for i, v in enumerate(a):
            out[i] += v
    return [out]


# Original melodies - warm and open for the arrival, bare and minor for the
# goodbye. Nothing quoted from anywhere.
def song_arrival():
    b = 0.34
    lead = [("E4", 1), ("G4", 1), ("C5", 2), ("B4", 1), ("A4", 1), ("G4", 2),
            ("A4", 1), ("G4", 1), ("E4", 2), ("D4", 1), ("E4", 1), ("G4", 2),
            ("E4", 1), ("D4", 1), ("C4", 3), (None, 1)]
    bass = [("C3", 2), ("G2", 2), ("A2", 2), ("F2", 2),
            ("C3", 2), ("F2", 2), ("G2", 2), ("C3", 2)]
    return mix(melody(lead, b, duty=0.5, shape="hold", gain=0.60),
               melody(bass, b, duty=0.25, shape="hold", gain=0.34))


def song_farewell():
    b = 0.46
    lead = [("A4", 2), ("G4", 1), ("F4", 1), ("E4", 2), ("D4", 1), ("E4", 1),
            ("F4", 2), ("E4", 1), ("D4", 1), ("C4", 2), ("B3", 1), ("A3", 1),
            ("A3", 2), ("C4", 1), ("E4", 1), ("D4", 3), (None, 1)]
    bass = [("A2", 2), ("E2", 2), ("F2", 2), ("C3", 2),
            ("D3", 2), ("A2", 2), ("E2", 2), ("A2", 2)]
    return mix(melody(lead, b, duty=0.5, shape="hold", gain=0.56),
               melody(bass, b, duty=0.125, shape="hold", gain=0.32))



class Voice:
    """Builds the bank in the background, then plays the WAVs via afplay."""

    def __init__(self, name, muted=False, volume=0.7):
        self.muted = muted
        self.volume = volume
        self.ready = False
        self.dir = os.path.join(config_dir(), "sfx")
        self.seed = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)
        self.paths = {}
        self.durs = {}
        self.slot = 0
        self.talking = None
        self.last = 0.0
        self.last_dur = 0.0
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            tag = f"{self.seed:08x}-{int(self.volume * 100)}-{SFX_VERSION}"
            need = False
            for k in ("cry", "chirp", "happy", "eat", "hop", "sad", "yawn",
                      "wake", "land", "crack", "ping", "fanfare", "evolve",
                      "cry_hi", "cry_low", "arrival", "farewell",
                      "splash", "sparkle"):
                fp = os.path.join(self.dir, f"{k}-{tag}.wav")
                self.paths[k] = fp
                if not os.path.exists(fp):
                    need = True
            bank = build_bank(self.seed)
            for k, segs in bank.items():
                self.durs[k] = sum(len(x) for x in segs) / float(SR)
            if need:
                for k, segs in bank.items():
                    write_wav(self.paths[k], render(segs, self.volume))
            keep = set(os.path.basename(v) for v in self.paths.values())
            keep |= {f"say{i}.wav" for i in range(4)}      # speech scratch files
            for f in os.listdir(self.dir):             # tidy old names/volumes
                if f.endswith(".wav") and f not in keep:
                    try:
                        os.remove(os.path.join(self.dir, f))
                    except OSError:
                        pass
            self.ready = True
        except Exception:
            self.ready = False

    def play(self, key, force=False):
        if self.muted or not self.ready:
            return
        now = time.time()
        if not force and now - self.last < 0.14:
            return
        fp = self.paths.get(key)
        if not fp or not os.path.exists(fp):
            return
        self.last = now
        self.last_dur = self.durs.get(key, 0.2)
        afplay(fp)

    def busy_for(self):
        """Seconds still left on whatever is playing, capped. Speech waits for
        a short cry to finish, but must never queue behind a whole song."""
        return 0.0            # afplay mixes; nothing waits its turn

    def speak(self, text, personality, tier):
        """Render this line as babble and play it. Returns (delay, seconds)."""
        if self.muted or not self.ready or not text:
            return 0.0, 0.0
        try:
            segs, secs = build_speech(text, self.seed, personality, tier)
            if secs <= 0.0:
                return 0.0, 0.0
            self.slot = (self.slot + 1) % 4               # rotate so we never
            fp = os.path.join(self.dir, f"say{self.slot}.wav")   # overwrite a
            write_wav(fp, render(segs, self.volume))      # file mid-playback
        except Exception:
            return 0.0, 0.0
        delay = self.busy_for()                           # let the cry finish

        try:                              # stop the previous line first, so
            if self.talking:              # two utterances never overlap
                self.talking.terminate()
        except Exception:
            pass
        self.talking = afplay(fp)
        self.last = time.time()
        self.last_dur = secs
        return 0.0, secs

    def rebuild(self, name=None, volume=None):
        if name is not None:
            self.seed = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)
        if volume is not None:
            self.volume = volume
        self.ready = False
        threading.Thread(target=self._build, daemon=True).start()






# ----------------------------------------------------------------------------
# Fun-fact quiz
#
# (statement, is_it_true, the reason). Roughly half are true and half are
# popular things that simply aren't - so guessing "true" every time scores
# about 50%. Add your own freely; keep the reason short enough for one line.
# ----------------------------------------------------------------------------
FACTS = [
    # --- true ---
    ("Honey never spoils.", True,
     "Edible pots of it turned up in Egyptian tombs."),
    ("An octopus has three hearts.", True,
     "Two pump the gills, one pumps the body."),
    ("Octopus blood is blue.", True,
     "It carries oxygen with copper, not iron."),
    ("Bananas are berries but strawberries are not.", True,
     "Botanically a berry comes from one flower, one ovary."),
    ("Sharks are older than trees.", True,
     "Sharks by about 100 million years."),
    ("A day on Venus lasts longer than its year.", True,
     "It spins slower than it orbits."),
    ("Wombats produce cube-shaped droppings.", True,
     "Their intestines shape it. It stacks without rolling away."),
    ("The Eiffel Tower is taller in summer.", True,
     "Heat expands the iron by about 15cm."),
    ("Sea otters hold hands while they sleep.", True,
     "So they don't drift apart on the current."),
    ("There are more trees on Earth than stars in our galaxy.", True,
     "Around three trillion, against a few hundred billion."),
    ("The shortest war in history lasted under an hour.", True,
     "Anglo-Zanzibar, 1896. About 38 minutes."),
    ("Scotland's national animal is the unicorn.", True,
     "It has been on the royal arms since the 1500s."),
    ("Bubble wrap was invented as wallpaper.", True,
     "It failed at that, then became packaging."),
    ("Cleopatra lived closer to the Moon landing than to the pyramids.", True,
     "The Great Pyramid was already ancient in her lifetime."),
    ("Oxford University is older than the Aztec Empire.", True,
     "Teaching there began around 1096; the Aztecs, 1428."),
    ("Carrots were originally purple.", True,
     "Orange ones were bred much later."),
    ("Nintendo was founded in the 1800s.", True,
     "1889, making playing cards."),
    ("Antarctica is a desert.", True,
     "Deserts are defined by rainfall, not heat."),
    ("Polar bears have black skin.", True,
     "Under fur that isn't white either - it's clear."),
    ("Butterflies taste with their feet.", True,
     "They stand on a leaf to decide if it's food."),
    ("A starfish has no brain.", True,
     "Just a nerve ring and one nerve per arm."),
    ("Hummingbirds can fly backwards.", True,
     "The only birds that truly can."),
    ("An octopus can squeeze through any hole bigger than its beak.", True,
     "The beak is the only rigid part of it."),
    ("Sound travels faster in water than in air.", True,
     "About four times faster."),
    ("Koalas have fingerprints almost identical to ours.", True,
     "Close enough to confuse a crime scene."),
    ("Water is genuinely blue, not just reflecting the sky.", True,
     "Water absorbs red light, so blue is what's left."),
    ("Jupiter has more than 50 known moons.", True,
     "Well over ninety, and still counting."),

    # --- false ---
    ("The Great Wall of China is visible from space with the naked eye.", False,
     "It's far too narrow. Astronauts have said so repeatedly."),
    ("Goldfish have a three-second memory.", False,
     "They remember things for months and can be trained."),
    ("Bats are blind.", False,
     "They all see. Many see very well."),
    ("Lightning never strikes the same place twice.", False,
     "Tall buildings are hit dozens of times a year."),
    ("We only use ten percent of our brains.", False,
     "Scans show essentially all of it is active."),
    ("Chameleons change colour to match their surroundings.", False,
     "It's mood, temperature and signalling to each other."),
    ("Bulls are enraged by the colour red.", False,
     "They can't see red. It's the movement of the cape."),
    ("Humans have exactly five senses.", False,
     "Balance and body position are senses too."),
    ("Water drains the opposite way in the southern hemisphere.", False,
     "The basin's shape wins. The Earth's spin is far too weak."),
    ("Sugar makes children hyperactive.", False,
     "Trials keep finding no effect. Parents expect it and see it."),
    ("A penny dropped from a skyscraper could kill someone.", False,
     "It's too light and tumbles. It would sting."),
    ("Dogs see only in black and white.", False,
     "They see blues and yellows, just not reds."),
    ("Fortune cookies come from China.", False,
     "They were popularised in California."),
    ("Vikings wore horned helmets.", False,
     "A 19th-century opera costume invented that."),
    ("Einstein failed mathematics at school.", False,
     "He was excellent at it and said so himself."),
    ("Camels store water in their humps.", False,
     "The humps are fat."),
    ("You lose most of your body heat through your head.", False,
     "Only about what its share of surface area suggests."),
    ("Cracking your knuckles causes arthritis.", False,
     "One doctor cracked one hand for 60 years to check."),
    ("The tongue has separate zones for each taste.", False,
     "That map came from a mistranslation. All zones taste all."),
    ("Everest is the tallest mountain measured base to peak.", False,
     "Mauna Kea is, if you start at the sea floor."),
    ("Peanuts are nuts.", False,
     "They're legumes, closer to peas."),
    ("Spiders are insects.", False,
     "Eight legs, two body parts. Arachnids."),
    ("The Sahara is the largest desert on Earth.", False,
     "Antarctica is, comfortably."),
    ("Ostriches bury their heads in the sand.", False,
     "They lie flat, or they run at 70km/h."),
    ("Hair and nails keep growing after death.", False,
     "The skin retracts, which makes them look longer."),
    ("All sharks must keep swimming or they drown.", False,
     "Plenty of species pump water over their gills at rest."),
    ("All bees die after they sting you.", False,
     "Honeybees do. Most other bees sting and carry on."),
    ("Diamonds are made from coal.", False,
     "They form far deeper, from much older carbon."),

    # --- screen trivia ---
    ("Toy Story was the first fully computer-animated feature film.", True,
     "1995. Everything before it had hand-drawn frames somewhere."),
    ("The Simpsons started as short cartoons on another TV show.", True,
     "Shorts on The Tracey Ullman Show, three years before their own series."),
    ("Jaws shows the shark less than planned because the shark kept breaking.", True,
     "The malfunction is why it works. You imagine it instead."),
    ("Psycho was the first American film to show a toilet flushing.", True,
     "It caused more complaints than the murder did."),
    ("The Wilhelm scream is named after a character in a 1953 western.", True,
     "Private Wilhelm, shot by an arrow. It's been reused for decades."),
    ("Anthony Hopkins is on screen under 20 minutes in Silence of the Lambs.", True,
     "About sixteen. He won Best Actor for it anyway."),
    ("MTV's first music video was Video Killed the Radio Star.", True,
     "August 1981. On the nose, really."),
    ("The Blair Witch Project was made for under a hundred thousand dollars.", True,
     "Around sixty thousand. It took nearly 250 million."),
    ("Star Trek invented the transporter to avoid filming ship landings.", True,
     "Landing a starship every episode was far too expensive."),
    ("Netflix began by posting DVDs to people.", True,
     "Streaming didn't arrive until 2007, a decade in."),
    ("Casablanca was based on a stage play.", True,
     "An unproduced one called Everybody Comes to Rick's."),
    ("Jurassic Park used more animatronic dinosaur footage than computer-generated.", True,
     "The puppets do most of the work. The CGI is only minutes."),

    ("Star Wars had 'Episode IV' in its title when it first came out.", False,
     "That was added for the 1981 re-release."),
    ("Alfred Hitchcock won the Oscar for Best Director.", False,
     "Nominated five times, never won. He got an honorary award instead."),
    ("The Wizard of Oz was filmed entirely in colour.", False,
     "The Kansas scenes are sepia. That's the whole trick."),
    ("Mickey Mouse was Disney's first cartoon character.", False,
     "Oswald the Lucky Rabbit came first, and Disney lost the rights to him."),
    ("The Lord of the Rings films were shot in Ireland.", False,
     "New Zealand, all of it."),
    ("Bert and Ernie were named after characters in It's a Wonderful Life.", False,
     "A persistent story. Sesame Workshop has denied it for years."),
    ("Central Perk in Friends was a real New York coffee shop.", False,
     "A set on a Warner lot in Burbank."),
]


# ----------------------------------------------------------------------------
# The treatment quiz. Settled, textbook-level material only - nothing
# contested, nothing dose-specific, nothing that reads as advice for a real
# situation. It is a game about a pixel creature.
# ----------------------------------------------------------------------------
HEALTH_FACTS = [
    # --- true ---
    ("Antibiotics do nothing against viruses like colds and flu.", True,
     "Colds are viral. Antibiotics only act on bacteria."),
    ("Overusing antibiotics helps drive antibiotic resistance.", True,
     "It selects for the bacteria that survive them."),
    ("Taking too much paracetamol can seriously damage the liver.", True,
     "It's one of the most common causes of acute liver failure."),
    ("Blood pressure is written as two numbers, systolic over diastolic.", True,
     "The pressure as the heart beats, over the pressure as it rests."),
    ("Most adults need roughly seven to nine hours of sleep.", True,
     "Consistently less is linked with a long list of problems."),
    ("Regular exercise can ease mild anxiety and low mood.", True,
     "It's well enough supported to be offered as a first-line option."),
    ("Sunscreen needs reapplying through the day, not just once.", True,
     "Roughly every two hours, and after swimming or sweating."),
    ("Ibuprofen can irritate the stomach lining.", True,
     "It's an NSAID. That's the classic side effect of the class."),
    ("Vaccines work by teaching the immune system to recognise something.", True,
     "It learns the shape without having to meet the real illness."),
    ("Dehydration can cause headaches.", True,
     "One of the most common and most fixable causes."),
    ("Grapefruit can interfere with how some medicines are absorbed.", True,
     "It blocks an enzyme in the gut. Some labels warn about it."),
    ("Smoking is the single biggest preventable cause of lung cancer.", True,
     "By an enormous margin."),
    ("Around twenty seconds is the usual advice for washing hands.", True,
     "Long enough for the soap to do its work."),
    ("Flu vaccines are reformulated every year.", True,
     "The circulating strains shift, so the vaccine follows them."),
    ("Losing sleep slows your reaction time.", True,
     "Badly enough that it has been compared to being over the limit."),
    ("Fibre helps keep digestion moving.", True,
     "Which is why it turns up in every dietary guideline."),

    # --- false ---
    ("Antibiotics will clear up a common cold faster.", False,
     "They do nothing to a virus. You just get the side effects."),
    ("You should starve a fever and feed a cold.", False,
     "Old saying, no evidence. Eat and drink normally for both."),
    ("Detox teas flush toxins out of your body.", False,
     "Your liver and kidneys already do that, for free."),
    ("Everyone must drink exactly eight glasses of water a day.", False,
     "There's no evidence for that specific number. Thirst is a decent guide."),
    ("Vitamin C stops you catching colds.", False,
     "Trials are clear it doesn't prevent them."),
    ("Going out with wet hair in the cold gives you a cold.", False,
     "Viruses give you colds. Being chilly doesn't."),
    ("Putting butter on a burn helps it heal.", False,
     "Cool running water. Butter traps the heat in."),
    ("Doubling a dose makes medicine work twice as fast.", False,
     "It mostly makes side effects arrive twice as fast."),
    ("Something being natural means it's safe to take.", False,
     "Plenty of natural things are extremely poisonous."),
    ("It's fine to share leftover antibiotics with family.", False,
     "Wrong drug, wrong dose, wrong bug, and it feeds resistance."),
    ("Everyone needs a daily multivitamin.", False,
     "Most people eating a varied diet get what they need from food."),
    ("You can sweat toxins out in a sauna.", False,
     "Sweat is mostly water and salt. Saunas are pleasant, not cleansing."),
    ("Eating sugar directly causes type 2 diabetes.", False,
     "It's a risk factor mainly through weight, not a direct cause."),
    ("Cold weather itself causes the flu.", False,
     "A virus does. Winter just puts us all indoors together."),
    ("Cracking your knuckles gives you arthritis.", False,
     "Checked repeatedly. It doesn't."),
    ("If a wound is deep it should be left uncovered to breathe.", False,
     "Covered and clean is the usual advice for healing."),
]

TREAT_ROUND = 5             # all five, or no cure


QUIZ_ROUND = 5          # questions per round



# ----------------------------------------------------------------------------
# Why it leaves. Rolled at hatch and kept for that pet's whole life, so the
# goodbye is a surprise the first time and consistent if you ask it to stay.
# Each has a baby version and a grown-up version of the same bad reasoning.
# ----------------------------------------------------------------------------
DEPARTURES = [
    dict(
        short="to ask the moon why it keeps following",
        baby=["me been finking about somefing",
              "da moon has been following me. every night",
              "me going to go and ask it why",
              "fank you for keeping me safe",
              "me will come back and tell you what it said"],
        grown=["I've been thinking about something",
               "the moon has followed me every single night",
               "I'm going to go and ask it what it wants",
               "thank you for keeping me safe",
               "I'll come back and tell you what it says"]),
    dict(
        short="to find the sock it lost",
        baby=["me lost a sock",
              "not on me foot. a diffewent sock. a secret one",
              "it is out dere. me can feel it",
              "fank you for da snacks and da baths",
              "me will find it. probably"],
        grown=["I lost a sock",
               "not one I was wearing. a different one. a secret one",
               "it's out there somewhere. I can feel it",
               "thank you for the snacks and the baths",
               "I will find it. probably"]),
    dict(
        short="to attend dinosaur school",
        baby=["me got a letter. well. me imagined a letter",
              "me got into dinosaur school!",
              "dey teach you to be enormous and to stomp",
              "fank you for believing me when me said me was one",
              "me will send you a picture of me being huge"],
        grown=["I got a letter. well. I imagined a letter",
               "I've been accepted into dinosaur school",
               "they teach you to be enormous, and to stomp",
               "thank you for never once correcting me about this",
               "I'll send a photograph of myself being huge"]),
    dict(
        short="to apologise to a bug's family",
        baby=["remember da bug me ated",
              "me been finking. him probably had a family",
              "me has to go and say sorry to dem. in person",
              "fank you for not being cross about da bug",
              "it is da wight fing to do"],
        grown=["you remember the bug I ate",
               "I've been thinking. he probably had a family",
               "I have to go and apologise to them. in person",
               "thank you for never bringing up the bug",
               "it's the right thing to do"]),
    dict(
        short="to collect the cloud it named",
        baby=["me named a cloud last tuesday",
              "dat means it belongs to me now. dat is da wule",
              "me going to go and collect it before someone else does",
              "fank you for da warm desk",
              "me will bring it back if it fits"],
        grown=["I named a cloud last Tuesday",
               "which means it belongs to me now. those are the rules",
               "I'm going to collect it before somebody else does",
               "thank you for the warm desk",
               "I'll bring it back if it fits through the door"]),
    dict(
        short="to check whether the sea is really that big",
        baby=["everyone keeps saying da sea is very big",
              "but nobody will say HOW big",
              "me going to go and measure it meself",
              "fank you for looking after me",
              "me will be back by breakfast. probably not breakfast"],
        grown=["everyone keeps telling me the sea is very big",
               "but nobody will say how big, exactly",
               "so I'm going to go and measure it myself",
               "thank you for looking after me",
               "back by breakfast. probably not breakfast"]),
]


# ----------------------------------------------------------------------------
# Personality
#
# Assigned at hatch, independent of species - so the same creature can turn up
# stoic or restless. It shifts how fast the stats drain, how much the pet
# wanders, how often it talks, and which shelf it quotes from.
#
# Every quote below is public domain: the authors are long dead and the works
# were published well before 1930. Swap the lists freely - just keep anything
# you add out of copyright, since this file gets shipped around.
# ----------------------------------------------------------------------------
PERSONALITIES = {
    "dreamer": dict(
        title="Dreamer", blurb="somewhere else, mostly",
        hunger=1.0, happy=0.8, energy=1.2, chatty=0.55, wander=0.5),
    "stoic": dict(
        title="Stoic", blurb="endures things you wouldn't",
        hunger=0.8, happy=0.7, energy=0.8, chatty=0.2, wander=0.3),
    "rascal": dict(
        title="Rascal", blurb="bores easily, causes problems",
        hunger=1.2, happy=1.3, energy=1.1, chatty=0.5, wander=0.8),
    "melancholy": dict(
        title="Melancholy", blurb="feels everything twice",
        hunger=0.9, happy=1.3, energy=0.9, chatty=0.45, wander=0.3),
    "curious": dict(
        title="Curious", blurb="has to know what that is",
        hunger=1.1, happy=0.9, energy=1.3, chatty=0.45, wander=0.9),
    "gentle": dict(
        title="Gentle", blurb="easy to keep, easy to please",
        hunger=0.8, happy=0.8, energy=0.9, chatty=0.35, wander=0.4),
    "fierce": dict(
        title="Fierce", blurb="runs hot, burns through everything",
        hunger=1.3, happy=1.0, energy=1.3, chatty=0.3, wander=0.7),
    "wanderer": dict(
        title="Wanderer", blurb="never in the same corner twice",
        hunger=1.1, happy=0.9, energy=1.2, chatty=0.4, wander=1.0),
}

QUOTES = {
    "dreamer": [
        ("I contain multitudes.", "Whitman"),
        ("I dwell in Possibility.", "Dickinson"),
        ("To see a world in a grain of sand.", "Blake"),
        ("The soul should always stand ajar.", "Dickinson"),
        ("I am large.", "Whitman"),
        ("We are such stuff as dreams are made on.", "Shakespeare"),
    ],
    "stoic": [
        ("Very little is needed to make a happy life.", "Marcus Aurelius"),
        ("Confine yourself to the present.", "Marcus Aurelius"),
        ("We suffer more in imagination than in reality.", "Seneca"),
        ("No man is free who is not master of himself.", "Epictetus"),
        ("The soul becomes dyed with the colour of its thoughts.", "Marcus Aurelius"),
        ("It is not death a man should fear.", "Marcus Aurelius"),
    ],
    "rascal": [
        ("I can resist everything except temptation.", "Wilde"),
        ("Always forgive your enemies. Nothing annoys them so much.", "Wilde"),
        ("When in doubt, tell the truth.", "Twain"),
        ("There is no sin except stupidity.", "Wilde"),
        ("Get your facts first, then distort them.", "Twain"),
        ("I am not young enough to know everything.", "Barrie"),
    ],
    "melancholy": [
        ("All that we see or seem is but a dream within a dream.", "Poe"),
        ("Hope is the thing with feathers.", "Dickinson"),
        ("Nothing beside remains.", "Shelley"),
        ("Parting is all we know of heaven.", "Dickinson"),
        ("Deep into that darkness peering, long I stood.", "Poe"),
        ("I have not broken your heart. You have.", "E. Bronte"),
    ],
    "curious": [
        ("Curiouser and curiouser!", "Carroll"),
        ("I have believed six impossible things before breakfast.", "Carroll"),
        ("It is a capital mistake to theorise before data.", "Doyle"),
        ("You see, but you do not observe.", "Doyle"),
        ("Anything one man can imagine, others can make real.", "Verne"),
        ("The world is big. I want a good look.", "London"),
    ],
    "gentle": [
        ("There is no charm equal to tenderness of heart.", "Austen"),
        ("Kindness effects more than severity.", "Aesop"),
        ("Little by little does the trick.", "Aesop"),
        ("Simplify, simplify.", "Thoreau"),
        ("I am learning to sail my ship.", "Alcott"),
        ("The sun does not shine for a few trees.", "Thoreau"),
    ],
    "fierce": [
        ("Call me Ishmael.", "Melville"),
        ("From hell's heart I stab at thee.", "Melville"),
        ("Once more unto the breach.", "Shakespeare"),
        ("Screw your courage to the sticking place.", "Shakespeare"),
        ("In the midst of chaos, there is opportunity.", "Sun Tzu"),
        ("I would prefer not to.", "Melville"),
    ],
    "wanderer": [
        ("I travel not to go anywhere, but to go.", "Stevenson"),
        ("Afoot and light-hearted I take to the open road.", "Whitman"),
        ("Tell me, O Muse, of that ingenious hero.", "Homer"),
        ("I have a great deal of company in my house.", "Thoreau"),
        ("Allons! the road is before us.", "Whitman"),
        ("To travel hopefully is better than to arrive.", "Stevenson"),
    ],
}



# ----------------------------------------------------------------------------
# What it says when it wants something. Babies talk like babies; the grown
# forms drop the baby talk but keep the attitude.
# ----------------------------------------------------------------------------
CUTE = {
    "hungry": {
        "baby": ["me hungwy", "tummy make noise", "food pwease?",
                 "is empty in here", "nom? nom nom?", "me forgot to eat. again."],
        "grown": ["I could eat", "the tummy has opinions", "feed me, I'll owe you",
                  "snack. now. please.", "running on fumes here"],
    },
    "sleepy": {
        "baby": ["me eyes heavy", "just a lil nap", "sleepy baby...",
                 "five more minutes", "*yaaawn*", "me no tired. me VERY tired."],
        "grown": ["fading fast", "I'll just rest my eyes", "one nap, then I'm useful",
                  "the day has defeated me", "*enormous yawn*"],
    },
    "bored": {
        "baby": ["pway wif me?", "me bored", "somefing fun? pwease?",
                 "is anyone dere", "*pokes screen*"],
        "grown": ["entertain me", "I'm withering here", "something. anything.",
                  "we could be having fun right now"],
    },
    "sick": {
        "baby": ["me no feel good", "tummy hurty", "need cuddle",
                 "me a bit poorly"],
        "grown": ["not my finest hour", "I've felt better", "a bit rough, honestly"],
    },
    "dropped": {
        "baby": ["pwease be gentle, me just a baby", "owie", "me not a toy!",
                 "be careful wif me", "dat was scawy"],
        "grown": ["gently, please", "I am not luggage", "put me down properly",
                  "we've talked about this"],
    },
}


def cute_line(kind, tier):
    return random.choice(CUTE[kind]["baby" if tier == 0 else "grown"])



# ----------------------------------------------------------------------------
# Baby chatter - the logic of a very small person who is certain about
# everything. Written for this pet rather than collected from anywhere, so
# there's nothing to credit and nothing shown.
# ----------------------------------------------------------------------------
KID_LINES = [
    "me not tired. me just resting me eyes wif me whole body",
    "if i eat da cookie fast, is it still one cookie?",
    "when i grow up i want to be a dinosaur. is dat allowed",
    "me can count to fwee. one, two, fwee, TEN",
    "i not crying. me eyes just sweaty",
    "why is da floor always at da bottom",
    "me made a fwiend. him is a rock. him name is Steve",
    "if i close me eyes you cant see me. dat is science",
    "me is not smol. everyone else is just very big",
    "i ate a bug. it was a mistake. i wud do it again",
    "does da sun go home at night or does it just hide",
    "me practiced being brave. i was brave for four seconds",
    "why do we have knees. two of dem. dat is a lot of knees",
    "me is helping. is dis helping",
    "i putted da thing in da place. do not ask which place",
    "me told a secret to nobody so it still a secret",
    "if you drop food on da floor it belongs to da floor now",
    "me can hold my breath for one hundred years. maybe five",
    "why do grown-ups walk when dey could run",
    "me not scared of da dark. da dark is scared of ME",
    "i has a plan. da plan is snacks",
    "me learned a new word today. it was BANANA",
    "do fish know dey are wet",
    "me is very fast. watch. ...ok me was fast in my head",
    "when i sneeze does my brain wobble",
    "me was saving dis for later. later is now. me ate it",
    "i drawed you. it is very good. you have nine legs",
    "me is going to stay up ALL night",
    "me knows everything. ask me somefing easy",
    "if i stand on a chair am i a grown-up now",
    "me is not arguing. me is explaining loudly",
    "why does soap taste bad if it smells so good",
    "i counted da stars. dere is lots",
    "me is a very good listener. what did you say",
    "do trees get bored just standing dere",
    "me heart is beating. apparently dat happens all da time",
    "if i name a cloud is it mine now",
    "me is hiding. you found me because i telled you where",
    "why is it called a building if it is already built",
    "me tummy is talking to me. it says biscuit",
    "i can whistle. listen. ...dat was a whisper",
    "me is not sleepy me is just horizontal",
    "when i am big i will eat cake for breakfast. dat is da plan",
    "do bees know dey make honey or is it an accident",
    "me lost a sock. it was on my foot da whole time",
    "why do you have a big screen if you not watching cartoons",
    "me is going to be quiet now. ...me lied",
    "if i put a hat on da chair is da chair wearing it",
    "me dreamed about soup. it was a good dream",
    "why do we say ouch. it does not help",
    "me is doing a very important job. it is sitting",
    "how do birds know where dey are going. dey has no map",
    "me is da boss of dis corner of da desk",
    "if i grow one more day will i be enormous",
    "me thinked very hard and now me needs a snack",
    "why is water not a flavour. it should be a flavour",
    "me is being patient. how long has it been. one second",
    "do you fink da moon knows we can see it",
    "me can see your screen. me not reading it. me can read it though",
    "why is it called a mouse if it does not squeak",
    "me tried to eat a pixel. it did not work",
    "if me sit very still am i furniture",
    "me been up since always",
    "do you fink numbers ever get tired of being in order",
    "me put somefing important somewhere safe. it is gone forever now",
    "why do we blink. what are we hiding from",
    "me is not procrastinating. me is marinating",
    "when you leave, does da room still happen",
    "me has strong opinions about doors",
    "if a snack falls and nobody sees, was it a snack",
    "me is good at hiding. me hide behind me own legs",
    "do clouds know dey are temporary",
    "me learned dat feet are just hands dat gave up",
    "why is monday. what did we do",
    "me is going to be very famous. for somefing. we will see",
    "if me shout at da screen does it hear me",
    "me dreamed dat me was a bigger me",
    "why does time only go one way. dat seems rude",
    "me practiced walking backwards. it went badly",
    "do you fink da desk gets tired of holding fings",
    "me counted to a hundred. me skipped some. dey were boring",
    "if me had pockets what would go in dem",
    "me is not upside down. da world is",
    "why do we say hello. we already found each other",
    "me tried to draw a circle. it is now a potato",
    "does da wind know where it is going",
    "me is very wise. me just cannot prove it",
    "if you fink about finking is dat two finks",
    "me made a rule. me forgot da rule. da rule stands",
    "why is dere a hole in da middle of donuts. where did it go",
    "me is not small me is efficiently sized",
    "do fish get firsty",
    "me been practicing my serious face. dis is it",
    "if me name a day is it mine",
    "me want to know what is behind da screen",
    "why do shadows follow us. dey were not invited",
    "me is going to invent a new colour",
    "me put a fought in me head. it fell out",
    "do birds fink we are very slow",
    "me is da fastest sitter you know",
    "why do we have to sleep every single night. every one",
    "me heard a noise. it was me",
    "if me close one eye is da world half gone",
    "me is collecting facts. me has two",
    "why is soup a drink and also not",
    "me been thinking about worms. dey has no arms and dey manage",
    "do you fink da moon is lonely up dere",
    "me is going to be taller tomorrow. me decided",
    "if me hum does dat count as singing",
    "me lost a fought. it was a good one",
    "why do we have eyebrows. what is dey for",
    "me is not bored. me is between activities",
    "does da sun know it is da sun",
    "me tried to keep a secret. it escaped",
    "if you stand still long enough do you become a statue",
]


# ----------------------------------------------------------------------------
# What it says when it feels short-changed. Sulking, not cruelty - it is a
# small creature having a small strop.
# ----------------------------------------------------------------------------
ATTITUDE = {
    "baby": [
        "me real mum wouldnt leave me live like dis",
        "me not mad. me just disappointed",
        "some owners feed dere pets. just saying",
        "me been keeping a list",
        "is dis how you treat somefing dat loves you",
        "me told da other pets about you. dey was shocked",
        "me wrote a poem about neglect. it is very long",
        "me not crying. me eyes just leaking on purpose",
        "me could have been adopted by anyone",
        "da desk is cold. you have a blanket",
        "me heard you laughing earlier. at somefing else",
        "me will remember dis when me is big",
        "me hungwy. but sure. finish your video",
        "even da poop is judging you now",
        "me starting to fink you like da computer more",
        "me was promised a nice life. me remembers da letter",
    ],
    "grown": [
        "my real mother would not have let me live like this",
        "I'm not angry. I'm disappointed",
        "some people feed their pets. just an observation",
        "I have been keeping a list",
        "is this how you treat something that loves you",
        "I mentioned this to the other pets. they were appalled",
        "I've written a poem about neglect. it runs long",
        "I'm not crying. my eyes are leaking deliberately",
        "I could have been adopted by anyone, you know",
        "the desk is cold. you have a blanket",
        "I heard you laughing earlier. at something else",
        "I will remember this when I am large",
        "I'm starving. but by all means, finish the video",
        "even the mess on the desk is judging you now",
        "I'm beginning to think you prefer the computer",
        "I was promised a nice life. I still have the letter",
    ],
}

# ----------------------------------------------------------------------------
# Screen quotes.
#
# Actual film and TV dialogue is copyrighted, and this file gets passed around,
# so almost everything here is ORIGINAL - written in the voice of a genre and
# credited to the genre rather than to a film. The handful of real quotes are
# from films that are genuinely in the public domain.
# ----------------------------------------------------------------------------
SCREEN = {
    "dreamer": [
        ("The mediator between head and hands must be the heart.", "Metropolis, 1927"),
        ("And in the end, the credits are just names of people who cared.",
         "every closing sequence"),
        ("A picture with a smile, and perhaps, a tear.", "The Kid, 1921"),
        ("Somewhere out there, a very small violin is playing.", "every montage"),
        ("Roll the opening titles. We begin.", "every epic"),
    ],
    "stoic": [
        ("The mission has not changed. Only the odds.", "every space opera"),
        ("I have been at this post a long time. I will be here tomorrow.",
         "every castle guard"),
        ("A man does what he can, until his destiny is revealed.", "every samurai film"),
        ("Hold the line. That is the whole plan.", "every siege scene"),
        ("I did not come here to be comfortable.", "every training montage"),
    ],
    "rascal": [
        ("I have a plan. You are not going to like the plan.", "every heist film"),
        ("Technically, nobody said I couldn't.", "every sidekick"),
        ("We'll fix it in post.", "every film set"),
        ("That was the good vase, wasn't it.", "every sitcom"),
        ("I regret nothing. I remember nothing either.", "every morning-after scene"),
    ],
    "melancholy": [
        ("They're coming to get you, Barbara.", "Night of the Living Dead, 1968"),
        ("The rain started, and nobody thought to stop it.", "every noir"),
        ("She left. The city kept going, which felt rude.", "every detective story"),
        ("Play the sad piano bit. You know the one.", "every third act"),
        ("It was raining. It is always raining.", "every noir"),
    ],
    "curious": [
        ("Future events such as these will affect you in the future.",
         "Plan 9 from Outer Space, 1959"),
        ("It's moving. Doctor, it's definitely moving.", "every monster film"),
        ("I've never seen readings like this.", "every lab scene"),
        ("What if we pressed it? Just to see.", "every disaster film"),
        ("Observe how it approaches the watering hole.", "every nature documentary"),
    ],
    "gentle": [
        ("There's always room at this table for one more.", "every family film"),
        ("Now, gently, we fold in the butter.", "every cooking show"),
        ("Nobody gets left behind. That's the rule.", "every adventure film"),
        ("Come in out of the cold. The kettle's on.", "every village drama"),
        ("Take your time. The story will wait.", "every bedtime scene"),
    ],
    "fierce": [
        ("This town isn't big enough. It never was.", "every western"),
        ("Draw at sundown. Bring water.", "every western"),
        ("You have insulted my school. My school!", "every kung fu film"),
        ("Are you not entertained?!", "every arena scene"),
        ("They can take the barn. They cannot take the hill.", "every war film"),
    ],
    "wanderer": [
        ("Next stop is wherever the road decides.", "every road movie"),
        ("Never look back. Not even once. Especially not now.", "every getaway"),
        ("Ride until the map runs out.", "every western"),
        ("Pack light. We leave at dawn.", "every quest"),
        ("Every port is the same port, eventually.", "every sea story"),
    ],
}


# ----------------------------------------------------------------------------
# Pixel art
#
# Sprites are rasterised into a small grid (one cell = one fat pixel), given a
# 1px dark outline, then blown up with PhotoImage.zoom so the edges stay hard.
# Empty cells are painted the window's transparent key, so the sprite sits on
# the wallpaper with no alpha channel needed.
# ----------------------------------------------------------------------------
GRID = 56          # sprite is GRID x GRID cells
PIX = 3            # nominal cell size, kept for anything measuring in cells
PIX_NUM = 12       # actual scale is PIX_NUM/PIX_DEN = 2.4x
PIX_DEN = 5        # (20% smaller than the 3x it used to be)


def scaled(cells):
    """Cells -> screen pixels at the current sprite scale."""
    return cells * PIX_NUM // PIX_DEN
BASELINE = 50      # row the feet stand on
SPR_PX = 56 * 12 // 5          # rendered sprite height, GRID at the live scale

# palette slots: b=body s=shade l=belly/light k=ink a=accent w=white
class Raster:
    def __init__(self, w=GRID, h=GRID):
        self.w, self.h = w, h
        self.g = [[None] * w for _ in range(h)]

    def set(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            self.g[y][x] = c

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.g[y][x]
        return None

    def ellipse(self, cx, cy, rx, ry, c):
        rx = max(0.5, rx)
        ry = max(0.5, ry)
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                    self.set(x, y, c)

    def rect(self, x0, y0, x1, y1, c):
        for y in range(int(y0), int(y1) + 1):
            for x in range(int(x0), int(x1) + 1):
                self.set(x, y, c)

    def line(self, x0, y0, x1, y1, c):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n):
            t = i / max(1, n - 1)
            self.set(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), c)

    def outline(self, c="k"):
        add = []
        for y in range(self.h):
            for x in range(self.w):
                if self.g[y][x] is not None:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = self.get(x + dx, y + dy)
                    if n is not None and n != c:
                        add.append((x, y))
                        break
        for x, y in add:
            self.set(x, y, c)

    def to_image(self, pal, flat=None):
        """Rasterise to a PhotoImage with genuine transparency.

        Empty cells are left untouched so they stay alpha-zero. Painting them
        TRANS instead would make the whole window transparent there, which
        cuts a hole through anything already drawn underneath.
        """
        img = tk.PhotoImage(width=self.w, height=self.h)
        for y in range(self.h):
            row = self.g[y]
            x = 0
            while x < self.w:
                if row[x] is None:
                    x += 1
                    continue
                run = x
                while run < self.w and row[run] is not None:
                    run += 1
                cells = " ".join(
                    (flat if flat else pal.get(row[i], "#000000"))
                    for i in range(x, run))
                img.put("{" + cells + "}", to=(x, y))
                x = run
        img = img.zoom(PIX_NUM)
        return img if PIX_DEN == 1 else img.subsample(PIX_DEN)


def _shift(col, dh, ds, dv):
    """Nudge a hex colour in HSV."""
    r, g, b = (int(col[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    h, sa, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + dh) % 1.0
    sa = max(0.0, min(1.0, sa * (1.0 + ds)))
    v = max(0.05, min(1.0, v * (1.0 + dv)))
    r, g, b = colorsys.hsv_to_rgb(h, sa, v)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))


def _palette(species, tint=0):
    """Species colours, nudged by this individual's tint. Same species still
    reads as the same species; two of them are visibly not the same pet.

    The outline is a warm dark version of the body rather than flat black -
    that is most of what makes this style feel hand-drawn rather than
    computed."""
    b, sh, l, k, a = SPECIES[species]["pal"]
    if tint:
        rng = random.Random(tint)
        dh = rng.uniform(-0.075, 0.075)
        ds = rng.uniform(-0.20, 0.22)
        dv = rng.uniform(-0.10, 0.12)
        b = _shift(b, dh, ds, dv)
        sh = _shift(sh, dh, ds, dv)
        l = _shift(l, dh, ds * 0.5, dv * 0.4)
        a = _shift(a, dh * 0.5, ds, dv)
    ink = _shift(b, 0.01, 0.45, -0.68)          # warm dark, not black
    return {"b": b, "s": sh, "l": l, "k": ink, "a": a, "w": "#FFFFFF",
            "m": _shift(l, 0.0, -0.35, 0.10),   # belly panel, paler still
            "p": "#F2909B",                     # blush
            "d": "#7A6146",                     # grime
            "t": "#E8798C",                     # tongue
            "q": "#BFE8F5",                     # drool
            "f": "#E86A5E",                     # fever flush
            "u": "#4C4657"}                     # under-eye shadow


# ---------------------------------------------------------------------------
# Anatomy
#
# The style these are drawn in is chibi: a head roughly as wide as the whole
# body, stubby limbs, a pale belly panel, and one or two silhouette features
# (wings, horns, a tail) that make each one recognisable at a glance. The
# outline is thick and warm-toned.
# ---------------------------------------------------------------------------
def draw_horns(r, kind, cx, hy, hw, hh):
    """On top of the head."""
    top = hy - hh
    if kind == "bulb":
        stroke(r, cx + 0.5, top + 2, cx + 0.5, top - 4, 1.3, "s")
        r.ellipse(cx + 0.5, top - 6, 3.0, 3.0, "a")
        r.ellipse(cx - 0.5, top - 7, 1.1, 0.9, "w")
    elif kind == "flame":
        r.ellipse(cx, top - 3, 3.4, 4.4, "a")
        r.ellipse(cx, top - 4, 1.8, 2.6, "w")
        stroke(r, cx - 3, top - 1, cx - 5, top - 5, 1.3, "a")
        stroke(r, cx + 3, top - 1, cx + 5, top - 5, 1.3, "a")
    elif kind == "smoke":
        for i in range(3):
            r.ellipse(cx + (i % 2) * 3 - 1.5, top - 1 - i * 3.2,
                      2.8 - i * 0.5, 2.0 - i * 0.3, "s")
    elif kind == "halo":
        for x in range(int(cx - 6), int(cx + 7)):
            dy = round(((x - cx) / 6.0) ** 2 * 1.8)
            r.set(x, top - 5 + dy, "a")
            r.set(x, top - 4 + dy, "a")
    elif kind == "ring":
        r.ellipse(cx, top - 5, 7, 3.0, "a")
        for y in range(r.h):
            for x in range(r.w):
                if ((x - cx) / 4.6) ** 2 + ((y - (top - 5)) / 1.4) ** 2 <= 1:
                    r.g[y][x] = None
    elif kind == "crystal":                      # a pair of shards
        for sd in (-1, 1):
            bx = cx + sd * 4
            fill_tri(r, [(bx - sd, top + 1), (bx + sd * 2, top + 1),
                         (bx + sd * 2.5, top - 7)], "a")
            r.set(bx + sd, top - 4, "w")
            r.set(bx + sd, top - 3, "w")
    elif kind == "drop":
        r.ellipse(cx, top - 4, 3.2, 3.6, "a")
        fill_tri(r, [(cx, top - 9), (cx - 2.4, top - 4), (cx + 2.4, top - 4)], "a")
        r.set(cx - 1, top - 4, "w")
    elif kind == "leaf":
        stroke(r, cx + 0.5, top + 2, cx + 0.5, top - 4, 1.3, "s")
        for sd in (-1, 1):
            r.ellipse(cx + 0.5 + sd * 3.2, top - 5, 3.0, 1.9, "a")
    elif kind == "petal":
        for i in range(5):
            ang = i * (2 * math.pi / 5) - math.pi / 2
            r.ellipse(cx + math.cos(ang) * 4.0, top - 4 + math.sin(ang) * 3.0,
                      2.3, 1.9, "a")
        r.ellipse(cx, top - 4, 1.7, 1.4, "w")
    elif kind == "thorn":                        # two curved horns
        for sd in (-1, 1):
            fill_tri(r, [(cx + sd * 2.5, top + 2), (cx + sd * 5, top + 2),
                         (cx + sd * 6.5, top - 5)], "s")
            r.ellipse(cx + sd * 6, top - 5, 1.4, 1.4, "a")
    elif kind == "shell":
        for i, (dx, dy, rr) in enumerate(((0, -4, 4.4), (1.5, -4, 2.9),
                                          (2.5, -3, 1.5))):
            r.ellipse(cx + dx, top + dy, rr, rr * 0.9, "a" if i % 2 == 0 else "w")


def draw_ears(r, kind, cx, hy, hw, hh):
    """Either side of the head."""
    if kind == "none":
        return
    for sd in (-1, 1):
        ex = cx + sd * hw * 0.86
        if kind == "small":
            r.ellipse(ex, hy - hh * 0.35, 3.0, 4.0, "s")
            r.ellipse(ex, hy - hh * 0.35, 1.4, 2.2, "m")
        elif kind == "long":
            r.ellipse(ex + sd, hy - hh * 0.55, 2.6, 7.0, "s")
            r.ellipse(ex + sd, hy - hh * 0.55, 1.2, 4.4, "m")
        elif kind == "tuft":
            stroke(r, ex - sd, hy - hh * 0.2, ex + sd * 4, hy - hh * 0.95, 1.5, "s")
            stroke(r, ex, hy - hh * 0.05, ex + sd * 5, hy - hh * 0.6, 1.4, "s")
            stroke(r, ex - sd, hy + hh * 0.1, ex + sd * 4, hy - hh * 0.2, 1.3, "s")
        elif kind == "fin":
            for i in range(3):
                stroke(r, ex + sd * i * 0.8, hy - hh * 0.35 + i * 1.2,
                       ex + sd * (2.5 + i), hy + hh * 0.1 - i * 0.6, 1.5, "s")
            r.ellipse(ex + sd * 2, hy - hh * 0.05, 1.6, 3.0, "m")
        elif kind == "frond":
            for i, (fx, fy) in enumerate(((0.7, -0.5), (1.15, -0.05), (0.8, 0.4))):
                r.ellipse(ex + sd * fx * 3, hy + fy * hh, 3.0, 1.9, "s")


def stroke(r, x0, y0, x1, y1, width, c):
    """A thick line, drawn as overlapping dots. Outlined shapes at this size
    turn into scattered noise, so everything is filled instead."""
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    for i in range(n):
        t = i / max(1, n - 1)
        r.ellipse(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, width, width, c)


def fill_tri(r, pts, c):
    """Scanline-fill a triangle."""
    ys = [pt[1] for pt in pts]
    for y in range(int(min(ys)), int(max(ys)) + 1):
        xs = []
        for i in range(3):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % 3]
            if (ay <= y < by) or (by <= y < ay):
                xs.append(ax + (bx - ax) * (y - ay) / (by - ay))
        if len(xs) >= 2:
            r.rect(min(xs), y, max(xs), y, c)


def draw_wings(r, kind, cx, by, bw, bh, frame):
    """Behind the body - the biggest silhouette cue there is."""
    if kind == "none":
        return
    flap = 2 if frame else -1
    for sd in (-1, 1):
        wx = cx + sd * bw * 0.80
        if kind == "small":                      # rounded nubs
            r.ellipse(wx + sd * 2, by - 1 + flap * 0.4, 3.6, 4.8, "s")
            r.ellipse(wx + sd * 2, by - 2 + flap * 0.4, 1.8, 2.6, "m")
        elif kind == "feather":                  # three splayed quills
            for i in range(3):
                a = -0.35 + i * 0.45
                ln = 9 - i * 1.5
                stroke(r, wx, by + 1,
                       wx + sd * math.cos(a) * ln, by - math.sin(a) * ln - flap,
                       1.6 - i * 0.25, "s")
            r.ellipse(wx + sd * 2, by, 2.4, 3.0, "m")
        elif kind == "bat":                      # filled membrane
            tip = (wx + sd * 9, by - 7 - flap)
            fill_tri(r, [(wx, by + 4), tip, (wx + sd * 8, by + 3)], "s")
            fill_tri(r, [(wx, by + 4), tip, (wx + sd * 3, by - 1)], "s")
            stroke(r, wx, by + 3, tip[0], tip[1], 1.1, "s")
        elif kind == "shard":                    # crystalline planes
            for i in range(2):
                fill_tri(r, [(wx, by + 3),
                             (wx + sd * (7 + i * 2), by - 4 - i * 4 - flap),
                             (wx + sd * (5 + i * 2), by + 1 - i * 2)], "a")
            r.ellipse(wx + sd * 4, by - 3, 1.2, 1.2, "w")


def draw_tail(r, kind, cx, by, bw, bh, frame):
    if kind == "none":
        return
    sway = 1 if frame else -1
    tx = cx - bw * 0.85
    if kind == "spark":
        stroke(r, cx - bw * 0.5, by + 1, tx - 5, by - 5 + sway, 1.4, "s")
        r.ellipse(tx - 6, by - 6 + sway, 2.8, 2.8, "a")
        r.ellipse(tx - 6.6, by - 6.6 + sway, 1.0, 0.9, "w")
    elif kind == "tuft":
        stroke(r, cx - bw * 0.5, by + 2, tx - 5, by - 2 + sway, 1.4, "s")
        r.ellipse(tx - 7, by - 3 + sway, 3.4, 2.8, "s")
        r.ellipse(tx - 7, by - 4 + sway, 1.5, 1.2, "m")
    elif kind == "curl":                          # a spiral, tapering
        px, py = cx - bw * 0.5, by + 2
        for i in range(7):
            a = i * 0.5
            nx = tx - 2 - math.cos(a) * (5.5 - i * 0.5)
            ny = by + 1 - math.sin(a) * (4.5 - i * 0.35) + sway * 0.4
            stroke(r, px, py, nx, ny, 1.5 - i * 0.12, "s")
            px, py = nx, ny
    elif kind == "fan":                           # three flat blades
        for i in range(3):
            a = -0.25 + i * 0.42
            stroke(r, cx - bw * 0.55, by + 2,
                   tx - 4 - math.cos(a) * 5.5, by + 1 - math.sin(a) * 6.5 + sway,
                   1.3, "s")


def draw_eyes(r, kind, cx, ey, spread, closed, look=0, happy=False,
              tired=False, dazed=False):
    """Big and glossy. Two highlights is what makes them read as wet, and
    that carries most of the expression in this style."""
    if tired:
        for sd in (-1, 1):
            x = cx + sd * spread
            r.ellipse(x, ey + 5, 4.6, 1.9, "u")
            r.set(x - 5, ey + 3, "u")
            r.set(x + 5, ey + 3, "u")

    if happy and not closed:
        for sd in (-1, 1):                      # ^ ^
            x = cx + sd * spread
            for i, dy in ((-4, 3), (-3, 1), (-2, 0), (-1, -1), (0, -2),
                          (1, -1), (2, 0), (3, 1), (4, 3)):
                r.set(x + i, ey + dy, "k")
                r.set(x + i, ey + dy + 1, "k")
        return

    for sd in (-1, 1):
        x = cx + sd * spread + look
        if closed or kind == "closed":
            for i in range(-5, 6):              # a soft closed curve
                r.set(x + i, ey + (1 if abs(i) > 3 else 0), "k")
                r.set(x + i, ey + (2 if abs(i) > 3 else 1), "k")
            continue
        if kind == "sharp":                     # narrowed, half-lidded
            r.ellipse(x, ey, 3.6, 3.4, "w")
            r.ellipse(x, ey + 0.6, 2.6, 2.6, "k")
            r.rect(x - 4, ey - 4, x + 4, ey - 1.6, None)
            r.line(x - 4, ey - 1.6, x + 4, ey - 2.2, "k")
            r.set(x - 1, ey, "w")
            continue
        r.ellipse(x, ey, 3.3, 3.9, "w")         # the big wet eye
        if dazed:
            r.ellipse(x + sd * 0.8, ey + 0.8, 2.1, 2.4, "k")
        else:
            r.ellipse(x, ey + 0.3, 2.4, 2.9, "k")
        if kind == "glow":
            r.ellipse(x, ey + 0.3, 1.2, 1.6, "a")
        r.ellipse(x - 1.2, ey - 1.5, 1.2, 1.1, "w")     # main highlight
        r.set(x + 1.4, ey + 1.4, "w")                   # counter-glint


def draw_mouth(r, cx, my, kind, drool=0):
    if kind == "grin":                          # wide open, tongue showing
        r.ellipse(cx, my + 1, 5.4, 3.4, "k")
        r.ellipse(cx, my + 2.6, 3.4, 1.9, "t")
        r.set(cx - 5, my, "k")
        r.set(cx + 5, my, "k")
    elif kind == "open":
        r.ellipse(cx, my + 1, 2.4, 2.0, "k")
        r.ellipse(cx, my + 1.8, 1.4, 1.0, "t")
    elif kind == "chew":
        r.rect(cx - 2, my + 1, cx + 2, my + 1, "k")
        r.set(cx - 3, my, "k")
        r.set(cx + 3, my, "k")
    elif kind == "smile":                       # a small w, cat-like
        r.set(cx - 4, my - 1, "k")
        r.set(cx - 3, my, "k")
        r.set(cx - 2, my + 1, "k")
        r.set(cx - 1, my, "k")
        r.set(cx, my - 1, "k")
        r.set(cx + 1, my, "k")
        r.set(cx + 2, my + 1, "k")
        r.set(cx + 3, my, "k")
        r.set(cx + 4, my - 1, "k")
    elif kind == "flat":
        r.rect(cx - 3, my + 1, cx + 3, my + 1, "k")
    elif kind == "frown":
        r.set(cx - 4, my + 2, "k")
        r.set(cx + 4, my + 2, "k")
        r.rect(cx - 3, my, cx + 3, my + 1, "k")
        r.set(cx - 3, my + 1, "k")
        r.set(cx + 3, my + 1, "k")
    elif kind == "wavy":
        for i, dy in ((-4, 1), (-3, 0), (-2, -1), (-1, 0), (0, 1), (1, 0),
                      (2, -1), (3, 0), (4, 1)):
            r.set(cx + i, my + dy, "k")
    elif kind == "gape":                        # asleep: wide, thin, slack
        r.ellipse(cx, my + 1, 5.2, 1.5, "k")
        r.rect(cx - 5, my + 1, cx + 5, my + 1, "k")
        r.set(cx - 6, my, "k")
        r.set(cx + 6, my, "k")
    elif kind == "oh":
        r.ellipse(cx, my + 1, 2.0, 2.4, "k")

    if drool:
        dx = cx + 4
        r.rect(dx, my + 2, dx + 1, my + 2 + drool * 2, "q")
        r.ellipse(dx + 0.5, my + 4 + drool * 2, 1.7, 2.1, "q")
        r.set(dx, my + 3 + drool * 2, "w")


def build_sprite(species, pose="idle", frame=0, pack=False, dirt=0):
    """One pose of one creature.

    Built as head + body + limbs rather than as a single blob, which is what
    lets the chibi proportions read: the head is nearly as wide as the whole
    creature and carries all the expression."""
    d = SPECIES[species]
    bw, bh = d["size"]
    r = Raster()
    cx = GRID // 2
    base = BASELINE

    squash, lift, lean = 0.0, 0, 0
    if pose == "idle":
        squash = 0.05 if frame else -0.02
        lift = 1 if frame else 0
    elif pose == "walk":
        squash = 0.04 if frame else -0.04
        lift = 1 if frame else 0
        lean = 1 if frame else -1
    elif pose == "hop":
        squash = -0.10
        lift = 3
    elif pose == "squat":
        squash = 0.16
    elif pose == "sleep":
        squash = 0.12
    elif pose == "dangle":
        squash = -0.13
        lift = 1
    elif pose == "land":
        squash = 0.26

    # ---- proportions ------------------------------------------------------
    leg_h = 4
    body_rx = bw * 0.66 * (1 + squash)
    body_ry = bh * 0.42 * (1 - squash)
    head_rx = bw * 0.92 * (1 + squash * 0.5)
    head_ry = bh * 0.66 * (1 - squash * 0.5)

    body_cy = base - leg_h - body_ry - lift
    head_cy = body_cy - body_ry - head_ry + 3.5
    head_top = head_cy - head_ry

    # ---- behind the body --------------------------------------------------
    draw_tail(r, d.get("tail", "none"), cx, body_cy, body_rx, body_ry, frame)
    draw_wings(r, d.get("wings", "none"), cx, body_cy, body_rx, body_ry, frame)

    # ---- legs -------------------------------------------------------------
    step = (2 if frame else -2) if pose == "walk" else 0
    if pose == "dangle":
        for sd in (-1, 1):
            lx = cx + sd * body_rx * 0.42
            r.rect(lx - 1.4, body_cy + body_ry - 1, lx + 1.4, base, "s")
            r.ellipse(lx + sd * (1 if frame else 0), base, 3.4, 2.2, "s")
    elif pose == "land":
        for sd in (-1, 1):
            r.ellipse(cx + sd * body_rx * 1.05, base - 1, 4.2, 2.0, "s")
    else:
        for sd, off in ((-1, step), (1, -step)):
            lx = cx + sd * body_rx * 0.46 + off * 0.5
            r.rect(lx - 1.6, body_cy + body_ry - 2, lx + 1.6, base - 1.5, "s")
            r.ellipse(lx + off * 0.4, base - 1, 3.6, 2.4, "s")

    # ---- body -------------------------------------------------------------
    r.ellipse(cx, body_cy, body_rx, body_ry, "b")
    r.ellipse(cx, body_cy + body_ry * 0.26, body_rx * 0.52, body_ry * 0.58, "m")

    # ---- arms -------------------------------------------------------------
    for sd in (-1, 1):
        ax = cx + sd * body_rx * 0.88
        ay = body_cy - body_ry * 0.15
        if pose == "wave" and sd == 1:
            r.ellipse(ax + 2, ay - body_ry - (1 if frame else 0), 2.2, 2.8, "s")
            r.line(ax, ay, ax + 2, ay - body_ry, "s")
            r.line(ax + 1, ay, ax + 3, ay - body_ry, "s")
        elif pose == "dangle":
            r.ellipse(ax + sd, ay + 3, 2.2, 3.0, "s")
        elif pose in ("eat", "happy", "bath"):
            r.ellipse(ax, ay - 1, 2.4, 2.3, "s")
        else:
            r.ellipse(ax, ay + (0.6 if frame else 0), 2.2, 2.7, "s")

    # ---- head -------------------------------------------------------------
    draw_ears(r, d["ears"], cx, head_cy, head_rx, head_ry)
    r.ellipse(cx, head_cy, head_rx, head_ry, "b")
    r.ellipse(cx, head_cy + head_ry * 0.42, head_rx * 0.56, head_ry * 0.44, "m")
    draw_horns(r, d["crest"], cx, head_cy, head_rx, head_ry)

    # ---- face -------------------------------------------------------------
    ey = head_cy - head_ry * 0.02
    closed = pose in ("sleep", "blink", "land")
    content = pose in ("eat", "bath")
    tired = pose in ("sad", "sick")
    draw_eyes(r, d["eyes"], cx + lean, ey, max(5.0, head_rx * 0.44), closed,
              happy=content, tired=tired, dazed=(pose == "sick"))

    if pose == "sick":
        for sd in (-1, 1):
            r.ellipse(cx + sd * head_rx * 0.72, ey + 5, 3.0, 1.8, "f")
            r.set(cx + sd * head_rx * 0.72 - 2, ey + 4, "f")
    elif pose not in ("sad",):                   # blush is the default here
        for sd in (-1, 1):
            r.ellipse(cx + sd * head_rx * 0.74, ey + 5, 2.6, 1.5, "p")

    my = ey + head_ry * 0.52 + 2
    drool = 0
    if pose == "eat":
        mouth = "open" if frame == 0 else "chew"
    elif pose == "bath":
        mouth = "grin"
    elif pose == "sleep":
        mouth = "gape"
        drool = 1 + frame
    elif pose == "dangle":
        mouth = "oh"
    elif pose == "land":
        mouth = "flat"
    elif pose in ("happy", "play", "wave"):
        mouth = "grin"
    else:
        mouth = {"sad": "frown", "sick": "wavy"}.get(pose, "smile")
    draw_mouth(r, cx + lean, my, mouth, drool)

    # ---- extras -----------------------------------------------------------
    if dirt:
        spots = [(-0.45, 0.55), (0.40, 0.30), (0.05, 0.72), (-0.15, 0.15),
                 (0.55, 0.62), (-0.62, 0.32)]
        for ox, oy in spots[:dirt * 2]:
            r.ellipse(cx + ox * body_rx * 1.1, body_cy + (oy - 0.4) * body_ry * 2,
                      2.4, 1.8, "d")

    if pack:                       # a suitcase, set down beside it
        sx = max(9, cx - body_rx - head_rx * 0.35 - 4)
        sy = base - 1
        r.rect(sx - 6, sy - 11, sx + 6, sy - 1, "a")
        r.rect(sx - 6, sy - 11, sx + 6, sy - 9, "s")
        r.rect(sx - 6, sy - 5, sx + 6, sy - 4, "s")
        r.rect(sx - 2, sy - 14, sx + 2, sy - 12, "s")
        for i in range(-2, 3):
            r.set(sx + i, sy - 13, None)
        r.set(sx - 4, sy - 8, "w")
        r.set(sx + 4, sy - 8, "w")
        r.rect(sx - 5, sy - 1, sx - 3, sy, "k")
        r.rect(sx + 3, sy - 1, sx + 5, sy, "k")

    r.outline("k")
    return r


MEDIC_PAL = {"c": "#F4F7FA", "s": "#C6D2DC", "n": "#F0C49A", "h": "#3A2A20",
             "r": "#E05B5B", "g": "#9FB4C2", "t": "#7FD1B9", "k": "#22303A",
             "b": "#F4F7FA", "l": "#FFFFFF", "a": "#E05B5B", "w": "#FFFFFF"}

MEDIC_W, MEDIC_H = 40, 46      # wide enough for the syringe arm to swing
MEDIC_CX = 17                  # sits left of centre, leaving room on the right
MEDIC_BASE = 41


def build_medic(pose="walk", frame=0):
    """A small pixel medic: big head, cross cap, and a syringe with something
    green in it. Poses: walk, raise, inject, wave."""
    r = Raster(MEDIC_W, MEDIC_H)
    cx, base = MEDIC_CX, MEDIC_BASE
    swing = (2 if frame else -2) if pose == "walk" else 0

    # legs and boots
    for sd, off in ((-1, swing), (1, -swing)):
        lx = cx + sd * 2.5
        r.rect(lx - 1, base - 7, lx + 1, base - 2, "s")
        r.rect(lx - 2 + off * 0.5, base - 2, lx + 2 + off * 0.5, base, "k")

    # coat - kept small so the head reads as the big friendly bit
    r.ellipse(cx, base - 13, 5.4, 6.2, "c")
    r.rect(cx - 5, base - 13, cx + 5, base - 7, "c")
    r.line(cx, base - 18, cx, base - 7, "s")           # seam
    r.rect(cx - 5, base - 8, cx + 5, base - 7, "s")    # hem

    # head, deliberately oversized
    r.ellipse(cx, base - 25, 6.4, 6.0, "n")
    r.ellipse(cx, base - 28, 6.4, 3.2, "h")            # hair
    r.ellipse(cx - 3, base - 25, 1.2, 1.4, "k")        # eyes
    r.ellipse(cx + 3, base - 25, 1.2, 1.4, "k")
    r.set(cx - 3, base - 26, "w")
    r.set(cx + 3, base - 26, "w")
    r.rect(cx - 1, base - 22, cx + 1, base - 22, "k")  # smile
    r.set(cx - 2, base - 23, "k")
    r.set(cx + 2, base - 23, "k")
    r.ellipse(cx - 5, base - 23, 1.4, 1.0, "r")        # cheeks
    r.ellipse(cx + 5, base - 23, 1.4, 1.0, "r")

    # cap with a cross
    r.rect(cx - 6, base - 33, cx + 6, base - 30, "c")
    r.rect(cx - 7, base - 30, cx + 7, base - 29, "s")
    r.rect(cx - 1, base - 33, cx + 1, base - 30, "r")
    r.rect(cx - 3, base - 32, cx + 3, base - 31, "r")

    # arms, and what's in the right hand
    if pose == "raise":
        hx, hy = cx + 10, base - 27
    elif pose == "inject":
        hx, hy = cx + 12, base - 16
    elif pose == "wave":
        hx, hy = cx + 10, base - 28
    else:
        hx, hy = cx + 8, base - 15 + swing
    r.line(cx + 4, base - 17, hx, hy, "c")
    r.line(cx - 4, base - 17, cx - 7, base - 13 - swing, "c")

    if pose in ("raise", "inject"):
        r.rect(hx - 1, hy - 5, hx + 1, hy + 1, "g")            # barrel
        r.rect(hx - 1, hy - 3, hx + 1, hy + 1, "t")            # contents
        r.rect(hx - 2, hy - 7, hx + 2, hy - 6, "g")            # plunger
        r.line(hx, hy + 2, hx + 3, hy + 4, "g")                # needle
    elif pose == "wave":
        r.ellipse(hx, hy - 1, 1.8, 1.8, "n")

    r.outline("k")
    return r


class SpriteBank:
    """Lazily rasterises and caches PhotoImages. Tk images must live on the
    main thread, and PhotoImage is garbage collected if unreferenced."""

    def __init__(self):
        self.cache = {}

    def get(self, species, pose="idle", frame=0, flat=None, pack=False, dirt=0,
            tint=0):
        key = (species, pose, frame, flat, pack, dirt, tint)
        img = self.cache.get(key)
        if img is None:
            r = build_sprite(species, pose, frame, pack, dirt)
            img = r.to_image(_palette(species, tint), flat=flat)
            self.cache[key] = img
        return img

    def medic(self, pose="walk", frame=0):
        key = ("_medic", pose, frame)
        img = self.cache.get(key)
        if img is None:
            img = build_medic(pose, frame).to_image(MEDIC_PAL)
            self.cache[key] = img
        return img

    def sponge(self, squish=0):
        key = ("_sponge", squish)
        img = self.cache.get(key)
        if img is not None:
            return img
        r = Raster(20, 16)
        cx, cy = 10, 8
        w, h = 7.5 + squish, 5.0 - squish * 0.6
        r.rect(cx - w, cy - h, cx + w, cy + h, "b")           # body
        r.rect(cx - w, cy - h, cx + w, cy - h + 1.5, "l")     # lighter top
        for hx, hy in ((-4, -1), (-1, 2), (2, -2), (4, 1), (0, -3), (-5, 2)):
            r.ellipse(cx + hx, cy + hy, 1.3, 1.0, "s")        # the holes
        r.outline("k")
        return self._store(key, r, {
            "b": "#F2CE5C", "l": "#FBE79B", "s": "#C79E2E", "w": "#FFFFFF",
            "a": "#F2CE5C", "k": "#5C4610"})

    def tub(self):
        key = ("_tub", 0)
        img = self.cache.get(key)
        if img is not None:
            return img
        r = Raster(52, 24)
        cx, base = 26, 20
        r.rect(cx - 17, base - 10, cx + 17, base, "b")          # body
        r.rect(cx - 17, base - 10, cx + 17, base - 8, "s")      # rim
        r.rect(cx - 15, base - 7, cx + 15, base - 3, "l")       # water
        for dx in (-11, -4, 4, 11):                             # staves
            r.rect(cx + dx, base - 8, cx + dx + 1, base, "s")
        r.rect(cx - 17, base - 4, cx + 17, base - 3, "s")       # hoop
        r.ellipse(cx - 20, base - 2, 2.5, 2.0, "s")             # feet
        r.ellipse(cx + 20, base - 2, 2.5, 2.0, "s")
        r.outline("k")
        return self._store(key, r, {
            "b": "#B5743F", "s": "#8A5427", "l": "#9FD8E8", "w": "#FFFFFF",
            "a": "#9FD8E8", "k": "#3D2513"})

    def food(self, bites):
        """A cupcake: ridged wrapper, frosting, cherry. Eaten in four stages."""
        bites = max(0, min(3, int(bites)))
        key = ("_food", bites)
        img = self.cache.get(key)
        if img is not None:
            return img
        r = Raster(26, 26)
        cx, base = 13, 22

        # wrapper: a trapezoid, wider at the top
        for i, y in enumerate(range(base - 8, base + 1)):
            half = 7 - i * 0.45
            r.rect(cx - half, y, cx + half, y, "b")
        for dx in (-5, -2, 1, 4):                      # ridges, 2 cells wide
            for i, y in enumerate(range(base - 8, base + 1)):
                sq = dx * (1 - i * 0.06)
                r.set(cx + sq, y, "s")
                r.set(cx + sq + 1, y, "s")

        # frosting: two overlapping domes so it reads as a swirl
        r.ellipse(cx, base - 10, 7.5, 4.2, "l")
        r.ellipse(cx - 2, base - 13, 4.6, 3.4, "l")
        r.ellipse(cx + 2.5, base - 12, 4.0, 3.0, "l")
        r.ellipse(cx - 3, base - 13, 2.0, 1.4, "w")    # highlight

        # cherry, chunky enough to survive the outline
        r.ellipse(cx + 1, base - 17, 2.6, 2.6, "a")
        r.set(cx, base - 18, "w")
        r.rect(cx + 1, base - 20, cx + 2, base - 19, "s")   # 2-wide stem

        if bites >= 3:
            # last stage: one chunky crumb, not a thin sliver
            r = Raster(26, 26)
            r.rect(cx - 3, base - 4, cx + 2, base, "b")
            r.rect(cx - 2, base - 4, cx - 1, base, "s")
            r.rect(cx + 1, base - 4, cx + 2, base, "s")
            r.ellipse(cx - 1, base - 5, 2.6, 1.6, "l")
            r.outline("k")
            return self._store(key, r, {
                "b": "#D98C4A", "s": "#A9642F", "l": "#F7E3C0", "w": "#FFF8EC",
                "a": "#E05B5B", "k": "#4A2A12"})

        if bites:
            # scoop rounded bites out of the right-hand side
            for i in range(bites):
                bx = 26 - 1 - i * 5
                by = base - 13 + i * 3
                for y in range(r.h):
                    for x in range(r.w):
                        if ((x - bx) / 7.5) ** 2 + ((y - by) / 8.5) ** 2 <= 1.0:
                            r.g[y][x] = None
            if bites >= 2:                              # cherry is long gone
                for y in range(0, base - 14):
                    for x in range(r.w):
                        r.g[y][x] = None

        r.outline("k")
        return self._store(key, r, {
            "b": "#D98C4A", "s": "#A9642F", "l": "#F7E3C0", "w": "#FFF8EC",
            "a": "#E05B5B", "k": "#4A2A12"})

    def _store(self, key, raster, pal):
        img = raster.to_image(pal)
        self.cache[key] = img
        return img

    def poop(self):
        key = ("_poop", 0)
        img = self.cache.get(key)
        if img is not None:
            return img
        r = Raster(16, 16)
        r.ellipse(8, 13, 6.0, 2.6, "b")               # base coil
        r.ellipse(8, 10, 4.2, 2.2, "b")
        r.ellipse(8, 7.5, 2.6, 1.8, "b")
        r.ellipse(7, 12.5, 2.0, 1.0, "l")             # highlight
        r.set(6, 10, "l")
        r.outline("k")
        pal = {"b": "#8A5A3B", "l": "#A9764F", "k": "#3A2416",
               "s": "#6B432A", "a": "#8A5A3B", "w": "#FFFFFF"}
        img = r.to_image(pal)
        self.cache[key] = img
        return img

    def egg(self, crack):
        step = min(3, int(crack * 4))
        key = ("_egg", step)
        img = self.cache.get(key)
        if img is not None:
            return img
        r = Raster()
        cx, base = GRID // 2, BASELINE
        r.ellipse(cx, base - 11, 9, 11.5, "b")
        r.ellipse(cx - 3, base - 16, 2.5, 2.0, "l")
        r.ellipse(cx + 4, base - 12, 2.0, 1.6, "l")
        r.ellipse(cx - 1, base - 6, 2.2, 1.8, "l")
        if step:
            y = base - 12
            for i in range(step * 3 + 2):
                x = cx - 8 + i * 2
                r.set(x, y + (2 if i % 2 else -2), "k")
                r.set(x + 1, y, "k")
        r.outline("k")
        pal = {"b": EGG, "l": EGG_SPOT, "k": BODY_DARK, "s": BODY_DARK,
               "a": ACCENT, "w": "#FFFFFF"}
        img = r.to_image(pal)
        self.cache[key] = img
        return img


# ----------------------------------------------------------------------------
# The Motelight line - an original family, drawn from scratch.
#
# The MECHANIC is the borrowed part (branching evolution gated on how the
# creature was raised); the creatures themselves are mine. Every form is a
# light-keeper of some kind: what it does with the light it stores depends
# entirely on how you treated it.
# ----------------------------------------------------------------------------
STAGE2_HOURS = 8.0          # baby -> middle form
STAGE3_HOURS = 36.0         # middle -> final form

SPECIES = {
    "mote": dict(
        title="Mote", tier=0, size=(11, 10), ears="none", eyes="big",
        crest="bulb", tail="none",
        blurb="a spark that hasn't decided what to be",
        pal=("#7FD1B9", "#57B49B", "#DCF4EC", "#1E3A34", "#FFD166")),

    "wick": dict(
        title="Wick", tier=1, size=(13, 12), ears="small", eyes="big",
        crest="flame", tail="none",
        blurb="kept warm and fed, so it burns steady",
        pal=("#7FD1B9", "#4FAE94", "#DCF4EC", "#1E3A34", "#FFC24A")),

    "cinder": dict(
        title="Cinder", tier=1, size=(12, 12), ears="tuft", eyes="sharp",
        crest="smoke", tail="none",
        blurb="ran cold too often and learned to guard its heat",
        pal=("#8C93A8", "#6A7186", "#D6DAE6", "#1B1D26", "#E8703F")),

    "lumen": dict(
        title="Lumen", tier=2, size=(14, 14), ears="long", eyes="glow",
        crest="halo", tail="spark",
        blurb="played with constantly - it gives its light away freely",
        pal=("#8FE0C4", "#54B896", "#EAFBF3", "#17332B", "#FFE08A")),

    "halo": dict(
        title="Halo", tier=2, size=(15, 13), ears="small", eyes="big",
        crest="ring", tail="none",
        blurb="fed and comfortable - round, calm, endlessly patient",
        pal=("#F3D9A4", "#D4B173", "#FFF6E4", "#33261A", "#FFFFFF")),

    "ember": dict(
        title="Ember", tier=2, size=(13, 14), ears="tuft", eyes="sharp",
        crest="flame", tail="spark",
        blurb="went hungry, then came back - and kept the fire",
        pal=("#E8825C", "#C05B39", "#FFD9C4", "#2A1610", "#FFC24A")),

    "cairn": dict(
        title="Cairn", tier=2, size=(14, 12), ears="none", eyes="closed",
        crest="crystal", tail="none",
        blurb="left alone long enough that it went quiet and hard",
        pal=("#7E869B", "#5A6175", "#C9CEDC", "#15171F", "#7FB6D9")),

    "prism": dict(
        title="Prism", tier=2, size=(12, 15), ears="tuft", eyes="glow",
        crest="crystal", tail="spark",
        blurb="never once sick, never once bored - it splits light now",
        pal=("#B9A9F2", "#8B76D9", "#F0EBFF", "#1E1733", "#79E8D6")),

    # ---- Tideglass: keeps its light underwater ----
    "drip": dict(
        title="Drip", tier=0, size=(11, 10), ears="none", eyes="big",
        crest="drop", tail="none",
        blurb="a held breath that hasn't surfaced yet",
        pal=("#7FBDE0", "#4F92C0", "#DCEFFA", "#12293B", "#BFEFFF")),
    "rill": dict(
        title="Rill", tier=1, size=(13, 12), ears="fin", eyes="big",
        crest="drop", tail="none",
        blurb="never let to run dry, so it runs clear",
        pal=("#6FC6DE", "#3F97B4", "#DFF6FA", "#0F2A33", "#CFF6FF")),
    "silt": dict(
        title="Silt", tier=1, size=(12, 12), ears="none", eyes="sharp",
        crest="smoke", tail="none",
        blurb="left standing too long and went cloudy",
        pal=("#8A9A8F", "#66766C", "#D5DFD8", "#1A211C", "#9FC4A8")),
    "cascade": dict(
        title="Cascade", tier=2, size=(14, 14), ears="fin", eyes="glow",
        crest="drop", tail="spark",
        blurb="played with until it couldn't hold still",
        pal=("#63C9E8", "#2F8FB4", "#E4FAFF", "#0C2530", "#FFFFFF")),
    "lagoon": dict(
        title="Lagoon", tier=2, size=(15, 13), ears="small", eyes="big",
        crest="ring", tail="none",
        blurb="fed and unhurried - warm all the way down",
        pal=("#5FC4B4", "#348C80", "#E0FAF4", "#0E2B27", "#FFE9A8")),
    "nautilus": dict(
        title="Nautilus", tier=2, size=(12, 15), ears="fin", eyes="glow",
        crest="shell", tail="spark",
        blurb="perfectly kept - it grew a chamber for every day",
        pal=("#F0D8C0", "#C79E7C", "#FFF4E8", "#2B1D14", "#7FD8E8")),
    "brack": dict(
        title="Brack", tier=2, size=(13, 14), ears="tuft", eyes="sharp",
        crest="drop", tail="spark",
        blurb="went brackish, then cleared - and kept the salt",
        pal=("#7A9E86", "#4E7059", "#DCEEE0", "#141F18", "#C0E86F")),
    "salt": dict(
        title="Salt", tier=2, size=(14, 12), ears="none", eyes="closed",
        crest="crystal", tail="none",
        blurb="evaporated slowly until only the mineral was left",
        pal=("#C9CBC4", "#9B9E96", "#F2F3EF", "#26251F", "#E8E4D0")),

    # ---- Thornwake: keeps its light as growth ----
    "sprig": dict(
        title="Sprig", tier=0, size=(11, 10), ears="none", eyes="big",
        crest="leaf", tail="none",
        blurb="two leaves and an enormous opinion of itself",
        pal=("#9BD06A", "#6BA243", "#E8F8D4", "#1D2E12", "#FFD166")),
    "bramble": dict(
        title="Bramble", tier=1, size=(13, 12), ears="frond", eyes="big",
        crest="leaf", tail="none",
        blurb="given room and water, and it took both",
        pal=("#8FCB63", "#5F9C3E", "#E6F7D0", "#1B2A11", "#FFC24A")),
    "thistle": dict(
        title="Thistle", tier=1, size=(12, 12), ears="tuft", eyes="sharp",
        crest="thorn", tail="none",
        blurb="grew where nothing helped it, and it shows",
        pal=("#9E8FA8", "#75677E", "#E4DCEA", "#1F1A24", "#C86FA8")),
    "bloom": dict(
        title="Bloom", tier=2, size=(14, 14), ears="frond", eyes="glow",
        crest="petal", tail="spark",
        blurb="played with daily until it opened all the way",
        pal=("#F2A0C0", "#C86F94", "#FFE8F2", "#331A26", "#FFE08A")),
    "orchard": dict(
        title="Orchard", tier=2, size=(15, 13), ears="small", eyes="big",
        crest="petal", tail="none",
        blurb="fed well and often - now it feeds other things",
        pal=("#E8B45C", "#BC873A", "#FFF0D4", "#2E2010", "#9BD06A")),
    "wilder": dict(
        title="Wilder", tier=2, size=(12, 15), ears="frond", eyes="glow",
        crest="thorn", tail="spark",
        blurb="never once sick, never once trimmed - it went everywhere",
        pal=("#6FD9A0", "#3FA470", "#DFFCEC", "#0F2A1C", "#FFEE99")),
    "barb": dict(
        title="Barb", tier=2, size=(13, 14), ears="tuft", eyes="sharp",
        crest="thorn", tail="spark",
        blurb="went hungry and came back with defences",
        pal=("#A88B6F", "#7C6349", "#EADCC8", "#241A11", "#E8703F")),
    "husk": dict(
        title="Husk", tier=2, size=(14, 12), ears="none", eyes="closed",
        crest="smoke", tail="none",
        blurb="dried out quietly while nobody was watching",
        pal=("#9A9078", "#726A56", "#DED7C4", "#211D15", "#B8A87F")),
}

# Which line you get is decided at hatch, at random - like an unlabelled egg.
LINES = {
    "motelight": dict(baby="mote", good="wick", bad="cinder",
                      good_finals=("lumen", "halo", "prism"),
                      bad_finals=("ember", "cairn")),
    "tideglass": dict(baby="drip", good="rill", bad="silt",
                      good_finals=("cascade", "lagoon", "nautilus"),
                      bad_finals=("brack", "salt")),
    "thornwake": dict(baby="sprig", good="bramble", bad="thistle",
                      good_finals=("bloom", "orchard", "wilder"),
                      bad_finals=("barb", "husk")),
}

# Silhouette features, applied after the table above so the entries stay
# readable. Wings and tails are what let you tell two forms apart across the
# room - colour alone doesn't do it at this size.
_TRAITS = {
    # motelight
    "mote":      ("none",    "none"),
    "wick":      ("none",    "tuft"),
    "cinder":    ("none",    "curl"),
    "lumen":     ("feather", "spark"),
    "halo":      ("small",   "tuft"),
    "prism":     ("shard",   "spark"),
    "ember":     ("bat",     "spark"),
    "cairn":     ("none",    "none"),
    # tideglass
    "drip":      ("none",    "none"),
    "rill":      ("small",   "fan"),
    "silt":      ("none",    "curl"),
    "cascade":   ("feather", "fan"),
    "lagoon":    ("small",   "curl"),
    "nautilus":  ("shard",   "curl"),
    "brack":     ("bat",     "fan"),
    "salt":      ("none",    "none"),
    # thornwake
    "sprig":     ("none",    "none"),
    "bramble":   ("small",   "tuft"),
    "thistle":   ("none",    "fan"),
    "bloom":     ("feather", "tuft"),
    "orchard":   ("small",   "curl"),
    "wilder":    ("feather", "fan"),
    "barb":      ("bat",     "tuft"),
    "husk":      ("none",    "curl"),
}

for _k, (_wings, _tail) in _TRAITS.items():
    if _k in SPECIES:
        SPECIES[_k]["wings"] = _wings
        SPECIES[_k]["tail"] = _tail
for _d in SPECIES.values():
    _d.setdefault("wings", "none")
    _d.setdefault("tail", "none")


FIRST = "mote"


def line_of(species):
    for key, L in LINES.items():
        if species in (L["baby"], L["good"], L["bad"]) + L["good_finals"] + L["bad_finals"]:
            return L
    return LINES["motelight"]


def forecast(p):
    """What it's currently heading toward, ignoring time. None if fully grown."""
    L = line_of(p.species)
    sp = p.species
    if sp == L["baby"]:
        return L["good"] if p.care >= 0.60 else L["bad"]
    if sp == L["good"]:
        if (not p.ever_sick and p.care >= 0.85 and p.play_count >= 12
                and p.play_count >= 25):
            return L["good_finals"][2]                    # the rare one
        return L["good_finals"][0] if p.play_count >= p.feed_count else L["good_finals"][1]
    if sp == L["bad"]:
        return L["bad_finals"][0] if p.care >= 0.50 else L["bad_finals"][1]
    return None


def next_form(p):
    """Same, but only once the age gate has passed."""
    age_h = (time.time() - p.born) / 3600.0
    gate = STAGE2_HOURS if SPECIES[p.species]["tier"] == 0 else STAGE3_HOURS
    return forecast(p) if age_h >= gate else None


# ----------------------------------------------------------------------------
class Pet:
    def __init__(self):
        self.name    = "Pip"
        self.born    = time.time()
        self.hunger  = 80.0
        self.happy   = 80.0
        self.energy  = 90.0
        self.sick    = False
        self.neglect = 0.0          # seconds spent at zero on something
        self.wellness = 0.0         # seconds spent healthy (clears sickness)
        self.hatched = False
        self.last_seen = time.time()
        self.species = FIRST
        self.personality = random.choice(list(PERSONALITIES))
        self.care = 0.8          # rolling average of how well it's been kept
        self.play_count = 0
        self.feed_count = 0
        self.notif_count = 0
        self.quiz_right = 0
        self.quiz_asked = 0
        self.hygiene = 100.0
        self.illness = 0         # 0 well, 1-3 how badly it's doing
        self.tint = random.randint(1, 9999)   # this pet's own shade
        self.departure = random.randrange(len(DEPARTURES))
        self.stay_weeks = 0      # times you've asked it to stay on
        self.left = False
        self.grime = 0.0
        self.poops = []          # [id, x, y] in screen coordinates
        self.ever_sick = False
        self.history = []        # [(species, timestamp)]

    # ---- persistence -------------------------------------------------------
    def to_dict(self):
        return {
            "name": self.name, "born": self.born, "hunger": self.hunger,
            "happy": self.happy, "energy": self.energy, "sick": self.sick,
            "neglect": self.neglect, "wellness": self.wellness,
            "hatched": self.hatched, "last_seen": time.time(),
            "species": self.species, "care": self.care,
            "personality": self.personality,
            "play_count": self.play_count, "feed_count": self.feed_count,
            "notif_count": self.notif_count, "ever_sick": self.ever_sick,
            "quiz_right": self.quiz_right, "quiz_asked": self.quiz_asked,
            "hygiene": self.hygiene, "grime": self.grime, "poops": self.poops,
            "illness": self.illness,
            "stay_weeks": self.stay_weeks, "left": self.left, "tint": self.tint,
            "departure": self.departure,
            "history": self.history,
        }

    @classmethod
    def load(cls):
        p = cls()
        try:
            with open(save_path(), "r", encoding="utf-8") as f:
                d = json.load(f)
            for k in ("name", "born", "hunger", "happy", "energy",
                      "sick", "neglect", "wellness", "hatched", "last_seen",
                      "species", "care", "personality", "play_count", "feed_count",
                      "notif_count", "ever_sick", "history",
                      "quiz_right", "quiz_asked", "hygiene", "grime", "poops",
                      "illness", "stay_weeks", "left", "tint", "departure"):
                if k in d:
                    setattr(p, k, d[k])
            away_h = min((time.time() - p.last_seen) / 3600.0, OFFLINE_CAP_H)
            if away_h > 0:
                p.hunger = clamp(p.hunger - 100.0 * away_h / HUNGER_HOURS)
                p.happy  = clamp(p.happy  - 100.0 * away_h / HAPPY_HOURS)
                # sleeps while you're gone, so energy recovers a little
                p.energy = clamp(p.energy + 40.0 * away_h)
            if p.species not in SPECIES:
                p.species = FIRST
            if p.personality not in PERSONALITIES:
                p.personality = random.choice(list(PERSONALITIES))
            p.existing = True
        except Exception:
            p.existing = False
        return p

    def save(self):
        try:
            with open(save_path(), "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=1)
        except Exception:
            pass

    # ---- growth ------------------------------------------------------------
    @property
    def age_days(self):
        return (time.time() - self.born) / 86400.0

    @property
    def stage(self):
        return "egg" if not self.hatched else self.species

    def hatch(self):
        """The only way to hatch. Rolls which line you get and what shade of
        it - do not set self.hatched anywhere else, or you get the default
        line every time."""
        self.hatched = True
        self.species = LINES[random.choice(list(LINES))]["baby"]
        self.tint = random.randint(1, 9999)
        self.departure = random.randrange(len(DEPARTURES))

    @property
    def leaving_reason(self):
        return DEPARTURES[self.departure % len(DEPARTURES)]

    @property
    def dirt(self):
        """0 clean, 3 filthy - drives the smudges and the bath button."""
        h = self.hygiene
        return 0 if h > 70 else 1 if h > 45 else 2 if h > 22 else 3

    @property
    def days_left(self):
        allowed = STAY_DAYS * (1 + self.stay_weeks)
        return allowed - self.age_days

    @property
    def nature(self):
        return PERSONALITIES[self.personality]

    @property
    def title(self):
        return SPECIES[self.species]["title"]

    @property
    def tier(self):
        return SPECIES[self.species]["tier"]

    @property
    def pal(self):
        return SPECIES[self.species]["pal"]

    def evolve_to(self, key):
        self.history.append([self.species, time.time()])
        del self.history[:-8]
        self.species = key

    @property
    def mood(self):
        if self.sick:
            return "sick"
        avg = (self.hunger + self.happy) / 2
        if avg > 65:
            return "great"
        if avg > 35:
            return "ok"
        return "low"

    def tick(self, dt, sleeping):
        if not self.hatched:
            if time.time() - self.born > HATCH_SECONDS:
                self.hatch()
            return
        h = dt / 3600.0
        n = self.nature
        self.hunger = clamp(self.hunger - 100.0 * h / HUNGER_HOURS * n["hunger"])
        drain = 100.0 * h / HAPPY_HOURS * n["happy"] * (1.6 if self.hunger < 20 else 1.0)
        drain *= 1.0 + 0.35 * self.illness
        self.happy = clamp(self.happy - drain)
        if sleeping:
            self.energy = clamp(self.energy + 100.0 * h / SLEEP_RESTORE)
        else:
            self.energy = clamp(self.energy - 100.0 * h / ENERGY_HOURS * n["energy"])

        mess = len(self.poops)
        if mess:
            self.hygiene = clamp(self.hygiene
                                 - 100.0 * h / HYGIENE_HOURS * (0.6 + 0.7 * mess))
        else:
            self.hygiene = clamp(self.hygiene + 100.0 * h / 6.0)

        if self.hygiene < 20:
            self.grime += dt
            if self.grime > GRIME_TO_SICK and not self.sick:
                self.sick = True
                self.illness = max(1, self.illness)
                self.ever_sick = True
        else:
            self.grime = max(0.0, self.grime - dt * 0.5)

        # rolling care average - this is what decides the branch
        now_care = ((self.hunger + self.happy) / 200.0) * (0.5 if self.sick else 1.0)
        k = min(1.0, dt / 900.0)                 # ~15 min smoothing
        self.care = self.care * (1 - k) + now_care * k

        if self.hunger <= 0 or self.happy <= 0:
            self.neglect += dt
            self.wellness = 0.0
            if self.neglect > 1800:
                if not self.sick:
                    self.ever_sick = True
                self.sick = True
                self.illness = max(1, self.illness)
        else:
            self.neglect = max(0.0, self.neglect - dt)
            if self.hunger > 50 and self.happy > 50:
                self.wellness += dt      # being sick now needs treating, not time
            else:
                self.wellness = 0.0


class Litter:
    """One mess on the desktop. Borderless, click-through except for itself."""

    SIZE = scaled(16)

    def __init__(self, app, key, x, y):
        self.app = app
        self.key = key
        w = tk.Toplevel(app.root)
        self.win = w
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        bg = getattr(app, "clear_bg", TRANS)
        try:
            w.wm_attributes("-transparent", True)
        except tk.TclError:
            pass
        w.config(bg=bg)
        n = self.SIZE
        w.geometry(f"{n}x{n}+{int(x - n // 2)}+{int(y - n)}")
        c = tk.Canvas(w, width=n, height=n, bg=bg, highlightthickness=0, bd=0)
        c.pack()
        c.create_image(n // 2, n, image=app.sprites.poop(), anchor="s")
        c.bind("<Button-1>", lambda _e: app.clean_one(self.key))
        self.canvas = c

    def lift(self):
        try:
            self.win.attributes("-topmost", True)
        except Exception:
            pass

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ----------------------------------------------------------------------------
class DeskPet:
    def __init__(self):
        set_dpi_aware()
        self.pet = Pet.load()
        first_run = not getattr(self.pet, "existing", False)

        self.root = tk.Tk()
        self.root.withdraw()

        measure_screen(self.root)
        wa = work_area()
        if wa:
            self.sx0, self.sy0, self.sx1, self.sy1 = wa
        else:
            self.sx0, self.sy0 = 0, 0
            self.sx1 = self.root.winfo_screenwidth()
            self.sy1 = self.root.winfo_screenheight()
        vs = virtual_screen()
        if vs:
            self.vx0, self.vy0, self.vx1, self.vy1 = vs
        else:
            self.vx0, self.vy0, self.vx1, self.vy1 = (self.sx0, self.sy0,
                                                      self.sx1, self.sy1)
        self.floor_y = self.sy1 - 4
        self.last_mon = 0.0
        self.last_stats = 0.0

        if first_run:
            self.pending_intro = True

        self.root.deiconify()
        self.root.attributes("-alpha", 1.0)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # macOS has no colour key. -transparent makes the window background
        # itself clear; widgets painted systemTransparent show through it.
        # The sprites already carry real alpha, so they composite properly.
        self.clear_bg = TRANS
        ok = False
        for bg in ("systemTransparent", "systemWindowBackgroundColor"):
            try:
                self.root.wm_attributes("-transparent", True)
                self.root.config(bg=bg)
                self.clear_bg = bg
                ok = True
                break
            except tk.TclError:
                continue
        if not ok:
            self.root.config(bg=TRANS)
            messagebox.showwarning(
                "DeskPet",
                "This build of Tk won't give a transparent window, so the pet "
                "will sit on a coloured square. Try the python.org build of "
                "Python rather than the system one.")
        self.root.geometry(f"{W}x{H}")

        self.cv = tk.Canvas(self.root, width=W, height=H, bg=self.clear_bg,
                            highlightthickness=0, bd=0)
        self.cv.pack()

        # ---- world state ---
        self.x = (self.sx0 + self.sx1) / 2
        self.y = self.floor_y
        self.vy = 0.0
        self.state = "idle"          # idle walk sleep eat play fall drag hatching
        self.state_t = 0.0
        self.next_think = 2.0
        self.target_x = self.x
        self.facing = 1
        self.hop = 0.0
        self.blink_t = random.uniform(1.5, 4.0)
        self.blink = 0.0
        self.phase = 0.0
        self.bubble = ""
        self.bubble_author = None
        self.bubble_lines = []
        self.bubble_total = 0
        self.bubble_shown = 0.0
        self.bubble_start = 0.0
        self.bubble_rate = 999.0
        self.bubble_t = 0.0
        self.hearts = []
        self.food = None
        self.crack = 0.0
        self.sleeping = False
        self.dragging = False
        self.drag_dx = self.drag_dy = 0
        self.prev_x = self.x
        self.stats_win = None
        self.last_t = time.time()
        self.last_save = time.time()


        self.cfg = load_config()
        self.sprites = SpriteBank()
        import tkinter.font as tkfont
        fam = pick_font(self.root, ["Monaco", "Menlo", "Andale Mono",
                                    "Courier New"], 10)[0]
        # negative size = pixels, not points: immune to display scaling
        self.font_ui = tkfont.Font(family=fam, size=-14)
        self.font_small = tkfont.Font(family=fam, size=-11)
        self.f_head = tkfont.Font(family="Helvetica Neue", size=-18)
        self.f_body = tkfont.Font(family="Helvetica Neue", size=-13)
        self.f_bold = tkfont.Font(family="Helvetica Neue", size=-13)
        self.f_note = tkfont.Font(family="Helvetica Neue", size=-12)
        self.f_quiz = tkfont.Font(family="Helvetica Neue", size=-19)
        self.evo_from = None
        self.evo_from_title = ""
        self.quiz_win = None
        self.quiz = None
        self.litter = {}
        self.next_poop = time.time() + random.uniform(240, 600)
        self.drops = 0
        self.drag_speeds = []
        self.drag_flips = 0
        self.drag_sign = 0
        self.drag_last = (0, 0, 0.0)
        self.land_timer = 0.0
        self.pending_gripe_last = ""
        self.last_bite = 0
        self.crumbs = []
        self.medic_done = False
        self.leaving_done = False
        self.farewell_said = 0
        self.bath_done = False
        self.state_t_at_finish = 0.0
        self.smudges = []
        self.sponge_xy = (0, 0)
        self.sponge_squish = 0
        self.scrubbed = 0
        self.bubbles = []
        self.pending_gripe = None
        self.secret_taps = 0
        self.secret_open = False
        self.last_evo_check = 0.0

        self.voice = Voice(self.pet.name,
                           muted=bool(self.cfg.get("muted")),
                           volume=float(self.cfg.get("volume", 0.7)))

        self.build_menu()
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Double-Button-1>", self.on_pet)
        self.cv.bind("<Button-3>", self.on_menu)
        self.cv.bind("<Motion>", self.on_hover)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.place_window()
        self.sync_litter()
        if getattr(self, "pending_intro", False):
            self.show_intro()
        self.say(f"hi, i'm {self.pet.name}" if self.pet.hatched else "", 3.5)
        self.root.after(50, self.loop)
        self.root.after(3000, self.keep_on_top)

    # ---- window ------------------------------------------------------------
    def place_window(self):
        self.root.geometry(f"{W}x{H}+{int(self.x - W // 2)}+{int(self.y - FLOOR_C)}")

    def retune_monitor(self, force=False):
        """Follow the pet onto whichever monitor it's now on."""
        wa = work_area_at(self.x, self.y)
        if not wa:
            return
        self.sx0, self.sy0, self.sx1, self.sy1 = wa
        floor = self.sy1 - 4
        if abs(floor - self.floor_y) > 1:
            self.floor_y = floor
            if not self.dragging and self.state != "fall":
                if self.y > floor or force:
                    self.y = min(self.y, floor)
                    self.set_state("fall")
        if not self.dragging:                    # don't walk off the edge
            self.target_x = max(self.sx0 + 40, min(self.sx1 - 40, self.target_x))

    def keep_on_top(self):
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        for lt in self.litter.values():
            lt.lift()
        self.root.after(3000, self.keep_on_top)

    # ---- hygiene -----------------------------------------------------------
    def sync_litter(self):
        """Make the windows on screen match the saved list."""
        want = {str(pid): (x, y) for pid, x, y in self.pet.poops}
        for key in list(self.litter):
            if key not in want:
                self.litter.pop(key).destroy()
        for key, (x, y) in want.items():
            if key not in self.litter:
                try:
                    self.litter[key] = Litter(self, key, x, y)
                except Exception:
                    pass

    def drop_mess(self):
        if len(self.pet.poops) >= MAX_MESSES:
            return
        key = f"{int(time.time() * 1000)}{random.randint(10, 99)}"
        x = max(self.sx0 + 40, min(self.sx1 - 40, self.x + random.uniform(-30, 30)))
        self.pet.poops.append([key, x, self.floor_y])
        self.sync_litter()
        self.voice.play("land")
        if not self.sleeping:
            self.say(random.choice(["...", "excuse me", "was not me",
                                    "me finished"]), 2.5)
        self.pet.save()

    def clean_one(self, key):
        before = len(self.pet.poops)
        self.pet.poops = [row for row in self.pet.poops if str(row[0]) != key]
        if len(self.pet.poops) == before:
            return
        self.pet.hygiene = clamp(self.pet.hygiene + 26)
        self.pet.happy = clamp(self.pet.happy + 2)
        self.sync_litter()
        self.voice.play("chirp", True)
        if not self.pet.poops:
            self.say("all clean!", 3.0)
            self.spawn_hearts(3)
        self.pet.save()
        self.draw_stats()

    def clean_all(self):
        if not self.pet.poops:
            self.say("already clean", 2.5)
            return
        n = len(self.pet.poops)
        self.pet.poops = []
        self.pet.hygiene = clamp(self.pet.hygiene + 26 * n)
        self.sync_litter()
        self.voice.play("happy", True)
        self.say("all clean!", 3.5)
        self.spawn_hearts(4)
        self.pet.save()
        self.draw_stats()

    # ---- menu --------------------------------------------------------------
    def build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Feed", command=self.feed)
        self.idx_feed = m.index("end")
        m.add_command(label="Play", command=self.play)
        self.idx_play = m.index("end")
        m.add_command(label="Nap / wake", command=self.toggle_sleep)
        m.add_command(label="Say something", command=self.quote)
        self.idx_say = m.index("end")
        m.add_command(label="Clean up", command=self.clean_all)
        self.idx_clean = m.index("end")
        m.add_command(label="Bath", command=self.bath)
        self.idx_bath = m.index("end")
        m.add_command(label="Call medic", command=self.call_medic)
        self.idx_medic = m.index("end")
        m.add_separator()
        m.add_command(label="Stats", command=self.show_stats)
        m.add_command(label="Rename", command=self.rename)
        m.add_separator()
        snd = tk.Menu(m, tearoff=0)
        snd.add_command(label="Hear its cry", command=lambda: self.voice.play("cry", True))
        snd.add_separator()
        for label, v in (("quiet", 0.35), ("normal", 0.7), ("loud", 1.0)):
            snd.add_command(label=label, command=lambda v=v: self.set_volume(v))
        snd.add_separator()
        snd.add_command(label="Mute / unmute", command=self.toggle_mute)
        m.add_cascade(label="Sound", menu=snd)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        self.menu = m

    def on_menu(self, e):
        z = self.sleeping
        for idx in (self.idx_feed, self.idx_play, self.idx_say):
            self.menu.entryconfig(idx, state="disabled" if z else "normal")
        n = len(self.pet.poops)
        self.menu.entryconfig(self.idx_clean,
                              label=f"Clean up ({n})" if n else "Clean up",
                              state="normal" if (n and not z) else "disabled")
        dirty = self.pet.hygiene < 80 and not z
        self.menu.entryconfig(self.idx_bath,
                              label="Bath" + (" (filthy!)" if self.pet.dirt >= 3
                                              else ""),
                              state="normal" if dirty else "disabled")
        ill = self.pet.illness
        self.menu.entryconfig(
            self.idx_medic,
            label="Call medic" + ("!" * ill if ill > 1 else ""),
            state="normal" if (self.pet.sick and not z) else "disabled")
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ---- interaction -------------------------------------------------------
    def drag_roughness(self):
        """0 gentle, 1 brisk, 2 rough. Judged on peak speed and how often the
        direction flipped - a slow careful carry should never read as rough."""
        if not self.drag_speeds:
            return 0
        peak = max(self.drag_speeds)
        avg = sum(self.drag_speeds) / len(self.drag_speeds)
        if peak > 2600 or (self.drag_flips >= 8 and avg > 900):
            return 2
        if peak > 1400 or (self.drag_flips >= 5 and avg > 500):
            return 1
        return 0

    def on_press(self, e):
        if self.state == "bath":
            self.scrub_at(e.x, e.y, False)
            return
        self.drag_dx = e.x - W // 2
        self.drag_dy = e.y - FLOOR_C
        self.dragging = True
        self.drag_speeds = []
        self.drag_flips = 0
        self.drag_last = (self.x, self.y, time.time())
        self.drag_sign = 0
        self.set_state("drag")

    def on_drag(self, e):
        if self.state == "bath":
            self.scrub_at(e.x, e.y, True)
            return
        if not self.dragging:
            return
        self.x = self.root.winfo_pointerx() - self.drag_dx
        self.y = self.root.winfo_pointery() - self.drag_dy
        self.x = max(self.vx0 + 30, min(self.vx1 - 30, self.x))
        self.y = max(self.vy0 + 30, min(self.vy1 - 4, self.y))

        px, py, pt = self.drag_last
        now = time.time()
        dt = now - pt
        if dt > 0.012:
            dx, dy = self.x - px, self.y - py
            self.drag_speeds.append(math.hypot(dx, dy) / dt)
            del self.drag_speeds[:-40]
            sign = 1 if dx > 2 else (-1 if dx < -2 else 0)
            if sign and self.drag_sign and sign != self.drag_sign:
                self.drag_flips += 1
            if sign:
                self.drag_sign = sign
            self.drag_last = (self.x, self.y, now)
        self.place_window()

    def on_release(self, e):
        if self.state == "bath":
            self.sponge_squish = 0
            return
        if not self.dragging:
            return
        self.dragging = False
        self.retune_monitor(force=True)          # adopt the screen it landed on
        self.vy = 0.0
        self.drops += 1
        rough = self.drag_roughness()
        # only gripe if it was actually shaken about, and never while asleep
        if rough >= 2 and not self.sleeping:
            self.pending_gripe = cute_line("dropped", self.pet.tier)
            self.pending_gripe_last = self.pending_gripe
        elif rough == 0 and not self.sleeping and random.random() < 0.18:
            self.pending_gripe = "wheee" if self.pet.tier == 0 else "ok, that was nice"
            self.pending_gripe_last = self.pending_gripe
        self.set_state("fall")

    def on_hover(self, e):
        if self.state == "bath":
            self.scrub_at(e.x, e.y, False)

    def on_pet(self, e):
        if not self.pet.hatched:
            self.crack = min(1.0, self.crack + 0.18)
            self.voice.play("crack", True)
            return
        if self.sleeping:                      # a nudge is how you wake it
            self.sleeping = False
            self.voice.play("wake", True)
            self.set_state("idle")
            self.say("...morning", 3.0)
            return
        if self.pet.sick:
            self.call_medic()                  # double-click a poorly pet to help
            return
        self.pet.happy = clamp(self.pet.happy + 4)
        self.voice.play("chirp")
        self.spawn_hearts(2)
        self.say(random.choice(["!", "hehe", "<3", "more"]), 1.4)

    def asleep_notice(self):
        """Everything except carrying it is refused while it sleeps."""
        self.say("zzz..." if self.pet.tier == 0 else "...zzz", 2.5)
        return True

    def feed(self):
        if not self.pet.hatched:
            return
        if self.sleeping:
            return self.asleep_notice()
        if self.pet.hunger > 95:
            self.say("too full", 1.8)
            return
        self.food = 0.0
        self.last_bite = 0
        self.voice.play("eat", True)
        self.set_state("eat")

    def play(self):
        if not self.pet.hatched:
            return
        if self.sleeping:
            return self.asleep_notice()
        if self.pet.energy < 12:
            self.voice.play("sad")
            self.say("too tired", 2.0)
            return
        self.voice.play("cry_hi", True)
        self.start_quiz()

    def toggle_sleep(self):
        if not self.pet.hatched:
            return
        self.sleeping = not self.sleeping
        self.voice.play("yawn" if self.sleeping else "wake", True)
        if self.sleeping:
            self.say(cute_line("sleepy", self.pet.tier), 3.0)
        self.set_state("sleep" if self.sleeping else "idle")
        self.say("" if self.sleeping else "morning", 1.5)

    def rename(self):
        n = simpledialog.askstring("Rename", "New name:", parent=self.root,
                                   initialvalue=self.pet.name)
        if n and n.strip():
            self.pet.name = n.strip()[:14]
            self.voice.rebuild(name=self.pet.name)     # new name, new voice
            self.say(self.pet.name, 2.0)
            self.pet.save()

    def quit(self):
        for lt in list(self.litter.values()):
            lt.destroy()
        self.litter = {}
        self.quiz_close()
        self.pet.save()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---- stats panel -------------------------------------------------------
    def show_stats(self):
        if self.stats_alive():
            self.stats_win.lift()
            return
        w = tk.Toplevel(self.root)
        w.title(self.pet.name)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.configure(bg="#12211D")
        self.stats_win = w
        c = tk.Canvas(w, width=300, height=300, bg="#12211D", highlightthickness=0)
        c.pack(padx=12, pady=12)
        self.stats_canvas = c
        self.secret_taps = 0
        self.secret_open = False
        c.bind("<Button-1>", self.stats_tap)
        self.secret_bar = tk.Frame(w, bg="#12211D")
        self.stats_close_btn = tk.Button(
            w, text="close", command=w.destroy, bg="#12211D", fg="#9FD8C6",
            relief="flat", activebackground="#1C302A", font=self.f_body,
            activeforeground="#DCF4EC")
        self.stats_close_btn.pack(pady=(0, 10))
        self.draw_stats()

    def stats_alive(self):
        try:
            return bool(self.stats_win) and bool(self.stats_win.winfo_exists())
        except Exception:
            return False

    def stats_tap(self, _e=None):
        """Five taps on the panel and the workshop drawer opens."""
        if self.secret_open:
            return
        self.secret_taps += 1
        if self.secret_taps >= 5:
            self.secret_open = True
            btn = dict(relief="flat", bg="#241C33", fg="#C7A8F5", bd=0,
                       activebackground="#31264A", activeforeground="#EBDFFF",
                       font=self.f_note)
            tk.Button(self.secret_bar, text="evolve now",
                      command=self.force_evolve, **btn).pack(side="left", padx=(0, 8))
            tk.Button(self.secret_bar, text="farewell now",
                      command=self.force_farewell, **btn).pack(side="left",
                                                               padx=(0, 8))
            tk.Button(self.secret_bar, text="start over (new egg)",
                      command=self.reset_pet, **btn).pack(side="left")
            self.secret_bar.pack(before=self.stats_close_btn, pady=(0, 8))
            self.voice.play("chirp", True)

    def draw_stats(self):
        if not self.stats_alive():
            return
        c = self.stats_canvas
        c.delete("all")
        p = self.pet
        CW = int(c.cget("width"))

        def line(text, font, fill, y, gap=4, wrap_to=None):
            """Draw, measure what actually landed, return the next free y."""
            i = c.create_text(0, y, text=text, anchor="nw", fill=fill, font=font,
                              width=wrap_to or CW)
            return c.bbox(i)[3] + gap

        y = 2
        y = line(p.name, self.f_head, BELLY, y, 2)
        d = p.age_days
        age = f"{int(d * 24)}h old" if d < 1 else f"{d:.1f} days old"
        if p.hatched:
            fam = next((k for k, L in LINES.items()
                        if p.species in (L["baby"], L["good"], L["bad"])
                        + L["good_finals"] + L["bad_finals"]), "?")
            head = f"{p.title}  -  {fam} line  (stage {p.tier + 1}/3)"
        else:
            head = "egg"
        y = line(f"{head}  -  {age}", self.f_body, "#6F9A8D", y, 8)

        if p.hatched:
            n = p.nature
            y = line(f"{n['title']} - {n['blurb']}", self.f_bold, "#C7A8F5", y, 3)
            y = line(SPECIES[p.species]["blurb"], self.f_note, "#4F7268", y, 12)

        rows = [("food", p.hunger, BODY),
                ("mood", p.happy, ACCENT),
                ("energy", p.energy, "#8FB8FF"),
                ("hygiene", p.hygiene, "#9BD0B4"),
                ("care  (this decides the branch)", p.care * 100, "#C7A8F5")]
        for label, val, col in rows:
            y = line(label, self.f_body, "#89B5A7", y, 3)
            c.create_rectangle(0, y, CW, y + 11, fill="#1C302A", outline="")
            c.create_rectangle(0, y, CW * max(0.0, min(100.0, val)) / 100, y + 11,
                               fill=col, outline="")
            y += 11 + 10

        y += 4
        nxt = forecast(p) if p.hatched else None
        if nxt:
            hrs = STAGE2_HOURS if p.tier == 0 else STAGE3_HOURS
            left = max(0.0, hrs - (time.time() - p.born) / 3600.0)
            when = f"in {left:.1f}h" if left > 0 else "any moment"
            y = line(f"heading toward  {SPECIES[nxt]['title']}  {when}",
                     self.f_bold, "#C7A8F5", y, 3)
            y = line("keep it fed and played with to change course",
                     self.f_note, "#4F7268", y, 10)
        elif p.hatched:
            y = line("fully grown", self.f_body, "#6F9A8D", y, 4)


        mess = f"    mess on desk: {len(p.poops)}" if p.poops else ""
        quiz = (f"    quiz {p.quiz_right}/{p.quiz_asked}" if p.quiz_asked else "")
        y = line(f"fed {p.feed_count}    played {p.play_count}    "
                 f"ever sick: {'yes' if p.ever_sick else 'no'}{quiz}{mess}",
                 self.f_note, "#4F7268", y, 4)
        if p.sick:
            y = line("feeling unwell - feed and play to mend",
                     self.f_note, BLUSH, y, 4)

        # grow the canvas to whatever the content actually needed
        if abs(int(c.cget("height")) - int(y)) > 2:
            c.config(height=int(y) + 4)

    # ---- first run ---------------------------------------------------------
    def show_intro(self, on_close=None):
        """The letter that came with the egg. Shown on the very first run and
        again whenever a new egg is taken in."""
        w = tk.Toplevel(self.root)
        w.title("a letter")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.configure(bg="#2A2118")
        w.protocol("WM_DELETE_WINDOW", lambda: None)

        PW, PH = 470, 430
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w.geometry(f"+{max(0, sw // 2 - PW // 2)}+{max(0, sh // 2 - PH // 2 - 40)}")

        c = tk.Canvas(w, width=PW, height=PH, bg="#2A2118", highlightthickness=0)
        c.pack(padx=14, pady=(14, 6))

        # the paper, with a soft drop shadow and a deckled edge
        c.create_rectangle(16, 16, PW - 8, PH - 8, fill="#1E1811", outline="")
        c.create_rectangle(10, 10, PW - 14, PH - 14, fill="#F3E7CE", outline="")
        for i in range(0, PH - 24, 7):                       # torn left edge
            off = 2 + (i // 7 % 3)
            c.create_rectangle(10, 10 + i, 10 + off, 17 + i, fill="#2A2118",
                               outline="")
        c.create_line(10, 44, PW - 14, 44, fill="#D8C6A4")   # faint rule
        for y in range(70, PH - 40, 26):                     # ruled lines
            c.create_line(34, y, PW - 38, y, fill="#E4D6B8")

        ink = "#4A3B2A"
        serif = "Georgia"
        c.create_text(34, 22, text="To whoever finds this,", anchor="nw",
                      fill=ink, font=(serif, -19, "italic"))

        body = ["I could not stay. I am sorry.",
                "",
                "Please look after my egg until I can",
                "come back for it. Feed it when it is",
                "hungry. Play with it when it is bored.",
                "Do not let it be lonely.",
                "",
                "It will tell you what it needs.",
                "It is not shy.",
                "",
                "What it becomes will depend on you.",
                "I do not know what kind it is either.",
                "Nobody does yet, including the egg."]
        y = 62
        for line in body:
            if line:
                c.create_text(34, y, text=line, anchor="nw", fill=ink,
                              font=(serif, -16))
            y += 26

        c.create_text(PW - 46, y + 6, text="- its mother", anchor="ne",
                      fill="#6B5940", font=(serif, -17, "italic"))
        c.create_oval(PW - 96, y + 30, PW - 56, y + 70, fill="#9E3B32",
                      outline="#7A2A22", width=2)          # wax seal
        c.create_text(PW - 76, y + 50, text="?", fill="#E8CFC8",
                      font=(serif, -20, "bold"))

        pad = tk.Frame(w, bg="#2A2118", padx=24, pady=10)
        pad.pack(fill="x")
        tk.Label(pad, text="what will you call it?", bg="#2A2118", fg="#D8C6A4",
                 anchor="w", font=self.f_bold).pack(fill="x")
        ent = tk.Entry(pad, bg="#3B3024", fg="#F3E7CE", insertbackground="#F3E7CE",
                       relief="flat", font=(serif, -19), justify="center")
        ent.insert(0, "Pip")
        ent.select_range(0, "end")
        ent.pack(fill="x", ipady=6, pady=(6, 12))

        def accept(_e=None):
            n = ent.get().strip()
            if n:
                self.pet.name = n[:14]
            self.pet.save()
            self.voice.rebuild(name=self.pet.name)
            w.destroy()
            self.say("it hatches in a minute or so", 6.0)
            if on_close:
                on_close()

        tk.Button(pad, text="take it in", command=accept, relief="flat", bd=0,
                  bg="#C9A860", fg="#2A2118", activebackground="#DDBE79",
                  activeforeground="#2A2118", font=self.f_bold).pack(
                      fill="x", ipady=8)

        ent.bind("<Return>", accept)
        ent.focus_force()
        w.transient(self.root)
        self.voice.play("arrival", True)
        w.wait_window()

    # ---- the quiz ----------------------------------------------------------
    def quiz_alive(self):
        try:
            return bool(self.quiz_win) and bool(self.quiz_win.winfo_exists())
        except Exception:
            return False

    def call_medic(self):
        if self.sleeping:
            return self.asleep_notice()
        if not self.pet.sick:
            self.say("me feel fine!" if self.pet.tier == 0 else "I'm fine, honestly",
                     3.0)
            return
        self.start_quiz(mode="treat")

    def start_quiz(self, mode="fun"):
        if self.quiz_alive():
            self.quiz_win.lift()
            return
        if mode == "treat":
            bank, size = HEALTH_FACTS, TREAT_ROUND
        else:
            bank, size = FACTS, QUIZ_ROUND
        deck = random.sample(bank, min(size, len(bank)))
        self.quiz = {"deck": deck, "i": 0, "score": 0, "answered": False,
                     "mode": mode}
        if mode == "treat":
            self.say("me no feel good..." if self.pet.tier == 0
                     else "right. let's sort this out", 4.0)
        else:
            self.say(random.choice(["quiz time", "one for you", "listen to this",
                                    "is this true?"]), 3.0)

        w = tk.Toplevel(self.root)
        self.quiz_win = w
        w.title("treating " + self.pet.name if self.quiz["mode"] == "treat"
                else f"{self.pet.name} asks")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.configure(bg="#12211D", padx=18, pady=16)
        w.protocol("WM_DELETE_WINDOW", self.quiz_close)

        # sit it beside the pet rather than in the middle of the screen
        qx = int(max(self.sx0 + 10, min(self.sx1 - 430, self.x - 210)))
        qy = int(max(self.sy0 + 10, self.floor_y - 460))
        w.geometry(f"+{qx}+{qy}")

        if self.quiz["mode"] == "treat":
            tk.Label(w, text="Get all five right and it recovers. "
                             "Any wrong and you'll have to start again.\n"
                             "(A game about a pixel creature - not medical advice.)",
                     bg="#12211D", fg="#C7A8F5", font=self.f_note, justify="left",
                     anchor="w", wraplength=400).pack(fill="x", pady=(0, 10))
        self.q_progress = tk.Label(w, text="", bg="#12211D", fg="#4F7268",
                                   font=self.f_note, anchor="w")
        self.q_progress.pack(fill="x")
        self.q_text = tk.Label(w, text="", bg="#12211D", fg="#DCF4EC",
                               font=self.f_quiz,
                               wraplength=380, justify="left", anchor="w")
        self.q_text.pack(fill="x", pady=(8, 4))
        self.q_result = tk.Label(w, text="", bg="#12211D", fg="#6F9A8D",
                                 font=self.f_note, wraplength=380,
                                 justify="left", anchor="w", height=3)
        self.q_result.pack(fill="x")

        bar = tk.Frame(w, bg="#12211D")
        bar.pack(fill="x", pady=(6, 0))
        btn = dict(relief="flat", font=self.f_bold, width=11, bd=0,
                   activeforeground="#12211D", fg="#12211D")
        self.q_true = tk.Button(bar, text="TRUE", bg=BODY, activebackground="#9BE0C9",
                                command=lambda: self.quiz_answer(True), **btn)
        self.q_false = tk.Button(bar, text="FALSE", bg="#E8956F",
                                 activebackground="#F2AE8E",
                                 command=lambda: self.quiz_answer(False), **btn)
        self.q_next = tk.Button(bar, text="next", bg="#1C302A", fg="#9FD8C6",
                                activebackground="#27453C", activeforeground="#DCF4EC",
                                relief="flat", font=self.f_body, width=9,
                                command=self.quiz_next)
        self.q_true.pack(side="left", padx=(0, 8))
        self.q_false.pack(side="left")
        self.q_next.pack(side="right")
        self.quiz_show()

    def quiz_show(self):
        q = self.quiz
        stmt, _, _ = q["deck"][q["i"]]
        self.q_progress.config(text=f"question {q['i'] + 1} of {len(q['deck'])}"
                                    f"     score {q['score']}")
        self.q_text.config(text=stmt)
        self.q_result.config(text="")
        q["answered"] = False
        self.q_true.config(state="normal")
        self.q_false.config(state="normal")
        self.q_next.config(state="disabled")

    def quiz_answer(self, said_true):
        q = self.quiz
        if not q or q["answered"]:
            return
        q["answered"] = True
        stmt, truth, why = q["deck"][q["i"]]
        right = (said_true == truth)
        p = self.pet
        p.quiz_asked += 1
        self.q_true.config(state="disabled")
        self.q_false.config(state="disabled")
        self.q_next.config(state="normal")

        if right:
            q["score"] += 1
            p.quiz_right += 1
            p.happy = clamp(p.happy + 5)
            self.q_result.config(fg=BODY, text=f"Right - it's {truth}.\n{why}")
            self.voice.play("happy", True)
            self.set_state("play")
        else:
            self.q_result.config(fg="#E8956F",
                                 text=f"Not quite - it's {truth}.\n{why}")
            self.voice.play("sad", True)
            self.say(random.choice(["ah", "nearly", "hm"]), 2.0)

    def quiz_next(self):
        q = self.quiz
        if not q or not q["answered"]:
            return
        q["i"] += 1
        if q["i"] >= len(q["deck"]):
            self.quiz_finish()
        else:
            self.quiz_show()

    def quiz_finish(self):
        q = self.quiz
        p = self.pet
        score, total = q["score"], len(q["deck"])

        if q.get("mode") == "treat":
            self.quiz_close()
            if score == total:
                self.begin_medic()
            else:
                p.illness = min(3, p.illness + 1)     # it gets worse
                p.happy = clamp(p.happy - 8)
                self.voice.play("sad", True)
                self.say(f"{score} of {total}... me feel worse" if p.tier == 0
                         else f"{score} of {total}. I'm worse, if anything", 6.0)
                p.save()
                self.draw_stats()
            return

        p.play_count += 1
        p.hygiene = clamp(p.hygiene - 3)
        p.happy = clamp(p.happy + 6 + 3 * score)
        p.energy = clamp(p.energy - 9)
        p.hunger = clamp(p.hunger - 4)
        if score == total:
            p.play_count += 1                       # a clean round counts double
            line = "perfect!"
            self.voice.play("fanfare", True)
            self.spawn_hearts(8)
        elif score >= total * 0.6:
            line = f"{score} out of {total}"
            self.voice.play("cry_hi", True)
            self.spawn_hearts(4)
        else:
            line = f"{score} out of {total}, next time"
            self.voice.play("chirp", True)
        self.say(line, 5.0)
        self.set_state("play")
        p.save()
        self.draw_stats()
        self.quiz_close()

    def quiz_close(self):
        self.quiz = None
        try:
            if self.quiz_win:
                self.quiz_win.destroy()
        except Exception:
            pass
        self.quiz_win = None

    # ---- X notifications ---------------------------------------------------




    def set_volume(self, v):
        self.cfg["volume"] = v
        self.cfg["muted"] = False
        store_config(self.cfg)
        self.voice.muted = False
        self.voice.rebuild(volume=v)
        self.say("ok", 1.2)

    def toggle_mute(self):
        self.voice.muted = not self.voice.muted
        self.cfg["muted"] = self.voice.muted
        store_config(self.cfg)
        if not self.voice.muted:
            self.voice.play("chirp", True)

    def begin_evolution(self, key):
        p = self.pet
        self.evo_from = p.species
        self.evo_from_title = p.title
        p.evolve_to(key)
        self.sleeping = False
        t = p.tint
        self.sprites.get(key, "idle", 0, tint=t)   # warm the cache first
        self.sprites.get(key, "idle", 0, "#FFFFFF", tint=t)
        self.sprites.get(key, "happy", 0, tint=t)
        self.voice.play("evolve", True)
        self.set_state("evolving")
        self.bubble = ""
        self.root.after(int(EVO_TOTAL * 1000) - 700,
                        lambda: self.voice.play("cry_low" if SPECIES[key]["tier"] == 2
                                                else "cry", True))
        p.save()

    def reset_pet(self, confirm=True):
        p = self.pet
        gone = p.name if not p.hatched else f"{p.name} the {p.title}"
        if confirm and not messagebox.askyesno(
                "Start over",
                f"{gone} will be gone for good, along with "
                f"{p.age_days:.1f} days of history.\n\n"
                "You'll get a fresh egg - a new line, a new personality, "
                "a new voice.\n\nContinue?",
                parent=self.root, icon="warning"):
            return
        for lt in list(self.litter.values()):
            lt.destroy()
        self.litter = {}
        self.pet = Pet()                       # fresh born time, re-rolled personality
        self.pet.save()
        self.crack = 0.0
        self.sleeping = False
        self.evo_from = None
        self.last_evo_check = 0.0
        self.hearts = []
        self.food = None
        self.x = (self.sx0 + self.sx1) / 2
        self.y = self.floor_y
        self.set_state("idle")
        self.say("", 0.0)
        self.draw_stats()
        self.show_intro()                      # a new egg comes with a new letter

    # ---- leaving ------------------------------------------------------------
    def bath(self):
        if not self.pet.hatched:
            return
        if self.sleeping:
            return self.asleep_notice()
        if self.pet.hygiene >= 80:
            self.say("me already clean" if self.pet.tier == 0 else "I'm clean",
                     2.5)
            return
        # one smudge per unit of grime, scattered over the body
        n = max(4, self.pet.dirt * 3)
        cx = W // 2
        top = FLOOR_C + 4 - SPR_PX + int(SPR_PX * 0.30)
        self.smudges = []
        for i in range(n):
            ang = (i / n) * 2 * math.pi + random.uniform(-0.3, 0.3)
            rad = random.uniform(0.25, 0.85)
            self.smudges.append([
                cx + math.cos(ang) * 38 * rad,
                top + 34 + math.sin(ang) * 30 * rad,
                random.uniform(7, 11),      # size
                1.0,                        # how dirty it still is
            ])
        self.bubbles = []
        self.bath_done = False
        self.sponge_xy = (cx, FLOOR_C - 40)
        self.sponge_squish = 0
        self.scrubbed = 0
        self.voice.play("splash", True)
        self.say("scrub me!" if self.pet.tier == 0 else "go on then", 4.0)
        self.set_state("bath")

    def scrub_at(self, x, y, moving):
        """Rub the sponge over a smudge and it fades."""
        self.sponge_xy = (x, y)
        self.sponge_squish = 2 if moving else 0
        if not moving:
            return
        for sm in self.smudges:
            if sm[3] <= 0:
                continue
            if math.hypot(sm[0] - x, sm[1] - y) < sm[2] + 14:
                sm[3] -= 0.16
                if random.random() < 0.5:
                    self.bubbles.append([x + random.uniform(-10, 10),
                                         y + random.uniform(-6, 6),
                                         random.uniform(-0.4, 0.4),
                                         random.uniform(-1.6, -0.8),
                                         random.uniform(2.5, 6.0), 1.0])
                if sm[3] <= 0:
                    self.scrubbed += 1
                    self.voice.play("chirp")
                    self.pet.hygiene = clamp(self.pet.hygiene
                                             + 100.0 / max(1, len(self.smudges)))

    def bath_finish(self, complete):
        p = self.pet
        self.bath_done = True
        self.state_t_at_finish = self.state_t
        if complete:
            p.hygiene = 100.0
            p.grime = 0.0
            p.happy = clamp(p.happy + 26)
            self.voice.play("sparkle", True)
            self.spawn_hearts(8)
            self.say("me all shiny!" if p.tier == 0 else "much better", 5.0)
        else:
            self.voice.play("chirp", True)
            self.say("dat will do" if p.tier == 0 else "that'll do", 4.0)
        p.save()
        self.draw_stats()

    def begin_farewell(self):
        p = self.pet
        self.leaving_done = False
        self.farewell_said = 0
        self.sleeping = False
        for pose in ("idle", "wave", "walk"):
            self.sprites.get(p.species, pose, 0, pack=True, tint=p.tint)
            self.sprites.get(p.species, pose, 1, pack=True, tint=p.tint)
        self.say("", 0.0)
        self.voice.play("farewell", True)
        self.set_state("leaving")

    def farewell_line(self, t):
        """Its goodbye, one line at a time. Which speech you get was decided
        when the egg hatched."""
        d = self.pet.leaving_reason
        script = d["baby"] if self.pet.tier == 0 else d["grown"]
        beats = (0.6, 4.2, 8.0, 12.0, 16.0)
        idx = self.farewell_said
        if idx < len(script) and t >= beats[min(idx, len(beats) - 1)]:
            self.farewell_said = idx + 1     # index, not a timing window,
            return script[idx]               # so a slow frame can't skip one
        return None

    def ask_to_stay(self):
        """Offered once it has walked off the edge."""
        p = self.pet
        w = tk.Toplevel(self.root)
        w.title(p.name)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.configure(bg="#2A2118", padx=26, pady=22)
        w.protocol("WM_DELETE_WINDOW", lambda: None)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w.geometry(f"+{max(0, sw // 2 - 230)}+{max(0, sh // 2 - 150)}")

        weeks = p.stay_weeks + 1
        tk.Label(w, text=f"{p.name} is at the edge of the desk.",
                 bg="#2A2118", fg="#F3E7CE", anchor="w",
                 font=("Georgia", -21)).pack(fill="x")
        note = (f"It stayed {weeks * 3} days. It says it has to go "
                f"{p.leaving_reason['short']}.\n\n"
                "You could call it back for another few days. "
                "Or you could let it go, and take in a new egg.")
        tk.Label(w, text=note, bg="#2A2118", fg="#C0AE8E", anchor="w",
                 justify="left", wraplength=400, font=("Georgia", -16)).pack(
                     fill="x", pady=(12, 20))

        def stay():
            w.destroy()
            p.stay_weeks += 1
            p.happy = clamp(p.happy + 30)
            p.save()
            self.x = self.sx0 + 60 if self.x > (self.sx0 + self.sx1) / 2 \
                else self.sx1 - 60
            self.facing = 1 if self.x < (self.sx0 + self.sx1) / 2 else -1
            self.target_x = (self.sx0 + self.sx1) / 2
            self.set_state("walk")
            self.voice.play("arrival", True)
            self.say("me stay! me stay!" if p.tier == 0
                     else "a few more days, then", 6.0)
            self.spawn_hearts(10)
            self.draw_stats()

        def farewell():
            w.destroy()
            self.reset_pet(confirm=False)

        tk.Button(w, text=f"ask {p.name} to stay a few more days", command=stay,
                  relief="flat", bd=0, bg=BODY, fg="#12211D",
                  activebackground="#9BE0C9", activeforeground="#12211D",
                  font=self.f_bold).pack(fill="x", ipady=9)
        tk.Button(w, text="let it go, and take in a new egg", command=farewell,
                  relief="flat", bd=0, bg="#3B3024", fg="#C0AE8E",
                  activebackground="#4B3E2E", activeforeground="#F3E7CE",
                  font=self.f_body).pack(fill="x", ipady=7, pady=(10, 0))
        w.transient(self.root)

    def begin_medic(self):
        """The medic arrives, does the deed, and leaves."""
        self.medic_done = False
        self.sleeping = False
        self.sprites.medic("walk", 0)               # warm the cache first
        self.sprites.medic("raise", 0)
        self.sprites.medic("inject", 0)
        self.sprites.medic("wave", 0)
        self.say("", 0.0)
        self.voice.play("wake", True)
        self.set_state("medic")

    def medic_pose(self, t):
        """(pose, frame, x) for the medic at time t into the visit."""
        cx = W // 2
        stand = cx - 88
        if t < 1.7:                                  # walks in from the left
            x = -40 + (stand + 40) * ease_out(t / 1.7)
            return "walk", int(t * 6) % 2, x
        if t < 2.5:
            return "raise", 0, stand
        if t < 2.9:
            return "inject", 0, stand + 10
        if t < 4.3:
            return "wave", 0, stand
        x = stand - (stand + 60) * ease_out(min(1.0, (t - 4.3) / 1.5))
        return "walk", int(t * 6) % 2, x

    def force_farewell(self):
        if not self.pet.hatched:
            self.say("not yet hatched", 2.5)
            return
        if self.state == "leaving":
            return
        self.begin_farewell()

    def force_evolve(self):
        p = self.pet
        if not p.hatched:
            p.hatch()
            self.voice.play("cry", True)
            self.say(f"hi! i'm {p.name}", 4.0)
            self.spawn_hearts(6)
            return
        nxt = forecast(p)
        if nxt:
            self.begin_evolution(nxt)
        else:
            self.say("fully grown", 2.5)




    # ---- speech ------------------------------------------------------------
    def say(self, text, secs=2.0, author=None, silent=False):
        self.bubble = text
        self.bubble_author = author
        self.bubble_lines = self.wrap(text, self.font_ui, W - 40) if text else []
        self.bubble_total = sum(len(l) for l in self.bubble_lines)
        self.bubble_shown = 0.0
        if text and silent:
            # let the music play; type the words out on their own
            self.bubble_start = time.time()
            self.bubble_rate = max(24.0, self.bubble_total / REVEAL_MAX)
            self.bubble_t = max(secs, self.bubble_total / self.bubble_rate + 1.8)
            return
        if text:
            delay, dur = self.voice.speak(text, self.pet.personality, self.pet.tier)
            self.bubble_start = time.time() + min(delay, 0.8)
            # follow the blips, but never crawl and never stall: a line is
            # always fully out within REVEAL_MAX seconds however long the
            # audio turned out to be
            if dur > 0.05 and self.bubble_total:
                rate = self.bubble_total / dur
            else:
                rate = 999.0
            floor = self.bubble_total / REVEAL_MAX if self.bubble_total else 999.0
            self.bubble_rate = max(rate, floor, 8.0)
            secs = max(secs, min(delay, 0.8) + min(dur, REVEAL_MAX) + 1.6)
        else:
            self.bubble_start = time.time()
            self.bubble_rate = 999.0
        self.bubble_t = secs

    def quote(self):
        if self.sleeping:
            return self.asleep_notice()
        k = self.pet.personality
        if self.pet.tier == 0 and random.random() < 0.8:
            self.say(random.choice(KID_LINES), 6.5)   # no source, none needed
            self.voice.play("chirp")
            return
        pool = QUOTES[k] + SCREEN[k]          # books and screen, same nature
        text, who = random.choice(pool)
        self.say(text, 6.5, author=who)
        self.voice.play("chirp")

    def spawn_hearts(self, n=3):
        for _ in range(n):
            self.hearts.append([W // 2 + random.uniform(-24, 24), FLOOR_C - 90,
                                random.uniform(-0.5, 0.5), random.uniform(-1.4, -0.9),
                                1.0])

    # ---- brain -------------------------------------------------------------
    def set_state(self, s):
        self.state = s
        self.state_t = 0.0

    def think(self):
        p = self.pet
        if not p.hatched:
            return
        if self.state in ("drag", "fall", "eat", "play", "notice", "evolving",
                          "medic", "leaving", "bath"):
            return
        if p.energy < 10 and not self.sleeping:
            self.sleeping = True
            self.set_state("sleep")
            self.say("sleepy...", 2.0)
            return
        if self.sleeping:
            if p.energy > 96:
                self.sleeping = False
                self.set_state("idle")
                self.say("morning", 2.0)
            return

        n = p.nature
        # sometimes it just has something to say
        chatty = n["chatty"] * (1.7 if p.tier == 0 else 1.0)
        if (random.random() < chatty * 0.4 and p.happy > 30
                and not p.sick and self.bubble_t <= 0):
            self.quote()
            return

        # if it's genuinely being let down, it says so
        wronged = (p.hunger < 30 or p.happy < 30 or p.hygiene < 35 or p.sick)
        if wronged and random.random() < 0.42:
            pool = ATTITUDE["baby" if p.tier == 0 else "grown"]
            self.voice.play("cry_low")
            self.say(random.choice(pool), 6.0)
            return

        # nag when something's low
        if random.random() < 0.5:
            if p.sick:
                self.voice.play("sad")
                self.say(cute_line("sick", p.tier), 4.0)
            elif p.hunger < 25:
                self.voice.play("cry_low")
                self.say(cute_line("hungry", p.tier), 4.0)
            elif p.happy < 25:
                self.voice.play("cry_low")
                self.say(cute_line("bored", p.tier), 4.0)
            elif p.energy < 25:
                self.say(cute_line("sleepy", p.tier), 4.0)

        r = random.random()
        if r < 0.25 + 0.35 * n["wander"] and not p.sick:
            span = (260 if p.happy > 40 else 110) * (0.6 + 0.7 * n["wander"])
            self.target_x = max(self.sx0 + 40, min(self.sx1 - 40,
                                self.x + random.uniform(-span, span)))
            self.facing = 1 if self.target_x > self.x else -1
            self.set_state("walk")
        elif r < 0.60 and not p.sick:
            if random.random() < 0.4:
                self.voice.play("hop")
            self.set_state("play")
        else:
            self.set_state("idle")
            self.facing = random.choice([-1, 1])

    def update(self, dt):
        p = self.pet
        self.phase += dt
        self.state_t += dt
        self.bubble_t = max(0.0, self.bubble_t - dt)
        self.land_timer = max(0.0, self.land_timer - dt)
        if self.bubble and time.time() >= self.bubble_start:
            self.bubble_shown = min(self.bubble_total,
                                    self.bubble_shown + dt * self.bubble_rate)
            # belt and braces: past REVEAL_MAX the whole line is visible no
            # matter what the rate worked out to be
            if time.time() - self.bubble_start > REVEAL_MAX:
                self.bubble_shown = self.bubble_total
        p.tick(dt, self.sleeping)

        if not p.hatched:
            self.crack = max(0.0, (time.time() - p.born) / HATCH_SECONDS)
        elif self.state == "hatching" or (self.crack > 0 and p.hatched):
            self.crack = 0.0
            if self.state not in ("drag", "fall"):
                self.set_state("play")
                self.voice.play("cry", True)
                self.say(f"hi! i'm {p.name}", 4.0)
                self.spawn_hearts(6)

        # blink
        self.blink_t -= dt
        if self.blink_t <= 0:
            self.blink = 0.16
            self.blink_t = random.uniform(2.0, 6.0)
        self.blink = max(0.0, self.blink - dt)

        # states
        if self.state == "walk":
            speed = 44 * (0.7 if p.hunger < 20 else 1.0)
            dx = self.target_x - self.x
            if abs(dx) < 4:
                self.set_state("idle")
            else:
                self.x += math.copysign(min(speed * dt, abs(dx)), dx)
                self.facing = 1 if dx > 0 else -1
            self.hop = abs(math.sin(self.phase * 7)) * 4

        elif self.state == "play":
            t = self.state_t
            if t < 0.22:                             # anticipation: crouch first
                self.hop = -3 * ease_out(t / 0.22)
            elif t < 1.7:
                k = (t - 0.22)
                self.hop = max(0.0, math.sin(k * 5.2) * 34 * (1 - k / 1.5))
            else:
                self.hop = 0.0
                p.happy = clamp(p.happy + 22)
                p.play_count += 1
                p.hygiene = clamp(p.hygiene - 4)          # working up a sweat
                p.energy = clamp(p.energy - 8)
                p.hunger = clamp(p.hunger - 4)
                self.voice.play("happy")
                self.spawn_hearts(3)
                self.set_state("idle")

        elif self.state == "evolving":
            self.hop = 0.0
            if self.state_t > EVO_TOTAL:
                self.set_state("idle")
                self.say(f"{self.evo_from_title} -> {p.title}!", 6.0)
                self.spawn_hearts(8)

        elif self.state == "bath":
            t = self.state_t
            self.hop = abs(math.sin(t * 6.5)) * 3.0           # happy wriggling
            if not self.bath_done:
                if all(sm[3] <= 0 for sm in self.smudges):
                    self.bath_finish(True)
                elif t > 45.0:                                # gave up on you
                    self.bath_finish(False)
            elif t > self.state_t_at_finish + 2.4:
                self.set_state("idle")

        elif self.state == "leaving":
            t = self.state_t
            line = self.farewell_line(t)
            if line:
                self.say(line, 3.8, silent=True)
            if t < 18.0:
                self.hop = abs(math.sin(self.phase * 1.4)) * 2.0
            elif t < 21.0:                                  # waving
                self.hop = abs(math.sin(self.phase * 3.2)) * 3.5
            else:                                           # walks off the edge
                self.x += 46 * dt * self.facing
                self.hop = abs(math.sin(self.phase * 7)) * 4
                edge = self.sx1 + 120 if self.facing > 0 else self.sx0 - 120
                if (self.facing > 0 and self.x > edge) or \
                   (self.facing < 0 and self.x < edge):
                    if not self.leaving_done:
                        self.leaving_done = True
                        self.ask_to_stay()

        elif self.state == "medic":
            t = self.state_t
            if 2.9 <= t and not self.medic_done:
                self.medic_done = True
                p.sick = False
                p.illness = 0
                p.grime = 0.0
                p.neglect = 0.0
                p.wellness = 0.0
                p.hygiene = clamp(p.hygiene + 25)
                p.happy = clamp(p.happy + 22)
                p.energy = clamp(p.energy + 12)
                self.voice.play("fanfare", True)
                self.say("me all better!" if p.tier == 0 else "much better. thank you",
                         6.0)
                self.spawn_hearts(10)
                p.save()
                self.draw_stats()
            if 2.5 <= t < 2.9:
                self.hop = -2.0                      # flinch
            elif t >= 2.9:
                k = t - 2.9
                self.hop = max(0.0, abs(math.sin(k * 6)) * 22 * (1 - k / 2.2))
            else:
                self.hop = 0.0
            if t > 5.8:
                self.set_state("idle")

        elif self.state == "notice":
            t = self.state_t
            if t < 0.18:                              # ears up, little crouch
                self.hop = -4 * ease_out(t / 0.18)
            elif t < 1.5:
                k = t - 0.18
                self.hop = max(0.0, abs(math.sin(k * 7.0)) * 26 * (1 - k / 1.32))
            else:
                self.hop = 0.0
                self.set_state("idle")

        elif self.state == "eat":
            self.hop = abs(math.sin(self.state_t * 9)) * 2.5     # chewing bob
            if self.food is not None:
                self.food = self.state_t
                bite = int(max(0.0, (self.state_t - 0.55) / 0.52))
                if bite != self.last_bite and 0 < bite <= 3:
                    self.last_bite = bite
                    self.voice.play("eat", True)
                    for _ in range(3):                          # crumbs
                        self.crumbs.append([
                            W // 2 + self.facing * 34 + random.uniform(-6, 6),
                            FLOOR_C - 34, random.uniform(-1.1, 1.1),
                            random.uniform(-1.6, -0.4), 1.0])
            if self.state_t > 2.2:
                self.food = None
                p.hunger = clamp(p.hunger + 32)
                p.feed_count += 1
                p.hygiene = clamp(p.hygiene - 5)          # crumbs everywhere
                self.next_poop = min(self.next_poop,
                                     time.time() + random.uniform(150, 420))
                p.happy = clamp(p.happy + 6)
                self.voice.play("happy")
                self.say("mm", 1.6)
                self.spawn_hearts(2)
                self.set_state("idle")

        elif self.state == "fall":
            self.vy += 1500 * dt
            self.y += self.vy * dt
            if self.y >= self.floor_y:
                self.y = self.floor_y
                hard = self.vy > 720           # roughly a 170px drop or more
                self.land_timer = 0.30 if hard else 0.18
                self.voice.play("land", True)   # always audible touchdown
                if self.sleeping:
                    pass                        # asleep: it notices nothing
                elif self.pending_gripe:
                    self.say(self.pending_gripe, 4.5)
                    self.pending_gripe = None
                    if "wheee" not in self.pending_gripe_last:
                        self.voice.play("sad")
                elif hard:
                    self.say("oof", 1.4)
                    p.happy = clamp(p.happy - 2)
                    p.happy = clamp(p.happy - 2)
                self.vy = 0.0
                self.set_state("idle")
            self.place_window()

        elif self.state == "sleep":
            self.hop = 0.0

        elif self.state == "drag":
            self.hop = 0.0

        else:  # idle
            self.hop = abs(math.sin(self.phase * 1.7)) * 2.5

        if self.sleeping and self.state in ("drag", "fall"):
            self.hop = 0.0
        if self.state not in ("drag", "fall"):
            self.next_think -= dt
            if self.state == "notice":
                self.next_think = max(self.next_think, 1.0)
            if self.next_think <= 0:
                self.next_think = random.uniform(2.5, 6.0)
                self.think()

        self.prev_x = self.x

        for bu in self.bubbles:
            bu[0] += bu[2]
            bu[1] += bu[3]
            bu[3] *= 0.985
            bu[5] -= dt * 0.5
        self.bubbles = [b for b in self.bubbles if b[5] > 0 and b[1] > 40]

        for cb in self.crumbs:
            cb[0] += cb[2]
            cb[1] += cb[3]
            cb[3] += 0.22                       # crumbs fall, hearts rise
            cb[4] -= dt * 1.6
        self.crumbs = [c for c in self.crumbs if c[4] > 0]

        # hearts drift
        for h in self.hearts:
            h[0] += h[2]
            h[1] += h[3]
            h[3] *= 0.99
            h[4] -= dt * 0.8
        self.hearts = [h for h in self.hearts if h[4] > 0]

        if self.state != "fall":
            self.place_window()


        now = time.time()
        if now - self.last_mon > 0.4:
            self.last_mon = now
            self.retune_monitor()
        if (p.hatched and now > self.next_poop
                and self.state not in ("drag", "fall", "evolving")):
            self.next_poop = now + random.uniform(600, 1500)
            self.drop_mess()
        if self.stats_alive() and now - self.last_stats > 0.35:
            self.last_stats = now
            self.draw_stats()

        if (p.hatched and p.days_left <= 0 and not p.left
                and self.state not in ("evolving", "drag", "fall", "leaving",
                                       "medic", "eat")):
            self.begin_farewell()

        if (p.hatched and self.state not in ("evolving", "drag", "fall", "leaving")
                and time.time() - self.last_evo_check > 5):
            self.last_evo_check = time.time()
            nxt = next_form(p)
            if nxt:
                self.begin_evolution(nxt)

        if time.time() - self.last_save > 20:
            self.last_save = time.time()
            p.save()
            self.draw_stats()

    # ---- drawing -----------------------------------------------------------
    def pose_now(self):
        """Which sprite pose + frame the current state calls for."""
        p = self.pet
        f = int(self.phase * (5 if self.state == "walk" else 1.6)) % 2
        if self.state == "bath":
            return "bath", int(self.phase * 4) % 2
        if self.state == "leaving":
            t = self.state_t
            if t < 18.0:
                return "sad", f
            if t < 21.0:
                return "wave", f
            return "walk", f
        if self.state == "medic":
            t = self.state_t
            if t < 2.5:
                return "sick", f
            if t < 2.9:
                return "squat", 0
            return "happy", f
        if self.sleeping:
            return "sleep", f
        if self.land_timer > 0:
            return "land", 0
        if self.state == "drag":
            return "dangle", f
        if self.state == "fall":
            return "dangle", f
        if self.state == "eat":
            return "eat", int(self.phase * 8) % 2
        if self.state in ("play", "notice") and self.hop > 6:
            return "hop", f
        if self.state == "play" and self.state_t < 0.22:
            return "squat", 0
        if self.state == "walk":
            return "walk", f
        if p.sick:
            return "sick", f
        if self.blink > 0:
            return "blink", f
        if p.mood == "low":
            return "sad", f
        return "idle", f

    def draw(self):
        c = self.cv
        c.delete("all")
        p = self.pet
        cx = W // 2
        lift = self.hop + (self.floor_y - self.y if self.dragging or self.state == "fall" else 0)
        base = FLOOR_C - self.hop

        # shadow
        sh = max(0.0, 1.0 - lift / 120.0)
        if sh > 0.05:
            sw = 22 * PIX * (0.55 + 0.45 * sh) * (1.15 if p.tier == 2 else 1.0) / 1.6
            c.create_oval(cx - sw, FLOOR_C - 6 * sh, cx + sw, FLOOR_C + 6 * sh,
                          fill="#000000", outline="", stipple="gray25")

        if not p.hatched:
            c.create_image(cx, base + 4, image=self.sprites.egg(self.crack), anchor="s")
            left = max(0, int(HATCH_SECONDS - (time.time() - p.born)))
            c.create_text(cx, base - 116, text=f"hatching in {left}s",
                          fill=BODY_DARK, font=self.font_small)
        elif self.state == "evolving":
            self.draw_evolution(cx, base)
        else:
            pose, frame = self.pose_now()
            packed = self.state == "leaving"
            grime = 0 if self.state == "bath" else p.dirt
            c.create_image(cx, base + 4,
                           image=self.sprites.get(p.species, pose, frame,
                                                  pack=packed, dirt=grime,
                                                  tint=p.tint),
                           anchor="s")
            if self.sleeping:
                for i in range(3):
                    t = (self.phase * 0.6 + i * 0.33) % 1.0
                    c.create_text(cx + 26 + t * 18, base - int(SPR_PX * 0.66) - t * 28,
                                  text="z",
                                  fill=BODY_DARK,
                                  font=(self.font_ui.cget("family"), -(11 + i * 4)))

        if self.state == "bath":
            t = self.state_t
            slide = ease_out(min(1.0, t / 0.5))
            ty = base + 26 - 26 * slide
            c.create_image(cx, ty, image=self.sprites.tub(), anchor="s")

            for sx, sy, rad, life in self.smudges:      # what's left to scrub
                if life <= 0:
                    continue
                rr = rad * (0.55 + 0.45 * life)
                c.create_oval(sx - rr, sy - rr * 0.75, sx + rr, sy + rr * 0.75,
                              fill="#7A6146", outline="",
                              stipple="" if life > 0.6 else "gray50")

            for bx, by, _, _, rad, life in self.bubbles:
                c.create_oval(bx - rad, by - rad, bx + rad, by + rad,
                              outline="#DFF6FF", width=1)
                c.create_arc(bx - rad, by - rad, bx + rad, by + rad,
                             start=60, extent=50, style="arc",
                             outline="#FFFFFF", width=1)

            if not self.bath_done:
                left = sum(1 for sm in self.smudges if sm[3] > 0)
                c.create_text(cx, base + 22,
                              text=f"rub the sponge over it  -  {left} spots left",
                              fill="#DFF6FF", font=self.font_small)
                sx, sy = self.sponge_xy
                c.create_image(sx, sy, image=self.sprites.sponge(self.sponge_squish),
                               anchor="center")
            else:
                k = min(1.0, (t - self.state_t_at_finish) / 0.6)
                rr = 12 + 90 * ease_out(k)
                c.create_oval(cx - rr, base - 60 - rr * 0.6,
                              cx + rr, base - 60 + rr * 0.6,
                              outline="#FFFFFF", width=max(1, int(4 * (1 - k))))

        if self.state == "medic":
            pose, frame, mx = self.medic_pose(self.state_t)
            c.create_image(mx, base + 4, image=self.sprites.medic(pose, frame),
                           anchor="s")
            if 2.5 <= self.state_t < 3.05:           # the flash of the jab
                r = 14 + 90 * ease_out((self.state_t - 2.5) / 0.55)
                c.create_oval(cx - r, base - 70 - r * 0.6,
                              cx + r, base - 70 + r * 0.6,
                              outline="#FFFFFF",
                              width=max(1, int(5 * (1 - (self.state_t - 2.5) / 0.55))))

        if self.food is not None and p.hatched:
            t = self.food
            bite = max(0, min(3, int(max(0.0, (t - 0.55) / 0.52))))
            slide = min(1.0, t / 0.5)
            fx = cx + self.facing * (58 - 30 * ease_out(slide))
            fy = base - 22 + math.sin(t * 9) * 1.5
            c.create_image(fx, fy, image=self.sprites.food(bite), anchor="center")

        for cb in self.crumbs:
            s2 = 2 if cb[4] > 0.5 else 1
            c.create_rectangle(cb[0], cb[1], cb[0] + s2, cb[1] + s2,
                               fill="#C98A4B", outline="")

        if p.hatched and self.state not in ("evolving", "medic", "bath"):
            head_y = base + 4 - SPR_PX + int(SPR_PX * 0.11)
            if p.sick:
                self.draw_fever(cx, head_y)
            if p.happy < 22 or (p.hygiene < 25 and p.dirt >= 3):
                self.draw_gloom(cx, head_y)

        for hx, hy, _, _, life in self.hearts:
            self.draw_heart(hx, hy, life)

        if self.bubble and self.bubble_t > 0:
            self.draw_bubble(cx, base, self.bubble)

    def draw_evolution(self, cx, base):
        """Flicker between forms, whiteout, reveal."""
        c = self.cv
        t = self.state_t
        old, new = self.evo_from, self.pet.species
        if t < EVO_FLICKER:
            rate = 2.5 + (t / EVO_FLICKER) * 13.0        # speeds up as it goes
            show_new = int(t * rate) % 2
            key = new if show_new else old
            flat = "#FFFFFF" if show_new else None
            c.create_image(cx, base + 4,
                           image=self.sprites.get(key, "idle", 0, flat,
                                                  tint=self.pet.tint),
                           anchor="s")
        elif t < EVO_FLICKER + 0.45:
            k = (t - EVO_FLICKER) / 0.45
            c.create_image(cx, base + 4,
                           image=self.sprites.get(new, "idle", 0, "#FFFFFF",
                                                  tint=self.pet.tint),
                           anchor="s")
            r = 30 + 120 * ease_out(k)
            c.create_oval(cx - r, base - 60 - r * 0.7, cx + r, base - 60 + r * 0.7,
                          outline="#FFFFFF", width=max(1, int(6 * (1 - k))))
        else:
            c.create_image(cx, base + 4,
                           image=self.sprites.get(new, "happy", 0,
                                                  tint=self.pet.tint),
                           anchor="s")


    def draw_fever(self, cx, head_y):
        """Heat coming off it in waves, plus a bead of sweat."""
        c = self.cv
        for i in (-1, 0, 1):
            ox = cx + i * 15
            pts = []
            for k in range(7):
                wob = math.sin(self.phase * 3.0 + k * 0.85 + i * 1.7) * 4.5
                pts += [ox + wob, head_y - 2 - k * 7]
            c.create_line(*pts, fill="#F09A8E", width=2, smooth=True)
        t = (self.phase * 0.9) % 1.0                     # sweat, running down
        sx = cx + 26
        sy = head_y + 16 + t * 26
        c.create_oval(sx - 3, sy - 4, sx + 3, sy + 3, fill="#BFE8F5", outline="")
        c.create_polygon(sx, sy - 8, sx - 3, sy - 2, sx + 3, sy - 2,
                         fill="#BFE8F5", outline="")

    def draw_gloom(self, cx, head_y):
        """Its own small weather system."""
        c = self.cv
        cy = head_y - 34
        drift = math.sin(self.phase * 0.8) * 4
        for ox, oy, rx, ry in ((-16, 5, 11, 8), (0, 0, 15, 11), (15, 5, 11, 8)):
            c.create_oval(cx + ox + drift - rx, cy + oy - ry,
                          cx + ox + drift + rx, cy + oy + ry,
                          fill="#565C6B", outline="")
        for ox, oy, rx, ry in ((-14, 3, 8, 5), (2, -2, 11, 7)):
            c.create_oval(cx + ox + drift - rx, cy + oy - ry,
                          cx + ox + drift + rx, cy + oy + ry,
                          fill="#6A7183", outline="")
        for i in range(4):                                # rain
            t = (self.phase * 1.3 + i * 0.27) % 1.0
            rx = cx + drift + (i - 1.5) * 11
            ry = cy + 12 + t * 34
            c.create_rectangle(rx, ry, rx + 2, ry + 7,
                               fill="#8FB6D6" if t < 0.8 else "#6E93B0",
                               outline="")

    def draw_heart(self, hx, hy, life):
        """A 7x6 pixel heart."""
        c = self.cv
        col = ACCENT if life > 0.5 else "#E8B85A"
        s = 2 if life > 0.35 else 1
        rows = ["0110110", "1111111", "1111111", "0111110", "0011100", "0001000"]
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch == "1":
                    x, y = hx + (i - 3) * s, hy + (j - 3) * s
                    c.create_rectangle(x, y, x + s, y + s, fill=col, outline="")

    def wrap(self, text, font, max_px):
        """Greedy wrap using the font's real pixel widths."""
        words, lines, cur = text.split(), [], ""
        for wd in words:
            trial = f"{cur} {wd}".strip()
            if cur and font.measure(trial) > max_px:
                lines.append(cur)
                cur = wd
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines[:4]

    def draw_bubble(self, cx, base, text):
        c = self.cv
        author = self.bubble_author
        fu, fs = self.font_ui, self.font_small
        lines = self.bubble_lines or [text]
        widest = max(fu.measure(l) for l in lines)
        lh = fu.metrics("linespace")
        ah = 0
        if author:
            atxt = f"- {author}"
            widest = max(widest, fs.measure(atxt))
            ah = fs.metrics("linespace")
        w = min(W - 8, max(52, widest + 22))
        bh = 10 + len(lines) * lh + ah
        # sprites carry blank padding above the creature, so sit the bubble
        # relative to where the artwork actually starts
        head = base + 4 - SPR_PX + int(SPR_PX * 0.11)
        y = head - 6 - bh
        x0, x1 = cx - w / 2, cx + w / 2
        for dx, dy in ((2, 0), (0, 2)):              # blocky stepped border
            c.create_rectangle(x0 - dx, y - dy, x1 + dx, y + bh + dy,
                               fill=INK, outline="")
        c.create_rectangle(x0, y, x1, y + bh, fill="white", outline="")
        c.create_rectangle(cx - 4, y + bh, cx + 4, y + bh + 5, fill=INK, outline="")
        c.create_rectangle(cx - 4, y + bh - 2, cx + 4, y + bh + 3, fill="white", outline="")
        c.create_rectangle(cx - 2, y + bh + 5, cx + 2, y + bh + 9, fill=INK, outline="")
        # type it out, but keep the box at its full size so nothing jumps
        total = self.bubble_total or sum(len(l) for l in lines)
        left = int(self.bubble_shown) if total else 10 ** 6
        done = left >= total
        ty = y + 5
        for line in lines:
            if left < 0:
                break
            shown = line if left >= len(line) else line[:left]
            left -= len(line)
            if shown:
                c.create_text(cx, ty, text=shown, fill=INK, font=fu, anchor="n")
            ty += lh
        if author and done:
            c.create_text(cx, y + 5 + len(lines) * lh, text=atxt,
                          fill="#6F7F7A", font=fs, anchor="n")


    # ---- loop --------------------------------------------------------------
    def loop(self):
        now = time.time()
        dt = min(0.2, now - self.last_t)
        self.last_t = now
        try:
            self.update(dt)
            self.draw()
        except tk.TclError:
            return
        self.root.after(FPS_MS, self.loop)

    def run(self):
        self.root.mainloop()
        self.pet.save()


def main():
    try:
        DeskPet().run()
    except Exception:
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("DeskPet crashed", traceback.format_exc())
        except Exception:
            print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
