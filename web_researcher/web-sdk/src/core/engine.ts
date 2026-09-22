/**
 * Hyper Vision Agent Engine - Top-Level Orchestrator & Session Registry
 * Port of engine.cpp / engine.hpp
 */

import { ENGINE_NAME, ENGINE_VERSION, type LaunchConfig } from "../types.js";
import { BrowserSession } from "./browser-session.js";

export class HyperVisionEngine {
  private static _instance: HyperVisionEngine | null = null;
  private defaultConfig: LaunchConfig = {};
  private activeSessions: BrowserSession[] = [];
  private initialized = false;

  constructor() {}

  public static instance(): HyperVisionEngine {
    if (!HyperVisionEngine._instance) {
      HyperVisionEngine._instance = new HyperVisionEngine();
    }
    return HyperVisionEngine._instance;
  }

  public initialize(defaultConfig: LaunchConfig = {}): boolean {
    this.defaultConfig = defaultConfig;
    this.initialized = true;
    return true;
  }

  public async launch(config: LaunchConfig = {}): Promise<BrowserSession> {
    const mergedConfig: LaunchConfig = {
      ...this.defaultConfig,
      ...config,
    };

    const session = await BrowserSession.create(mergedConfig);
    this.activeSessions.push(session);
    return session;
  }

  public async connect(wsUrl: string, timeoutMs = 15000): Promise<BrowserSession> {
    const session = await BrowserSession.connect(wsUrl, timeoutMs);
    this.activeSessions.push(session);
    return session;
  }

  public async closeSession(session: BrowserSession): Promise<void> {
    const idx = this.activeSessions.indexOf(session);
    if (idx !== -1) {
      this.activeSessions.splice(idx, 1);
    }
    await session.close();
  }

  public activeSessionCount(): number {
    return this.activeSessions.filter((s) => s.isAlive()).length;
  }

  public getActiveSessions(): BrowserSession[] {
    return this.activeSessions.filter((s) => s.isAlive());
  }

  public async shutdown(): Promise<void> {
    const sessions = [...this.activeSessions];
    this.activeSessions = [];
    for (const session of sessions) {
      try {
        await session.close();
      } catch {
        // Ignored
      }
    }
    this.initialized = false;
  }

  public static getVersion(): string {
    return ENGINE_VERSION;
  }

  public static getEngineBrand(): string {
    return ENGINE_NAME;
  }
}
