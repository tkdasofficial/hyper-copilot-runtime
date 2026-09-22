#ifndef HYPER_VISION_AGENT_CDP_CONNECTION_HPP
#define HYPER_VISION_AGENT_CDP_CONNECTION_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/websocket_client.hpp"
#include <string>
#include <unordered_map>
#include <future>
#include <mutex>
#include <atomic>
#include <memory>
#include <vector>

namespace hyper_vision_agent {

class CdpConnection {
public:
    CdpConnection();
    ~CdpConnection();

    // Prevent copies
    CdpConnection(const CdpConnection&) = delete;
    CdpConnection& operator=(const CdpConnection&) = delete;

    bool Connect(const std::string& ws_url, std::chrono::milliseconds timeout = std::chrono::milliseconds(5000));
    void Disconnect();
    bool IsConnected() const;

    // Send CDP command asynchronously or synchronously
    std::future<CdpResponse> SendCommandAsync(const std::string& method, 
                                             const std::string& params_json = "{}",
                                             const std::string& session_id = "");
    
    CdpResponse SendCommand(const std::string& method, 
                           const std::string& params_json = "{}",
                           const std::string& session_id = "",
                           std::chrono::milliseconds timeout = std::chrono::milliseconds(10000));

    // Event Subscriptions
    void SubscribeEvent(const std::string& method, EventCallback callback);
    void UnsubscribeEvent(const std::string& method);
    void SetDefaultEventHandler(EventCallback callback);

private:
    void OnMessageReceived(const std::string& raw_message);
    void OnStateChanged(WebSocketState state);
    void OnError(const std::string& err);

    std::unique_ptr<WebSocketClient> ws_client_;
    std::atomic<CommandId> next_command_id_{1};

    struct PendingCommand {
        std::promise<CdpResponse> promise;
        std::string method;
        std::chrono::steady_clock::time_point sent_at;
    };

    std::unordered_map<CommandId, std::shared_ptr<PendingCommand>> pending_commands_;
    std::mutex pending_mutex_;

    std::unordered_map<std::string, std::vector<EventCallback>> event_listeners_;
    EventCallback default_event_handler_;
    std::mutex event_mutex_;
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_CDP_CONNECTION_HPP
