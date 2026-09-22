/**
 * Chromium Launcher Flags & Sandboxing Constraints
 * Standard high-performance automation arguments
 */

import type { LaunchConfig } from "../types.js";

export function buildChromiumFlags(config: LaunchConfig, port: number, userDataDir: string): string[] {
  const flags = [
    // Automation & Headless mode
    config.headless !== false ? "--headless=new" : "",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    `--window-size=${config.windowWidth || 1920},${config.windowHeight || 1080}`,

    // Container / Cloud Run stability flags
    config.noSandbox !== false ? "--no-sandbox" : "",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    config.disableGpu !== false ? "--disable-gpu" : "",

    // Performance & Background throttling mitigation
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-extensions",
    "--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--force-color-profile=srgb",
    "--metrics-recording-only",
    "--safebrowsing-disable-auto-update",
    "--enable-automation",
    "--password-store=basic",
    "--use-mock-keychain",
    "--hide-scrollbars",
    "--mute-audio",

    ...(config.extraFlags || []),
  ];

  return flags.filter((flag) => flag.length > 0);
}
