#ifndef HYPER_VISION_AGENT_COMMAND_DISPATCHER_HPP
#define HYPER_VISION_AGENT_COMMAND_DISPATCHER_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/cdp_connection.hpp"
#include <string>
#include <memory>
#include <vector>

namespace hyper_vision_agent {

class CommandDispatcher {
public:
    explicit CommandDispatcher(std::shared_ptr<CdpConnection> connection);
    ~CommandDispatcher() = default;

    // Domain Enablement
    bool EnablePage(const SessionId& session_id = "");
    bool EnableDOM(const SessionId& session_id = "");
    bool EnableRuntime(const SessionId& session_id = "");
    bool EnableNetwork(const SessionId& session_id = "");

    // Page Domain
    CdpResponse PageNavigate(const std::string& url, const SessionId& session_id = "");
    CdpResponse PageReload(const SessionId& session_id = "");
    CdpResponse PageCaptureScreenshot(const std::string& format = "png", int quality = 80, const SessionId& session_id = "");
    
    // Runtime Domain
    CdpResponse RuntimeEvaluate(const std::string& expression, bool return_by_value = true, bool await_promise = true, const SessionId& session_id = "");
    
    // DOM Domain
    CdpResponse DOMGetDocument(int depth = 1, bool pierce = false, const SessionId& session_id = "");
    CdpResponse DOMQuerySelector(int node_id, const std::string& selector, const SessionId& session_id = "");
    CdpResponse DOMQuerySelectorAll(int node_id, const std::string& selector, const SessionId& session_id = "");
    CdpResponse DOMGetBoxModel(int node_id, const SessionId& session_id = "");
    CdpResponse DOMFocus(int node_id, const SessionId& session_id = "");

    // Input Domain
    CdpResponse InputDispatchMouseEvent(const std::string& type, double x, double y, const std::string& button = "left", int click_count = 1, const SessionId& session_id = "");
    CdpResponse InputDispatchKeyEvent(const std::string& type, const std::string& key, const std::string& text = "", int windows_virtual_key_code = 0, const SessionId& session_id = "");
    CdpResponse InputInsertText(const std::string& text, const SessionId& session_id = "");

    // Emulation Domain
    CdpResponse EmulationSetDeviceMetrics(int width, int height, double device_scale_factor = 1.0, bool mobile = false, const SessionId& session_id = "");
    CdpResponse EmulationSetUserAgent(const std::string& user_agent, const SessionId& session_id = "");

    // Generic command passthrough
    CdpResponse Dispatch(const std::string& method, const std::string& params_json = "{}", const SessionId& session_id = "");

private:
    std::shared_ptr<CdpConnection> connection_;
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_COMMAND_DISPATCHER_HPP
