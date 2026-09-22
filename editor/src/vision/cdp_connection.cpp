#include "hyper_vision_agent/cdp_connection.hpp"
#include <iostream>
#include <sstream>
#include <regex>

namespace hyper_vision_agent {

namespace {

// Lightweight fast JSON field extraction without external library dependencies
std::string ExtractJsonString(const std::string& json, const std::string& key) {
    std::string pattern = "\"" + key + "\"\\s*:\\s*\"([^\"]*)\"";
    std::regex re(pattern);
    std::smatch match;
    if (std::regex_search(json, match, re) && match.size() > 1) {
        return match[1].str();
    }
    return "";
}

int64_t ExtractJsonInt(const std::string& json, const std::string& key, int64_t default_val = -1) {
    std::string pattern = "\"" + key + "\"\\s*:\\s*(-?\\d+)";
    std::regex re(pattern);
    std::smatch match;
    if (std::regex_search(json, match, re) && match.size() > 1) {
        return std::stoll(match[1].str());
    }
    return default_val;
}

std::string ExtractJsonObject(const std::string& json, const std::string& key) {
    std::string search_key = "\"" + key + "\"";
    size_t key_pos = 0;
    while ((key_pos = json.find(search_key, key_pos)) != std::string::npos) {
        size_t after_key = key_pos + search_key.length();
        size_t colon_pos = json.find_first_not_of(" \t\r\n", after_key);
        if (colon_pos != std::string::npos && json[colon_pos] == ':') {
            size_t val_start = json.find_first_not_of(" \t\r\n", colon_pos + 1);
            if (val_start == std::string::npos) return "";

            char open_char = json[val_start];
            if (open_char == '{') {
                int depth = 0;
                for (size_t i = val_start; i < json.size(); ++i) {
                    if (json[i] == '{') depth++;
                    else if (json[i] == '}') {
                        depth--;
                        if (depth == 0) {
                            return json.substr(val_start, i - val_start + 1);
                        }
                    }
                }
            } else if (open_char == '[') {
                int depth = 0;
                for (size_t i = val_start; i < json.size(); ++i) {
                    if (json[i] == '[') depth++;
                    else if (json[i] == ']') {
                        depth--;
                        if (depth == 0) {
                            return json.substr(val_start, i - val_start + 1);
                        }
                    }
                }
            } else if (open_char == '"') {
                size_t end_quote = json.find('"', val_start + 1);
                if (end_quote != std::string::npos) {
                    return json.substr(val_start, end_quote - val_start + 1);
                }
            } else {
                size_t end_val = json.find_first_of(",}\r\n", val_start);
                if (end_val != std::string::npos) {
                    return json.substr(val_start, end_val - val_start);
                }
            }
            return "";
        }
        key_pos = after_key;
    }
    return "";
}

} // namespace

CdpConnection::CdpConnection()
    : ws_client_(std::make_unique<WebSocketClient>()) {
    ws_client_->SetMessageHandler([this](const std::string& msg) {
        this->OnMessageReceived(msg);
    });
    ws_client_->SetStateHandler([this](WebSocketState state) {
        this->OnStateChanged(state);
    });
    ws_client_->SetErrorHandler([this](const std::string& err) {
        this->OnError(err);
    });
}

CdpConnection::~CdpConnection() {
    Disconnect();
}

bool CdpConnection::Connect(const std::string& ws_url, std::chrono::milliseconds timeout) {
    return ws_client_->Connect(ws_url, timeout);
}

void CdpConnection::Disconnect() {
    if (ws_client_) {
        ws_client_->Close();
    }
    
    // Fail any pending commands
    std::lock_guard<std::mutex> lock(pending_mutex_);
    for (auto& [id, pending] : pending_commands_) {
        CdpResponse resp;
        resp.id = id;
        resp.success = false;
        resp.error_message = "Connection disconnected while command was pending";
        pending->promise.set_value(resp);
    }
    pending_commands_.clear();
}

bool CdpConnection::IsConnected() const {
    return ws_client_ && ws_client_->IsConnected();
}

std::future<CdpResponse> CdpConnection::SendCommandAsync(const std::string& method,
                                                        const std::string& params_json,
                                                        const std::string& session_id) {
    CommandId id = next_command_id_++;
    auto pending = std::make_shared<PendingCommand>();
    pending->method = method;
    pending->sent_at = std::chrono::steady_clock::now();
    std::future<CdpResponse> future = pending->promise.get_future();

    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        pending_commands_[id] = pending;
    }

    std::ostringstream payload;
    payload << "{\"id\":" << id << ",\"method\":\"" << method << "\"";
    if (!params_json.empty() && params_json != "{}") {
        payload << ",\"params\":" << params_json;
    } else {
        payload << ",\"params\":{}";
    }
    if (!session_id.empty()) {
        payload << ",\"sessionId\":\"" << session_id << "\"";
    }
    payload << "}";

    if (!ws_client_->Send(payload.str())) {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        pending_commands_.erase(id);
        CdpResponse resp;
        resp.id = id;
        resp.success = false;
        resp.error_message = "Failed to send WebSocket payload";
        pending->promise.set_value(resp);
    }

    return future;
}

CdpResponse CdpConnection::SendCommand(const std::string& method,
                                      const std::string& params_json,
                                      const std::string& session_id,
                                      std::chrono::milliseconds timeout) {
    auto future = SendCommandAsync(method, params_json, session_id);
    if (future.wait_for(timeout) == std::future_status::ready) {
        return future.get();
    }

    throw TimeoutException("CDP Command '" + method + "' timed out after " + 
                           std::to_string(timeout.count()) + "ms");
}

void CdpConnection::SubscribeEvent(const std::string& method, EventCallback callback) {
    std::lock_guard<std::mutex> lock(event_mutex_);
    event_listeners_[method].push_back(std::move(callback));
}

void CdpConnection::UnsubscribeEvent(const std::string& method) {
    std::lock_guard<std::mutex> lock(event_mutex_);
    event_listeners_.erase(method);
}

void CdpConnection::SetDefaultEventHandler(EventCallback callback) {
    std::lock_guard<std::mutex> lock(event_mutex_);
    default_event_handler_ = std::move(callback);
}

void CdpConnection::OnMessageReceived(const std::string& raw_message) {
    // Check if this is a response to a command (has "id")
    int64_t id = ExtractJsonInt(raw_message, "id", -1);
    if (id > 0) {
        std::shared_ptr<PendingCommand> pending;
        {
            std::lock_guard<std::mutex> lock(pending_mutex_);
            auto it = pending_commands_.find(static_cast<CommandId>(id));
            if (it != pending_commands_.end()) {
                pending = it->second;
                pending_commands_.erase(it);
            }
        }

        if (pending) {
            CdpResponse resp;
            resp.id = static_cast<CommandId>(id);
            resp.raw_json = raw_message;

            std::string err_obj = ExtractJsonObject(raw_message, "error");
            if (!err_obj.empty()) {
                resp.success = false;
                resp.error_message = ExtractJsonString(err_obj, "message");
                resp.error_code = static_cast<int>(ExtractJsonInt(err_obj, "code", -1));
            } else {
                resp.success = true;
                resp.result_json = ExtractJsonObject(raw_message, "result");
                if (resp.result_json.empty()) {
                    resp.result_json = "{}";
                }
            }
            pending->promise.set_value(resp);
        }
        return;
    }

    // Otherwise, this is a CDP Event (has "method")
    std::string method = ExtractJsonString(raw_message, "method");
    if (!method.empty()) {
        CdpEvent event;
        event.method = method;
        event.params_json = ExtractJsonObject(raw_message, "params");
        event.session_id = ExtractJsonString(raw_message, "sessionId");
        event.timestamp = std::chrono::system_clock::now();

        std::vector<EventCallback> callbacks;
        EventCallback def_handler;
        {
            std::lock_guard<std::mutex> lock(event_mutex_);
            auto it = event_listeners_.find(method);
            if (it != event_listeners_.end()) {
                callbacks = it->second;
            }
            def_handler = default_event_handler_;
        }

        for (const auto& cb : callbacks) {
            if (cb) cb(event);
        }
        if (def_handler) {
            def_handler(event);
        }
    }
}

void CdpConnection::OnStateChanged(WebSocketState state) {
    if (state == WebSocketState::CLOSED || state == WebSocketState::FAILED) {
        Disconnect();
    }
}

void CdpConnection::OnError([[maybe_unused]] const std::string& err) {
    // Log or forward
}

} // namespace hyper_vision_agent
