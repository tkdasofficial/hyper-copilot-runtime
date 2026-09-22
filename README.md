# Hyper Copilot Runtime

Advanced AI-driven architecture uniting high-performance C++ rendering engines with the **Native C++ Headless Browser** and automated dual-mode Web Research workflows.

---

## Architecture Overview

```
hyper-copilot-runtime/
├── .github/workflows/
│   ├── create-video.yml        # Landscape 16:9 documentary pipeline via C++ engine
│   ├── create-reel.yml         # Vertical 9:16 reel pipeline via C++ engine
│   ├── web_research.yml        # Dual-mode public & private research via Native C++ Browser
│   └── web-research.yml        # Workflow alias
├── editor/                     # Primary Native C++ High-Performance Engine
│   ├── CMakeLists.txt          # Unified C++17 build for Editor & Vision Agent Core
│   ├── include/                # Core C++ headers (FFmpeg bridge, timeline, vision SDK)
│   │   ├── core/
│   │   ├── hyper_vision_agent/ # Native C++ Headless Browser headers
│   │   ├── parsers/
│   │   ├── tools/
│   │   └── utils/
│   ├── src/                    # Video engine & Native C++ Vision Engine sources
│   │   ├── core/
│   │   ├── parsers/
│   │   ├── tools/
│   │   ├── utils/
│   │   └── vision/             # Native C++ CDP client, launcher, session manager, browser engine
│   ├── extensions/             # Native C++ Anti-bot stealth, DDG search, screen recorder, screenshot
│   ├── long_form_pipeline.py   # Primary unified rendering pipeline (16:9 & 9:16)
│   └── export_to_drive.py      # Google Drive export integration
└── web_researcher/             # Automated Web Research Module
    ├── README.md               # Research module documentation
    ├── package.json            # Run scripts
    └── research_agent.py       # Dual-mode research engine with dynamic 2FA/OTP handling
```

---

## Native C++ Headless Browser Engine (`editor/src/vision/`)

The repository builds a dedicated **Native C++ Headless Browser** executable (`hyper_vision_agent_engine`) leveraging direct Chrome DevTools Protocol (CDP) WebSocket communication and process isolation:
- **Zero-Node Native C++ Implementation**: Built in ISO C++17 (`process_launcher.cpp`, `websocket_client.cpp`, `cdp_connection.cpp`, `browser_session.cpp`, `page.cpp`, `engine.cpp`).
- **Low-Latency CDP IPC**: Sub-millisecond direct JSON-RPC command dispatching over WebSockets.
- **Stealth Extensions**: Native Bezier/Spline human mouse simulation, webdriver masking, and runtime property spoofing (`extensions/anti_bot_stealth/`).
- **Precision Capture**: Hardware-accelerated full-page PNG capture and screencasting (`extensions/screenshot/`, `extensions/screen_recorder/`).

---

## Dual-Mode Web Research Workflows (`web_researcher/`)
- **Mode A (Public Web Research)**: Open-web search indexing, DOM extraction, and synthesis without requiring credentials.
- **Mode B (Private Web Research)**: Authenticated access with automated account creation/sign-up, credentials log-in, and dynamic interactive 2FA/OTP barriers.

---

## CI/CD Concurrency & Execution Guards
- All GitHub Actions workflows enforce `concurrency` groups with `cancel-in-progress: true` to prevent job queuing bottlenecks and respect GitHub Actions runner limits.
- Primary C++ engine serves as the single source of truth for all heavy video and browser automation workloads.
