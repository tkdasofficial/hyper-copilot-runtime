#include "stealth.hpp"
#include "captcha_solver.hpp"
#include <iostream>
#include <sstream>
#include <cmath>
#include <random>
#include <thread>
#include <algorithm>

namespace hyper_vision_agent {
namespace extensions {

static std::string ExtractJsonField(const std::string& json, const std::string& key) {
    std::string pattern = "\"" + key + "\":";
    size_t pos = json.find(pattern);
    if (pos == std::string::npos) return "";

    pos += pattern.length();
    while (pos < json.length() && (json[pos] == ' ' || json[pos] == '\t')) pos++;

    if (pos < json.length() && json[pos] == '"') {
        size_t end_quote = json.find('"', pos + 1);
        if (end_quote != std::string::npos) {
            return json.substr(pos + 1, end_quote - pos - 1);
        }
    } else {
        size_t end_delim = json.find_first_of(",}\n", pos);
        if (end_delim != std::string::npos) {
            return json.substr(pos, end_delim - pos);
        }
    }
    return "";
}

static double ExtractJsonNumber(const std::string& json, const std::string& key, double default_val = 0.0) {
    std::string s = ExtractJsonField(json, key);
    if (s.empty()) return default_val;
    try {
        return std::stod(s);
    } catch (...) {
        return default_val;
    }
}

// Track current virtual mouse cursor position
static thread_local Point2D g_current_cursor{200.0, 200.0};

std::string Stealth::GenerateStealthScript(const StealthConfig& config) {
    std::stringstream ss;
    ss << "(function() {\n";
    ss << "  'use strict';\n";

    if (config.hide_webdriver) {
        ss << "  // 1. Hide navigator.webdriver\n";
        ss << "  try {\n";
        ss << "    Object.defineProperty(navigator, 'webdriver', {\n";
        ss << "      get: () => undefined,\n";
        ss << "      configurable: true\n";
        ss << "    });\n";
        ss << "    delete Object.getPrototypeOf(navigator).webdriver;\n";
        ss << "  } catch(e) {}\n";
    }

    if (config.mock_chrome_runtime) {
        ss << "  // 2. Mock window.chrome runtime\n";
        ss << "  try {\n";
        ss << "    if (!window.chrome) window.chrome = {};\n";
        ss << "    if (!window.chrome.runtime) window.chrome.runtime = {};\n";
        ss << "    if (!window.chrome.app) window.chrome.app = { isInstalled: false };\n";
        ss << "    if (!window.chrome.csi) window.chrome.csi = function() { return {}; };\n";
        ss << "    if (!window.chrome.loadTimes) window.chrome.loadTimes = function() { return {}; };\n";
        ss << "  } catch(e) {}\n";
    }

    if (config.mock_plugins) {
        ss << "  // 3. Mock navigator.plugins and mimeTypes\n";
        ss << "  try {\n";
        ss << "    const fakePlugins = [\n";
        ss << "      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },\n";
        ss << "      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },\n";
        ss << "      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }\n";
        ss << "    ];\n";
        ss << "    Object.defineProperty(navigator, 'plugins', {\n";
        ss << "      get: () => fakePlugins,\n";
        ss << "      configurable: true\n";
        ss << "    });\n";
        ss << "  } catch(e) {}\n";
    }

    // Languages
    ss << "  // 4. Languages\n";
    ss << "  try {\n";
    ss << "    Object.defineProperty(navigator, 'languages', {\n";
    ss << "      get: () => [";
    for (size_t i = 0; i < config.languages.size(); ++i) {
        ss << "'" << config.languages[i] << "'" << (i + 1 < config.languages.size() ? "," : "");
    }
    ss << "],\n      configurable: true\n    });\n";
    ss << "  } catch(e) {}\n";

    // Hardware Concurrency & Memory
    ss << "  // 5. Hardware Specs\n";
    ss << "  try {\n";
    ss << "    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => " << config.hardware_concurrency << ", configurable: true });\n";
    ss << "    Object.defineProperty(navigator, 'deviceMemory', { get: () => " << config.device_memory << ", configurable: true });\n";
    ss << "  } catch(e) {}\n";

    if (config.mock_webgl) {
        ss << "  // 6. WebGL Vendor & Renderer Spoofing\n";
        ss << "  try {\n";
        ss << "    const getParameterProto = WebGLRenderingContext.prototype.getParameter;\n";
        ss << "    WebGLRenderingContext.prototype.getParameter = function(param) {\n";
        ss << "      if (param === 37445) return '" << config.webgl_vendor << "'; // UNMASKED_VENDOR_WEBGL\n";
        ss << "      if (param === 37446) return '" << config.webgl_renderer << "'; // UNMASKED_RENDERER_WEBGL\n";
        ss << "      return getParameterProto.apply(this, arguments);\n";
        ss << "    };\n";
        ss << "    if (window.WebGL2RenderingContext) {\n";
        ss << "      const getParameterProto2 = WebGL2RenderingContext.prototype.getParameter;\n";
        ss << "      WebGL2RenderingContext.prototype.getParameter = function(param) {\n";
        ss << "        if (param === 37445) return '" << config.webgl_vendor << "';\n";
        ss << "        if (param === 37446) return '" << config.webgl_renderer << "';\n";
        ss << "        return getParameterProto2.apply(this, arguments);\n";
        ss << "      };\n";
        ss << "    }\n";
        ss << "  } catch(e) {}\n";
    }

    if (config.mock_audio_context) {
        ss << "  // 7. AudioContext Noise Injection\n";
        ss << "  try {\n";
        ss << "    const getChannelDataProto = AudioBuffer.prototype.getChannelData;\n";
        ss << "    AudioBuffer.prototype.getChannelData = function(channel) {\n";
        ss << "      const data = getChannelDataProto.apply(this, arguments);\n";
        ss << "      for (let i = 0; i < data.length; i += 100) {\n";
        ss << "        data[i] = data[i] + 0.0000001 * (Math.sin(i) * 0.5);\n";
        ss << "      }\n";
        ss << "      return data;\n";
        ss << "    };\n";
        ss << "  } catch(e) {}\n";
    }

    if (config.mock_permissions) {
        ss << "  // 8. Notification Permissions Query\n";
        ss << "  try {\n";
        ss << "    if (navigator.permissions && navigator.permissions.query) {\n";
        ss << "      const originalQuery = navigator.permissions.query;\n";
        ss << "      navigator.permissions.query = function(params) {\n";
        ss << "        if (params && params.name === 'notifications') {\n";
        ss << "          return Promise.resolve({ state: Notification.permission });\n";
        ss << "        }\n";
        ss << "        return originalQuery.apply(this, arguments);\n";
        ss << "      };\n";
        ss << "    }\n";
        ss << "  } catch(e) {}\n";
    }

    ss << "})();\n";
    return ss.str();
}

bool Stealth::Apply(Page& page, const StealthConfig& config) {
    std::string script = GenerateStealthScript(config);

    // 1. Injected for all subsequent document creations / navigations
    std::stringstream json_stream;
    json_stream << "{\"source\":";
    // Properly escape script for JSON
    json_stream << "\"";
    for (char c : script) {
        if (c == '"') json_stream << "\\\"";
        else if (c == '\\') json_stream << "\\\\";
        else if (c == '\n') json_stream << "\\n";
        else if (c == '\r') json_stream << "\\r";
        else if (c == '\t') json_stream << "\\t";
        else json_stream << c;
    }
    json_stream << "\"}";

    auto resp = page.GetDispatcher()->Dispatch("Page.addScriptToEvaluateOnNewDocument", json_stream.str(), page.GetSessionId());

    // 2. Also evaluate immediately in current execution context
    page.EvaluateScript(script);

    return resp.success;
}

std::vector<Point2D> Stealth::CalculateHumanTrajectory(Point2D start, Point2D end, int steps, double curvature) {
    std::vector<Point2D> trajectory;
    if (steps < 2) steps = 2;
    trajectory.reserve(steps);

    double dx = end.x - start.x;
    double dy = end.y - start.y;
    double dist = std::hypot(dx, dy);

    if (dist < 1.0) {
        trajectory.push_back(end);
        return trajectory;
    }

    // Normal unit vector perpendicular to direct path
    double nx = -dy / dist;
    double ny = dx / dist;

    // Randomize control points with realistic wrist arc deviation
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<double> curve_dist(-curvature, curvature);
    std::uniform_real_distribution<double> jitter_dist(-1.5, 1.5);

    double offset1 = curve_dist(gen) * dist;
    double offset2 = curve_dist(gen) * dist;

    Point2D c1{
        start.x + dx * 0.25 + nx * offset1,
        start.y + dy * 0.25 + ny * offset1
    };

    Point2D c2{
        start.x + dx * 0.75 + nx * offset2,
        start.y + dy * 0.75 + ny * offset2
    };

    for (int i = 0; i <= steps; ++i) {
        double linear_t = static_cast<double>(i) / steps;

        // Fitts' Law ease-in ease-out curve (smoothstep / S-curve)
        double t = linear_t * linear_t * (3.0 - 2.0 * linear_t);

        // Cubic Bezier polynomial
        double one_minus_t = 1.0 - t;
        double b0 = one_minus_t * one_minus_t * one_minus_t;
        double b1 = 3.0 * one_minus_t * one_minus_t * t;
        double b2 = 3.0 * one_minus_t * t * t;
        double b3 = t * t * t;

        double x = b0 * start.x + b1 * c1.x + b2 * c2.x + b3 * end.x;
        double y = b0 * start.y + b1 * c1.y + b2 * c2.y + b3 * end.y;

        // Add subtle human tremor/jitter, dying out as approaching target
        double jitter_attenuation = (1.0 - linear_t);
        x += jitter_dist(gen) * jitter_attenuation;
        y += jitter_dist(gen) * jitter_attenuation;

        trajectory.push_back({x, y});
    }

    return trajectory;
}

bool Stealth::HumanMoveTo(Page& page, double target_x, double target_y, int steps, int total_duration_ms) {
    Point2D start = g_current_cursor;
    Point2D end{target_x, target_y};

    auto points = CalculateHumanTrajectory(start, end, steps);
    int sleep_per_step_ms = total_duration_ms / std::max(1, static_cast<int>(points.size()));
    if (sleep_per_step_ms < 5) sleep_per_step_ms = 5;

    for (const auto& pt : points) {
        page.GetDispatcher()->InputDispatchMouseEvent("mouseMoved", pt.x, pt.y, "none", 0, page.GetSessionId());
        g_current_cursor = pt;
        std::this_thread::sleep_for(std::chrono::milliseconds(sleep_per_step_ms));
    }

    // Ensure cursor ends precisely on target
    page.GetDispatcher()->InputDispatchMouseEvent("mouseMoved", target_x, target_y, "none", 0, page.GetSessionId());
    g_current_cursor = end;
    return true;
}

bool Stealth::HumanClickAt(Page& page, double x, double y, int duration_ms) {
    HumanMoveTo(page, x, y, 20, duration_ms);

    // Natural human pre-click micro hesitation (50-120ms)
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<int> dwell_dist(60, 120);

    std::this_thread::sleep_for(std::chrono::milliseconds(dwell_dist(gen)));
    page.GetDispatcher()->InputDispatchMouseEvent("mousePressed", x, y, "left", 1, page.GetSessionId());

    std::this_thread::sleep_for(std::chrono::milliseconds(dwell_dist(gen)));
    page.GetDispatcher()->InputDispatchMouseEvent("mouseReleased", x, y, "left", 1, page.GetSessionId());

    return true;
}

bool Stealth::HumanClick(Page& page, const std::string& selector, int duration_ms) {
    std::stringstream find_script;
    find_script << "(function() {"
                << "  var el = document.querySelector('" << selector << "');"
                << "  if (!el) return JSON.stringify({ found: false });"
                << "  var rect = el.getBoundingClientRect();"
                << "  return JSON.stringify({"
                << "    found: true,"
                << "    x: rect.left + rect.width / 2.0 + window.scrollX,"
                << "    y: rect.top + rect.height / 2.0 + window.scrollY"
                << "  });"
                << "})()";

    auto eval_res = page.EvaluateScript(find_script.str());
    if (!eval_res.success) return false;

    if (ExtractJsonField(eval_res.value_string, "found") != "true") {
        return false;
    }

    double cx = ExtractJsonNumber(eval_res.value_string, "x", 0.0);
    double cy = ExtractJsonNumber(eval_res.value_string, "y", 0.0);

    return HumanClickAt(page, cx, cy, duration_ms);
}

// -----------------------------------------------------------------------------
// CaptchaSolver Implementation
// -----------------------------------------------------------------------------

CaptchaDetectResult CaptchaSolver::DetectCaptcha(Page& page) {
    CaptchaDetectResult res;

    std::string scan_script = 
        "(function() {"
        "  /* 1. Cloudflare Turnstile */\n"
        "  var turnstileIframe = document.querySelector('iframe[src*=\"challenges.cloudflare.com\"], iframe[src*=\"turnstile\"], div.cf-turnstile');"
        "  if (turnstileIframe) {"
        "    var rect = turnstileIframe.getBoundingClientRect();"
        "    return JSON.stringify({"
        "      type: 'turnstile',"
        "      selector: 'iframe[src*=\"challenges.cloudflare.com\"]',"
        "      x: rect.left + rect.width * 0.15 + window.scrollX,"
        "      y: rect.top + rect.height * 0.5 + window.scrollY,"
        "      url: turnstileIframe.src || ''"
        "    });"
        "  }"
        "  /* 2. Google reCAPTCHA v2 */\n"
        "  var recaptchaIframe = document.querySelector('iframe[src*=\"google.com/recaptcha\"], div.g-recaptcha');"
        "  if (recaptchaIframe) {"
        "    var rect = recaptchaIframe.getBoundingClientRect();"
        "    return JSON.stringify({"
        "      type: 'recaptcha_v2',"
        "      selector: 'iframe[src*=\"google.com/recaptcha\"]',"
        "      x: rect.left + 28 + window.scrollX,"
        "      y: rect.top + rect.height * 0.5 + window.scrollY,"
        "      url: recaptchaIframe.src || ''"
        "    });"
        "  }"
        "  /* 3. hCaptcha */\n"
        "  var hcaptchaIframe = document.querySelector('iframe[src*=\"hcaptcha.com\"], div.h-captcha');"
        "  if (hcaptchaIframe) {"
        "    var rect = hcaptchaIframe.getBoundingClientRect();"
        "    return JSON.stringify({"
        "      type: 'hcaptcha',"
        "      selector: 'iframe[src*=\"hcaptcha.com\"]',"
        "      x: rect.left + 28 + window.scrollX,"
        "      y: rect.top + rect.height * 0.5 + window.scrollY,"
        "      url: hcaptchaIframe.src || ''"
        "    });"
        "  }"
        "  return JSON.stringify({ type: 'none' });"
        "})()";

    auto eval_res = page.EvaluateScript(scan_script);
    if (!eval_res.success) return res;

    std::string type_str = ExtractJsonField(eval_res.value_string, "type");
    if (type_str == "turnstile") {
        res.type = CaptchaType::CLOUDFLARE_TURNSTILE;
        res.detected = true;
    } else if (type_str == "recaptcha_v2") {
        res.type = CaptchaType::RECAPTCHA_V2;
        res.detected = true;
    } else if (type_str == "hcaptcha") {
        res.type = CaptchaType::HCAPTCHA;
        res.detected = true;
    }

    if (res.detected) {
        res.selector = ExtractJsonField(eval_res.value_string, "selector");
        res.frame_url = ExtractJsonField(eval_res.value_string, "url");
        res.center_coords.x = ExtractJsonNumber(eval_res.value_string, "x", 0.0);
        res.center_coords.y = ExtractJsonNumber(eval_res.value_string, "y", 0.0);
    }

    return res;
}

bool CaptchaSolver::HandleTurnstile(Page& page, std::chrono::milliseconds timeout) {
    auto detection = DetectCaptcha(page);
    if (!detection.detected || detection.type != CaptchaType::CLOUDFLARE_TURNSTILE) {
        return false;
    }

    // Approach and click checkbox with human curve
    Stealth::HumanClickAt(page, detection.center_coords.x, detection.center_coords.y, 400);

    // Poll for verification token in input[name="cf-turnstile-response"]
    auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        auto check_res = page.EvaluateScript(
            "(function() {"
            "  var inp = document.querySelector('input[name=\"cf-turnstile-response\"]');"
            "  if (inp && inp.value && inp.value.length > 5) return inp.value;"
            "  return '';"
            "})()"
        );
        if (check_res.success && !check_res.value_string.empty()) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }

    return false;
}

bool CaptchaSolver::HandleRecaptcha(Page& page, std::chrono::milliseconds timeout) {
    auto detection = DetectCaptcha(page);
    if (!detection.detected || detection.type != CaptchaType::RECAPTCHA_V2) {
        return false;
    }

    Stealth::HumanClickAt(page, detection.center_coords.x, detection.center_coords.y, 450);

    auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        auto check_res = page.EvaluateScript(
            "(function() {"
            "  var resp = document.querySelector('textarea[name=\"g-recaptcha-response\"], #g-recaptcha-response');"
            "  if (resp && resp.value && resp.value.length > 5) return resp.value;"
            "  var checkedAnchor = document.querySelector('.recaptcha-checkbox-checked, [aria-checked=\"true\"]');"
            "  if (checkedAnchor) return 'checked';"
            "  return '';"
            "})()"
        );
        if (check_res.success && !check_res.value_string.empty()) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }

    return false;
}

CaptchaSolveResult CaptchaSolver::Solve(Page& page, std::chrono::milliseconds timeout) {
    auto start_time = std::chrono::steady_clock::now();
    CaptchaSolveResult res;

    auto detection = DetectCaptcha(page);
    res.type = detection.type;

    if (!detection.detected) {
        res.success = false;
        res.error_message = "No active captcha detected on current page";
        return res;
    }

    bool solved = false;
    if (detection.type == CaptchaType::CLOUDFLARE_TURNSTILE) {
        solved = HandleTurnstile(page, timeout);
    } else if (detection.type == CaptchaType::RECAPTCHA_V2) {
        solved = HandleRecaptcha(page, timeout);
    } else {
        // Generic click approach
        solved = Stealth::HumanClickAt(page, detection.center_coords.x, detection.center_coords.y, 400);
    }

    res.success = solved;
    res.elapsed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start_time);

    return res;
}

} // namespace extensions
} // namespace hyper_vision_agent
