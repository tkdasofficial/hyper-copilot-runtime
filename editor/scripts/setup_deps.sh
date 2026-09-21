#!/usr/bin/env bash
set -e

echo "=== Hyper Editor Agent: Dependency Installation ==="

if [ -f /etc/debian_version ]; then
    echo "Detected Debian/Ubuntu system..."
    apt-get update
    apt-get install -y \
        build-essential \
        cmake \
        pkg-config \
        libavcodec-dev \
        libavformat-dev \
        libavfilter-dev \
        libswscale-dev \
        libswresample-dev \
        libavutil-dev \
        libfreetype-dev \
        libharfbuzz-dev \
        nlohmann-json3-dev \
        libomp-dev \
        fonts-dejavu-core
elif [ -f /etc/fedora-release ] || [ -f /etc/redhat-release ]; then
    echo "Detected Fedora/RHEL system..."
    dnf install -y \
        gcc-c++ \
        cmake \
        pkgconf-pkg-config \
        ffmpeg-free-devel \
        freetype-devel \
        harfbuzz-devel \
        json-devel \
        libgomp
elif [ -f /etc/arch-release ]; then
    echo "Detected Arch Linux system..."
    pacman -Sy --noconfirm \
        base-devel \
        cmake \
        pkgconf \
        ffmpeg \
        freetype2 \
        harfbuzz \
        nlohmann-json \
        openmp
else
    echo "Unsupported OS or manual installation required."
    exit 1
fi

echo "=== All dependencies installed successfully! ==="
