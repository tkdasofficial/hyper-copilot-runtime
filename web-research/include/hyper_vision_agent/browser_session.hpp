#ifndef HYPER_VISION_AGENT_BROWSER_SESSION_HPP
#define HYPER_VISION_AGENT_BROWSER_SESSION_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/process_launcher.hpp"
#include "hyper_vision_agent/cdp_connection.hpp"
#include "hyper_vision_agent/target_session_manager.hpp"
#include "hyper_vision_agent/command_dispatcher.hpp"
#include "hyper_vision_agent/page.hpp"
#include <string>
#include <vector>
#include <memory>
#include <mutex>

namespace hyper_vision_agent {

class BrowserSession {
public:
    BrowserSession(std::unique_ptr<ProcessLauncher> launcher,
                   std::shared_ptr<CdpConnection> connection);
    ~BrowserSession();

    // Factory method
    static std::shared_ptr<BrowserSession> Create(const LaunchConfig& config = LaunchConfig{});

    // Page creation & management
    std::shared_ptr<Page> NewPage(const std::string& url = "about:blank");
    std::vector<std::shared_ptr<Page>> GetPages() const;
    std::shared_ptr<Page> GetActivePage() const;
    bool ClosePage(std::shared_ptr<Page> page);

    // Browser queries
    std::string GetBrowserVersion();
    std::string GetUserAgent();
    int GetProcessId() const;
    int GetPort() const;

    // Shutdown
    void Close();
    bool IsAlive() const;

private:
    std::unique_ptr<ProcessLauncher> launcher_;
    std::shared_ptr<CdpConnection> connection_;
    std::shared_ptr<TargetSessionManager> target_manager_;
    std::shared_ptr<CommandDispatcher> dispatcher_;

    mutable std::mutex pages_mutex_;
    std::vector<std::shared_ptr<Page>> pages_;
    std::shared_ptr<Page> active_page_;
    std::atomic<bool> is_closed_{false};
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_BROWSER_SESSION_HPP
