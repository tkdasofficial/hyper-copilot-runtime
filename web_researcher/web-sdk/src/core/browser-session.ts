/**
 * Browser Session - Container for Targets, Pages, and Isolated Contexts
 * Port of browser_session.cpp / browser_session.hpp
 */

import type { CdpConnection } from "../connection/cdp-connection.js";
import { CommandDispatcher } from "../dispatcher/command-dispatcher.js";
import type { ProcessLauncher } from "../launcher/process-launcher.js";
import { TargetSessionManager } from "../target/target-session-manager.js";
import { CdpError, type LaunchConfig } from "../types.js";
import { Page } from "./page.js";

export class BrowserSession {
  private pages: Page[] = [];
  private activePage: Page | null = null;
  private isClosed = false;

  constructor(
    private launcher: ProcessLauncher | null,
    private connection: CdpConnection,
    private dispatcher: CommandDispatcher,
    private targetManager: TargetSessionManager
  ) {}

  public static async create(config: LaunchConfig = {}): Promise<BrowserSession> {
    // Dynamically import process launcher to avoid bundle-time issues
    const { ProcessLauncher } = await import("../launcher/process-launcher.js");
    const { CdpConnection } = await import("../connection/cdp-connection.js");

    const launcher = new ProcessLauncher();
    const status = await launcher.launch(config);

    const connection = new CdpConnection();
    await connection.connect(status.webSocketDebuggerUrl, config.launchTimeoutMs || 15000);

    const dispatcher = new CommandDispatcher(connection);
    const targetManager = new TargetSessionManager(connection, dispatcher);

    return new BrowserSession(launcher, connection, dispatcher, targetManager);
  }

  public static async connect(wsUrl: string, timeoutMs = 15000): Promise<BrowserSession> {
    const { CdpConnection } = await import("../connection/cdp-connection.js");

    const connection = new CdpConnection();
    await connection.connect(wsUrl, timeoutMs);

    const dispatcher = new CommandDispatcher(connection);
    const targetManager = new TargetSessionManager(connection, dispatcher);

    return new BrowserSession(null, connection, dispatcher, targetManager);
  }

  public async newPage(url = "about:blank"): Promise<Page> {
    if (this.isClosed) {
      throw new CdpError("Cannot create page: Browser session is closed.");
    }

    const { targetId, sessionId } = await this.targetManager.createTarget(url);
    const page = new Page(targetId, sessionId, this.connection, this.dispatcher);
    await page.initialize();

    this.pages.push(page);
    this.activePage = page;

    if (url && url !== "about:blank") {
      await page.navigate(url);
    }

    return page;
  }

  public getPages(): Page[] {
    return [...this.pages.filter((p) => !p.isClosed())];
  }

  public getActivePage(): Page | null {
    if (this.activePage && !this.activePage.isClosed()) {
      return this.activePage;
    }
    const openPages = this.getPages();
    return openPages.length > 0 ? openPages[0] : null;
  }

  public async closePage(page: Page): Promise<boolean> {
    const idx = this.pages.indexOf(page);
    if (idx !== -1) {
      this.pages.splice(idx, 1);
    }
    await page.close();

    if (this.activePage === page) {
      this.activePage = this.pages.length > 0 ? this.pages[0] : null;
    }
    return true;
  }

  public async getBrowserVersion(): Promise<string> {
    const res = await this.dispatcher.dispatch<{ product: string }>("Browser.getVersion");
    return res.result?.product || "Unknown";
  }

  public async getUserAgent(): Promise<string> {
    const res = await this.dispatcher.dispatch<{ userAgent: string }>("Browser.getVersion");
    return res.result?.userAgent || "Unknown";
  }

  public getProcessId(): number {
    return this.launcher ? this.launcher.getStatus().pid : 0;
  }

  public getPort(): number {
    return this.launcher ? this.launcher.getStatus().port : 0;
  }

  public isAlive(): boolean {
    return !this.isClosed && this.connection.isConnected();
  }

  public async close(): Promise<void> {
    if (this.isClosed) return;
    this.isClosed = true;

    for (const page of [...this.pages]) {
      try {
        await page.close();
      } catch {
        // Ignored during shutdown
      }
    }
    this.pages = [];
    this.activePage = null;

    try {
      this.connection.disconnect();
    } catch {
      // Ignored
    }

    if (this.launcher) {
      this.launcher.kill();
    }
  }
}
