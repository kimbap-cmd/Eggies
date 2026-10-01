# Building your first APK

The goal here is a working toolchain, proven by a small app, before you
point it at anything large.

---

## Why WSL2 and not Windows

Buildozer only runs on Linux or macOS. On Windows you use WSL2 — and it
**must be WSL2, not WSL1**; WSL1 does not work at all.

Ubuntu 24.04 is the version to pick. Its default Python is 3.12, which the
stable python-for-android branch supports. Ubuntu 26.04 ships Python 3.14,
which currently needs the in-development branch and extra configuration —
not what you want on your first attempt.

---

## Step 1 — Install WSL2

In **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Reboot when it asks. On first launch it asks for a username and password.
The password isn't echoed as you type — no asterisks, nothing. That's
normal. Write it down; you'll need it for every `sudo`.

Check you got version 2:

```powershell
wsl -l -v
```

If it says `1`, fix it:

```powershell
wsl --set-version Ubuntu-24.04 2
```

---

## Step 2 — Run the setup script

Copy this folder into WSL. **This part matters more than it looks.**

Open Ubuntu and run:

```bash
mkdir -p ~/apk
cd ~/apk
```

Then copy the three files here into `~/apk`. From Windows you can reach it
at `\\wsl$\Ubuntu-24.04\home\<you>\apk` in Explorer.

Then:

```bash
bash setup.sh
```

This installs Java 17, the build dependencies, and Buildozer in a
virtualenv. Ten minutes or so.

### The one mistake everyone makes

**Never build in `/mnt/c/`.** It's tempting — your Windows files are right
there. But the Windows filesystem doesn't support Linux permissions, and
the build fails on it, usually twenty minutes in with an error that doesn't
mention permissions at all. Always work in `~/`. The setup script refuses
to run if you get this wrong.

---

## Step 3 — Build

```bash
source ~/.venv-buildozer/bin/activate
cd ~/apk
buildozer -v android debug
```

**The first build takes 20–45 minutes.** It downloads the Android SDK and
NDK and compiles CPython for ARM. It will sit on some steps for many
minutes looking frozen. It isn't. Let it run.

Subsequent builds take 1–3 minutes.

The result lands in `bin/apktest-0.1-arm64-v8a_armeabi-v7a-debug.apk`.

---

## Step 4 — Get it onto the phone

**The easy way:** copy the APK to Windows and transfer it however you
normally move files.

```bash
cp bin/*.apk /mnt/c/Users/t1030/Desktop/
```

On the phone, tap the file. Android will ask you to allow installing from
unknown sources — that's expected for anything not from the Play Store.

**The better way, once you're iterating:** enable Developer Options on the
phone (Settings → About → tap Build Number seven times), turn on USB
Debugging, then:

```bash
buildozer android debug deploy run logcat
```

That builds, installs, launches, and streams the phone's log to your
terminal. `logcat` is how you debug — a Python traceback on the phone
appears there and nowhere else. It's the single most useful command in
this toolchain.

USB passthrough to WSL2 needs `usbipd-win` on the Windows side. If that's
more trouble than it's worth, copying the file manually is fine.

---

## What the test app proves

It isn't hello-world. It exercises the four things the pet needs:

| What | Why it matters |
|---|---|
| Canvas drawing | the sprites |
| Touch and drag | picking it up, scrubbing it |
| Saving to `user_data_dir` | the save file |
| A 30fps clock | the game loop |

Drag the blob, press **save +1**, force-close the app, reopen it, press
**load**. If the count survived, storage works.

---

## When it breaks

It will break. That's normal, and the errors are unhelpful. The common ones:

**`Aidl not found`** — the SDK didn't fully download. Delete `~/.buildozer`
and build again.

**Any Java/Gradle error** — you're on the wrong JDK. Check with
`java -version`; it must be 17. Fix with
`sudo update-alternatives --config java`.

**`Could not create Venv`** — install `python3-venv` and re-run setup.

**Fails around 20 minutes with a permissions error** — you're building in
`/mnt/c/`. Move to `~/`.

**Cython errors** — the version matters. `cython==0.29.36` is what the
setup script pins; newer ones break python-for-android.

**Anything else** — start clean:

```bash
buildozer android clean
rm -rf .buildozer
```

The full error is almost never the last line printed. Scroll up.

---

## When you're ready for the pet

Once this builds and runs, the pet is a rewrite rather than a port: the
species, evolution, personalities, dialogue, quizzes and synth all carry
over unchanged, but every window and every drawing call is Kivy instead of
tkinter.

The `requirements` line in `buildozer.spec` will need `pillow` for image
handling, and possibly `plyer` for notifications. Each addition is another
way for the build to fail, which is exactly why you're proving the simple
case first.
