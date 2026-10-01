"""
Toolchain test app.

This is deliberately tiny, but it is NOT "hello world" - it exercises the
four things the pet actually needs, so if this builds and runs, the real
app will too:

    1. drawing shapes to a canvas   (the sprites)
    2. touch input                  (dragging, scrubbing)
    3. writing to app storage       (the save file)
    4. an animation clock           (the game loop)

If it builds but misbehaves on the phone, the failure tells you which of
those four is the problem.
"""

import json
import os
import random

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget


class Blob(Widget):
    """A creature-ish thing that bobs, and follows your finger."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.t = 0.0
        self.pos_x = 0.5          # as a fraction of the screen
        self.pos_y = 0.5
        self.target = None
        self.hue = random.random()
        Clock.schedule_interval(self.tick, 1 / 30.0)

    def tick(self, dt):
        self.t += dt
        if self.target:
            tx, ty = self.target
            self.pos_x += (tx - self.pos_x) * min(1.0, dt * 6)
            self.pos_y += (ty - self.pos_y) * min(1.0, dt * 6)
        self.redraw()

    def redraw(self):
        from math import sin
        self.canvas.clear()
        w, h = self.width, self.height
        cx = self.x + self.pos_x * w
        cy = self.y + self.pos_y * h
        bob = sin(self.t * 3) * 6
        size = min(w, h) * 0.22
        squash = 1.0 + sin(self.t * 3) * 0.06

        with self.canvas:
            Color(0.5, 0.82, 0.72)
            Ellipse(pos=(cx - size / 2 * squash, cy - size / 2 / squash + bob),
                    size=(size * squash, size / squash))
            Color(0.12, 0.23, 0.20)                       # eyes
            for sd in (-1, 1):
                Ellipse(pos=(cx + sd * size * 0.20 - size * 0.07,
                             cy + size * 0.08 + bob),
                        size=(size * 0.14, size * 0.17))
            Color(1, 1, 1)
            for sd in (-1, 1):
                Rectangle(pos=(cx + sd * size * 0.20 - size * 0.05,
                               cy + size * 0.16 + bob),
                          size=(size * 0.04, size * 0.04))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.target = ((touch.x - self.x) / self.width,
                           (touch.y - self.y) / self.height)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.collide_point(*touch.pos):
            self.target = ((touch.x - self.x) / self.width,
                           (touch.y - self.y) / self.height)
            return True
        return super().on_touch_move(touch)


class TestApp(App):
    def build(self):
        self.title = "APK toolchain test"
        root = BoxLayout(orientation="vertical", padding=12, spacing=8)

        self.status = Label(text="drag the blob", size_hint=(1, 0.12),
                            color=(0.6, 0.75, 0.70, 1))
        root.add_widget(self.status)

        self.blob = Blob()
        root.add_widget(self.blob)

        bar = BoxLayout(size_hint=(1, 0.14), spacing=8)
        bar.add_widget(Button(text="save +1", on_press=self.bump))
        bar.add_widget(Button(text="load", on_press=self.load))
        root.add_widget(bar)

        self.count = 0
        self.load()
        return root

    # storage: user_data_dir is the app's private folder on the device
    def save_file(self):
        return os.path.join(self.user_data_dir, "test.json")

    def bump(self, *_):
        self.count += 1
        try:
            with open(self.save_file(), "w") as f:
                json.dump({"count": self.count}, f)
            self.status.text = f"saved count = {self.count}"
        except Exception as e:
            self.status.text = f"SAVE FAILED: {e}"

    def load(self, *_):
        try:
            with open(self.save_file()) as f:
                self.count = json.load(f).get("count", 0)
            self.status.text = f"loaded count = {self.count}  (survives restart)"
        except Exception:
            self.status.text = "no save yet - press 'save +1'"


if __name__ == "__main__":
    TestApp().run()
