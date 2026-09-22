/**
 * CDP Connection - Bidirectional WebSocket Client for Chrome DevTools Protocol
 * Port of cdp_connection.cpp / cdp_connection.hpp
 */

import {
  CdpError,
  TimeoutError,
  type CdpEvent,
  type CdpMessage,
  type CdpResponse,
  type CommandId,
  type EventCallback,
  type MessageCallback,
  type SessionId,
} from "../types.js";
import { createUniversalWebSocket, type IWebSocket } from "./websocket-adapter.js";

interface PendingRequest {
  id: CommandId;
  method: string;
  resolve: (response: CdpResponse) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class CdpConnection {
  private ws: IWebSocket | null = null;
  private wsUrl = "";
  private nextCommandId: CommandId = 1;
  private pendingRequests = new Map<CommandId, PendingRequest>();
  private eventListeners = new Map<string, Set<EventCallback>>();
  private wildcardEventListeners = new Set<EventCallback>();
  private rawMessageCallback: MessageCallback | null = null;
  private isConnectedFlag = false;

  constructor() {}

  public isConnected(): boolean {
    return this.isConnectedFlag && this.ws !== null && this.ws.readyState === 1;
  }

  public getWebSocketUrl(): string {
    return this.wsUrl;
  }

  public async connect(url: string, timeoutMs = 15000): Promise<boolean> {
    if (this.isConnected()) {
      return true;
    }

    this.wsUrl = url;

    return new Promise<boolean>((resolve, reject) => {
      let resolved = false;

      const timeoutTimer = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          this.disconnect();
          reject(new TimeoutError(`Connection to CDP WebSocket timed out after ${timeoutMs}ms (${url})`));
        }
      }, timeoutMs);

      createUniversalWebSocket(url)
        .then((socket) => {
          this.ws = socket;

          this.ws.onopen = () => {
            if (!resolved) {
              resolved = true;
              clearTimeout(timeoutTimer);
              this.isConnectedFlag = true;
              resolve(true);
            }
          };

          this.ws.onmessage = (event) => {
            const rawData = typeof event.data === "string" ? event.data : String(event.data);
            this.handleIncomingMessage(rawData);
          };

          this.ws.onerror = (err) => {
            if (!resolved) {
              resolved = true;
              clearTimeout(timeoutTimer);
              reject(new CdpError(`WebSocket connection error to ${url}: ${String(err)}`));
            }
          };

          this.ws.onclose = () => {
            this.isConnectedFlag = false;
            this.flushPendingRequests(new CdpError("WebSocket closed"));
          };
        })
        .catch((err) => {
          if (!resolved) {
            resolved = true;
            clearTimeout(timeoutTimer);
            reject(err);
          }
        });
    });
  }

  public disconnect(): void {
    this.isConnectedFlag = false;
    if (this.ws) {
      try {
        this.ws.close(1000, "Clean disconnect");
      } catch {
        // Ignore error on close
      }
      this.ws = null;
    }
    this.flushPendingRequests(new CdpError("CDP Connection closed"));
  }

  public sendCommand<T = Record<string, unknown>>(
    method: string,
    params?: Record<string, unknown>,
    sessionId?: SessionId,
    timeoutMs = 30000
  ): Promise<CdpResponse<T>> {
    if (!this.isConnected() || !this.ws) {
      return Promise.reject(new CdpError(`Cannot send command '${method}': Not connected to CDP`));
    }

    const id = this.nextCommandId++;
    const message: CdpMessage = {
      id,
      method,
      params: params ?? {},
    };

    if (sessionId) {
      message.sessionId = sessionId;
    }

    return new Promise<CdpResponse<T>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new TimeoutError(`Command '${method}' (ID: ${id}) timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      this.pendingRequests.set(id, {
        id,
        method,
        resolve: resolve as (res: CdpResponse) => void,
        reject,
        timer,
      });

      try {
        this.ws!.send(JSON.stringify(message));
      } catch (err) {
        clearTimeout(timer);
        this.pendingRequests.delete(id);
        reject(new CdpError(`Failed to send command '${method}': ${String(err)}`));
      }
    });
  }

  public sendCommandAsync(
    method: string,
    params?: Record<string, unknown>,
    sessionId?: SessionId
  ): void {
    if (!this.isConnected() || !this.ws) {
      return;
    }

    const id = this.nextCommandId++;
    const message: CdpMessage = {
      id,
      method,
      params: params ?? {},
    };

    if (sessionId) {
      message.sessionId = sessionId;
    }

    try {
      this.ws.send(JSON.stringify(message));
    } catch {
      // Ignored for asynchronous non-blocking dispatch
    }
  }

  public subscribeEvent<T = Record<string, unknown>>(
    method: string,
    callback: EventCallback<T>
  ): () => void {
    if (!this.eventListeners.has(method)) {
      this.eventListeners.set(method, new Set());
    }
    const listeners = this.eventListeners.get(method)!;
    listeners.add(callback as EventCallback);

    return () => {
      listeners.delete(callback as EventCallback);
    };
  }

  public unsubscribeEvent(method: string): void {
    this.eventListeners.delete(method);
  }

  public subscribeAllEvents(callback: EventCallback): () => void {
    this.wildcardEventListeners.add(callback);
    return () => {
      this.wildcardEventListeners.delete(callback);
    };
  }

  public setRawMessageCallback(callback: MessageCallback | null): void {
    this.rawMessageCallback = callback;
  }

  private handleIncomingMessage(raw: string): void {
    if (this.rawMessageCallback) {
      this.rawMessageCallback(raw);
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }

    // Check if this is a response to a command (has 'id')
    if (typeof parsed.id === "number") {
      const commandId = parsed.id as CommandId;
      const pending = this.pendingRequests.get(commandId);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingRequests.delete(commandId);

        if (parsed.error) {
          const errObj = parsed.error as { message?: string; code?: number };
          const response: CdpResponse = {
            id: commandId,
            success: false,
            errorMessage: errObj.message || "CDP Error",
            errorCode: errObj.code || -1,
            raw: parsed,
          };
          pending.resolve(response);
        } else {
          const response: CdpResponse = {
            id: commandId,
            success: true,
            result: (parsed.result as Record<string, unknown>) || {},
            raw: parsed,
          };
          pending.resolve(response);
        }
      }
      return;
    }

    // Check if this is an Event notification (has 'method')
    if (typeof parsed.method === "string") {
      const event: CdpEvent = {
        method: parsed.method,
        params: (parsed.params as Record<string, unknown>) || {},
        sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : undefined,
        timestamp: Date.now(),
      };

      // Notify specific listeners
      const listeners = this.eventListeners.get(event.method);
      if (listeners) {
        for (const cb of listeners) {
          try {
            cb(event);
          } catch (e) {
            console.error(`[HyperVisionAgent] Error in event listener for ${event.method}:`, e);
          }
        }
      }

      // Notify wildcard listeners
      for (const cb of this.wildcardEventListeners) {
        try {
          cb(event);
        } catch (e) {
          console.error("[HyperVisionAgent] Error in wildcard event listener:", e);
        }
      }
    }
  }

  private flushPendingRequests(error: Error): void {
    for (const pending of this.pendingRequests.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pendingRequests.clear();
  }
}
