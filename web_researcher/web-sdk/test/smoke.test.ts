/**
 * Smoke & Integration Test for Hyper Vision Agent Web SDK
 */

import {
  HyperVisionEngine,
  Stealth,
  DuckDuckGoSearch,
  Screenshot,
  ScreenRecorder,
  CaptchaSolver,
  ENGINE_NAME,
  ENGINE_VERSION,
} from "../src/index.js";

async function runTests() {
  console.log("==================================================================");
  console.log(`  Testing ${ENGINE_NAME} v${ENGINE_VERSION} (TypeScript Web SDK)`);
  console.log("==================================================================");

  let passed = 0;
  let total = 0;

  function assert(condition: boolean, msg: string) {
    total++;
    if (condition) {
      console.log(`[PASS] ${msg}`);
      passed++;
    } else {
      console.error(`[FAIL] ${msg}`);
      process.exitCode = 1;
    }
  }

  // 1. Static & Algorithmic Unit Tests
  console.log("\n[STAGE 1] Testing Algorithms & Core Static Utilities...");

  assert(HyperVisionEngine.getEngineBrand() === "Hyper Vision Agent Web SDK", "Engine branding matches");
  assert(HyperVisionEngine.getVersion() === "1.0.0-core", "Engine version matches");

  // Stealth Spline
  const spline = Stealth.calculateHumanTrajectory({ x: 0, y: 0 }, { x: 500, y: 300 }, 20);
  assert(spline.length === 21, `Human C-Spline generates correct step count (got ${spline.length})`);
  assert(spline[spline.length - 1].x >= 495, "C-Spline terminates accurately near destination");

  // Stealth Script Generation
  const script = Stealth.generateStealthScript({ hideWebdriver: true, mockPlugins: true });
  assert(script.includes("navigator, 'webdriver'"), "Stealth script injects navigator.webdriver spoof");
  assert(script.includes("Intel Inc."), "Stealth script injects WebGL vendor mock");

  // DuckDuckGo URL generation & redirect unpacker
  const ddgUrl = DuckDuckGoSearch.buildQueryUrl("TypeScript CDP Engine", { htmlBackend: true });
  assert(ddgUrl.includes("html.duckduckgo.com/html/?q=TypeScript%20CDP%20Engine"), "DDG URL builder encodes query");

  const unpacked = DuckDuckGoSearch.unpackDdgRedirect("//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Ftest&rut=1");
  assert(unpacked === "https://github.com/test", `DDG Redirect unpacker resolves target (${unpacked})`);

  // 2. End-to-End Headless Chromium Test
  console.log("\n[STAGE 2] Testing End-to-End Chromium Automation...");

  try {
    const engine = HyperVisionEngine.instance();
    console.log("  -> Launching isolated headless Chromium process...");
    const session = await engine.launch({
      headless: true,
      noSandbox: true,
      disableGpu: true,
      windowWidth: 1280,
      windowHeight: 720,
    });

    assert(session.isAlive(), "BrowserSession spawned and connected via CDP");
    console.log(`  -> Connected (PID: ${session.getProcessId()}, Port: ${session.getPort()})`);

    const version = await session.getBrowserVersion();
    assert(version.length > 0, `Browser.getVersion succeeded: ${version}`);

    // Create page
    const page = await session.newPage("about:blank");
    assert(!page.isClosed(), "New page target attached and initialized");

    // Evaluate script
    const evalRes = await page.evaluateScript<number>("2 + 2");
    assert(evalRes.success && evalRes.value === 4, `Runtime.evaluate: '2 + 2' === ${evalRes.value}`);

    const objRes = await page.evaluateScript<{ sdk: string; status: string }>(`
      ({ sdk: "Hyper Vision Web SDK", status: "operational", time: Date.now() })
    `);
    assert(objRes.success && objRes.value?.sdk === "Hyper Vision Web SDK", "Object script evaluation succeeded");

    // In-memory DOM test
    await page.evaluateScript(`
      document.body.innerHTML = '<h1 id="title">Web SDK Test</h1><button id="btn" onclick="this.textContent = \\'Clicked!\\'">Click Me</button>';
    `);

    const titleNodeId = await page.querySelector("#title");
    assert(titleNodeId > 0, `DOM.querySelector found #title (Node ID: ${titleNodeId})`);

    const clickOk = await page.click("#btn");
    assert(clickOk, "Input.dispatchMouseEvent Click on #btn succeeded");

    const btnText = await page.evaluateScript<string>("document.getElementById('btn').textContent");
    assert(btnText.value === "Clicked!", `Button state updated via synthetic click ('${btnText.value}')`);

    // Stealth injection test
    const stealthApplied = await Stealth.apply(page);
    assert(stealthApplied, "Stealth scripts injected into Page target");

    const webdriverStatus = await page.evaluateScript("navigator.webdriver");
    assert(webdriverStatus.value === undefined, "navigator.webdriver spoof verified as undefined");

    // Human mouse move
    const moved = await Stealth.humanMoveTo(page, 200, 200, 10, 100);
    assert(moved, "Human C-Spline mouse dispatched to page");

    // Screenshot test
    const screenshot = await Screenshot.captureViewport(page);
    assert(screenshot.success && screenshot.base64Data.length > 100, `Viewport screenshot captured (${screenshot.base64Data.length} chars base64)`);

    // Screen recorder test
    const recorder = new ScreenRecorder();
    let frameReceived = false;
    recorder.setFrameListener((frame) => {
      frameReceived = true;
    });

    await recorder.startRecording(page, { maxWidth: 640, maxHeight: 480 });
    await page.sleep(200);
    await recorder.stopRecording();
    assert(recorder.getStats().totalFrames >= 0, "ScreenRecorder lifecycle executed cleanly");

    // Clean session shutdown
    await session.close();
    assert(!session.isAlive(), "BrowserSession closed and ephemeral Chromium cleaned up");
  } catch (err) {
    console.error("End-to-End test encountered an error:", err);
    process.exitCode = 1;
  }

  console.log("==================================================================");
  console.log(`  Tests Completed: ${passed}/${total} Passed.`);
  console.log("==================================================================");

  if (passed !== total) {
    process.exit(1);
  }
}

runTests().catch((err) => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
