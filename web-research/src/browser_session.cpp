#include "hyper_vision_agent/browser_session.hpp"
#include <iostream>
#include <regex>

namespace hyper_vision_agent {

namespace {

std::string ExtractField(const std::string& json, const std::string& key) {
    std::string pattern = "\"" + key + "\"\\s*:\\s*\"([^\"]*)\"";
    std::regex re(pattern);
    std::smatch match;
    if (std::regex_search(json, match, re) && match.size() > 1) {
        return match[1].str();
    }
    return "";
}

} // namespace

BrowserSession::BrowserSession(std::unique_ptr<ProcessLauncher> launcher,
                               std::shared_ptr<CdpConnection> connection)
    : launcher_(std::move(launcher)),
      connection_(connection),
      target_manager_(std::make_shared<TargetSessionManager>(connection_)),
      dispatcher_(std::make_shared<CommandDispatcher>(connection_)) {
    target_manager_->Initialize();
}

BrowserSession::~BrowserSession() {
    Close();
}

std::shared_ptr<BrowserSession> BrowserSession::Create(const LaunchConfig& config) {
    auto launcher = std::make_unique<ProcessLauncher>(config);
    if (!launcher->Launch()) {
        throw ProcessException("Failed to launch Chromium headless process");
    }

    std::string ws_url = launcher->GetWebSocketUrl();
    if (ws_url.empty()) {
        throw ProcessException("Empty WebSocket URL returned from Chromium process");
    }

    auto connection = std::make_shared<CdpConnection>();
    if (!connection->Connect(ws_url)) {
        launcher->Terminate();
        throw CdpException("Failed to connect WebSocket to Chromium at " + ws_url);
    }

    return std::make_shared<BrowserSession>(std::move(launcher), connection);
}

std::shared_ptr<Page> BrowserSession::NewPage(const std::string& url) {
    if (is_closed_) {
        throw EngineException("Cannot create new page in a closed BrowserSession");
    }

    TargetId target_id = target_manager_->CreateTarget(url);
    SessionId session_id = target_manager_->AttachToTarget(target_id);

    auto page = std::make_shared<Page>(target_id, session_id, connection_, dispatcher_);
    page->Initialize();

    {
        std::lock_guard<std::mutex> lock(pages_mutex_);
        pages_.push_back(page);
        active_page_ = page;
    }

    return page;
}

std::vector<std::shared_ptr<Page>> BrowserSession::GetPages() const {
    std::lock_guard<std::mutex> lock(pages_mutex_);
    return pages_;
}

std::shared_ptr<Page> BrowserSession::GetActivePage() const {
    std::lock_guard<std::mutex> lock(pages_mutex_);
    return active_page_;
}

bool BrowserSession::ClosePage(std::shared_ptr<Page> page) {
    if (!page) return false;

    TargetId target_id = page->GetTargetId();
    SessionId session_id = page->GetSessionId();

    target_manager_->DetachFromTarget(session_id);
    target_manager_->CloseTarget(target_id);
    page->Close();

    std::lock_guard<std::mutex> lock(pages_mutex_);
    for (auto it = pages_.begin(); it != pages_.end(); ++it) {
        if (*it == page) {
            pages_.erase(it);
            break;
        }
    }
    if (active_page_ == page) {
        active_page_ = pages_.empty() ? nullptr : pages_.back();
    }
    return true;
}

std::string BrowserSession::GetBrowserVersion() {
    CdpResponse resp = dispatcher_->Dispatch("Browser.getVersion");
    if (resp.success) {
        return ExtractField(resp.result_json, "product");
    }
    return "Chromium Headless";
}

std::string BrowserSession::GetUserAgent() {
    CdpResponse resp = dispatcher_->Dispatch("Browser.getVersion");
    if (resp.success) {
        return ExtractField(resp.result_json, "userAgent");
    }
    return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HyperVisionAgent";
}

int BrowserSession::GetProcessId() const {
    return launcher_ ? launcher_->GetStatus().pid : -1;
}

int BrowserSession::GetPort() const {
    return launcher_ ? launcher_->GetPort() : 0;
}

void BrowserSession::Close() {
    if (is_closed_) return;
    is_closed_ = true;

    {
        std::lock_guard<std::mutex> lock(pages_mutex_);
        for (auto& p : pages_) {
            p->Close();
        }
        pages_.clear();
        active_page_ = nullptr;
    }

    if (connection_) {
        connection_->Disconnect();
    }

    if (launcher_) {
        launcher_->Terminate();
    }
}

bool BrowserSession::IsAlive() const {
    return !is_closed_ && launcher_ && launcher_->IsRunning();
}

} // namespace hyper_vision_agent
