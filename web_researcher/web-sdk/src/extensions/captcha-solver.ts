/**
 * Captcha Solver - Detection and Human-Emulated Interaction for Challenges
 * Port of extensions/anti_bot_stealth/captcha_solver.hpp
 */

import type { Page } from "../core/page.js";
import { Stealth, type Point2D } from "./stealth.js";

export enum CaptchaType {
  NONE = "NONE",
  CLOUDFLARE_TURNSTILE = "CLOUDFLARE_TURNSTILE",
  RECAPTCHA_V2 = "RECAPTCHA_V2",
  HCAPTCHA = "HCAPTCHA",
}

export interface CaptchaDetectResult {
  type: CaptchaType;
  detected: boolean;
  selector: string;
  centerCoords: Point2D;
  frameUrl?: string;
}

export interface CaptchaSolveResult {
  success: boolean;
  type: CaptchaType;
  token?: string;
  elapsedTimeMs: number;
  errorMessage?: string;
}

export class CaptchaSolver {
  public static async detectCaptcha(page: Page): Promise<CaptchaDetectResult> {
    const scanScript = `
      (() => {
        // 1. Cloudflare Turnstile
        const cfIframe = document.querySelector('iframe[src*="cloudflare.com/turnstile"], iframe[src*="challenges.cloudflare.com"], div.cf-turnstile iframe');
        if (cfIframe) {
          const rect = cfIframe.getBoundingClientRect();
          return {
            type: 'CLOUDFLARE_TURNSTILE',
            detected: true,
            selector: 'iframe[src*="cloudflare.com/turnstile"], iframe[src*="challenges.cloudflare.com"]',
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
            frameUrl: cfIframe.src
          };
        }

        // 2. reCAPTCHA v2 Anchor
        const recaptchaIframe = document.querySelector('iframe[src*="google.com/recaptcha/api2/anchor"], iframe[title*="reCAPTCHA"]');
        if (recaptchaIframe) {
          const rect = recaptchaIframe.getBoundingClientRect();
          return {
            type: 'RECAPTCHA_V2',
            detected: true,
            selector: 'iframe[src*="google.com/recaptcha/api2/anchor"]',
            // Checkbox in reCAPTCHA v2 anchor is typically around (x: 28, y: 38) inside iframe
            x: rect.left + 28,
            y: rect.top + 38,
            frameUrl: recaptchaIframe.src
          };
        }

        // 3. hCaptcha
        const hcaptchaIframe = document.querySelector('iframe[src*="hcaptcha.com"]');
        if (hcaptchaIframe) {
          const rect = hcaptchaIframe.getBoundingClientRect();
          return {
            type: 'HCAPTCHA',
            detected: true,
            selector: 'iframe[src*="hcaptcha.com"]',
            x: rect.left + 28,
            y: rect.top + 38,
            frameUrl: hcaptchaIframe.src
          };
        }

        return { type: 'NONE', detected: false, selector: '', x: 0, y: 0 };
      })();
    `;

    const res = await page.evaluateScript<{
      type: string;
      detected: boolean;
      selector: string;
      x: number;
      y: number;
      frameUrl?: string;
    }>(scanScript);

    if (res.success && res.value && res.value.detected) {
      return {
        type: res.value.type as CaptchaType,
        detected: true,
        selector: res.value.selector,
        centerCoords: { x: res.value.x, y: res.value.y },
        frameUrl: res.value.frameUrl,
      };
    }

    return {
      type: CaptchaType.NONE,
      detected: false,
      selector: "",
      centerCoords: { x: 0, y: 0 },
    };
  }

  public static async solve(page: Page, timeoutMs = 15000): Promise<CaptchaSolveResult> {
    const startTime = Date.now();
    const detect = await CaptchaSolver.detectCaptcha(page);

    if (!detect.detected) {
      return {
        success: true,
        type: CaptchaType.NONE,
        elapsedTimeMs: Date.now() - startTime,
      };
    }

    if (detect.type === CaptchaType.CLOUDFLARE_TURNSTILE) {
      const ok = await CaptchaSolver.handleTurnstile(page, timeoutMs);
      return {
        success: ok,
        type: CaptchaType.CLOUDFLARE_TURNSTILE,
        elapsedTimeMs: Date.now() - startTime,
      };
    }

    if (detect.type === CaptchaType.RECAPTCHA_V2) {
      const ok = await CaptchaSolver.handleRecaptcha(page, timeoutMs);
      return {
        success: ok,
        type: CaptchaType.RECAPTCHA_V2,
        elapsedTimeMs: Date.now() - startTime,
      };
    }

    return {
      success: false,
      type: detect.type,
      elapsedTimeMs: Date.now() - startTime,
      errorMessage: `Unsupported captcha solver type: ${detect.type}`,
    };
  }

  public static async handleTurnstile(page: Page, timeoutMs = 15000): Promise<boolean> {
    const detect = await CaptchaSolver.detectCaptcha(page);
    if (!detect.detected || detect.type !== CaptchaType.CLOUDFLARE_TURNSTILE) {
      return false;
    }

    // Move smoothly to the widget center and trigger human click
    await Stealth.humanClick(page, detect.centerCoords.x, detect.centerCoords.y);

    // Wait for response token input
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const checkRes = await page.evaluateScript<string>(`
        (() => {
          const input = document.querySelector('[name="cf-turnstile-response"]');
          return input && input.value ? input.value : '';
        })()
      `);
      if (checkRes.success && checkRes.value && checkRes.value.length > 10) {
        return true;
      }
      await page.sleep(250);
    }

    return true;
  }

  public static async handleRecaptcha(page: Page, timeoutMs = 15000): Promise<boolean> {
    const detect = await CaptchaSolver.detectCaptcha(page);
    if (!detect.detected || detect.type !== CaptchaType.RECAPTCHA_V2) {
      return false;
    }

    await Stealth.humanClick(page, detect.centerCoords.x, detect.centerCoords.y);

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const checkRes = await page.evaluateScript<string>(`
        (() => {
          const input = document.querySelector('#g-recaptcha-response');
          return input && input.value ? input.value : '';
        })()
      `);
      if (checkRes.success && checkRes.value && checkRes.value.length > 10) {
        return true;
      }
      await page.sleep(250);
    }

    return true;
  }
}
