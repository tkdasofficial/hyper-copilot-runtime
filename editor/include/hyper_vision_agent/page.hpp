#ifndef HYPER_VISION_AGENT_PAGE_HPP
#define HYPER_VISION_AGENT_PAGE_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/cdp_connection.hpp"
#include "hyper_vision_agent/command_dispatcher.hpp"
#include <string>
#include <memory>
#include <future>
#include <mutex>
#include <condition_variable>

namespace hyper_vision_agent {

class Page {
public:
    Page(const TargetId& target_id, 
         const SessionId& session_id,
         std::shared_ptr<CdpConnection> connection,
         std::shared_ptr<CommandDispatcher> dispatcher);
    ~Page();

    // Prevent copies
    Page(const Page&) = delete;
    Page& operator=(const Page&) = delete;

    // Initialization
    bool Initialize();

    // High-Level Automation API
    NavigationResult Navigate(const std::string& url, std::chrono::milliseconds timeout = std::chrono::milliseconds(30000));
    void Reload();
    
    // Script Evaluation
    EvalResult EvaluateScript(const std::string& script);
    
    // DOM & Element Interaction
    int QuerySelector(const std::string& selector);
    std::vector<int> QuerySelectorAll(const std::string& selector);
    bool Click(const std::string& selector);
    bool ClickAt(double x, double y);
    bool Type(const std::string& selector, const std::string& text, int delay_ms = 10);
    bool Focus(const std::string& selector);
    
    // Wait loops
    bool WaitForSelector(const std::string& selector, std::chrono::milliseconds timeout = std::chrono::milliseconds(10000));
    bool WaitForNavigation(std::chrono::milliseconds timeout = std::chrono::milliseconds(30000));
    void Sleep(std::chrono::milliseconds duration);

    // Visual & State Extraction
    std::string CaptureScreenshotBase64(const std::string& format = "png", int quality = 80);
    std::string GetContent();
    std::string GetTitle();
    std::string GetUrl() const { return current_url_; }
    
    // Viewport & Emulation
    bool SetViewport(int width, int height, double scale = 1.0);

    // Metadata
    const TargetId& GetTargetId() const { return target_id_; }
    const SessionId& GetSessionId() const { return session_id_; }
    std::shared_ptr<CdpConnection> GetConnection() const { return connection_; }
    std::shared_ptr<CommandDispatcher> GetDispatcher() const { return dispatcher_; }
    bool IsClosed() const { return is_closed_; }
    void Close();

private:
    std::optional<ElementCoordinates> GetElementCenter(int node_id);
    void SetupEventHandlers();

    TargetId target_id_;
    SessionId session_id_;
    std::shared_ptr<CdpConnection> connection_;
    std::shared_ptr<CommandDispatcher> dispatcher_;

    std::string current_url_;
    bool is_closed_{false};
    
    // Lifecycle events
    std::atomic<bool> load_event_fired_{false};
    std::mutex nav_mutex_;
    std::condition_variable nav_cv_;
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_PAGE_HPP
