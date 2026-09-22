/**
 * Process Launcher - Ephemeral Chromium Isolation & Environment Detector
 * Port of process_launcher.cpp / process_launcher.hpp
 */

import { ProcessError, TimeoutError, type LaunchConfig, type ProcessStatus } from "../types.js";
import { buildChromiumFlags } from "./flags.js";

export class ProcessLauncher {
  private status: ProcessStatus = {
    pid: -1,
    port: 0,
    webSocketDebuggerUrl: "",
    userDataDir: "",
    isRunning: false,
    startTime: 0,
  };

  private childProcess: unknown = null;
  private isNodeRuntime = false;

  constructor() {
    this.isNodeRuntime =
      typeof process !== "undefined" &&
      Boolean(process.versions?.node);
  }

  public getStatus(): ProcessStatus {
    return { ...this.status };
  }

  public isRunning(): boolean {
    return this.status.isRunning;
  }

  public async launch(config: LaunchConfig = {}): Promise<ProcessStatus> {
    // If a direct WebSocket debugger endpoint is provided, use it directly (ideal for browser/serverless/remote CDP)
    if (config.wsEndpoint) {
      this.status = {
        pid: 0,
        port: 0,
        webSocketDebuggerUrl: config.wsEndpoint,
        userDataDir: config.userDataDir || "",
        isRunning: true,
        startTime: Date.now(),
      };
      return this.status;
    }

    // In non-Node runtimes without wsEndpoint, local binary spawning is unavailable
    if (!this.isNodeRuntime) {
      throw new ProcessError(
        "Direct Chromium process spawning is only supported in Node.js environments. For Web Browsers, Cloudflare Workers, or Edge runtimes, please provide 'config.wsEndpoint'."
      );
    }

    return this.launchInNode(config);
  }

  private async launchInNode(config: LaunchConfig): Promise<ProcessStatus> {
    // Dynamic import to prevent bundlers from evaluating node internals in browser targets
    const childProcessModule = await import("node:child_process");
    const fsModule = await import("node:fs");
    const osModule = await import("node:os");
    const pathModule = await import("node:path");
    const netModule = await import("node:net");

    const executablePath = config.executablePath || this.detectChromiumBinary(fsModule);
    if (!executablePath || !fsModule.existsSync(executablePath)) {
      throw new ProcessError(
        `Chromium binary not found at '${executablePath || ""}'. Please provide config.executablePath or install chromium/google-chrome.`
      );
    }

    // Allocate port
    const port = config.remoteDebuggingPort || (await this.getAvailablePort(netModule));

    // Create temporary profile directory
    const tempDirPrefix = pathModule.join(osModule.tmpdir(), "hyper_vision_agent_profile_");
    const userDataDir = config.userDataDir || fsModule.mkdtempSync(tempDirPrefix);

    const flags = buildChromiumFlags(config, port, userDataDir);

    const child = childProcessModule.spawn(executablePath, flags, {
      detached: false,
      stdio: ["ignore", "ignore", "ignore"],
    });

    if (!child.pid) {
      throw new ProcessError("Failed to spawn Chromium child process.");
    }

    this.childProcess = child;
    this.status = {
      pid: child.pid,
      port,
      webSocketDebuggerUrl: "",
      userDataDir,
      isRunning: true,
      startTime: Date.now(),
    };

    child.on("exit", () => {
      this.status.isRunning = false;
      this.cleanupUserDataDir(fsModule, userDataDir);
    });

    // Wait for Chrome DevTools Protocol to become ready
    const timeoutMs = config.launchTimeoutMs || 15000;
    try {
      const wsUrl = await this.waitForWsDebuggerUrl(port, timeoutMs);
      this.status.webSocketDebuggerUrl = wsUrl;
      return this.status;
    } catch (err) {
      this.kill();
      throw err;
    }
  }

  private detectChromiumBinary(fs: typeof import("node:fs")): string {
    const candidates = [
      process.env.CHROME_BIN,
      process.env.CHROMIUM_BIN,
      "/usr/bin/chromium",
      "/usr/bin/chromium-browser",
      "/usr/bin/google-chrome",
      "/usr/bin/google-chrome-stable",
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Chromium.app/Contents/MacOS/Chromium",
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    ].filter(Boolean) as string[];

    for (const candidate of candidates) {
      try {
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      } catch {
        // Skip
      }
    }

    return "/usr/bin/chromium";
  }

  private getAvailablePort(net: typeof import("node:net")): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      server.unref();
      server.on("error", reject);
      server.listen(0, "127.0.0.1", () => {
        const address = server.address();
        const port = typeof address === "object" && address ? address.port : 9222;
        server.close(() => resolve(port));
      });
    });
  }

  private async waitForWsDebuggerUrl(port: number, timeoutMs: number): Promise<string> {
    const deadline = Date.now() + timeoutMs;
    const versionUrl = `http://127.0.0.1:${port}/json/version`;

    while (Date.now() < deadline) {
      try {
        const res = await fetch(versionUrl);
        if (res.ok) {
          const data = (await res.json()) as { webSocketDebuggerUrl?: string };
          if (data && data.webSocketDebuggerUrl) {
            return data.webSocketDebuggerUrl;
          }
        }
      } catch {
        // Wait and retry
      }
      await new Promise((r) => setTimeout(r, 100));
    }

    throw new TimeoutError(`Failed to obtain WebSocket Debugger URL from Chromium on port ${port} within ${timeoutMs}ms`);
  }

  public kill(): void {
    if (this.childProcess && typeof (this.childProcess as { kill?: (signal: string) => void }).kill === "function") {
      try {
        (this.childProcess as { kill: (signal: string) => void }).kill("SIGKILL");
      } catch {
        // Ignored
      }
      this.childProcess = null;
    }
    this.status.isRunning = false;
  }

  private cleanupUserDataDir(fs: typeof import("node:fs"), dir: string): void {
    try {
      if (dir.includes("hyper_vision_agent_profile_") && fs.existsSync(dir)) {
        fs.rmSync(dir, { recursive: true, force: true });
      }
    } catch {
      // Ignored
    }
  }
}
