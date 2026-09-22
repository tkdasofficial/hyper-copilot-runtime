/**
 * Screen Recorder Extension - CDP Screencast Stream & Frame Buffer
 * Port of extensions/screen_recorder/
 */

import type { Page } from "../core/page.js";

export interface ScreenRecorderConfig {
  format?: "png" | "jpeg";
  quality?: number;
  maxWidth?: number;
  maxHeight?: number;
  everyNthFrame?: number;
  outputFile?: string;
}

export interface ScreenRecorderStats {
  totalFrames: number;
  droppedFrames: number;
  bytesWritten: number;
  durationSeconds: number;
  isRecording: boolean;
  outputPath?: string;
}

export interface ScreencastFrame {
  data: Uint8Array;
  base64: string;
  metadata: Record<string, unknown>;
  timestamp: number;
}

export type FrameCallback = (frame: ScreencastFrame) => void;

export class ScreenRecorder {
  private page: Page | null = null;
  private isRecording = false;
  private startTime = 0;
  private stats: ScreenRecorderStats = {
    totalFrames: 0,
    droppedFrames: 0,
    bytesWritten: 0,
    durationSeconds: 0,
    isRecording: false,
  };
  private frameListener: FrameCallback | null = null;
  private unsubscribeScreencast: (() => void) | null = null;

  constructor() {}

  public async startRecording(page: Page, config: ScreenRecorderConfig = {}): Promise<boolean> {
    if (this.isRecording) {
      return true;
    }

    this.page = page;
    this.isRecording = true;
    this.startTime = Date.now();
    this.stats = {
      totalFrames: 0,
      droppedFrames: 0,
      bytesWritten: 0,
      durationSeconds: 0,
      isRecording: true,
      outputPath: config.outputFile,
    };

    const format = config.format || "png";
    const quality = config.quality ?? 80;
    const maxWidth = config.maxWidth || 1920;
    const maxHeight = config.maxHeight || 1080;
    const everyNthFrame = config.everyNthFrame || 1;

    // Listen to Screencast events from Page domain
    this.unsubscribeScreencast = page.getConnection().subscribeEvent("Page.screencastFrame", (event) => {
      const params = event.params as {
        data: string;
        metadata: Record<string, unknown>;
        sessionId: number;
      };

      if (!params || !params.data) return;

      // Acknowledge frame to keep Chrome streaming smoothly
      if (params.sessionId !== undefined) {
        page.getDispatcher().pageScreencastFrameAck(page.getSessionId(), params.sessionId);
      }

      this.pushFrame(params.data, params.metadata);
    });

    const res = await page
      .getDispatcher()
      .pageStartScreencast(format, quality, maxWidth, maxHeight, everyNthFrame, page.getSessionId());

    return res.success;
  }

  public async stopRecording(): Promise<ScreenRecorderStats> {
    if (!this.isRecording || !this.page) {
      return { ...this.stats };
    }

    this.isRecording = false;
    this.stats.isRecording = false;
    this.stats.durationSeconds = (Date.now() - this.startTime) / 1000;

    if (this.unsubscribeScreencast) {
      this.unsubscribeScreencast();
      this.unsubscribeScreencast = null;
    }

    try {
      await this.page.getDispatcher().pageStopScreencast(this.page.getSessionId());
    } catch {
      // Ignored
    }

    return { ...this.stats };
  }

  public pushFrame(base64Data: string, metadata: Record<string, unknown> = {}): boolean {
    const binary = this.base64ToUint8Array(base64Data);

    this.stats.totalFrames++;
    this.stats.bytesWritten += binary.byteLength;
    this.stats.durationSeconds = (Date.now() - this.startTime) / 1000;

    const frame: ScreencastFrame = {
      data: binary,
      base64: base64Data,
      metadata,
      timestamp: Date.now(),
    };

    if (this.frameListener) {
      try {
        this.frameListener(frame);
      } catch (err) {
        console.error("[ScreenRecorder] Frame listener error:", err);
      }
    }

    return true;
  }

  public setFrameListener(callback: FrameCallback | null): void {
    this.frameListener = callback;
  }

  public getStats(): ScreenRecorderStats {
    return {
      ...this.stats,
      durationSeconds: this.isRecording ? (Date.now() - this.startTime) / 1000 : this.stats.durationSeconds,
    };
  }

  private base64ToUint8Array(base64: string): Uint8Array {
    if (typeof Buffer !== "undefined") {
      return new Uint8Array(Buffer.from(base64, "base64"));
    }
    const binaryString = atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
  }
}
