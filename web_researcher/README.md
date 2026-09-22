# Hyper Web Researcher Module (`web_researcher/`)

High-Performance Dual-Mode Automated Web Research Engine powered by the **Native C++ Headless Browser** (`editor/src/vision/` & `hyper_vision_agent_engine`).

---

## Capabilities

### Mode A: Public Web Research
- **Open-Web Search & Indexing**: Real-time multi-engine queries (e.g. DuckDuckGo, search indexes).
- **DOM & Content Extraction**: Automated HTML cleanup, script/ad filtering, and readable content parsing.
- **Synthesis Engine**: Thematic clustering, key insight summarization, and source attribution.
- **Output Artifacts**: Structured Markdown synthesis reports (`research_report.md`) and JSON datasets (`research_report.json`).

### Mode B: Private Web Research (Authenticated Access via Native C++ Browser)
- **Automated Sign-Up / Account Creation**: Dynamic form detection, input population, terms acceptance, and activation link/URL entry.
- **Automated Credential Log-In**: Intelligent discovery of username/email and password fields with multi-step support.
- **Dynamic Interactive 2FA / OTP Handling**:
  - Automatically identifies Two-Factor Authentication (2FA), One-Time Password (OTP), TOTP, and SMS verification challenge screens.
  - Pauses browser automation and prompts the user or CI environment for the verification code.
  - Dynamically ingests the code via interactive console prompt, environment variables (`OTP_CODE`, `RESEARCH_OTP`), or workspace file drop (`otp_code.txt`).
  - Seamlessly resumes navigation upon receiving user verification, validating authenticated session cookies/tokens.
- **Deep Authenticated Navigation**: Explores dashboards, settings, and internal documentation behind auth barriers, saving timestamped screenshot proof.

---

## Architecture & Integration with Native C++ Headless Browser

```
web_researcher/
├── README.md               # Architecture and documentation
├── package.json            # Run scripts
└── research_agent.py       # Core Python dual-mode research engine driving Native C++ Headless Browser
```

The heavy automated headless browser backend is compiled directly from C++17 inside `editor/`:
- `editor/src/vision/`: Native C++ Chromium CDP process launcher, WebSocket connection, command dispatcher, and browser session manager.
- `editor/extensions/`: Native C++ stealth anti-bot bypass, screenshot capture, screen recorder, and DuckDuckGo search.
- Binary: `editor/build/hyper_vision_agent_engine`

---

## CLI Usage

### Mode A: Public Research
```bash
python3 web_researcher/research_agent.py \
  --mode public \
  --query "Latest breakthroughs in multimodal agent reasoning 2026"
```

### Mode B: Private Research (Interactive Log-In & 2FA)
```bash
python3 web_researcher/research_agent.py \
  --mode private \
  --url "https://example.com/login" \
  --query "Internal project milestones and dashboard metrics" \
  --auth-flow login \
  --email "user@example.com" \
  --password "SecretPassword123"
```
