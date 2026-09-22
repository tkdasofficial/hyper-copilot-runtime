#ifndef HYPER_VISION_AGENT_TARGET_SESSION_MANAGER_HPP
#define HYPER_VISION_AGENT_TARGET_SESSION_MANAGER_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/cdp_connection.hpp"
#include <string>
#include <vector>
#include <unordered_map>
#include <mutex>
#include <memory>

namespace hyper_vision_agent {

struct TargetInfo {
    TargetId target_id;
    std::string type;
    std::string title;
    std::string url;
    bool attached = false;
    SessionId session_id;
};

class TargetSessionManager {
public:
    explicit TargetSessionManager(std::shared_ptr<CdpConnection> connection);
    ~TargetSessionManager();

    // Initialization: discover targets and listen for target lifecycle events
    bool Initialize();

    // Target Management
    TargetId CreateTarget(const std::string& url = "about:blank", int width = 1920, int height = 1080);
    SessionId AttachToTarget(const TargetId& target_id);
    bool DetachFromTarget(const SessionId& session_id);
    bool CloseTarget(const TargetId& target_id);
    bool ActivateTarget(const TargetId& target_id);

    // Queries
    std::vector<TargetInfo> GetTargetList() const;
    std::optional<TargetInfo> GetTarget(const TargetId& target_id) const;
    std::optional<SessionId> GetSessionForTarget(const TargetId& target_id) const;
    std::optional<TargetId> GetTargetForSession(const SessionId& session_id) const;

private:
    void HandleTargetCreated(const CdpEvent& event);
    void HandleTargetDestroyed(const CdpEvent& event);
    void HandleTargetInfoChanged(const CdpEvent& event);
    void HandleAttachedToTarget(const CdpEvent& event);
    void HandleDetachedFromTarget(const CdpEvent& event);

    std::shared_ptr<CdpConnection> connection_;
    mutable std::mutex targets_mutex_;
    std::unordered_map<TargetId, TargetInfo> targets_;
    std::unordered_map<SessionId, TargetId> session_to_target_;
    std::unordered_map<TargetId, SessionId> target_to_session_;
};

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_TARGET_SESSION_MANAGER_HPP
