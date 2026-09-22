#ifndef HYPER_VISION_AGENT_PROCESS_LAUNCHER_HPP
#define HYPER_VISION_AGENT_PROCESS_LAUNCHER_HPP

#include "hyper_vision_agent/types.hpp"
#include <string>
#include <vector>
#include <memory>
#include <atomic>
#include <mutex>
#include <sys/types.h>

namespace hyper_vision_agent {

class ProcessLauncher {
public:
    explicit ProcessLauncher(LaunchConfig config = LaunchConfig{});
    ~ProcessLauncher();

    // Delete copy semantics, enable move semantics
    ProcessLauncher(const ProcessLauncher&) = delete;
    ProcessLauncher& operator=(const ProcessLauncher&) = delete;
    ProcessLauncher(ProcessLauncher&&) noexcept;
    ProcessLauncher& operator=(ProcessLauncher&&) noexcept;

    // Process lifecycle API
    bool Launch();
    void Terminate(std::chrono::milliseconds timeout = std::chrono::milliseconds(3000));
    void Kill();
    
    // Status queries
    bool IsRunning() const;
    const ProcessStatus& GetStatus() const { return status_; }
    int GetPort() const { return status_.port; }
    const std::string& GetWebSocketUrl() const { return status_.web_socket_debugger_url; }
    const std::string& GetUserDataDir() const { return status_.user_data_dir; }

    // Helpers
    static std::string DiscoverChromiumBinary();
    static int FindAvailablePort();

private:
    bool WaitForDebuggerReady(std::chrono::milliseconds timeout);
    void CleanupProfileDirectory();
    std::vector<std::string> BuildArgumentList() const;

    LaunchConfig config_;
    ProcessStatus status_;
    std::atomic<bool> is_running_{false};
    mutable std::mutex process_mutex_;
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_PROCESS_LAUNCHER_HPP
