/**
 * Page - Automation Surface & Visual Extraction Controller
 * Port of page.cpp / page.hpp
 */

import type { CdpConnection } from "../connection/cdp-connection.js";
import type { CommandDispatcher } from "../dispatcher/command-dispatcher.js";
import {
  CdpError,
  TimeoutError,
  type BoxModel,
  type ElementCoordinates,
  type EvalResult,
  type NavigationResult,
  type SessionId,
  type TargetId,
} from "../types.js";

export class Page {
  private currentUrl = "about:blank";
  private isClosedFlag = false;
  private loadResolvers: Array<() => void> = [];

  constructor(
    private targetId: TargetId,
    private sessionId: SessionId,
    private connection: CdpConnection,
    private dispatcher: CommandDispatcher
  ) {
    this.setupEventHandlers();
  }

  public async initialize(): Promise<boolean> {
    await Promise.all([
      this.dispatcher.pageEnable(this.sessionId),
      this.dispatcher.runtimeEnable(this.sessionId),
      this.dispatcher.domEnable(this.sessionId),
    ]);
    return true;
  }

  public getTargetId(): TargetId {
    return this.targetId;
  }

  public getSessionId(): SessionId {
    return this.sessionId;
  }

  public getConnection(): CdpConnection {
    return this.connection;
  }

  public getDispatcher(): CommandDispatcher {
    return this.dispatcher;
  }

  public getUrl(): string {
    return this.currentUrl;
  }

  public isClosed(): boolean {
    return this.isClosedFlag;
  }

  /**
   * High-Level Automation API
   */
  public async navigate(url: string, timeoutMs = 30000): Promise<NavigationResult> {
    const startTime = Date.now();
    this.currentUrl = url;

    const loadPromise = new Promise<void>((resolve) => {
      this.loadResolvers.push(resolve);
    });

    const timeoutPromise = new Promise<void>((_, reject) => {
      setTimeout(() => reject(new TimeoutError(`Navigation to '${url}' timed out after ${timeoutMs}ms`)), timeoutMs);
    });

    try {
      const navRes = await this.dispatcher.pageNavigate(url, this.sessionId);
      if (!navRes.success) {
        throw new CdpError(`Navigation failed: ${navRes.errorMessage || "Unknown error"}`);
      }

      // Await page load or timeout
      await Promise.race([loadPromise, timeoutPromise]);

      return {
        success: true,
        url: this.currentUrl,
        httpStatus: 200,
        frameId: navRes.result?.frameId || "",
        elapsedTimeMs: Date.now() - startTime,
      };
    } catch (err) {
      // Still consider partial success if frame navigated despite timeout
      return {
        success: false,
        url: this.currentUrl,
        httpStatus: 500,
        frameId: "",
        elapsedTimeMs: Date.now() - startTime,
      };
    }
  }

  public async reload(ignoreCache = false): Promise<void> {
    await this.dispatcher.pageReload(ignoreCache, this.sessionId);
  }

  /**
   * Script Evaluation
   */
  public async evaluateScript<T = unknown>(script: string): Promise<EvalResult<T>> {
    const res = await this.dispatcher.runtimeEvaluate<T>(script, true, true, this.sessionId);
    if (!res.success || !res.result?.result) {
      return {
        success: false,
        type: "undefined",
        errorDescription: res.errorMessage || res.result?.exceptionDetails?.text || "Evaluation failed",
      };
    }

    const val = res.result.result.value;
    const type = res.result.result.type;

    return {
      success: true,
      type,
      value: val,
      valueString: typeof val === "string" ? val : typeof val === "object" ? JSON.stringify(val) : String(val),
      valueNumber: typeof val === "number" ? val : undefined,
      valueBoolean: typeof val === "boolean" ? val : undefined,
      rawResult: res.result.result,
    };
  }

  /**
   * DOM & Element Interaction
   */
  public async querySelector(selector: string): Promise<number> {
    const docRes = await this.dispatcher.domGetDocument(-1, true, this.sessionId);
    if (!docRes.success || !docRes.result?.root?.nodeId) {
      return 0;
    }

    const queryRes = await this.dispatcher.domQuerySelector(docRes.result.root.nodeId, selector, this.sessionId);
    return queryRes.result?.nodeId || 0;
  }

  public async querySelectorAll(selector: string): Promise<number[]> {
    const docRes = await this.dispatcher.domGetDocument(-1, true, this.sessionId);
    if (!docRes.success || !docRes.result?.root?.nodeId) {
      return [];
    }

    const queryRes = await this.dispatcher.domQuerySelectorAll(docRes.result.root.nodeId, selector, this.sessionId);
    return queryRes.result?.nodeIds || [];
  }

  public async getBoxModel(selectorOrNodeId: string | number): Promise<BoxModel | null> {
    let nodeId = typeof selectorOrNodeId === "number" ? selectorOrNodeId : 0;
    if (typeof selectorOrNodeId === "string") {
      nodeId = await this.querySelector(selectorOrNodeId);
    }
    if (!nodeId) return null;

    const res = await this.dispatcher.domGetBoxModel(nodeId, this.sessionId);
    if (!res.success || !res.result?.model?.content) {
      return null;
    }

    // CDP quad points: [x1, y1, x2, y2, x3, y3, x4, y4]
    const q = res.result.model.content;
    const xs = [q[0], q[2], q[4], q[6]];
    const ys = [q[1], q[3], q[5], q[7]];
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);

    return {
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
    };
  }

  public async getElementCenter(selectorOrNodeId: string | number): Promise<ElementCoordinates | null> {
    const box = await this.getBoxModel(selectorOrNodeId);
    if (!box) return null;

    return {
      x: box.x + box.width / 2,
      y: box.y + box.height / 2,
      visible: box.width > 0 && box.height > 0,
    };
  }

  public async click(selector: string): Promise<boolean> {
    const center = await this.getElementCenter(selector);
    if (!center) {
      return false;
    }
    return this.clickAt(center.x, center.y);
  }

  public async clickAt(x: number, y: number): Promise<boolean> {
    await this.dispatcher.inputDispatchMouseEvent("mouseMoved", x, y, "none", 0, 0, 0, 0, this.sessionId);
    await this.dispatcher.inputDispatchMouseEvent("mousePressed", x, y, "left", 1, 0, 0, 0, this.sessionId);
    await this.sleep(30);
    await this.dispatcher.inputDispatchMouseEvent("mouseReleased", x, y, "left", 1, 0, 0, 0, this.sessionId);
    return true;
  }

  public async focus(selector: string): Promise<boolean> {
    const nodeId = await this.querySelector(selector);
    if (!nodeId) return false;
    const res = await this.dispatcher.domFocus(nodeId, this.sessionId);
    return res.success;
  }

  public async type(selector: string, text: string, delayMs = 10): Promise<boolean> {
    const focused = await this.focus(selector);
    if (!focused) {
      await this.click(selector);
    }

    for (const char of text) {
      await this.dispatcher.inputDispatchKeyEvent("keyDown", char, char, char, undefined, undefined, undefined, 0, this.sessionId);
      await this.dispatcher.inputDispatchKeyEvent("char", char, char, char, undefined, undefined, undefined, 0, this.sessionId);
      await this.dispatcher.inputDispatchKeyEvent("keyUp", char, char, char, undefined, undefined, undefined, 0, this.sessionId);
      if (delayMs > 0) {
        await this.sleep(delayMs);
      }
    }
    return true;
  }

  public async waitForSelector(selector: string, timeoutMs = 10000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const id = await this.querySelector(selector);
      if (id > 0) return true;
      await this.sleep(100);
    }
    return false;
  }

  public async waitForNavigation(timeoutMs = 30000): Promise<boolean> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), timeoutMs);
      this.loadResolvers.push(() => {
        clearTimeout(timer);
        resolve(true);
      });
    });
  }

  public sleep(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }

  /**
   * Visual & State Extraction
   */
  public async captureScreenshotBase64(format = "png", quality = 80): Promise<string> {
    const res = await this.dispatcher.pageCaptureScreenshot(format, quality, undefined, true, true, this.sessionId);
    return res.result?.data || "";
  }

  public async getContent(): Promise<string> {
    const evalRes = await this.evaluateScript<string>("document.documentElement.outerHTML");
    return evalRes.value || "";
  }

  public async getTitle(): Promise<string> {
    const evalRes = await this.evaluateScript<string>("document.title");
    return evalRes.value || "";
  }

  public async setViewport(width: number, height: number, scale = 1.0): Promise<boolean> {
    const res = await this.dispatcher.emulationSetDeviceMetricsOverride(width, height, scale, false, this.sessionId);
    return res.success;
  }

  public async close(): Promise<void> {
    if (this.isClosedFlag) return;
    this.isClosedFlag = true;
    await this.dispatcher.targetCloseTarget(this.targetId);
  }

  private setupEventHandlers(): void {
    this.connection.subscribeEvent("Page.loadEventFired", (event) => {
      if (event.sessionId === this.sessionId || !event.sessionId) {
        const resolvers = [...this.loadResolvers];
        this.loadResolvers = [];
        for (const resolve of resolvers) {
          resolve();
        }
      }
    });

    this.connection.subscribeEvent("Page.frameNavigated", (event) => {
      if (event.sessionId === this.sessionId || !event.sessionId) {
        const frame = (event.params as { frame?: { url?: string; parentId?: string } })?.frame;
        if (frame && !frame.parentId && frame.url) {
          this.currentUrl = frame.url;
        }
      }
    });
  }
}
