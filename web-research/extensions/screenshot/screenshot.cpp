#include "screenshot.hpp"
#include "../common/base64.hpp"
#include <iostream>
#include <fstream>
#include <sstream>

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

std::string Screenshot::FormatToString(ImageFormat fmt) {
    switch (fmt) {
        case ImageFormat::JPEG: return "jpeg";
        case ImageFormat::WEBP: return "webp";
        case ImageFormat::PNG:
        default: return "png";
    }
}

ImageFormat Screenshot::StringToFormat(const std::string& fmt_str) {
    if (fmt_str == "jpeg" || fmt_str == "jpg") return ImageFormat::JPEG;
    if (fmt_str == "webp") return ImageFormat::WEBP;
    return ImageFormat::PNG;
}

bool Screenshot::SaveToFile(const ScreenshotResult& result, const std::string& file_path) {
    if (result.binary_data.empty()) return false;
    std::ofstream out(file_path, std::ios::binary);
    if (!out.is_open()) return false;
    out.write(reinterpret_cast<const char*>(result.binary_data.data()), result.binary_data.size());
    return out.good();
}

ScreenshotResult Screenshot::CaptureViewport(Page& page, const ScreenshotOptions& options) {
    ScreenshotResult res;
    res.format_str = FormatToString(options.format);

    std::stringstream params;
    params << "{"
           << "\"format\":\"" << res.format_str << "\","
           << "\"fromSurface\":" << (options.from_surface ? "true" : "false");
    if (options.format != ImageFormat::PNG) {
        params << ",\"quality\":" << options.quality;
    }
    params << "}";

    auto cdp_resp = page.GetDispatcher()->Dispatch("Page.captureScreenshot", params.str(), page.GetSessionId());
    if (!cdp_resp.success) {
        res.success = false;
        res.error_message = cdp_resp.error_message;
        return res;
    }

    res.base64_data = ExtractJsonField(cdp_resp.result_json, "data");
    res.binary_data = utils::Base64Decode(res.base64_data);
    res.success = !res.binary_data.empty();

    if (res.success && !options.output_path.empty()) {
        if (SaveToFile(res, options.output_path)) {
            res.file_path = options.output_path;
        }
    }

    return res;
}

ScreenshotResult Screenshot::CaptureFullPage(Page& page, const ScreenshotOptions& options) {
    ScreenshotResult res;
    res.format_str = FormatToString(options.format);

    // 1. Measure full document scrollable metrics
    std::string measure_script = 
        "(function() {"
        "  var body = document.body || {};"
        "  var de = document.documentElement || {};"
        "  var width = Math.max(body.scrollWidth || 0, de.scrollWidth || 0, body.offsetWidth || 0, de.offsetWidth || 0, de.clientWidth || 0, window.innerWidth || 0);"
        "  var height = Math.max(body.scrollHeight || 0, de.scrollHeight || 0, body.offsetHeight || 0, de.offsetHeight || 0, de.clientHeight || 0, window.innerHeight || 0);"
        "  return JSON.stringify({ width: width, height: height });"
        "})()";

    auto eval_res = page.EvaluateScript(measure_script);
    double full_width = 1920;
    double full_height = 1080;

    if (eval_res.success && !eval_res.value_string.empty()) {
        double w = ExtractJsonNumber(eval_res.value_string, "width");
        double h = ExtractJsonNumber(eval_res.value_string, "height");
        if (w > 0) full_width = w;
        if (h > 0) full_height = h;
    }

    res.width = full_width;
    res.height = full_height;

    // 2. Capture screenshot with clip encompassing the full layout
    std::stringstream params;
    params << "{"
           << "\"format\":\"" << res.format_str << "\","
           << "\"fromSurface\":" << (options.from_surface ? "true" : "false") << ","
           << "\"captureBeyondViewport\":" << (options.capture_beyond_viewport ? "true" : "false") << ","
           << "\"clip\":{"
           << "\"x\":0,"
           << "\"y\":0,"
           << "\"width\":" << full_width << ","
           << "\"height\":" << full_height << ","
           << "\"scale\":" << options.scale
           << "}";
    if (options.format != ImageFormat::PNG) {
        params << ",\"quality\":" << options.quality;
    }
    params << "}";

    auto cdp_resp = page.GetDispatcher()->Dispatch("Page.captureScreenshot", params.str(), page.GetSessionId());
    if (!cdp_resp.success) {
        res.success = false;
        res.error_message = cdp_resp.error_message;
        return res;
    }

    res.base64_data = ExtractJsonField(cdp_resp.result_json, "data");
    res.binary_data = utils::Base64Decode(res.base64_data);
    res.success = !res.binary_data.empty();

    if (res.success && !options.output_path.empty()) {
        if (SaveToFile(res, options.output_path)) {
            res.file_path = options.output_path;
        }
    }

    return res;
}

ScreenshotResult Screenshot::CaptureElement(Page& page, const std::string& selector, const ScreenshotOptions& options) {
    ScreenshotResult res;
    res.format_str = FormatToString(options.format);

    // 1. Find element and compute bounding client rectangle
    std::stringstream find_script;
    find_script << "(function() {"
                << "  var el = document.querySelector('" << selector << "');"
                << "  if (!el) return JSON.stringify({ found: false });"
                << "  var rect = el.getBoundingClientRect();"
                << "  return JSON.stringify({"
                << "    found: true,"
                << "    x: rect.left + window.scrollX,"
                << "    y: rect.top + window.scrollY,"
                << "    width: rect.width,"
                << "    height: rect.height"
                << "  });"
                << "})()";

    auto eval_res = page.EvaluateScript(find_script.str());
    if (!eval_res.success || eval_res.value_string.empty()) {
        res.success = false;
        res.error_message = "Element query script failed for selector: " + selector;
        return res;
    }

    std::string found_str = ExtractJsonField(eval_res.value_string, "found");
    if (found_str != "true") {
        res.success = false;
        res.error_message = "Element not found for selector: " + selector;
        return res;
    }

    double elem_x = ExtractJsonNumber(eval_res.value_string, "x", 0.0);
    double elem_y = ExtractJsonNumber(eval_res.value_string, "y", 0.0);
    double elem_w = ExtractJsonNumber(eval_res.value_string, "width", 0.0);
    double elem_h = ExtractJsonNumber(eval_res.value_string, "height", 0.0);

    if (elem_w <= 0 || elem_h <= 0) {
        res.success = false;
        res.error_message = "Element has zero or negative bounding dimensions";
        return res;
    }

    res.width = elem_w;
    res.height = elem_h;

    // 2. Capture screenshot with clip matching element bounding box
    std::stringstream params;
    params << "{"
           << "\"format\":\"" << res.format_str << "\","
           << "\"fromSurface\":" << (options.from_surface ? "true" : "false") << ","
           << "\"captureBeyondViewport\":" << (options.capture_beyond_viewport ? "true" : "false") << ","
           << "\"clip\":{"
           << "\"x\":" << elem_x << ","
           << "\"y\":" << elem_y << ","
           << "\"width\":" << elem_w << ","
           << "\"height\":" << elem_h << ","
           << "\"scale\":" << options.scale
           << "}";
    if (options.format != ImageFormat::PNG) {
        params << ",\"quality\":" << options.quality;
    }
    params << "}";

    auto cdp_resp = page.GetDispatcher()->Dispatch("Page.captureScreenshot", params.str(), page.GetSessionId());
    if (!cdp_resp.success) {
        res.success = false;
        res.error_message = cdp_resp.error_message;
        return res;
    }

    res.base64_data = ExtractJsonField(cdp_resp.result_json, "data");
    res.binary_data = utils::Base64Decode(res.base64_data);
    res.success = !res.binary_data.empty();

    if (res.success && !options.output_path.empty()) {
        if (SaveToFile(res, options.output_path)) {
            res.file_path = options.output_path;
        }
    }

    return res;
}

} // namespace extensions
} // namespace hyper_vision_agent
