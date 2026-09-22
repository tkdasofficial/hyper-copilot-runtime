#include "hyper_vision_agent/page.hpp"
#include <iostream>
#include <regex>
#include <thread>

namespace hyper_vision_agent {

namespace {

std::string ExtractField(const std::string& json, const std::string& key) {
    std::string search_key = "\"" + key + "\"";
    size_t key_pos = json.find(search_key);
    if (key_pos == std::string::npos) return "";

    size_t colon_pos = json.find(':', key_pos + search_key.length());
    if (colon_pos == std::string::npos) return "";

    size_t quote_start = json.find('"', colon_pos + 1);
    if (quote_start == std::string::npos) return "";

    std::string result;
    bool escaped = false;
    for (size_t i = quote_start + 1; i < json.length(); ++i) {
        char c = json[i];
        if (escaped) {
            switch (c) {
                case '"': result += '"'; break;
                case '\\': result += '\\'; break;
                case '/': result += '/'; break;
                case 'b': result += '\b'; break;
                case 'f': result += '\f'; break;
                case 'n': result += '\n'; break;
                case 'r': result += '\r'; break;
                case 't': result += '\t'; break;
                default: result += c; break;
            }
            escaped = false;
        } else if (c == '\\') {
            escaped = true;
        } else if (c == '"') {
            return result;
        } else {
            result += c;
        }
    }
    return result;
}

int64_t ExtractIntField(const std::string& json, const std::string& key, int64_t def = 0) {
    std::string pattern = "\"" + key + "\"\\s*:\\s*(-?\\d+)";
    std::regex re(pattern);
    std::smatch match;
    if (std::regex_search(json, match, re) && match.size() > 1) {
        return std::stoll(match[1].str());
    }
    return def;
}

} // namespace

Page::Page(const TargetId& target_id,
           const SessionId& session_id,
           std::shared_ptr<CdpConnection> connection,
           std::shared_ptr<CommandDispatcher> dispatcher)
    : target_id_(target_id),
      session_id_(session_id),
      connection_(connection),
      dispatcher_(dispatcher) {
    SetupEventHandlers();
}

Page::~Page() {
    Close();
}

void Page::SetupEventHandlers() {
    connection_->SubscribeEvent("Page.loadEventFired", [this](const CdpEvent& ev) {
        if (ev.session_id.empty() || ev.session_id == this->session_id_) {
            {
                std::lock_guard<std::mutex> lock(this->nav_mutex_);
                this->load_event_fired_ = true;
            }
            this->nav_cv_.notify_all();
        }
    });

    connection_->SubscribeEvent("Page.frameNavigated", [this](const CdpEvent& ev) {
        if (ev.session_id.empty() || ev.session_id == this->session_id_) {
            std::string url = ExtractField(ev.params_json, "url");
            if (!url.empty()) {
                this->current_url_ = url;
            }
        }
    });
}

bool Page::Initialize() {
    try {
        dispatcher_->EnablePage(session_id_);
        dispatcher_->EnableDOM(session_id_);
        dispatcher_->EnableRuntime(session_id_);
        dispatcher_->EnableNetwork(session_id_);
        return true;
    } catch (...) {
        return false;
    }
}

NavigationResult Page::Navigate(const std::string& url, std::chrono::milliseconds timeout) {
    auto start_time = std::chrono::steady_clock::now();
    NavigationResult result;
    result.url = url;

    {
        std::lock_guard<std::mutex> lock(nav_mutex_);
        load_event_fired_ = false;
    }

    CdpResponse resp = dispatcher_->PageNavigate(url, session_id_);
    if (!resp.success) {
        result.success = false;
        result.elapsed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start_time);
        return result;
    }

    result.frame_id = ExtractField(resp.result_json, "frameId");

    // Wait for Page.loadEventFired
    std::unique_lock<std::mutex> lock(nav_mutex_);
    bool completed = nav_cv_.wait_for(lock, std::min(timeout, std::chrono::milliseconds(5000)), [this]() {
        return load_event_fired_.load();
    });

    if (!completed) {
        auto ready = EvaluateScript("document.readyState");
        if (ready.success && (ready.value_string == "complete" || ready.value_string == "interactive")) {
            completed = true;
        }
    }

    result.success = completed;
    current_url_ = url;
    result.elapsed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start_time);
    return result;
}

void Page::Reload() {
    dispatcher_->PageReload(session_id_);
}

EvalResult Page::EvaluateScript(const std::string& script) {
    EvalResult result;
    try {
        CdpResponse resp = dispatcher_->RuntimeEvaluate(script, true, true, session_id_);
        result.raw_result_json = resp.result_json;
        if (!resp.success) {
            result.success = false;
            result.error_description = resp.error_message;
            return result;
        }

        result.success = true;
        std::string result_obj = resp.result_json;
        result.type = ExtractField(result_obj, "type");
        
        if (result.type == "string") {
            result.value_string = ExtractField(result_obj, "value");
        } else if (result.type == "number") {
            std::string num_str = ExtractField(result_obj, "value");
            if (num_str.empty()) {
                result.value_number = static_cast<double>(ExtractIntField(result_obj, "value", 0));
            } else {
                result.value_number = std::stod(num_str);
            }
        } else if (result.type == "boolean") {
            result.value_boolean = (result_obj.find("\"value\":true") != std::string::npos);
        } else {
            result.value_string = ExtractField(result_obj, "description");
        }
    } catch (const std::exception& e) {
        result.success = false;
        result.error_description = e.what();
    }
    return result;
}

int Page::QuerySelector(const std::string& selector) {
    CdpResponse doc_resp = dispatcher_->DOMGetDocument(1, false, session_id_);
    if (!doc_resp.success) return 0;

    int root_node_id = static_cast<int>(ExtractIntField(doc_resp.result_json, "nodeId", 0));
    if (root_node_id <= 0) return 0;

    CdpResponse q_resp = dispatcher_->DOMQuerySelector(root_node_id, selector, session_id_);
    if (!q_resp.success) return 0;

    return static_cast<int>(ExtractIntField(q_resp.result_json, "nodeId", 0));
}

std::vector<int> Page::QuerySelectorAll(const std::string& selector) {
    std::vector<int> node_ids;
    CdpResponse doc_resp = dispatcher_->DOMGetDocument(1, false, session_id_);
    if (!doc_resp.success) return node_ids;

    int root_node_id = static_cast<int>(ExtractIntField(doc_resp.result_json, "nodeId", 0));
    if (root_node_id <= 0) return node_ids;

    CdpResponse q_resp = dispatcher_->DOMQuerySelectorAll(root_node_id, selector, session_id_);
    if (!q_resp.success) return node_ids;

    // Parse array of nodeId numbers
    std::regex num_re("\\d+");
    std::string str = q_resp.result_json;
    auto words_begin = std::sregex_iterator(str.begin(), str.end(), num_re);
    auto words_end = std::sregex_iterator();
    for (std::sregex_iterator i = words_begin; i != words_end; ++i) {
        node_ids.push_back(std::stoi(i->str()));
    }
    return node_ids;
}

std::optional<ElementCoordinates> Page::GetElementCenter(int node_id) {
    CdpResponse resp = dispatcher_->DOMGetBoxModel(node_id, session_id_);
    if (!resp.success) return std::nullopt;

    // BoxModel content quad has 8 points: [x1, y1, x2, y2, x3, y3, x4, y4]
    std::string json = resp.result_json;
    size_t quad_pos = json.find("\"content\":[");
    if (quad_pos == std::string::npos) return std::nullopt;

    size_t end_bracket = json.find(']', quad_pos);
    if (end_bracket == std::string::npos) return std::nullopt;

    std::string quad_str = json.substr(quad_pos + 11, end_bracket - quad_pos - 11);
    std::stringstream ss(quad_str);
    std::string token;
    std::vector<double> coords;
    while (std::getline(ss, token, ',')) {
        try {
            coords.push_back(std::stod(token));
        } catch (...) {}
    }

    if (coords.size() >= 8) {
        ElementCoordinates center;
        center.x = (coords[0] + coords[2] + coords[4] + coords[6]) / 4.0;
        center.y = (coords[1] + coords[3] + coords[5] + coords[7]) / 4.0;
        center.visible = true;
        return center;
    }

    return std::nullopt;
}

bool Page::Click(const std::string& selector) {
    int node_id = QuerySelector(selector);
    if (node_id <= 0) return false;

    auto center = GetElementCenter(node_id);
    if (!center.has_value()) {
        // Fallback to DOM Focus and JavaScript click
        EvaluateScript("document.querySelector('" + selector + "')?.click();");
        return true;
    }

    return ClickAt(center->x, center->y);
}

bool Page::ClickAt(double x, double y) {
    dispatcher_->InputDispatchMouseEvent("mouseMoved", x, y, "none", 0, session_id_);
    dispatcher_->InputDispatchMouseEvent("mousePressed", x, y, "left", 1, session_id_);
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    dispatcher_->InputDispatchMouseEvent("mouseReleased", x, y, "left", 1, session_id_);
    return true;
}

bool Page::Type(const std::string& selector, const std::string& text, int delay_ms) {
    int node_id = QuerySelector(selector);
    if (node_id > 0) {
        dispatcher_->DOMFocus(node_id, session_id_);
    }

    for (char c : text) {
        std::string char_str(1, c);
        dispatcher_->InputInsertText(char_str, session_id_);
        if (delay_ms > 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
        }
    }
    return true;
}

bool Page::Focus(const std::string& selector) {
    int node_id = QuerySelector(selector);
    if (node_id <= 0) return false;
    return dispatcher_->DOMFocus(node_id, session_id_).success;
}

bool Page::WaitForSelector(const std::string& selector, std::chrono::milliseconds timeout) {
    auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        int node = QuerySelector(selector);
        if (node > 0) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    return false;
}

bool Page::WaitForNavigation(std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(nav_mutex_);
    return nav_cv_.wait_for(lock, timeout, [this]() {
        return load_event_fired_.load();
    });
}

void Page::Sleep(std::chrono::milliseconds duration) {
    std::this_thread::sleep_for(duration);
}

std::string Page::CaptureScreenshotBase64(const std::string& format, int quality) {
    CdpResponse resp = dispatcher_->PageCaptureScreenshot(format, quality, session_id_);
    if (!resp.success) {
        throw CdpException("CaptureScreenshot failed: " + resp.error_message);
    }
    return ExtractField(resp.result_json, "data");
}

std::string Page::GetContent() {
    EvalResult res = EvaluateScript("document.documentElement.outerHTML");
    return res.value_string;
}

std::string Page::GetTitle() {
    EvalResult res = EvaluateScript("document.title");
    return res.value_string;
}

bool Page::SetViewport(int width, int height, double scale) {
    CdpResponse resp = dispatcher_->EmulationSetDeviceMetrics(width, height, scale, false, session_id_);
    return resp.success;
}

void Page::Close() {
    if (!is_closed_) {
        is_closed_ = true;
    }
}

} // namespace hyper_vision_agent
