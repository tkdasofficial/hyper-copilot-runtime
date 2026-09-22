/**
 * Stealth Extension - Anti-Bot Evasion & Humanized Motion Splines
 * Port of extensions/anti_bot_stealth/
 */

import type { Page } from "../core/page.js";

export interface Point2D {
  x: number;
  y: number;
}

export interface StealthConfig {
  hideWebdriver?: boolean;
  mockPlugins?: boolean;
  mockChromeRuntime?: boolean;
  mockWebgl?: boolean;
  mockAudioContext?: boolean;
  mockPermissions?: boolean;
  languages?: string[];
  webglVendor?: string;
  webglRenderer?: string;
  hardwareConcurrency?: number;
  deviceMemory?: number;
}

export class Stealth {
  private static lastMousePosition: Point2D = { x: 100, y: 100 };

  public static async apply(page: Page, config: StealthConfig = {}): Promise<boolean> {
    const script = Stealth.generateStealthScript(config);
    const res = await page
      .getDispatcher()
      .pageAddScriptToEvaluateOnNewDocument(script, page.getSessionId());

    // Also run immediately on the current execution context
    await page.evaluateScript(script);

    return res.success;
  }

  public static generateStealthScript(config: StealthConfig = {}): string {
    const hideWebdriver = config.hideWebdriver ?? true;
    const mockPlugins = config.mockPlugins ?? true;
    const mockChrome = config.mockChromeRuntime ?? true;
    const mockWebgl = config.mockWebgl ?? true;
    const languages = JSON.stringify(config.languages || ["en-US", "en"]);
    const webglVendor = config.webglVendor || "Intel Inc.";
    const webglRenderer = config.webglRenderer || "Intel(R) Iris(R) Xe Graphics";
    const hardwareConcurrency = config.hardwareConcurrency ?? 8;
    const deviceMemory = config.deviceMemory ?? 8;

    return `
      (() => {
        try {
          ${
            hideWebdriver
              ? `
          // 1. Hide navigator.webdriver
          Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
          });
          `
              : ""
          }

          // 2. Spoof navigator.languages
          Object.defineProperty(navigator, 'languages', {
            get: () => ${languages},
            configurable: true
          });

          // 3. Hardware concurrency & device memory
          Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => ${hardwareConcurrency},
            configurable: true
          });
          Object.defineProperty(navigator, 'deviceMemory', {
            get: () => ${deviceMemory},
            configurable: true
          });

          ${
            mockChrome
              ? `
          // 4. Mock window.chrome runtime
          if (!window.chrome) {
            window.chrome = {};
          }
          window.chrome.runtime = {
            id: undefined,
            connect: () => {},
            sendMessage: () => {},
            onMessage: { addListener: () => {} }
          };
          window.chrome.app = {
            isInstalled: false,
            InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
            RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
          };
          `
              : ""
          }

          ${
            mockPlugins
              ? `
          // 5. Mock plugins & mimeTypes
          const fakePlugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
          ];
          Object.defineProperty(navigator, 'plugins', {
            get: () => fakePlugins,
            configurable: true
          });
          `
              : ""
          }

          ${
            mockWebgl
              ? `
          // 6. Mock WebGL Vendor & Renderer
          const getParameterProto = WebGLRenderingContext.prototype.getParameter;
          WebGLRenderingContext.prototype.getParameter = function(parameter) {
            // UNMASKED_VENDOR_WEBGL
            if (parameter === 37445) return '${webglVendor}';
            // UNMASKED_RENDERER_WEBGL
            if (parameter === 37446) return '${webglRenderer}';
            return getParameterProto.apply(this, arguments);
          };

          if (typeof WebGL2RenderingContext !== 'undefined') {
            const getParameter2Proto = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(parameter) {
              if (parameter === 37445) return '${webglVendor}';
              if (parameter === 37446) return '${webglRenderer}';
              return getParameter2Proto.apply(this, arguments);
            };
          }
          `
              : ""
          }

          // 7. Permissions query spoofing
          if (navigator.permissions && navigator.permissions.query) {
            const origQuery = navigator.permissions.query;
            navigator.permissions.query = (parameters) => {
              if (parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
              }
              return origQuery(parameters);
            };
          }
        } catch (e) {
          // Suppress fingerprint injection errors
        }
      })();
    `;
  }

  /**
   * C-Spline (Cubic Hermite/Bezier) mathematical human cursor model
   */
  public static calculateHumanTrajectory(
    start: Point2D,
    end: Point2D,
    steps = 25,
    curvature = 0.2
  ): Point2D[] {
    const points: Point2D[] = [];
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    // Perpendicular vector for natural curve deviation
    const perpX = -dy / (dist || 1);
    const perpY = dx / (dist || 1);

    // Random inflection control points
    const deviation = dist * curvature * (Math.random() > 0.5 ? 1 : -1);
    const c1: Point2D = {
      x: start.x + dx * 0.3 + perpX * deviation,
      y: start.y + dy * 0.3 + perpY * deviation,
    };
    const c2: Point2D = {
      x: start.x + dx * 0.7 + perpX * (deviation * 0.5),
      y: start.y + dy * 0.7 + perpY * (deviation * 0.5),
    };

    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      // Cubic Bezier formula: (1-t)^3*P0 + 3(1-t)^2*t*P1 + 3(1-t)*t^2*P2 + t^3*P3
      const u = 1 - t;
      const tt = t * t;
      const uu = u * u;
      const uuu = uu * u;
      const ttt = tt * t;

      const px = uuu * start.x + 3 * uu * t * c1.x + 3 * u * tt * c2.x + ttt * end.x;
      const py = uuu * start.y + 3 * uu * t * c1.y + 3 * u * tt * c2.y + ttt * end.y;

      // Add microscopic human hand tremor (noise)
      const tremorX = (Math.random() - 0.5) * 1.5;
      const tremorY = (Math.random() - 0.5) * 1.5;

      points.push({
        x: Math.round(px + tremorX),
        y: Math.round(py + tremorY),
      });
    }

    return points;
  }

  public static async humanMoveTo(
    page: Page,
    targetX: number,
    targetY: number,
    steps = 25,
    totalDurationMs = 350
  ): Promise<boolean> {
    const trajectory = Stealth.calculateHumanTrajectory(
      Stealth.lastMousePosition,
      { x: targetX, y: targetY },
      steps
    );

    const stepDelay = Math.max(1, Math.floor(totalDurationMs / steps));

    for (const pt of trajectory) {
      await page
        .getDispatcher()
        .inputDispatchMouseEvent("mouseMoved", pt.x, pt.y, "none", 0, 0, 0, 0, page.getSessionId());
      Stealth.lastMousePosition = pt;
      await page.sleep(stepDelay);
    }

    return true;
  }

  public static async humanClick(
    page: Page,
    targetX: number,
    targetY: number,
    steps = 25,
    totalDurationMs = 350
  ): Promise<boolean> {
    await Stealth.humanMoveTo(page, targetX, targetY, steps, totalDurationMs);

    // Natural pause before pressing
    await page.sleep(Math.floor(Math.random() * 40 + 20));

    await page
      .getDispatcher()
      .inputDispatchMouseEvent("mousePressed", targetX, targetY, "left", 1, 0, 0, 0, page.getSessionId());

    // Human click dwell time (60-120ms)
    await page.sleep(Math.floor(Math.random() * 60 + 60));

    await page
      .getDispatcher()
      .inputDispatchMouseEvent("mouseReleased", targetX, targetY, "left", 1, 0, 0, 0, page.getSessionId());

    return true;
  }
}
