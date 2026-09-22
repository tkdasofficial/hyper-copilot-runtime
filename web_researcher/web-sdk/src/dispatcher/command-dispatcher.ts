/**
 * Command Dispatcher - High-Level CDP Domain Command Serializer
 * Port of command_dispatcher.cpp / command_dispatcher.hpp
 */

import type { CdpConnection } from "../connection/cdp-connection.js";
import type { BoxModel, CdpResponse, SessionId } from "../types.js";

export class CommandDispatcher {
  constructor(private connection: CdpConnection) {}

  public getConnection(): CdpConnection {
    return this.connection;
  }

  public async dispatch<T = Record<string, unknown>>(
    method: string,
    params?: Record<string, unknown>,
    sessionId?: SessionId
  ): Promise<CdpResponse<T>> {
    return this.connection.sendCommand<T>(method, params, sessionId);
  }

  // ==========================================
  // Page Domain
  // ==========================================
  public async pageEnable(sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("Page.enable", {}, sessionId);
  }

  public async pageNavigate(
    url: string,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ frameId: string; loaderId?: string; errorText?: string }>> {
    return this.dispatch("Page.navigate", { url }, sessionId);
  }

  public async pageReload(ignoreCache = false, sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("Page.reload", { ignoreCache }, sessionId);
  }

  public async pageGetFrameTree(sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("Page.getFrameTree", {}, sessionId);
  }

  public async pageCaptureScreenshot(
    format = "png",
    quality = 80,
    clip?: { x: number; y: number; width: number; height: number; scale?: number },
    fromSurface = true,
    captureBeyondViewport = true,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ data: string }>> {
    const params: Record<string, unknown> = {
      format,
      fromSurface,
      captureBeyondViewport,
    };
    if (format === "jpeg" || format === "webp") {
      params.quality = quality;
    }
    if (clip) {
      params.clip = {
        x: clip.x,
        y: clip.y,
        width: clip.width,
        height: clip.height,
        scale: clip.scale ?? 1.0,
      };
    }
    return this.dispatch<{ data: string }>("Page.captureScreenshot", params, sessionId);
  }

  public async pagePrintToPdf(sessionId?: SessionId): Promise<CdpResponse<{ data: string }>> {
    return this.dispatch<{ data: string }>("Page.printToPDF", {}, sessionId);
  }

  public async pageAddScriptToEvaluateOnNewDocument(
    source: string,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ identifier: string }>> {
    return this.dispatch<{ identifier: string }>(
      "Page.addScriptToEvaluateOnNewDocument",
      { source },
      sessionId
    );
  }

  public async pageStartScreencast(
    format = "png",
    quality = 80,
    maxWidth = 1920,
    maxHeight = 1080,
    everyNthFrame = 1,
    sessionId?: SessionId
  ): Promise<CdpResponse> {
    return this.dispatch(
      "Page.startScreencast",
      {
        format,
        quality,
        maxWidth,
        maxHeight,
        everyNthFrame,
      },
      sessionId
    );
  }

  public async pageStopScreencast(sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("Page.stopScreencast", {}, sessionId);
  }

  public pageScreencastFrameAck(sessionId?: SessionId, frameNumber = 1): void {
    this.connection.sendCommandAsync("Page.screencastFrameAck", { sessionId: frameNumber }, sessionId);
  }

  // ==========================================
  // Runtime Domain
  // ==========================================
  public async runtimeEnable(sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("Runtime.enable", {}, sessionId);
  }

  public async runtimeEvaluate<T = unknown>(
    expression: string,
    returnByValue = true,
    awaitPromise = true,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ result: { type: string; value?: T; description?: string }; exceptionDetails?: { text: string } }>> {
    return this.dispatch("Runtime.evaluate", {
      expression,
      returnByValue,
      awaitPromise,
    }, sessionId);
  }

  public async runtimeCallFunctionOn<T = unknown>(
    functionDeclaration: string,
    objectId: string,
    args: unknown[] = [],
    returnByValue = true,
    awaitPromise = true,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ result: { type: string; value?: T; description?: string } }>> {
    return this.dispatch("Runtime.callFunctionOn", {
      functionDeclaration,
      objectId,
      arguments: args.map((v) => ({ value: v })),
      returnByValue,
      awaitPromise,
    }, sessionId);
  }

  // ==========================================
  // DOM Domain
  // ==========================================
  public async domEnable(sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("DOM.enable", {}, sessionId);
  }

  public async domGetDocument(
    depth = -1,
    pierce = true,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ root: { nodeId: number } }>> {
    return this.dispatch("DOM.getDocument", { depth, pierce }, sessionId);
  }

  public async domQuerySelector(
    nodeId: number,
    selector: string,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ nodeId: number }>> {
    return this.dispatch("DOM.querySelector", { nodeId, selector }, sessionId);
  }

  public async domQuerySelectorAll(
    nodeId: number,
    selector: string,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ nodeIds: number[] }>> {
    return this.dispatch("DOM.querySelectorAll", { nodeId, selector }, sessionId);
  }

  public async domGetBoxModel(
    nodeId: number,
    sessionId?: SessionId
  ): Promise<CdpResponse<{ model: { content: number[]; padding: number[]; border: number[]; margin: number[]; width: number; height: number } }>> {
    return this.dispatch("DOM.getBoxModel", { nodeId }, sessionId);
  }

  public async domFocus(nodeId: number, sessionId?: SessionId): Promise<CdpResponse> {
    return this.dispatch("DOM.focus", { nodeId }, sessionId);
  }

  // ==========================================
  // Input Domain
  // ==========================================
  public async inputDispatchMouseEvent(
    type: "mousePressed" | "mouseReleased" | "mouseMoved" | "mouseWheel",
    x: number,
    y: number,
    button: "none" | "left" | "middle" | "right" = "none",
    clickCount = 0,
    modifiers = 0,
    deltaX = 0,
    deltaY = 0,
    sessionId?: SessionId
  ): Promise<CdpResponse> {
    const params: Record<string, unknown> = {
      type,
      x,
      y,
      button,
      clickCount,
      modifiers,
    };
    if (type === "mouseWheel") {
      params.deltaX = deltaX;
      params.deltaY = deltaY;
    }
    return this.dispatch("Input.dispatchMouseEvent", params, sessionId);
  }

  public async inputDispatchKeyEvent(
    type: "keyDown" | "keyUp" | "rawKeyDown" | "char",
    text?: string,
    unmodifiedText?: string,
    key?: string,
    code?: string,
    windowsVirtualKeyCode?: number,
    nativeVirtualKeyCode?: number,
    modifiers = 0,
    sessionId?: SessionId
  ): Promise<CdpResponse> {
    const params: Record<string, unknown> = {
      type,
      modifiers,
    };
    if (text !== undefined) params.text = text;
    if (unmodifiedText !== undefined) params.unmodifiedText = unmodifiedText;
    if (key !== undefined) params.key = key;
    if (code !== undefined) params.code = code;
    if (windowsVirtualKeyCode !== undefined) params.windowsVirtualKeyCode = windowsVirtualKeyCode;
    if (nativeVirtualKeyCode !== undefined) params.nativeVirtualKeyCode = nativeVirtualKeyCode;

    return this.dispatch("Input.dispatchKeyEvent", params, sessionId);
  }

  // ==========================================
  // Emulation Domain
  // ==========================================
  public async emulationSetDeviceMetricsOverride(
    width: number,
    height: number,
    deviceScaleFactor = 1.0,
    mobile = false,
    sessionId?: SessionId
  ): Promise<CdpResponse> {
    return this.dispatch(
      "Emulation.setDeviceMetricsOverride",
      {
        width,
        height,
        deviceScaleFactor,
        mobile,
      },
      sessionId
    );
  }

  public async emulationSetUserAgentOverride(
    userAgent: string,
    acceptLanguage?: string,
    platform?: string,
    sessionId?: SessionId
  ): Promise<CdpResponse> {
    const params: Record<string, unknown> = { userAgent };
    if (acceptLanguage) params.acceptLanguage = acceptLanguage;
    if (platform) params.platform = platform;
    return this.dispatch("Emulation.setUserAgentOverride", params, sessionId);
  }

  // ==========================================
  // Target Domain
  // ==========================================
  public async targetCreateTarget(
    url = "about:blank",
    width?: number,
    height?: number,
    browserContextId?: string,
    newWindow = false,
    background = false
  ): Promise<CdpResponse<{ targetId: string }>> {
    const params: Record<string, unknown> = {
      url,
      newWindow,
      background,
    };
    if (width !== undefined) params.width = width;
    if (height !== undefined) params.height = height;
    if (browserContextId) params.browserContextId = browserContextId;

    return this.dispatch<{ targetId: string }>("Target.createTarget", params);
  }

  public async targetCloseTarget(targetId: string): Promise<CdpResponse<{ success: boolean }>> {
    return this.dispatch<{ success: boolean }>("Target.closeTarget", { targetId });
  }

  public async targetAttachToTarget(
    targetId: string,
    flatten = true
  ): Promise<CdpResponse<{ sessionId: string }>> {
    return this.dispatch<{ sessionId: string }>("Target.attachToTarget", {
      targetId,
      flatten,
    });
  }

  public async targetDetachFromTarget(
    sessionId?: SessionId,
    targetId?: string
  ): Promise<CdpResponse> {
    const params: Record<string, unknown> = {};
    if (sessionId) params.sessionId = sessionId;
    if (targetId) params.targetId = targetId;
    return this.dispatch("Target.detachFromTarget", params);
  }

  public async targetGetTargets(): Promise<CdpResponse<{ targetInfos: Array<{ targetId: string; type: string; title: string; url: string; attached: boolean }> }>> {
    return this.dispatch("Target.getTargets", {});
  }
}
