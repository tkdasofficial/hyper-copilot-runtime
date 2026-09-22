# Hyper Copilot Runtime

Advanced AI-driven architecture uniting high-performance C++ rendering engines with the **Native C++ Heavy Web Research Engine** (`web-research/`).

---

## Architecture Overview

```
hyper-copilot-runtime/
├── .github/workflows/
│   ├── create-video.yml        # Landscape 16:9 documentary pipeline via C++ engine
│   ├── create-reel.yml         # Vertical 9:16 reel pipeline via C++ engine
│   └── web-research.yml        # Heavy web research triggered via Native C++ Engine
├── editor/                     # Video Editing & FFmpeg Rendering Engine
└── web-research/               # Native C++ Heavy Web Research Engine
    ├── CMakeLists.txt          # Native C++17 build configuration
    ├── build.sh                # CMake build runner
    ├── run_heavy_fetch.sh      # CLI heavy research & fetch runner
    ├── include/                # Native headers
    ├── src/                    # Native C++ CDP implementation & main
    └── extensions/             # Stealth, DuckDuckGo search, screen recorder, screenshot
```

---

## Native C++ Heavy Web Research Engine (`web-research/`)

The repository builds a dedicated **Native C++ Headless Browser** executable (`hyper_vision_agent_engine`) leveraging direct Chrome DevTools Protocol (CDP) WebSocket communication and process isolation:
- **Zero-Node Native C++ Implementation**: Built in ISO C++17 (`process_launcher.cpp`, `websocket_client.cpp`, `cdp_connection.cpp`, `browser_session.cpp`, `page.cpp`, `engine.cpp`).
- **Low-Latency CDP IPC**: Sub-millisecond direct JSON-RPC command dispatching over WebSockets.
- **Stealth Extensions**: Native Bezier/Spline human mouse simulation, webdriver masking, and runtime property spoofing (`extensions/anti_bot_stealth/`).
- **Heavy Data Fetching**: Deep DOM extraction, structured JSON reporting, and hardware-accelerated screenshot capture (`extensions/screenshot/`, `extensions/duckduckgo_search/`).

---

## CI/CD Concurrency & Execution Guards
- All GitHub Actions workflows enforce `concurrency` groups with `cancel-in-progress: true` to prevent job queuing bottlenecks and respect GitHub Actions runner limits.
