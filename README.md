# Hyper Copilot Runtime

Advanced AI-driven architecture uniting high-performance C++ rendering engines with automated dual-mode Web Research workflows.

---

## Architecture Overview

```
hyper-copilot-runtime/
├── .github/workflows/
│   ├── create-video.yml        # Landscape 16:9 documentary pipeline via C++ engine
│   ├── create-reel.yml         # Vertical 9:16 reel pipeline via C++ engine
│   ├── web_research.yml        # Dual-mode public & private authenticated web research
│   └── web-research.yml        # Workflow alias
├── editor/                     # Primary Native C++ High-Performance Engine
│   ├── CMakeLists.txt          # Unified C++17 build for Editor & Vision Agent Core
│   ├── include/                # Core C++ headers (FFmpeg bridge, timeline, vision SDK)
│   │   ├── core/
│   │   ├── hyper_vision_agent/ # Headless CDP browser & vision agent headers
│   │   ├── parsers/
│   │   ├── tools/
│   │   └── utils/
│   ├── src/                    # Video engine & Vision engine sources
│   │   ├── core/
│   │   ├── parsers/
│   │   ├── tools/
│   │   ├── utils/
│   │   └── vision/             # CDP client, process launcher, session manager
│   ├── extensions/             # Anti-bot stealth, DDG search, screen recorder, screenshot
│   ├── long_form_pipeline.py   # Primary unified rendering pipeline (16:9 & 9:16)
│   └── export_to_drive.py      # Google Drive export integration
└── web_researcher/             # Automated Web Research Module
    ├── README.md               # Research module documentation
    ├── package.json            # Node automation scripts
    ├── research_agent.py       # Dual-mode research engine with dynamic 2FA/OTP handling
    └── web-sdk/                # High-Performance stateless Chromium CDP Web SDK
```

---

## Key Modules

### 1. Primary C++ Editor Engine (`editor/`)
- **Direct FFmpeg C-APIs**: Zero-overhead frame manipulation (`libavcodec`, `libavformat`, `libavfilter`, `libswscale`, `libswresample`).
- **Dynamic Kinetics**: HarfBuzz & FreeType2 animated typography, captions, and glow shaders.
- **Vision Agent Core**: Stateless Chromium CDP headless browser integration in native C++17.

### 2. Dual-Mode Web Research Workflows (`web_researcher/`)
- **Mode A (Public Web Research)**: Open-web search indexing, DOM extraction, and synthesis without requiring credentials.
- **Mode B (Private Web Research)**: Authenticated access with automated account creation/sign-up, credentials log-in, and dynamic interactive 2FA/OTP barriers.

### 3. CI/CD Concurrency & Execution Guards
- All GitHub Actions workflows enforce `concurrency` groups with `cancel-in-progress: true` to prevent queuing bottlenecks and resource exhaustion.
- Primary C++ engine serves as the single source of truth for both long-form and vertical short-form rendering.
