#include "hyper_vision_agent/command_dispatcher.hpp"
#include <iostream>
#include <sstream>

namespace hyper_vision_agent {

namespace {

std::string EscapeJsonString(const std::string& input) {
    std::ostringstream ss;
    for (char c : input) {
        switch (c) {
            case '"': ss << "\\\""; break;
            case '\\': ss << "\\\\"; break;
            case '\b': ss << "\\b"; break;
            case '\f': ss << "\\f"; break;
            case '\n': ss << "\\n"; break;
            case '\r': ss << "\\r"; break;
            case '\t': ss << "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    ss << buf;
                } else {
                    ss << c;
                }
        }
    }
    return ss.str();
}

} // namespace

CommandDispatcher::CommandDispatcher(std::shared_ptr<CdpConnection> connection)
    : connection_(connection) {}

bool CommandDispatcher::EnablePage(const SessionId& session_id) {
    return connection_->SendCommand("Page.enable", "{}", session_id).success;
}

bool CommandDispatcher::EnableDOM(const SessionId& session_id) {
    return connection_->SendCommand("DOM.enable", "{}", session_id).success;
}

bool CommandDispatcher::EnableRuntime(const SessionId& session_id) {
    return connection_->SendCommand("Runtime.enable", "{}", session_id).success;
}

bool CommandDispatcher::EnableNetwork(const SessionId& session_id) {
    return connection_->SendCommand("Network.enable", "{}", session_id).success;
}

CdpResponse CommandDispatcher::PageNavigate(const std::string& url, const SessionId& session_id) {
    std::string params = "{\"url\":\"" + EscapeJsonString(url) + "\"}";
    return connection_->SendCommand("Page.navigate", params, session_id);
}

CdpResponse CommandDispatcher::PageReload(const SessionId& session_id) {
    return connection_->SendCommand("Page.reload", "{\"ignoreCache\":true}", session_id);
}

CdpResponse CommandDispatcher::PageCaptureScreenshot(const std::string& format, int quality, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"format\":\"" << format << "\"";
    if (format == "jpeg") {
        params << ",\"quality\":" << quality;
    }
    params << ",\"fromSurface\":true,\"captureBeyondViewport\":false}";
    return connection_->SendCommand("Page.captureScreenshot", params.str(), session_id);
}

CdpResponse CommandDispatcher::RuntimeEvaluate(const std::string& expression, bool return_by_value, bool await_promise, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"expression\":\"" << EscapeJsonString(expression) << "\""
           << ",\"returnByValue\":" << (return_by_value ? "true" : "false")
           << ",\"awaitPromise\":" << (await_promise ? "true" : "false")
           << ",\"userGesture\":true}";
    return connection_->SendCommand("Runtime.evaluate", params.str(), session_id);
}

CdpResponse CommandDispatcher::DOMGetDocument(int depth, bool pierce, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"depth\":" << depth << ",\"pierce\":" << (pierce ? "true" : "false") << "}";
    return connection_->SendCommand("DOM.getDocument", params.str(), session_id);
}

CdpResponse CommandDispatcher::DOMQuerySelector(int node_id, const std::string& selector, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"nodeId\":" << node_id << ",\"selector\":\"" << EscapeJsonString(selector) << "\"}";
    return connection_->SendCommand("DOM.querySelector", params.str(), session_id);
}

CdpResponse CommandDispatcher::DOMQuerySelectorAll(int node_id, const std::string& selector, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"nodeId\":" << node_id << ",\"selector\":\"" << EscapeJsonString(selector) << "\"}";
    return connection_->SendCommand("DOM.querySelectorAll", params.str(), session_id);
}

CdpResponse CommandDispatcher::DOMGetBoxModel(int node_id, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"nodeId\":" << node_id << "}";
    return connection_->SendCommand("DOM.getBoxModel", params.str(), session_id);
}

CdpResponse CommandDispatcher::DOMFocus(int node_id, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"nodeId\":" << node_id << "}";
    return connection_->SendCommand("DOM.focus", params.str(), session_id);
}

CdpResponse CommandDispatcher::InputDispatchMouseEvent(const std::string& type, double x, double y, const std::string& button, int click_count, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"type\":\"" << type << "\""
           << ",\"x\":" << x
           << ",\"y\":" << y
           << ",\"button\":\"" << button << "\""
           << ",\"clickCount\":" << click_count << "}";
    return connection_->SendCommand("Input.dispatchMouseEvent", params.str(), session_id);
}

CdpResponse CommandDispatcher::InputDispatchKeyEvent(const std::string& type, const std::string& key, const std::string& text, int windows_virtual_key_code, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"type\":\"" << type << "\""
           << ",\"key\":\"" << EscapeJsonString(key) << "\"";
    if (!text.empty()) {
        params << ",\"text\":\"" << EscapeJsonString(text) << "\"";
    }
    if (windows_virtual_key_code > 0) {
        params << ",\"windowsVirtualKeyCode\":" << windows_virtual_key_code;
    }
    params << "}";
    return connection_->SendCommand("Input.dispatchKeyEvent", params.str(), session_id);
}

CdpResponse CommandDispatcher::InputInsertText(const std::string& text, const SessionId& session_id) {
    std::string params = "{\"text\":\"" + EscapeJsonString(text) + "\"}";
    return connection_->SendCommand("Input.insertText", params, session_id);
}

CdpResponse CommandDispatcher::EmulationSetDeviceMetrics(int width, int height, double device_scale_factor, bool mobile, const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"width\":" << width
           << ",\"height\":" << height
           << ",\"deviceScaleFactor\":" << device_scale_factor
           << ",\"mobile\":" << (mobile ? "true" : "false") << "}";
    return connection_->SendCommand("Emulation.setDeviceMetricsOverride", params.str(), session_id);
}

CdpResponse CommandDispatcher::EmulationSetUserAgent(const std::string& user_agent, const SessionId& session_id) {
    std::string params = "{\"userAgent\":\"" + EscapeJsonString(user_agent) + "\"}";
    return connection_->SendCommand("Emulation.setUserAgentOverride", params, session_id);
}

CdpResponse CommandDispatcher::Dispatch(const std::string& method, const std::string& params_json, const SessionId& session_id) {
    return connection_->SendCommand(method, params_json, session_id);
}

} // namespace hyper_vision_agent
