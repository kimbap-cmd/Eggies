[app]

# What the app is called on the phone's home screen
title = APK Test

# Internal name - letters and numbers only, no spaces
package.name = apktest

# Reverse-domain id. Must be unique on the device and on Play.
# Anything you control works; org.test is fine while learning.
package.domain = org.test

source.dir = .

# Which file types get packaged. If you add sounds or images later, the
# extension MUST be listed here or the file silently won't ship.
source.include_exts = py,png,jpg,kv,atlas,json,wav,ttf

version = 0.1

# Python packages to bundle. python3 and kivy are the baseline.
# Every extra one is a chance for the build to fail, so add sparingly.
requirements = python3,kivy

orientation = portrait
fullscreen = 0

# ---------------------------------------------------------------------------
# Android specifics
# ---------------------------------------------------------------------------

# Target the current Play requirement; 21 covers Android 5 and up.
android.api = 34
android.minapi = 21

# NDK 25b pairs reliably with the stable python-for-android branch.
android.ndk = 25b

# Both modern architectures. Dropping to just arm64-v8a roughly halves
# build time while you're learning - almost every real phone is arm64.
android.archs = arm64-v8a, armeabi-v7a

# Accept the Android SDK licences without prompting mid-build
android.accept_sdk_license = True

# Permissions. The test app needs none. The pet would add INTERNET here
# only if it ever talked to the network, and SYSTEM_ALERT_WINDOW if you
# ever went the floating-overlay route.
# android.permissions = INTERNET

# Keep the screen on while the app is open (handy for a pet)
# android.wakelock = True

[buildozer]

# 2 = show everything. Keep it here: when a build fails you need the log.
log_level = 2
warn_on_root = 1
