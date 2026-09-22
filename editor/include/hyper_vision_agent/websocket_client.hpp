#ifndef HYPER_VISION_AGENT_WEBSOCKET_CLIENT_HPP
#define HYPER_VISION_AGENT_WEBSOCKET_CLIENT_HPP

#include "hyper_vision_agent/types.hpp"
#include <string>
#include <functional>
#include <thread>
#include <atomic>
#include <mutex>
#include <vector>
#include <queue>
#include <condition_variable>

namespace hyper_vision_agent {

enum class WebSocketState {
    DISCONNECTED,
    CONNECTING,
    OPEN,
    CLOSING,
    CLOSED,
    FAILED
};

class WebSocketClient {
public:
    using MessageHandler = std::function<void(const std::string& message)>;
    using StateHandler = std::function<void(WebSocketState new_state)>;
    using ErrorHandler = std::function<void(const std::string& error_msg)>;

    WebSocketClient();
    ~WebSocketClient();

    // Prevent copies
    WebSocketClient(const WebSocketClient&) = delete;
    WebSocketClient& operator=(const WebSocketClient&) = delete;

    // Connection Control
    bool Connect(const std::string& ws_url, std::chrono::milliseconds timeout = std::chrono::milliseconds(5000));
    void Close(uint16_t code = 1000, const std::string& reason = "Normal Closure");
    bool Send(const std::string& text);

    // Callbacks
    void SetMessageHandler(MessageHandler handler);
    void SetStateHandler(StateHandler handler);
    void SetErrorHandler(ErrorHandler handler);

    // Query
    bool IsConnected() const;
    WebSocketState GetState() const;
    const std::string& GetUrl() const { return url_; }

private:
    void NetworkWorkerLoop();
    bool PerformHandshake(const std::string& host, int port, const std::string& path);
    bool SendFrame(uint8_t opcode, const uint8_t* payload, size_t length, bool mask = true);
    void HandleIncomingData(const std::vector<uint8_t>& buffer);

    std::string url_;
    int socket_fd_{-1};
    std::atomic<WebSocketState> state_{WebSocketState::DISCONNECTED};
    
    std::thread worker_thread_;
    std::atomic<bool> stop_worker_{false};
    
    MessageHandler message_handler_;
    StateHandler state_handler_;
    ErrorHandler error_handler_;
    
    mutable std::mutex send_mutex_;
    mutable std::mutex handler_mutex_;
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_WEBSOCKET_CLIENT_HPP
