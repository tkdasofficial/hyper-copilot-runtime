/**
 * Universal WebSocket Adapter for Cross-Environment Compatibility
 * Operates seamlessly across Browser, Node.js (20+), Deno, Bun, and Edge Runtimes
 */

export interface IWebSocket {
  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onclose: ((event: { code: number; reason: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  readyState: number;
}

export async function createUniversalWebSocket(url: string): Promise<IWebSocket> {
  // 1. Check globalThis.WebSocket (Supported in Browsers, modern Node 20+, Deno, Bun, Cloudflare Workers)
  if (typeof globalThis !== "undefined" && typeof (globalThis as unknown as { WebSocket?: new (u: string) => IWebSocket }).WebSocket === "function") {
    const WSClass = (globalThis as unknown as { WebSocket: new (u: string) => IWebSocket }).WebSocket;
    return new WSClass(url);
  }

  // 2. Node.js environment fallback: attempt dynamic import of 'ws'
  if (typeof process !== "undefined" && process.versions && process.versions.node) {
    try {
      // Dynamic import string to prevent bundlers from statically requiring 'ws' in browser environments
      // @ts-ignore - optional dependency in Node environments
      const wsModule: any = await import("ws");
      const WsConstructor = (wsModule.default || wsModule) as unknown as new (u: string) => IWebSocket;
      return new WsConstructor(url);
    } catch {
      throw new Error(
        "WebSocket implementation not found in this environment. Please ensure globalThis.WebSocket is present or install 'ws' in Node.js."
      );
    }
  }

  throw new Error("No WebSocket implementation found in current runtime environment.");
}
