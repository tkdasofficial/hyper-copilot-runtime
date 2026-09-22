/**
 * Target Session Manager - Chrome Multi-Target and Tab Lifecycle
 * Port of target_session_manager.cpp / target_session_manager.hpp
 */

import type { CdpConnection } from "../connection/cdp-connection.js";
import type { CommandDispatcher } from "../dispatcher/command-dispatcher.js";
import { CdpError, type SessionId, type TargetId } from "../types.js";

export interface TargetInfo {
  targetId: TargetId;
  type: string;
  title: string;
  url: string;
  attached: boolean;
  sessionId?: SessionId;
}

export class TargetSessionManager {
  private targetToSession = new Map<TargetId, SessionId>();
  private sessionToTarget = new Map<SessionId, TargetId>();
  private targets = new Map<TargetId, TargetInfo>();

  constructor(
    private connection: CdpConnection,
    private dispatcher: CommandDispatcher
  ) {
    this.setupEventListeners();
  }

  public async createTarget(url = "about:blank"): Promise<{ targetId: TargetId; sessionId: SessionId }> {
    const createRes = await this.dispatcher.targetCreateTarget(url);
    if (!createRes.success || !createRes.result?.targetId) {
      throw new CdpError(`Failed to create target: ${createRes.errorMessage || "Unknown"}`);
    }

    const targetId = createRes.result.targetId;
    const attachRes = await this.dispatcher.targetAttachToTarget(targetId, true);
    if (!attachRes.success || !attachRes.result?.sessionId) {
      throw new CdpError(`Failed to attach to target ${targetId}: ${attachRes.errorMessage || "Unknown"}`);
    }

    const sessionId = attachRes.result.sessionId;
    this.targetToSession.set(targetId, sessionId);
    this.sessionToTarget.set(sessionId, targetId);

    return { targetId, sessionId };
  }

  public async attachToTarget(targetId: TargetId): Promise<SessionId> {
    const existingSession = this.targetToSession.get(targetId);
    if (existingSession) {
      return existingSession;
    }

    const attachRes = await this.dispatcher.targetAttachToTarget(targetId, true);
    if (!attachRes.success || !attachRes.result?.sessionId) {
      throw new CdpError(`Failed to attach to target ${targetId}: ${attachRes.errorMessage || "Unknown"}`);
    }

    const sessionId = attachRes.result.sessionId;
    this.targetToSession.set(targetId, sessionId);
    this.sessionToTarget.set(sessionId, targetId);
    return sessionId;
  }

  public async detachFromTarget(sessionId: SessionId): Promise<boolean> {
    const targetId = this.sessionToTarget.get(sessionId);
    if (targetId) {
      this.targetToSession.delete(targetId);
    }
    this.sessionToTarget.delete(sessionId);

    const res = await this.dispatcher.targetDetachFromTarget(sessionId);
    return res.success;
  }

  public async closeTarget(targetId: TargetId): Promise<boolean> {
    const sessionId = this.targetToSession.get(targetId);
    if (sessionId) {
      this.sessionToTarget.delete(sessionId);
      this.targetToSession.delete(targetId);
    }
    this.targets.delete(targetId);

    const res = await this.dispatcher.targetCloseTarget(targetId);
    return res.success;
  }

  public getSessionIdForTarget(targetId: TargetId): SessionId | undefined {
    return this.targetToSession.get(targetId);
  }

  public getTargetIdForSession(sessionId: SessionId): TargetId | undefined {
    return this.sessionToTarget.get(sessionId);
  }

  private setupEventListeners(): void {
    this.connection.subscribeEvent("Target.attachedToTarget", (event) => {
      const params = event.params as { sessionId: string; targetInfo: TargetInfo };
      if (params.sessionId && params.targetInfo?.targetId) {
        this.targetToSession.set(params.targetInfo.targetId, params.sessionId);
        this.sessionToTarget.set(params.sessionId, params.targetInfo.targetId);
        this.targets.set(params.targetInfo.targetId, {
          ...params.targetInfo,
          sessionId: params.sessionId,
        });
      }
    });

    this.connection.subscribeEvent("Target.detachedFromTarget", (event) => {
      const params = event.params as { sessionId: string; targetId?: string };
      if (params.sessionId) {
        const targetId = this.sessionToTarget.get(params.sessionId) || params.targetId;
        if (targetId) {
          this.targetToSession.delete(targetId);
        }
        this.sessionToTarget.delete(params.sessionId);
      }
    });

    this.connection.subscribeEvent("Target.targetDestroyed", (event) => {
      const params = event.params as { targetId: string };
      if (params.targetId) {
        const sessionId = this.targetToSession.get(params.targetId);
        if (sessionId) {
          this.sessionToTarget.delete(sessionId);
        }
        this.targetToSession.delete(params.targetId);
        this.targets.delete(params.targetId);
      }
    });
  }
}
