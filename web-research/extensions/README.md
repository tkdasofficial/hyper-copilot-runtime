# Hyper Vision Agent - Modular Extension System

This directory houses the native C++17 modular extensions for **Hyper Vision Agent**, providing high-performance capabilities on top of the headless Chromium CDP execution runtime.

## Registered Modular Extensions

| Extension ID | Name | Path | Description |
|---|---|---|---|
| `screen_recorder` | **Screen Recorder** | `extensions/screen_recorder/` | Streams CDP screencast frames to 1080p video via direct FFmpeg pipe. |
| `screenshot` | **Screenshot** | `extensions/screenshot/` | Captures full-page scrolling screenshots and element-specific cropped images. |
| `anti_bot_stealth` | **Anti-Bot Stealth** | `extensions/anti_bot_stealth/` | Bypasses bot detection, hides `navigator.webdriver`, applies natural human mouse curves, and handles captcha frames. |
| `duckduckgo_search` | **DuckDuckGo Search** | `extensions/duckduckgo_search/` | Zero-API search query provider and URL link extractor. |

---

## Extension Specifications

### 1. Screen Recorder (`screen_recorder`)
- **CDP Protocol**: `Page.startScreencast`, `Page.screencastFrame`, `Page.screencastFrameAck`, `Page.stopScreencast`
- **Video Pipeline**: Native POSIX pipe (`popen`) to FFmpeg CLI (`-f image2pipe -vcodec png -i - -c:v libx264 -pix_fmt yuv420p output.mp4`)
- **Key Methods**:
  - `start_recording(page, config)`
  - `stop_recording()`
  - `push_frame(data, timestamp)`

### 2. Screenshot (`screenshot`)
- **CDP Protocol**: `Page.captureScreenshot`, `DOM.getBoxModel`, `Emulation.setDeviceMetricsOverride`
- **Capabilities**:
  - Viewport captures (`CaptureViewport`)
  - Scrollable Full-Page captures (`CaptureFullPage`) with automatic dimension calculation
  - CSS Selector Element Cropping (`CaptureElement`) with bounding-box clipping
  - Formats: PNG, JPEG, WEBP with configurable compression quality and binary/base64 outputs.

### 3. Anti-Bot Stealth (`anti_bot_stealth`)
- **CDP Protocol**: `Page.addScriptToEvaluateOnNewDocument`, `Runtime.evaluate`, `Input.dispatchMouseEvent`
- **Capabilities**:
  - Webdriver fingerprint masking (`navigator.webdriver` undefined, fake plugins, WebGL vendor spoofing, AudioContext jitter)
  - Human-like C-Spline (Cubic Bezier) mouse trajectory calculation with Fitts' Law velocity profiles and micro-corrective jitter
  - Integrated Captcha Solver (`captcha_solver.hpp`) for Cloudflare Turnstile, reCAPTCHA, and hCaptcha interactive challenges.

### 4. DuckDuckGo Search (`duckduckgo_search`)
- **Capabilities**:
  - Zero-API search querying via native page automation
  - Direct URL redirect unpacking (`/l/?uddg=...` decoder)
  - Structured output extraction: Titles, URLs, Snippets, and Positions.

---

## Build System Integration
Extensions are compiled into modular static libraries via CMake and linked directly with `hyper_vision_agent_core` and the `hyper_vision_agent_engine` CLI binary.
