#ifndef HYPER_VISION_AGENT_ENGINE_HPP
#define HYPER_VISION_AGENT_ENGINE_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/browser_session.hpp"
#include <string>
#include <memory>
#include <vector>
#include <mutex>

namespace hyper_vision_agent {

class Engine {
public:
    Engine();
    ~Engine();

    // Singleton / Global instance accessor if needed
    static Engine& Instance();

    // Lifecycle
    bool Initialize(const LaunchConfig& default_config = LaunchConfig{});
    void Shutdown();

    // Session Management
    std::shared_ptr<BrowserSession> Launch(const LaunchConfig& config = LaunchConfig{});
    std::shared_ptr<BrowserSession> Connect(const std::string& ws_url);
    void CloseSession(std::shared_ptr<BrowserSession> session);
    
    // Status
    size_t ActiveSessionCount() const;
    std::vector<std::shared_ptr<BrowserSession>> GetActiveSessions() const;
    
    static std::string GetVersion();
    static std::string GetEngineBrand();

private:
    LaunchConfig default_config_;
    mutable std::mutex sessions_mutex_;
    std::vector<std::shared_ptr<BrowserSession>> active_sessions_;
    std::atomic<bool> initialized_{false};
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_ENGINE_HPP
