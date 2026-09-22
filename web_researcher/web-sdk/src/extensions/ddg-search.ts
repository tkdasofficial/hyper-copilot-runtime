/**
 * DuckDuckGo Search Extension - Structured Search Automation
 * Port of extensions/duckduckgo_search/
 */

import type { Page } from "../core/page.js";

export interface SearchResultItem {
  title: string;
  url: string;
  snippet: string;
  position: number;
}

export interface SearchResponse {
  query: string;
  items: SearchResultItem[];
  success: boolean;
  errorMessage?: string;
  elapsedTimeMs: number;
  totalResults: number;
}

export interface SearchOptions {
  maxResults?: number;
  htmlBackend?: boolean;
  region?: string;
  safeSearch?: boolean;
  timeoutMs?: number;
}

export class DuckDuckGoSearch {
  public static async search(
    page: Page,
    query: string,
    options: SearchOptions = {}
  ): Promise<SearchResponse> {
    const startTime = Date.now();
    const queryUrl = DuckDuckGoSearch.buildQueryUrl(query, options);

    try {
      const navRes = await page.navigate(queryUrl, options.timeoutMs || 15000);
      if (!navRes.success) {
        return {
          query,
          items: [],
          success: false,
          errorMessage: "Failed to navigate to search provider",
          elapsedTimeMs: Date.now() - startTime,
          totalResults: 0,
        };
      }

      // Wait briefly for content rendering
      await page.sleep(400);

      const items = await DuckDuckGoSearch.extractResultsFromDom(page, options.maxResults || 10);

      return {
        query,
        items,
        success: true,
        elapsedTimeMs: Date.now() - startTime,
        totalResults: items.length,
      };
    } catch (err) {
      return {
        query,
        items: [],
        success: false,
        errorMessage: String(err),
        elapsedTimeMs: Date.now() - startTime,
        totalResults: 0,
      };
    }
  }

  public static buildQueryUrl(query: string, options: SearchOptions = {}): string {
    const encoded = encodeURIComponent(query);
    const useHtml = options.htmlBackend ?? true;

    if (useHtml) {
      return `https://html.duckduckgo.com/html/?q=${encoded}&kl=${options.region || "wt-wt"}`;
    }
    return `https://duckduckgo.com/?q=${encoded}&kl=${options.region || "wt-wt"}`;
  }

  public static async extractResultsFromDom(page: Page, maxResults = 10): Promise<SearchResultItem[]> {
    const script = `
      (() => {
        const results = [];
        
        // 1. HTML backend selector (.result.results_links)
        const htmlRows = document.querySelectorAll('.result.results_links, .result__body');
        if (htmlRows.length > 0) {
          for (let i = 0; i < htmlRows.length && results.length < ${maxResults}; i++) {
            const row = htmlRows[i];
            const titleEl = row.querySelector('.result__a, .result__title a');
            const snippetEl = row.querySelector('.result__snippet');
            if (titleEl) {
              const rawHref = titleEl.getAttribute('href') || '';
              results.push({
                title: (titleEl.textContent || '').trim(),
                url: rawHref,
                snippet: snippetEl ? (snippetEl.textContent || '').trim() : '',
                position: results.length + 1
              });
            }
          }
          return results;
        }

        // 2. Modern React/SPA backend selector (article, [data-testid="result"])
        const modernRows = document.querySelectorAll('article[data-testid="result"], [data-nr-anchor]');
        for (let i = 0; i < modernRows.length && results.length < ${maxResults}; i++) {
          const row = modernRows[i];
          const titleEl = row.querySelector('h2 a, [data-testid="result-title-a"]');
          const snippetEl = row.querySelector('[data-result="snippet"], [data-testid="result-snippet"]');
          if (titleEl) {
            results.push({
              title: (titleEl.textContent || '').trim(),
              url: titleEl.getAttribute('href') || '',
              snippet: snippetEl ? (snippetEl.textContent || '').trim() : '',
              position: results.length + 1
            });
          }
        }

        return results;
      })();
    `;

    const res = await page.evaluateScript<SearchResultItem[]>(script);
    if (!res.success || !Array.isArray(res.value)) {
      return [];
    }

    // Clean redirects in retrieved URLs
    return res.value.map((item) => ({
      ...item,
      url: DuckDuckGoSearch.unpackDdgRedirect(item.url),
    }));
  }

  public static unpackDdgRedirect(rawUrl: string): string {
    if (!rawUrl) return "";

    // Match /l/?uddg=... or /r/?uddg=...
    const match = rawUrl.match(/[?&]uddg=([^&]+)/);
    if (match && match[1]) {
      try {
        return decodeURIComponent(match[1]);
      } catch {
        return match[1];
      }
    }

    if (rawUrl.startsWith("//duckduckgo.com/l/?uddg=")) {
      const part = rawUrl.substring(rawUrl.indexOf("uddg=") + 5);
      const ampIdx = part.indexOf("&");
      const clean = ampIdx !== -1 ? part.substring(0, ampIdx) : part;
      try {
        return decodeURIComponent(clean);
      } catch {
        return clean;
      }
    }

    return rawUrl;
  }
}
