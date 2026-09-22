#include "hyper_vision_agent/engine.hpp"
#include <algorithm>

namespace hyper_vision_agent {

Engine::Engine() = default;

Engine::~Engine() {
    Shutdown();
}

Engine& Engine::Instance() {
    static Engine instance;
    return instance;
}

bool Engine::Initialize(const LaunchConfig& default_config) {
    default_config_ = default_config;
    initialized_ = true;
    return true;
}

void Engine::Shutdown() {
    std::lock_guard<std::mutex> lock(sessions_mutex_);
    for (auto& session : active_sessions_) {
        if (session) {
            session->Close();
        }
    }
    active_sessions_.clear();
    initialized_ = false;
}

std::shared_ptr<BrowserSession> Engine::Launch(const LaunchConfig& config) {
    LaunchConfig effective_config = initialized_ ? default_config_ : config;
    if (!config.executable_path.empty()) {
        effective_config.executable_path = config.executable_path;
    }
    if (config.remote_debugging_port != 0) {
        effective_config.remote_debugging_port = config.remote_debugging_port;
    }
    if (config.headless != effective_config.headless) {
        effective_config.headless = config.headless;
    }

    auto session = BrowserSession::Create(effective_config);

    {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        active_sessions_.push_back(session);
    }

    return session;
}

std::shared_ptr<BrowserSession> Engine::Connect(const std::string& ws_url) {
    auto connection = std::make_shared<CdpConnection>();
    if (!connection->Connect(ws_url)) {
        throw CdpException("Failed to connect to existing WebSocket at " + ws_url);
    }

    auto session = std::make_shared<BrowserSession>(nullptr, connection);

    {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        active_sessions_.push_back(session);
    }

    return session;
}

void Engine::CloseSession(std::shared_ptr<BrowserSession> session) {
    if (!session) return;

    session->Close();

    std::lock_guard<std::mutex> lock(sessions_mutex_);
    auto it = std::find(active_sessions_.begin(), active_sessions_.end(), session);
    if (it != active_sessions_.end()) {
        active_sessions_.erase(it);
    }
}

size_t Engine::ActiveSessionCount() const {
    std::lock_guard<std::mutex> lock(sessions_mutex_);
    return active_sessions_.size();
}

std::vector<std::shared_ptr<BrowserSession>> Engine::GetActiveSessions() const {
    std::lock_guard<std::mutex> lock(sessions_mutex_);
    return active_sessions_;
}

std::string Engine::GetVersion() {
    return ENGINE_VERSION;
}

std::string Engine::GetEngineBrand() {
    return ENGINE_NAME;
}

} // namespace hyper_vision_agent
