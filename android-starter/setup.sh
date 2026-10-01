#!/usr/bin/env bash
#
# Buildozer setup for Ubuntu 24.04 on WSL2.
# Run with:  bash setup.sh
#
# Safe to run more than once.

set -e

echo "==> checking where we are"
if ! grep -qi microsoft /proc/version 2>/dev/null; then
    echo "    (not WSL - that's fine if this is real Linux)"
else
    echo "    WSL detected"
fi

if [ "$(pwd)" != "${HOME}"* ] && [[ "$(pwd)" == /mnt/* ]]; then
    echo ""
    echo "!!  You are in $(pwd), which is the Windows filesystem."
    echo "!!  Builds MUST run on the Linux side (/home/you/...) or they fail"
    echo "!!  on file permissions, often 20 minutes in. Move the project first:"
    echo "!!      mkdir -p ~/apk && cp -r . ~/apk && cd ~/apk"
    exit 1
fi

echo "==> system packages"
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
    python3-virtualenv python3-venv autoconf libtool pkg-config \
    zlib1g-dev libncurses-dev libtinfo6 cmake libffi-dev \
    libssl-dev automake autopoint gettext build-essential ccache \
    libltdl-dev

echo "==> selecting Java 17"
# python-for-android needs 17 specifically. Newer JDKs break the Gradle step.
sudo update-alternatives --set java \
    "$(update-alternatives --list java | grep 17 | head -1)" 2>/dev/null || true
java -version

echo "==> python virtualenv for buildozer"
python3 -m venv ~/.venv-buildozer
# shellcheck disable=SC1090
source ~/.venv-buildozer/bin/activate
pip install --upgrade pip wheel setuptools
pip install buildozer cython==0.29.36

echo "==> adding an activation shortcut"
if ! grep -q "venv-buildozer" ~/.bashrc; then
    cat >> ~/.bashrc <<'EOF'

# type 'bd' to enter the buildozer environment
alias bd='source ~/.venv-buildozer/bin/activate'
EOF
fi

echo ""
echo "==> done."
buildozer --version
echo ""
echo "Next:"
echo "  1. source ~/.venv-buildozer/bin/activate     (or just: bd)"
echo "  2. cd to the folder with main.py"
echo "  3. buildozer -v android debug"
echo ""
echo "The FIRST build downloads the Android SDK and NDK and compiles"
echo "Python itself - expect 20-45 minutes and a few GB. Later builds"
echo "take 1-3 minutes. Leave it alone; it is not stuck."
