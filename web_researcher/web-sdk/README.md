# Hyper Vision Agent Web SDK

**High-Performance Stateless Chromium CDP Execution Runtime for Modern TypeScript & JavaScript**

A 1:1 idiomatic TypeScript port of the native C++17 Hyper Vision Agent Core Engine. Designed to execute seamlessly across any JavaScript environment—whether client-side directly in the browser or server-side across Node.js, Express.js, Next.js, Vercel Serverless, and Edge runtimes.

---

## Key Capabilities

- **Truly Universal (Isomorphic)**:
  - **Browser & Edge Runtimes**: Connects directly to remote browser instances (Browserless, Cloud Run, Docker, or external CDP endpoints) via native WebSocket without requiring Node.js native bindings.
  - **Node.js & Serverless**: Auto-detects Chromium/Google Chrome binaries, allocates ephemeral isolated ports, manages sandboxed profiles in temporary storage, and automates instances natively.
- **Dual Build Exports (ESM & CommonJS)**:
  - Ready to be imported via `import` (ESM) or `require` (CJS) with complete TypeScript declaration maps.
- **Chrome DevTools Protocol (CDP)**:
  - Full support for `Page`, `Runtime`, `DOM`, `Input`, `Emulation`, and `Target` CDP domains.
- **Built-in Modular Extensions**:
  - **Stealth & Anti-Bot**: Spoofs `navigator.webdriver`, `chrome.runtime`, WebGL vendor/renderer, languages, and simulates natural human-like cursor trajectories via C-Spline (Cubic Bezier) mathematical models with randomized hand tremors.
  - **Visual Capture**: Viewport, full-page scrolling, and CSS selector element-cropped screenshots in PNG, JPEG, and WEBP formats.
  - **Screen Recording**: Real-time screencast streaming with automated frame acknowledgment.
  - **Captcha Detection & Solver**: Passive detection and humanized interaction for Cloudflare Turnstile, Google reCAPTCHA v2, and hCaptcha.
  - **DuckDuckGo Search**: Search automation with redirect extraction and structured DOM data scraping.

---

## Installation & Building

Inside the `web-sdk/` directory:

```bash
# Compile both ESM and CommonJS bundles
npm run build

# Run the test suite
npm test
```

---

## Quick Start Guide

### 1. Server-Side Automation (Node.js, Express, Next.js, Fastify)

In server-side environments, the SDK can spawn an isolated local Chromium process:

```typescript
import { HyperVisionEngine } from "@hyper-vision/web-sdk";

async function main() {
  const engine = HyperVisionEngine.instance();

  // Spawns local sandboxed headless Chromium on an ephemeral port
  const session = await engine.launch({
    headless: true,
    noSandbox: true,
    disableGpu: true,
  });

  const page = await session.newPage("https://example.com");

  // Script evaluation
  const title = await page.getTitle();
  console.log("Page title:", title);

  // Click & Type
  await page.click("button#submit");
  await page.type("input[name='q']", "Automated query");

  // Clean shutdown
  await session.close();
}
```

### 2. Client-Side & Serverless / Edge (Vercel, Supabase, Cloudflare Workers, Browser)

In web browsers or edge runtimes where local binary execution is not possible, simply provide the `wsEndpoint` parameter to connect over WebSocket:

```typescript
import { BrowserSession } from "@hyper-vision/web-sdk";

async function runInBrowserOrEdge() {
  // Connect directly to a remote CDP endpoint (e.g. Browserless, Playwright container, or Cloud Run instance)
  const session = await BrowserSession.connect("wss://chrome.browserless.io?token=YOUR_API_TOKEN");

  const page = await session.newPage("https://example.com");
  const content = await page.getContent();
  console.log("Extracted HTML:", content.slice(0, 100));

  await session.close();
}
```

---

## Modular Extensions

### 1. Anti-Bot Stealth & Human Cursor Splines

```typescript
import { Stealth } from "@hyper-vision/web-sdk";

// Inject fingerprint evasion before page navigation
await Stealth.apply(page, {
  hideWebdriver: true,
  mockChromeRuntime: true,
  mockWebgl: true,
  webglVendor: "Intel Inc.",
  webglRenderer: "Intel(R) Iris(R) Xe Graphics",
});

// Humanized curved movement followed by natural mouse click with dwell time
await Stealth.humanClick(page, 450, 280, 30, 400);
```

### 2. Viewport, Full-Page, & Element Screenshots

```typescript
import { Screenshot } from "@hyper-vision/web-sdk";

// Viewport screenshot
const viewport = await Screenshot.captureViewport(page, { format: "png" });

// Full-page screenshot (dynamically measures document scroll dimensions)
const fullPage = await Screenshot.captureFullPage(page, {
  format: "jpeg",
  quality: 85,
  outputPath: "./fullpage.jpg"
});

// Element-cropped screenshot
const card = await Screenshot.captureElement(page, "#target-card", {
  format: "png"
});
```

### 3. Screen Recording (CDP Screencast Stream)

```typescript
import { ScreenRecorder } from "@hyper-vision/web-sdk";

const recorder = new ScreenRecorder();

recorder.setFrameListener((frame) => {
  // Frame binary data (Uint8Array) and base64 string
  console.log("Frame captured, bytes:", frame.data.byteLength);
});

await recorder.startRecording(page, {
  maxWidth: 1280,
  maxHeight: 720,
  everyNthFrame: 1
});

// Perform browser actions...
await page.sleep(3000);

const stats = await recorder.stopRecording();
console.log("Recorded", stats.totalFrames, "frames");
```

### 4. DuckDuckGo Search Automation

```typescript
import { DuckDuckGoSearch } from "@hyper-vision/web-sdk";

const response = await DuckDuckGoSearch.search(page, "TypeScript CDP Engine", {
  maxResults: 5,
  htmlBackend: true,
});

for (const item of response.items) {
  console.log(`[#${item.position}] ${item.title}`);
  console.log(`URL: ${item.url}`);
  console.log(`Snippet: ${item.snippet}\n`);
}
```

---

## Package Exports Structure

```
@hyper-vision/web-sdk
├── . (Main Engine, Page, Session, Types, Launcher, CDP)
└── ./extensions (Screenshot, Stealth, CaptchaSolver, ScreenRecorder, DuckDuckGoSearch)
```

Both ESM (`import`) and CommonJS (`require`) are supported out-of-the-box.
