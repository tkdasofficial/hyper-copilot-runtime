/**
 * Screenshot Extension - Viewport, Full-Page, and Element-Cropped Visuals
 * Port of extensions/screenshot/
 */

import type { Page } from "../core/page.js";

export type ImageFormat = "png" | "jpeg" | "webp";

export interface ScreenshotOptions {
  format?: ImageFormat;
  quality?: number; // 1-100, for jpeg and webp
  outputPath?: string;
  fromSurface?: boolean;
  scale?: number;
  captureBeyondViewport?: boolean;
}

export interface ScreenshotResult {
  success: boolean;
  formatStr: string;
  base64Data: string;
  binaryData?: Uint8Array;
  width: number;
  height: number;
  filePath?: string;
  errorMessage?: string;
}

export class Screenshot {
  public static async captureViewport(
    page: Page,
    options: ScreenshotOptions = {}
  ): Promise<ScreenshotResult> {
    const format = options.format || "png";
    const quality = options.quality ?? 90;
    const fromSurface = options.fromSurface ?? true;

    try {
      const res = await page
        .getDispatcher()
        .pageCaptureScreenshot(
          format,
          quality,
          undefined,
          fromSurface,
          options.captureBeyondViewport ?? true,
          page.getSessionId()
        );

      if (!res.success || !res.result?.data) {
        return {
          success: false,
          formatStr: format,
          base64Data: "",
          width: 0,
          height: 0,
          errorMessage: res.errorMessage || "Failed to capture viewport screenshot",
        };
      }

      const base64 = res.result.data;
      const binary = Screenshot.base64ToUint8Array(base64);

      const result: ScreenshotResult = {
        success: true,
        formatStr: format,
        base64Data: base64,
        binaryData: binary,
        width: 1920,
        height: 1080,
      };

      if (options.outputPath) {
        await Screenshot.saveToFile(result, options.outputPath);
      }

      return result;
    } catch (err) {
      return {
        success: false,
        formatStr: format,
        base64Data: "",
        width: 0,
        height: 0,
        errorMessage: String(err),
      };
    }
  }

  public static async captureFullPage(
    page: Page,
    options: ScreenshotOptions = {}
  ): Promise<ScreenshotResult> {
    const format = options.format || "png";

    try {
      // 1. Measure full scrollable document dimensions
      const evalRes = await page.evaluateScript<{ width: number; height: number }>(`
        ({
          width: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, document.documentElement.clientWidth),
          height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.documentElement.clientHeight)
        })
      `);

      const fullWidth = evalRes.value?.width || 1920;
      const fullHeight = evalRes.value?.height || 1080;

      // 2. Temporarily set viewport emulation to match full content dimensions
      await page.setViewport(fullWidth, fullHeight, options.scale || 1.0);

      // 3. Capture screenshot
      const result = await Screenshot.captureViewport(page, options);
      result.width = fullWidth;
      result.height = fullHeight;

      // 4. Restore standard viewport
      await page.setViewport(1920, 1080, 1.0);

      return result;
    } catch (err) {
      return {
        success: false,
        formatStr: format,
        base64Data: "",
        width: 0,
        height: 0,
        errorMessage: String(err),
      };
    }
  }

  public static async captureElement(
    page: Page,
    selector: string,
    options: ScreenshotOptions = {}
  ): Promise<ScreenshotResult> {
    const format = options.format || "png";
    const quality = options.quality ?? 90;

    try {
      const box = await page.getBoxModel(selector);
      if (!box || box.width <= 0 || box.height <= 0) {
        return {
          success: false,
          formatStr: format,
          base64Data: "",
          width: 0,
          height: 0,
          errorMessage: `Element '${selector}' not found or has 0 dimensions`,
        };
      }

      const res = await page
        .getDispatcher()
        .pageCaptureScreenshot(
          format,
          quality,
          {
            x: box.x,
            y: box.y,
            width: box.width,
            height: box.height,
            scale: options.scale ?? 1.0,
          },
          options.fromSurface ?? true,
          true,
          page.getSessionId()
        );

      if (!res.success || !res.result?.data) {
        return {
          success: false,
          formatStr: format,
          base64Data: "",
          width: 0,
          height: 0,
          errorMessage: res.errorMessage || "Failed to capture element screenshot",
        };
      }

      const base64 = res.result.data;
      const result: ScreenshotResult = {
        success: true,
        formatStr: format,
        base64Data: base64,
        binaryData: Screenshot.base64ToUint8Array(base64),
        width: box.width,
        height: box.height,
      };

      if (options.outputPath) {
        await Screenshot.saveToFile(result, options.outputPath);
      }

      return result;
    } catch (err) {
      return {
        success: false,
        formatStr: format,
        base64Data: "",
        width: 0,
        height: 0,
        errorMessage: String(err),
      };
    }
  }

  public static async saveToFile(result: ScreenshotResult, filePath: string): Promise<boolean> {
    result.filePath = filePath;

    // Node.js environment
    if (typeof process !== "undefined" && Boolean(process.versions?.node)) {
      try {
        const fs = await import("node:fs/promises");
        const path = await import("node:path");
        const dir = path.dirname(filePath);
        await fs.mkdir(dir, { recursive: true });

        const buffer = Buffer.from(result.base64Data, "base64");
        await fs.writeFile(filePath, buffer);
        return true;
      } catch (err) {
        result.errorMessage = `Failed to save screenshot: ${String(err)}`;
        return false;
      }
    }

    return true;
  }

  private static base64ToUint8Array(base64: string): Uint8Array {
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
