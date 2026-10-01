# Eggies

A pixel-art virtual pet that lives on your desktop — not in a window, on the
wallpaper itself. Feed it, play with it, keep it clean, and find out what it
grows into.

One file. Pure Python standard library. **No `pip install`, no dependencies.**

```
python deskpet.py
```

---

## What it does

You get an egg and a letter from its mother, who had to leave. Ninety seconds
later it hatches into one of three creature lines — you don't get to choose
which — and then it's yours for three days.

It wanders your desktop, naps, gets hungry, makes a mess, and talks. A lot.

**It grows into one of 24 forms.** Three lines, each branching twice, and which
branch you get depends entirely on how you treated it. Keep it fed and happy
and it goes one way; neglect it and it goes another. One form per line is rare
and needs near-perfect care.

**It has a personality**, rolled separately from its species, so the same
creature can turn up stoic or restless. It changes how fast it gets hungry, how
far it wanders, and how much it talks.

**It says about 300 different things** — kid-logic observations as a baby,
literary and film-genre quotes once grown, and pointed remarks when you've been
neglecting it.

> me not tired. me just resting me eyes wif me whole body

> my real mother would not have let me live like this

**Play is a quiz.** 74 true/false fun facts, balanced so guessing "true" every
time scores about 50%.

**Hygiene is real.** It leaves messes on your desktop that you have to click to
clean. Let it get filthy and it falls ill — and sickness only clears if you
pass a 5-out-of-5 health quiz, after which a pixel medic walks on screen and
gives it a shot.

**Bathing is a minigame** — rub a sponge over it to scrub the dirt off.

**It has a voice.** Every line it says is spoken in Game Boy-style blips,
pitched from the letters themselves, so the same word always sounds the same.
Its cry is generated from its name.

After three days it packs a suitcase and leaves, for reasons it has thought
about very carefully:

> I named a cloud last Tuesday, which means it belongs to me now. those are the
> rules

You can ask it to stay, or let it go and take in a new egg.

---

## Controls

| | |
|---|---|
| drag | pick it up and drop it |
| double-click | pet it — or wake it, if it's asleep |
| right-click | the menu |

Menu items grey out when they don't apply: **Bath** only when it's dirty,
**Call medic** only when it's sick, everything but dragging while it sleeps.

There's a hidden panel for testing — open **Stats** and click it five times.

---

## How it works

Everything is generated at runtime. There are no image or sound files.

**Transparency** uses a magenta colour key with `-transparentcolor`, which makes
those pixels not just invisible but click-through, so the desktop keeps working
underneath. Sprites carry real per-pixel alpha so they can overlap without
punching holes.

**Sprites** are rasterised into a 56×56 cell grid and scaled up 2.4×, with a
1px outline in a warm dark version of each pet's own colour. Every pet rolls its
own tint, so no two are quite the same shade.

**Sound** is a Game Boy synthesiser written from scratch — pulse waves with
12.5/25/50/75% duty cycles, a 15-bit LFSR for noise, 16-step volume envelopes,
and 4-bit output quantisation. Rendered to WAVs on first run.

**Saves** live in `%APPDATA%\DeskPet\`. Stats keep draining while the app is
closed, capped at 12 hours.

---

## Requirements

Windows, and Python 3 with tkinter (included in the standard python.org
installer — just don't untick "tcl/tk and IDLE").

`deskpet_mac.py` is a macOS port. It uses `afplay` for sound and Tk's
`-transparent` instead of the Windows colour key. It is **untested on real
hardware** — see the notes at the top of the file.

---

## Optional: X notifications

The pet can react when your X notifications come in. Two ways, either or both,
set up under **X notifications setup…**:

- **Reading the browser window title** (on by default). X puts the unread count
  in its page title. Costs nothing, needs no login. X has to be the active tab,
  so running it in its own window helps:
  `chrome.exe --app=https://x.com/notifications`
- **Reading X's notification emails over IMAP.** Needs an app password. Opens
  your mailbox read-only and never marks anything as read. Works with Gmail,
  Yahoo, iCloud, Fastmail, Zoho, GMX and Proton via Bridge. **Not** Outlook —
  Microsoft ended basic authentication in March 2026.

There's no API option: X ended free API reads in February 2026, and never had a
notifications endpoint anyway.

---

## `android-starter/`

An unrelated side quest — a toolchain starter for building Android APKs with
Buildozer, with a small test app that exercises canvas drawing, touch, storage
and an animation clock. See its README.

DeskPet itself doesn't run on Android: a borderless always-on-top window on the
wallpaper is a desktop idea, and Android has no equivalent.

---

## Credits

Creatures, dialogue, music and sprites are original. The pet's structure owes an
obvious debt to Tamagotchi and to branching-evolution games, but nothing is
copied from them — no sprites, no names, no dialogue, no music. Literary quotes
are public domain; film-style lines are written in the voice of a genre and
credited to the genre, not to any film.

MIT licensed.
