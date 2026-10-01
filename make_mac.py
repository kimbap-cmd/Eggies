"""Generate the macOS port from the Windows source.

Kept as a script rather than a hand-maintained second file, so the two can't
drift: everything except the platform layer is shared.
"""
import ast
import io
import sys

SRC = "/home/claude/deskpet-repo/deskpet.py"
DST = "/home/claude/deskpet-repo/deskpet_mac.py"

src = io.open(SRC, encoding="utf-8").read()
lines = src.split("\n")
tree = ast.parse(src)

# ---------------------------------------------------------------------------
# Drop everything that exists only to serve X notifications.
# ---------------------------------------------------------------------------
DROP_DEFS = {"x_window_count", "decode_subject", "classify", "XWatcher",
             "seen_path", "load_seen", "store_seen"}
DROP_NAMES = {"X_SENDERS", "PROVIDERS", "PROVIDER_NOTES", "VERBS", "SKIP",
              "X_TITLE_RE", "X_ONLY_RE", "COUNT_RE"}
DROP_METHODS = {"start_watcher", "drain_notifications", "on_notification",
                "open_x", "refresh_x_status", "show_x_setup", "check_x_window",
                "draw_badge"}

kill = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in DROP_DEFS:
        kill.append((node.lineno, node.end_lineno))
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in DROP_NAMES:
                kill.append((node.lineno, node.end_lineno))
    elif isinstance(node, ast.ClassDef) and node.name == "DeskPet":
        for sub in node.body:
            if isinstance(sub, ast.FunctionDef) and sub.name in DROP_METHODS:
                kill.append((sub.lineno, sub.end_lineno))

for needle in ("# Reading X straight off the screen",
               "# X (Twitter) notifications, read from"):
    for i, l in enumerate(lines):
        if needle in l:
            start = i
            while start > 0 and lines[start - 1].startswith("# ---"):
                start -= 1
            end = i
            while end < len(lines) - 1 and not (lines[end].startswith("# ---")
                                                and end > i):
                end += 1
            kill.append((start + 1, end + 1))
            break

drop = set()
for a, b in kill:
    drop.update(range(a - 1, b))
s = "\n".join(l for i, l in enumerate(lines) if i not in drop)

# ---------------------------------------------------------------------------
a = s.index("DEFAULT_CFG = {")
b = s.index("}", a) + 1
s = s[:a] + 'DEFAULT_CFG = {\n    "muted": False,\n    "volume": 0.7,\n}' + s[b:]

CALLSITES = [
    '''        # X notifications
        self.cfg = load_config()
        self.nq = queue.Queue()
        self.watcher = None
        self.badge = 0
        self.win_count = None
        self.last_win_check = 0.0
        self.notif_log = []
        self.x_status = "off"
        self.badge_xy = None
        self.notif_win = None
        self.start_watcher()
''',
    '''        if self.cfg.get("watch_window", True) and now - self.last_win_check > 4.0:
            self.last_win_check = now
            self.check_x_window()
''',
    '''        self.drain_notifications()
''',
    '''        m.add_separator()
        m.add_command(label="Open X notifications", command=self.open_x)
        m.add_command(label="X notifications setup...", command=self.show_x_setup)
''',
    '''        if self.badge and self.badge_xy:
            bx, by = self.badge_xy
            if (e.x - bx) ** 2 + (e.y - by) ** 2 < 15 ** 2:
                self.open_x()
                return
''',
    '''            self.badge_xy = None
            if self.badge:
                bx, by = cx + int(SPR_PX * 0.20), base - int(SPR_PX * 0.64)
                self.badge_xy = (bx, by)
                self.draw_badge(bx, by)
''',
    '''        if self.watcher:
            self.watcher.stop()
''',
    '''        self.badge = 0
        self.notif_log = []
''',
    '''        self.pet.save()
        self.badge = 0
        self.win_count = None
        self.last_win_check = 0.0
        self.notif_log = []
''',
]
for frag in CALLSITES:
    if frag == '''        self.pet.save()
        self.badge = 0
        self.win_count = None
        self.last_win_check = 0.0
        self.notif_log = []
''':
        s = s.replace(frag, "        self.pet.save()\n")
    else:
        s = s.replace(frag, "")

s = s.replace("        self.sprites = SpriteBank()",
              "        self.cfg = load_config()\n        self.sprites = SpriteBank()")
s = s.replace('and (p.notif_count >= 5 or p.play_count >= 25)):',
              'and p.play_count >= 25):')

# ---------------------------------------------------------------------------
# imports
# ---------------------------------------------------------------------------
for drop_imp in ("import email as emaillib\n", "import imaplib\n", "import ssl\n",
                 "import queue\n", "import re\n",
                 "from email.header import decode_header\n"):
    s = s.replace(drop_imp, "")
s = s.replace("import json\n", "import json\nimport subprocess\n")

# ---------------------------------------------------------------------------
# audio: afplay instead of winsound
# ---------------------------------------------------------------------------
s = s.replace('''try:
    import winsound
except Exception:
    winsound = None''',
'''# macOS ships afplay, so nothing needs installing. Unlike winsound it will
# mix several sounds at once, so speech never has to queue behind a cry.
def afplay(path):
    try:
        return subprocess.Popen(["afplay", path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except Exception:
        return None''')

s = s.replace('''        if self.muted or not self.ready or winsound is None:
            return''', '''        if self.muted or not self.ready:
            return''')
s = s.replace('''        try:
            winsound.PlaySound(fp, winsound.SND_FILENAME | winsound.SND_ASYNC
                               | winsound.SND_NODEFAULT)
        except Exception:
            pass''', '''        afplay(fp)''')
s = s.replace('''        return min(0.8, max(0.0, (self.last + self.last_dur) - time.time()))''',
              '''        return 0.0            # afplay mixes; nothing waits its turn''')
s = s.replace('''        if self.muted or not self.ready or winsound is None or not text:''',
              '''        if self.muted or not self.ready or not text:''')
s = s.replace('''        def go():
            try:
                winsound.PlaySound(fp, winsound.SND_FILENAME | winsound.SND_ASYNC
                                   | winsound.SND_NODEFAULT)
                self.last = time.time()
                self.last_dur = secs
            except Exception:
                pass

        if delay <= 0.01:
            go()
        else:
            threading.Timer(delay, go).start()
        return delay, secs''',
'''        try:                              # stop the previous line first, so
            if self.talking:              # two utterances never overlap
                self.talking.terminate()
        except Exception:
            pass
        self.talking = afplay(fp)
        self.last = time.time()
        self.last_dur = secs
        return 0.0, secs''')
s = s.replace('''        self.slot = 0
        self.last = 0.0''', '''        self.slot = 0
        self.talking = None
        self.last = 0.0''')
s = s.replace('''    """Builds the bank in the background, then plays WAVs via winsound."""''',
              '''    """Builds the bank in the background, then plays the WAVs via afplay."""''')
s = s.replace('''# played once, because winsound only keeps a single sound alive at a time.''',
              '''# played once - simpler than firing one process per blip.''')

# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
a = s.index("def work_area():")
b = s.index("def save_path():")
s = s[:a] + '''def set_dpi_aware():
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


''' + s[b:]

# the old Windows set_dpi_aware is now orphaned between work_area and save_path
old_dpi_start = s.find("def set_dpi_aware():\n    \"\"\"Per-monitor v2")
if old_dpi_start != -1:
    old_dpi_end = s.index("\n\n\n", old_dpi_start) + 3
    s = s[:old_dpi_start] + s[old_dpi_end:]

s = s.replace('''        wa = work_area()
        if wa:''', '''        measure_screen(self.root)
        wa = work_area()
        if wa:''')

s = s.replace('''    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "DeskPet")''',
'''    d = os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                     "DeskPet")''')

# ---------------------------------------------------------------------------
# transparency
# ---------------------------------------------------------------------------
s = s.replace('''        self.root.config(bg=TRANS)
        try:
            self.root.attributes("-transparentcolor", TRANS)
        except tk.TclError:
            messagebox.showwarning("DeskPet", "Transparency isn't available on this system,\\n"
                                              "so the pet will sit on a coloured square.")''',
'''        # macOS has no colour key. -transparent makes the window background
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
                "Python rather than the system one.")''')

s = s.replace('''        self.cv = tk.Canvas(self.root, width=W, height=H, bg=TRANS,
                            highlightthickness=0, bd=0)''',
'''        self.cv = tk.Canvas(self.root, width=W, height=H, bg=self.clear_bg,
                            highlightthickness=0, bd=0)''')

s = s.replace('''        w.config(bg=TRANS)
        try:
            w.attributes("-transparentcolor", TRANS)
        except tk.TclError:
            pass
        n = self.SIZE''',
'''        bg = getattr(app, "clear_bg", TRANS)
        try:
            w.wm_attributes("-transparent", True)
        except tk.TclError:
            pass
        w.config(bg=bg)
        n = self.SIZE''')
s = s.replace('''        c = tk.Canvas(w, width=n, height=n, bg=TRANS, highlightthickness=0, bd=0)''',
'''        c = tk.Canvas(w, width=n, height=n, bg=bg, highlightthickness=0, bd=0)''')

# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------
s = s.replace('''        fam = pick_font(self.root, ["Fixedsys", "Terminal", "Small Fonts",
                                    "Consolas", "Courier New"], 10)[0]''',
'''        fam = pick_font(self.root, ["Monaco", "Menlo", "Andale Mono",
                                    "Courier New"], 10)[0]''')
s = s.replace('family="Segoe UI Semibold"', 'family="Helvetica Neue"')
s = s.replace('family="Segoe UI"', 'family="Helvetica Neue"')
s = s.replace('return ("Courier New", size)', 'return ("Menlo", size)')

# ---------------------------------------------------------------------------
header = '''"""
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
'''
first_doc_end = s.index('"""', s.index('"""') + 3) + 3
s = header + s[first_doc_end:]

io.open(DST, "w", encoding="utf-8").write(s)
print(f"wrote {DST}: {len(s.split(chr(10)))} lines")
