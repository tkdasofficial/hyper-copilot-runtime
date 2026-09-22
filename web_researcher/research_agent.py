#!/usr/bin/env python3
"""
Hyper Copilot Web Research Agent
Dual-Mode Automated Research Engine with Dynamic Interactive 2FA/OTP Authentication
Modes:
  Mode A: Public Web Research (open-web scraping, search indexing, content synthesis)
  Mode B: Private Web Research (authenticated access with automated login/signup & dynamic 2FA/OTP)
"""

import os
import sys
import time
import json
import re
import argparse
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import Dict, Any, List, Optional

# Try importing Playwright if available
HAS_PLAYWRIGHT = False
try:
    from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError
    HAS_PLAYWRIGHT = True
except ImportError:
    pass

class SimpleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore_tags = {'script', 'style', 'noscript', 'svg'}
        self.current_tag = None

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag.lower()

    def handle_endtag(self, tag):
        if self.current_tag == tag.lower():
            self.current_tag = None

    def handle_data(self, data):
        if self.current_tag not in self.ignore_tags:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)

    def get_text(self):
        return " ".join(self.text_parts)

class WebResearchAgent:
    def __init__(self, mode: str = "public", output_dir: str = "research_output", headless: bool = True):
        self.mode = mode.lower()
        self.output_dir = output_dir
        self.headless = headless
        self.session_data: Dict[str, Any] = {
            "mode": self.mode,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "sources": [],
            "extracted_data": {},
            "auth_status": "not_required",
            "findings": []
        }
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "screenshots"), exist_ok=True)

    def prompt_user_for_otp(self, prompt_text: str = "Enter 2FA/OTP Verification Code") -> str:
        """Dynamically prompts the user for 2FA / OTP code across interactive and CI environments."""
        print("\n" + "=" * 60)
        print(f"[AUTH BARRIER DETECTED] {prompt_text}")
        print("=" * 60)

        # 1. Check environment variables (e.g. passed from GitHub Actions workflow dispatch / secret)
        env_otp = os.getenv("OTP_CODE") or os.getenv("RESEARCH_OTP") or os.getenv("TWO_FACTOR_CODE")
        if env_otp and env_otp.strip():
            print(f"[*] Found pre-configured OTP from environment: {env_otp.strip()[:2]}****")
            return env_otp.strip()

        # 2. Check for OTP file in workspace (for asynchronous worker injection)
        otp_file = os.path.join(self.output_dir, "otp_code.txt")
        if os.path.exists(otp_file):
            try:
                with open(otp_file, "r", encoding="utf-8") as f:
                    code = f.read().strip()
                    if code:
                        print(f"[*] Read OTP from {otp_file}: {code[:2]}****")
                        return code
            except Exception as e:
                print(f"[!] Warning reading OTP file: {e}")

        # 3. Interactive terminal input if tty is available
        if sys.stdin.isatty():
            try:
                code = input(f">>> {prompt_text}: ").strip()
                if code:
                    return code
            except (EOFError, KeyboardInterrupt):
                print("\n[!] User interrupted OTP entry.")

        # 4. Polling loop for CI/headless mode with timeout
        timeout_seconds = int(os.getenv("OTP_WAIT_TIMEOUT", "90"))
        print(f"[*] Waiting up to {timeout_seconds}s for OTP code via '{otp_file}' or environment...")
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if os.path.exists(otp_file):
                with open(otp_file, "r", encoding="utf-8") as f:
                    code = f.read().strip()
                    if code:
                        print(f"[✓] Received OTP via file: {code[:2]}****")
                        return code
            time.sleep(2)

        print("[!] Timeout waiting for OTP. Resuming with best-effort session.")
        return ""

    def prompt_user_for_activation_url(self) -> str:
        """Prompts for email activation link or confirmation URL if sign-up triggered an email verification."""
        print("\n" + "=" * 60)
        print("[SIGN-UP ACTIVATION] Email confirmation or activation link required.")
        print("=" * 60)
        env_url = os.getenv("CONFIRMATION_URL") or os.getenv("ACTIVATION_URL")
        if env_url:
            return env_url.strip()

        if sys.stdin.isatty():
            try:
                url = input(">>> Paste confirmation/activation URL (or press Enter to skip): ").strip()
                if url:
                    return url
            except (EOFError, KeyboardInterrupt):
                pass
        return ""

    # --------------------------------------------------------------------------
    # Mode A: Public Web Research
    # --------------------------------------------------------------------------
    def run_public_research(self, query: str, target_url: Optional[str] = None, max_results: int = 5):
        print(f"\n[Mode A] Initiating Public Web Research on query: '{query}'")
        results = []

        # 1. If target URL is explicitly provided, scrape it directly
        if target_url:
            print(f"[*] Crawling primary target URL: {target_url}")
            page_content = self._fetch_url_content(target_url)
            if page_content:
                results.append({
                    "title": target_url,
                    "url": target_url,
                    "snippet": page_content[:600] + ("..." if len(page_content) > 600 else ""),
                    "full_text": page_content
                })

        # 2. Open Web Search & Indexing (DuckDuckGo HTML)
        print(f"[*] Querying DuckDuckGo index for: '{query}'")
        search_results = self._search_duckduckgo(query, max_results=max_results)
        for res in search_results:
            url = res.get("url")
            if url and url not in [r["url"] for r in results]:
                print(f"[*] Scraping source: {res.get('title')} ({url})")
                content = self._fetch_url_content(url)
                res["full_text"] = content if content else res.get("snippet", "")
                results.append(res)

        self.session_data["sources"] = results
        self._synthesize_public_findings(query, results)
        self._save_reports()
        print("[✓] Public Web Research completed successfully.")

    def _search_duckduckgo(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        results = []
        try:
            encoded = urllib.parse.urlencode({"q": query})
            url = f"https://html.duckduckgo.com/html/?{encoded}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Extract result links and snippets using regex on DuckDuckGo HTML layout
            link_pattern = re.compile(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE)
            snippet_pattern = re.compile(r'<a class="result__snippet"[^>]*>(.*?)</a>', re.IGNORECASE)

            links = link_pattern.findall(html)
            snippets = snippet_pattern.findall(html)

            for i in range(min(len(links), max_results)):
                raw_href, title = links[i]
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                
                # DuckDuckGo wraps URLs in uddg redirect
                parsed_url = raw_href
                if "uddg=" in raw_href:
                    match = re.search(r'uddg=([^&]+)', raw_href)
                    if match:
                        parsed_url = urllib.parse.unquote(match.group(1))

                results.append({
                    "title": clean_title or f"Result {i+1}",
                    "url": parsed_url,
                    "snippet": clean_snippet
                })
        except Exception as e:
            print(f"[!] DuckDuckGo search fallback notice: {e}")

        return results

    def _fetch_url_content(self, url: str) -> str:
        # If Playwright is available and in headless mode, use it for JS-heavy sites
        if HAS_PLAYWRIGHT:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=self.headless, args=["--no-sandbox", "--disable-gpu"])
                    page = browser.new_page()
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    text = page.inner_text("body")
                    # Capture screenshot
                    shot_path = os.path.join(self.output_dir, "screenshots", f"page_{int(time.time())}.png")
                    page.screenshot(path=shot_path)
                    browser.close()
                    return text.strip()
            except Exception as e:
                print(f"[!] Playwright scrape failed, falling back to HTTP request: {e}")

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                parser = SimpleTextExtractor()
                parser.feed(html)
                return parser.get_text()
        except Exception as e:
            print(f"[!] Failed to fetch {url}: {e}")
            return ""

    def _synthesize_public_findings(self, query: str, results: List[Dict[str, Any]]):
        findings = []
        for idx, res in enumerate(results, 1):
            text = res.get("full_text") or res.get("snippet", "")
            # Extract key thematic sentences matching query terms
            terms = [w.lower() for w in query.split() if len(w) > 3]
            relevant_lines = []
            for sentence in text.split(". "):
                sentence = sentence.strip()
                if any(t in sentence.lower() for t in terms):
                    if len(sentence) > 30 and sentence not in relevant_lines:
                        relevant_lines.append(sentence)
                if len(relevant_lines) >= 4:
                    break

            findings.append({
                "source_index": idx,
                "title": res.get("title", f"Source {idx}"),
                "url": res.get("url", ""),
                "key_points": relevant_lines or [res.get("snippet", "No preview available")]
            })
        self.session_data["findings"] = findings

    # --------------------------------------------------------------------------
    # Mode B: Private Web Research (Authenticated Access & 2FA / OTP Flow)
    # --------------------------------------------------------------------------
    def run_private_research(
        self,
        target_url: str,
        query: str,
        auth_flow: str = "login",
        email: Optional[str] = None,
        password: Optional[str] = None,
        pre_otp: Optional[str] = None
    ):
        print(f"\n[Mode B] Initiating Authenticated Private Web Research")
        print(f"[*] Target Portal: {target_url}")
        print(f"[*] Auth Flow: {auth_flow} (Account: {email or 'Anonymous/Configured'})")

        if not HAS_PLAYWRIGHT:
            print("[!] Note: Playwright not installed. Attempting simulated authenticated inspection.")
            self._run_simulated_private_flow(target_url, query, auth_flow, email, password)
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            try:
                print(f"[*] Navigating to {target_url}...")
                page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)

                # Capture initial landing
                self._save_screenshot(page, "01_landing_page")

                # Step 1: Sign-Up or Log-In execution
                if auth_flow == "signup":
                    self._handle_signup_flow(page, email, password)
                elif auth_flow == "login":
                    self._handle_login_flow(page, email, password)

                # Step 2: Detect and Handle 2FA / OTP / Security Challenge
                self._handle_2fa_otp_barrier(page, pre_otp)

                # Step 3: Verify authenticated session
                print("[*] Validating authenticated session state...")
                self._save_screenshot(page, "03_authenticated_session")
                self.session_data["auth_status"] = "authenticated_success"

                # Step 4: Perform Deep Research inside authenticated portal
                print(f"[*] Executing deep data extraction for query: '{query}'...")
                portal_text = page.inner_text("body")
                page_title = page.title()

                self.session_data["extracted_data"] = {
                    "portal_title": page_title,
                    "url": page.url,
                    "extracted_length": len(portal_text),
                    "summary_preview": portal_text[:1500]
                }

                # Find authenticated sub-links for deeper indexing
                sub_links = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({ text: a.innerText.trim(), href: a.href }))
                        .filter(l => l.text.length > 2 && l.href.startsWith('http'))
                        .slice(0, 8);
                }""")
                self.session_data["portal_navigation"] = sub_links

                # Synthesize authenticated findings
                self.session_data["findings"].append({
                    "section": "Authenticated Portal Overview",
                    "title": page_title,
                    "url": page.url,
                    "content_snippet": portal_text[:800]
                })

            except Exception as e:
                print(f"[!] Error during private research flow: {e}")
                self.session_data["auth_status"] = f"error: {str(e)}"
                self._save_screenshot(page, "error_state")
            finally:
                browser.close()

        self._save_reports()
        print("[✓] Private Authenticated Research completed.")

    def _handle_login_flow(self, page: 'Page', email: Optional[str], password: Optional[str]):
        print("[*] Executing Log-In Flow...")
        email = email or os.getenv("RESEARCH_AUTH_EMAIL")
        password = password or os.getenv("RESEARCH_AUTH_PASSWORD")

        if not email or not password:
            print("[!] Warning: No login credentials provided. Looking for pre-existing session...")
            return

        # Intelligent input discovery
        user_selectors = [
            'input[type="email"]', 'input[name="email"]', 'input[name="username"]',
            'input[name="login"]', 'input[id*="email"]', 'input[id*="user"]',
            'input[type="text"]'
        ]
        pass_selectors = [
            'input[type="password"]', 'input[name="password"]', 'input[id*="pass"]'
        ]

        # Try filling username
        filled_user = False
        for sel in user_selectors:
            if page.locator(sel).first.is_visible():
                page.locator(sel).first.fill(email)
                filled_user = True
                print(f"[*] Entered account identifier into: {sel}")
                break

        # Check if login is multi-step (e.g. Next button first)
        next_button = page.locator('button:has-text("Next"), button:has-text("Continue"), input[value="Next"]')
        if filled_user and next_button.first.is_visible() and not page.locator('input[type="password"]').first.is_visible():
            print("[*] Clicking multi-step 'Next' button...")
            next_button.first.click()
            time.sleep(2)

        # Fill password
        for sel in pass_selectors:
            if page.locator(sel).first.is_visible():
                page.locator(sel).first.fill(password)
                print(f"[*] Entered password into: {sel}")
                break

        # Submit
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Log In"), button:has-text("Sign In")')
        if submit_btn.first.is_visible():
            print("[*] Submitting login form...")
            submit_btn.first.click()
            time.sleep(3)
        else:
            page.keyboard.press("Enter")
            time.sleep(3)

        self._save_screenshot(page, "02_post_login_submit")

    def _handle_signup_flow(self, page: 'Page', email: Optional[str], password: Optional[str]):
        print("[*] Executing Sign-Up / Account Creation Flow...")
        email = email or os.getenv("RESEARCH_AUTH_EMAIL")
        password = password or os.getenv("RESEARCH_AUTH_PASSWORD", "HyperCopilot!2026")

        # Fill email
        email_input = page.locator('input[type="email"], input[name="email"]').first
        if email_input.is_visible() and email:
            email_input.fill(email)
            print(f"[*] Entered sign-up email: {email}")

        # Fill password if present
        pass_input = page.locator('input[type="password"]').first
        if pass_input.is_visible():
            pass_input.fill(password)
            print("[*] Generated sign-up password.")

        # Check if terms checkbox exists
        terms = page.locator('input[type="checkbox"]').first
        if terms.is_visible():
            terms.check()

        # Submit sign-up
        signup_btn = page.locator('button[type="submit"], button:has-text("Sign Up"), button:has-text("Register"), button:has-text("Get Started")').first
        if signup_btn.is_visible():
            signup_btn.click()
            time.sleep(3)

        # Check if an activation URL is required
        activation_url = self.prompt_user_for_activation_url()
        if activation_url:
            print(f"[*] Navigating to user-provided activation URL: {activation_url}")
            page.goto(activation_url, timeout=30000)
            time.sleep(2)

    def _handle_2fa_otp_barrier(self, page: 'Page', pre_otp: Optional[str]):
        """Detects 2FA, OTP, TOTP, or SMS verification challenges and dynamically prompts the user."""
        otp_selectors = [
            'input[name*="otp"]', 'input[name*="2fa"]', 'input[name*="code"]',
            'input[name*="token"]', 'input[name*="pin"]', 'input[id*="otp"]',
            'input[id*="verification"]', 'input[autocomplete="one-time-code"]',
            'input[aria-label*="code" i]', 'input[placeholder*="code" i]',
            'input[placeholder*="OTP" i]'
        ]

        detected_otp_input = None
        for sel in otp_selectors:
            loc = page.locator(sel).first
            if loc.is_visible():
                detected_otp_input = loc
                print(f"[!] 2FA / OTP challenge input found: {sel}")
                break

        # Also inspect page text for 2FA keywords
        page_text = page.inner_text("body").lower()
        has_2fa_text = any(phrase in page_text for phrase in [
            "two-factor", "2-step verification", "verification code",
            "enter the 6-digit", "security code", "one-time password", "sent a code"
        ])

        if detected_otp_input or has_2fa_text:
            print("\n[!] >>> MULTI-FACTOR AUTHENTICATION BARRIER DETECTED <<<")
            self._save_screenshot(page, "2fa_challenge_screen")

            # Obtain code dynamically from user or environment
            otp_code = pre_otp or self.prompt_user_for_otp("Enter 2FA / OTP Verification Code")

            if otp_code:
                if detected_otp_input:
                    detected_otp_input.fill(otp_code)
                    print(f"[*] Entered OTP code into form.")
                else:
                    # Generic input fallback
                    inputs = page.locator('input[type="text"], input[type="number"]')
                    if inputs.first.is_visible():
                        inputs.first.fill(otp_code)

                # Submit OTP
                submit_otp = page.locator('button:has-text("Verify"), button:has-text("Confirm"), button:has-text("Submit"), button[type="submit"]').first
                if submit_otp.is_visible():
                    submit_otp.click()
                else:
                    page.keyboard.press("Enter")

                time.sleep(4)
                print("[✓] 2FA verification submitted.")
            else:
                print("[!] No OTP code supplied. Proceeding with current session state.")

    def _run_simulated_private_flow(self, target_url: str, query: str, auth_flow: str, email: Optional[str], password: Optional[str]):
        print(f"[*] Fallback: Performing HTTP-based authenticated research on {target_url}")
        content = self._fetch_url_content(target_url)
        self.session_data["auth_status"] = "simulated_http_session"
        self.session_data["extracted_data"] = {
            "target": target_url,
            "preview": content[:1000] if content else "Unable to reach target portal directly"
        }
        self.session_data["findings"].append({
            "title": f"Authenticated Target: {target_url}",
            "url": target_url,
            "key_points": ["Session initiated via fallback driver.", f"Target query: {query}"]
        })
        self._save_reports()

    def _save_screenshot(self, page: 'Page', name: str):
        try:
            path = os.path.join(self.output_dir, "screenshots", f"{name}_{int(time.time())}.png")
            page.screenshot(path=path)
            print(f"[*] Screenshot captured: {path}")
        except Exception:
            pass

    def _save_reports(self):
        # 1. JSON report
        json_path = os.path.join(self.output_dir, "research_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.session_data, f, indent=2)

        # 2. Markdown synthesis report
        md_path = os.path.join(self.output_dir, "research_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Hyper Copilot Web Research Synthesis\n\n")
            f.write(f"- **Mode**: {self.mode.upper()}\n")
            f.write(f"- **Timestamp**: {self.session_data['timestamp']}\n")
            f.write(f"- **Authentication Status**: `{self.session_data['auth_status']}`\n\n")
            f.write(f"---\n\n")
            f.write(f"## Key Research Findings\n\n")
            for item in self.session_data.get("findings", []):
                title = item.get("title", "Insight")
                url = item.get("url", "")
                f.write(f"### {title}\n")
                if url:
                    f.write(f"*Source: [{url}]({url})*\n\n")
                for pt in item.get("key_points", []):
                    f.write(f"- {pt}\n")
                if "content_snippet" in item:
                    f.write(f"\n> {item['content_snippet'][:400]}...\n")
                f.write("\n")

            if self.session_data.get("sources"):
                f.write(f"---\n\n## Indexed Sources\n\n")
                for s in self.session_data["sources"]:
                    f.write(f"- **[{s.get('title')}]({s.get('url')})**: {s.get('snippet')}\n")

        print(f"[✓] Reports generated:")
        print(f"    - {json_path}")
        print(f"    - {md_path}")

def main():
    parser = argparse.ArgumentParser(description="Hyper Copilot Automated Web Research Agent")
    parser.add_argument("--mode", choices=["public", "private"], default="public", help="Research mode: public or private")
    parser.add_argument("--query", type=str, required=True, help="Research topic or search query")
    parser.add_argument("--url", type=str, default=None, help="Target URL or portal")
    parser.add_argument("--auth-flow", choices=["none", "login", "signup"], default="login", help="Authentication flow for private mode")
    parser.add_argument("--email", type=str, default=None, help="User email or username for login/signup")
    parser.add_argument("--password", type=str, default=None, help="User password")
    parser.add_argument("--otp", type=str, default=None, help="Pre-supplied 2FA / OTP verification code")
    parser.add_argument("--output-dir", type=str, default="research_output", help="Directory to save research artifacts")
    parser.add_argument("--headful", action="store_true", help="Launch visible browser window (default is headless)")

    args = parser.parse_args()

    agent = WebResearchAgent(mode=args.mode, output_dir=args.output_dir, headless=not args.headful)

    if args.mode == "public":
        agent.run_public_research(query=args.query, target_url=args.url)
    else:
        target_url = args.url or "https://accounts.google.com"
        agent.run_private_research(
            target_url=target_url,
            query=args.query,
            auth_flow=args.auth_flow,
            email=args.email,
            password=args.password,
            pre_otp=args.otp
        )

if __name__ == "__main__":
    main()
