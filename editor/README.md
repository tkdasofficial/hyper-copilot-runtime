# Hyper Editor Agent (Advanced Headless Editor)

A production-grade, highly modular **Advanced Headless Editor** written strictly in modern C++ (C++17/C++20) utilizing direct FFmpeg C-APIs (`libavcodec`, `libavformat`, `libavfilter`, `libswscale`, `libswresample`, `libavutil`), FreeType2, HarfBuzz, and `nlohmann/json`.

Designed for headless execution inside cloud servers, microservices, and CI/CD runners (e.g., GitHub Actions) without any GUI overhead.

---

## Architecture & Modular Design

```
.
├── CMakeLists.txt              # Standard production CMake build definition
├── include/
│   ├── core/
│   │   ├── editor.hpp          # Advanced Headless Editor orchestrator
│   │   ├── ffmpeg_bridge.hpp   # Direct libav* decoder/encoder bridge
│   │   └── timeline.hpp        # Core timeline, clip, track & keyframe data types
│   ├── parsers/
│   │   └── json_parser.hpp     # Timeline JSON configuration parser
│   ├── tools/
│   │   ├── audio_effects.hpp   # RBJ Biquad filters, 3-band EQ, noise gate, pitch shift
│   │   ├── audio_mixer.hpp     # Multi-track mixing with automatic ducking
│   │   ├── captions.hpp        # FreeType2 & HarfBuzz kinetic typography & glow
│   │   ├── chroma_key.hpp      # Green/blue screen keyer with despill algorithms
│   │   ├── color_grading.hpp   # Exposure, contrast, saturation & 3D LUT grading
│   │   ├── frame_scaler.hpp    # 16:9, 9:16, 1:1 scaling, smart crop & letterbox
│   │   ├── keyframing.hpp      # Linear, Ease-In, Ease-Out & Cubic Bezier curves
│   │   ├── masking.hpp         # Rectangular, elliptical, linear masks & feathering
│   │   ├── motion_zoom.hpp     # Ken Burns pan & scan with motion blur
│   │   ├── overlays.hpp        # Multiply, Screen, Overlay, Additive blend modes
│   │   ├── speed_ramping.hpp   # Non-linear speed curves & audio stretching
│   │   └── transitions.hpp     # Crossfade, Zoom, Wipe, Gaussian Blur transitions
│   └── utils/
│       ├── logger.hpp          # Thread-safe ANSI terminal logger & progress bar
│       └── memory.hpp          # RAII smart pointers for AVFrame, AVPacket, buffers
├── sample_timeline.json        # Test timeline demonstrating all 12 tools
├── scripts/
│   ├── build.sh                # Automated Release build script
│   └── setup_deps.sh           # System package installation script
└── src/                        # Complete C++ implementations matching include/
```

---

## The 12 Headless Editing Tools

1. **Keyframing Tool**: Evaluates continuous parameter changes across clip timelines supporting Linear, Ease-In, Ease-Out, Ease-InOut, and custom Cubic Bezier (`(x1, y1, x2, y2)`) curves.
2. **Masking Tool**: Applies custom shape masks (Rectangular, Elliptical, Linear gradient) with configurable edge feathering and inversion.
3. **Overlays & Blending Tool**: Multi-track composition supporting standard alpha compositing as well as Photoshop-grade blend modes: `Multiply`, `Screen`, `Overlay`, and `Additive`.
4. **Dynamic Captions Tool**: Renders text using FreeType2 and HarfBuzz shaping with word-by-word timing highlights, customizable neon glow, and pop-in scaling.
5. **Transitions Tool**: Inter-scene transitions: `Crossfade`, `Zoom-In`, `Zoom-Out`, directional `Wipes` (Left/Right/Up/Down), and multi-pass separable `Gaussian Blur`.
6. **Audio Mixer Tool**: Mixes multiple audio tracks with volume levels, soft-knee peak limiting, and intelligent voiceover auto-ducking with configurable attack/release envelopes.
7. **Color Grading & 3D LUT Tool**: Real-time color correction (exposure, brightness, contrast, saturation) and Adobe `.cube` 3D LUT trilinear interpolation.
8. **Motion Zoom Tool**: Cinematic Ken Burns pan-and-scan camera motion with multi-frame temporal motion blur accumulation.
9. **Speed Ramping Tool**: Non-linear speed ramping curves with synchronized timeline-to-source time remapping.
10. **Chroma Key Tool**: Background removal for green/blue screens utilizing YUV/RGB color distance metric, soft edge alpha blending, and green spill suppression.
11. **Audio Effects Tool**: DSP audio chain including Robert Bristow-Johnson Biquad High-Pass and Low-Pass filters, 3-Band Equalizer (Low Shelf, Mid Peaking, High Shelf), Noise Gate, and pitch shifting.
12. **Frame Scaler Tool**: Multi-aspect ratio scaling (16:9, 9:16 vertical video for Reels/TikTok/Shorts, 1:1 square) supporting Letterbox, Smart-Crop, and Stretch modes via `libswscale`.

---

## Building & Verification

### 1. Install System Dependencies
```bash
./scripts/setup_deps.sh
```

### 2. Build with CMake
```bash
./scripts/build.sh
```

### 3. Run Headless Render
```bash
./build/hyper_editor --timeline sample_timeline.json -o output_master.mp4
```

### 4. CLI Arguments
- `--timeline, -t <file>`: Path to input JSON timeline specification (Required).
- `--output, -o <file>`: Override output MP4 container destination path.
- `--threads, -j <N>`: Set worker thread count (defaults to auto-detect CPU cores).
- `--verbose, -v`: Enable verbose debug logging.
- `--help, -h`: Display usage information.
