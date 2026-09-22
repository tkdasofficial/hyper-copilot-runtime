# Native C++ Heavy Web Research Engine (`web-research/`)

Stateless high-performance C++17 Headless Browser Engine powered by Chrome DevTools Protocol (CDP) WebSocket communication and native hardware-accelerated extensions.

---

## Architecture

```
web-research/
├── CMakeLists.txt          # Native C++17 build configuration
├── build.sh                # Automated CMake build script
├── run_heavy_fetch.sh      # CLI heavy research & fetch runner
├── include/                # Native C++ headers
│   └── hyper_vision_agent/ # Browser session, CDP, engine, and launcher headers
├── src/                    # Native C++ source implementation
│   ├── browser_session.cpp
│   ├── cdp_connection.cpp
│   ├── command_dispatcher.cpp
│   ├── engine.cpp
│   ├── main.cpp            # Heavy data fetch and research entry point
│   ├── page.cpp
│   ├── process_launcher.cpp
│   ├── target_session_manager.cpp
│   └── websocket_client.cpp
└── extensions/             # Native C++ Extensions
    ├── anti_bot_stealth/   # Bezier human mouse curves, webdriver spoofing
    ├── duckduckgo_search/  # Direct SERP extraction & URL redirection unpacker
    ├── screen_recorder/    # Video stream screencasting
    └── screenshot/         # Viewport and full-page PNG capture
```

---

## Heavy Data Fetching Usage

### 1. Build the Engine
```bash
./build.sh
```

### 2. Deep URL Scraping & High-Resolution Snapshot
```bash
./run_heavy_fetch.sh --fetch "https://example.com"
```

### 3. Deep Web Research Query
```bash
./run_heavy_fetch.sh --research "Autonomous AI Agents and C++ Headless Browsers"
```
