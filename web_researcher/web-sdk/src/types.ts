/**
 * Hyper Vision Agent - Universal Web & Node TypeScript SDK
 * Port of Hyper Vision Agent C++17 Core Engine
 */

export const ENGINE_NAME = "Hyper Vision Agent Web SDK";
export const ENGINE_VERSION = "1.0.0-core";

export type SessionId = string;
export type TargetId = string;
export type CommandId = number;

/**
 * Custom Error Hierarchies matching C++ Engine Exceptions
 */
export class EngineError extends Error {
  constructor(message: string) {
    super(`[HyperVisionAgent] ${message}`);
    this.name = "EngineError";
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export class ProcessError extends EngineError {
  constructor(message: string) {
    super(`Process Error: ${message}`);
    this.name = "ProcessError";
  }
}

export class CdpError extends EngineError {
  public readonly errorCode: number;
  constructor(message: string, code: number = -1) {
    super(`CDP Error (${code}): ${message}`);
    this.name = "CdpError";
    this.errorCode = code;
  }
}

export class TimeoutError extends EngineError {
  constructor(message: string) {
    super(`Timeout: ${message}`);
    this.name = "TimeoutError";
  }
}

/**
 * Process Configuration & State
 */
export interface LaunchConfig {
  /** Path to Chromium or Chrome binary. If empty, auto-detects in Node.js environment. */
  executablePath?: string;
  /** Remote debugging port. 0 = auto-assign ephemeral port */
  remoteDebuggingPort?: number;
  /** Isolated user data directory. If empty, uses temporary directory */
  userDataDir?: string;
  /** Run in headless mode */
  headless?: boolean;
  /** Disable GPU hardware acceleration */
  disableGpu?: boolean;
  /** Disable Chromium sandbox (recommended for containerized / Cloud Run environments) */
  noSandbox?: boolean;
  /** Default viewport width */
  windowWidth?: number;
  /** Default viewport height */
  windowHeight?: number;
  /** Extra Chromium command-line flags */
  extraFlags?: string[];
  /** Process launch timeout in milliseconds (default: 10000) */
  launchTimeoutMs?: number;
  /** Direct WebSocket debugger endpoint URL (e.g. ws://localhost:9222/devtools/browser/...). If provided, skips local process spawning */
  wsEndpoint?: string;
}

export interface ProcessStatus {
  pid: number;
  port: number;
  webSocketDebuggerUrl: string;
  userDataDir: string;
  isRunning: boolean;
  startTime: number;
}

/**
 * Chrome DevTools Protocol Message Types
 */
export interface CdpMessage {
  id: CommandId;
  method: string;
  params?: Record<string, unknown>;
  sessionId?: SessionId;
}

export interface CdpResponse<T = Record<string, unknown>> {
  id: CommandId;
  success: boolean;
  result?: T;
  errorMessage?: string;
  errorCode?: number;
  raw?: unknown;
}

export interface CdpEvent<T = Record<string, unknown>> {
  method: string;
  params: T;
  sessionId?: SessionId;
  timestamp: number;
}

/**
 * Automation Specific Structures
 */
export interface NavigationResult {
  success: boolean;
  url: string;
  httpStatus: number;
  frameId: string;
  elapsedTimeMs: number;
}

export interface EvalResult<T = unknown> {
  success: boolean;
  type: string;
  value?: T;
  valueString?: string;
  valueNumber?: number;
  valueBoolean?: boolean;
  rawResult?: unknown;
  errorDescription?: string;
}

export interface BoxModel {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ElementCoordinates {
  x: number;
  y: number;
  visible: boolean;
}

export type EventCallback<T = Record<string, unknown>> = (event: CdpEvent<T>) => void;
export type MessageCallback = (rawMessage: string) => void;
