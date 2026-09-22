#include "hyper_vision_agent/target_session_manager.hpp"
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

TargetSessionManager::TargetSessionManager(std::shared_ptr<CdpConnection> connection)
    : connection_(connection) {}

TargetSessionManager::~TargetSessionManager() = default;

bool TargetSessionManager::Initialize() {
    if (!connection_ || !connection_->IsConnected()) {
        return false;
    }

    // Subscribe to Target lifecycle events
    connection_->SubscribeEvent("Target.targetCreated", [this](const CdpEvent& ev) {
        this->HandleTargetCreated(ev);
    });
    connection_->SubscribeEvent("Target.targetDestroyed", [this](const CdpEvent& ev) {
        this->HandleTargetDestroyed(ev);
    });
    connection_->SubscribeEvent("Target.targetInfoChanged", [this](const CdpEvent& ev) {
        this->HandleTargetInfoChanged(ev);
    });
    connection_->SubscribeEvent("Target.attachedToTarget", [this](const CdpEvent& ev) {
        this->HandleAttachedToTarget(ev);
    });
    connection_->SubscribeEvent("Target.detachedFromTarget", [this](const CdpEvent& ev) {
        this->HandleDetachedFromTarget(ev);
    });

    // Enable target discovery
    try {
        CdpResponse resp = connection_->SendCommand("Target.setDiscoverTargets", "{\"discover\":true}");
        return resp.success;
    } catch (...) {
        return false;
    }
}

TargetId TargetSessionManager::CreateTarget(const std::string& url, [[maybe_unused]] int width, [[maybe_unused]] int height) {
    std::ostringstream params;
    params << "{\"url\":\"" << url << "\"}";
    
    CdpResponse resp = connection_->SendCommand("Target.createTarget", params.str());
    if (!resp.success) {
        throw CdpException("Failed to create target: " + resp.error_message);
    }

    std::string target_id = ExtractField(resp.result_json, "targetId");
    if (target_id.empty()) {
        throw CdpException("Target ID missing in createTarget response");
    }

    std::lock_guard<std::mutex> lock(targets_mutex_);
    TargetInfo info;
    info.target_id = target_id;
    info.url = url;
    info.type = "page";
    targets_[target_id] = info;

    return target_id;
}

SessionId TargetSessionManager::AttachToTarget(const TargetId& target_id) {
    std::ostringstream params;
    params << "{\"targetId\":\"" << target_id << "\",\"flatten\":true}";

    CdpResponse resp = connection_->SendCommand("Target.attachToTarget", params.str());
    if (!resp.success) {
        throw CdpException("Failed to attach to target " + target_id + ": " + resp.error_message);
    }

    std::string session_id = ExtractField(resp.result_json, "sessionId");
    if (session_id.empty()) {
        throw CdpException("Session ID missing in attachToTarget response");
    }

    std::lock_guard<std::mutex> lock(targets_mutex_);
    session_to_target_[session_id] = target_id;
    target_to_session_[target_id] = session_id;
    if (targets_.find(target_id) != targets_.end()) {
        targets_[target_id].attached = true;
        targets_[target_id].session_id = session_id;
    }

    return session_id;
}

bool TargetSessionManager::DetachFromTarget(const SessionId& session_id) {
    std::ostringstream params;
    params << "{\"sessionId\":\"" << session_id << "\"}";

    CdpResponse resp = connection_->SendCommand("Target.detachFromTarget", params.str());
    {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        auto it = session_to_target_.find(session_id);
        if (it != session_to_target_.end()) {
            TargetId target_id = it->second;
            target_to_session_.erase(target_id);
            if (targets_.find(target_id) != targets_.end()) {
                targets_[target_id].attached = false;
                targets_[target_id].session_id = "";
            }
            session_to_target_.erase(it);
        }
    }
    return resp.success;
}

bool TargetSessionManager::CloseTarget(const TargetId& target_id) {
    std::ostringstream params;
    params << "{\"targetId\":\"" << target_id << "\"}";

    CdpResponse resp = connection_->SendCommand("Target.closeTarget", params.str());
    {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        auto s_it = target_to_session_.find(target_id);
        if (s_it != target_to_session_.end()) {
            session_to_target_.erase(s_it->second);
            target_to_session_.erase(s_it);
        }
        targets_.erase(target_id);
    }
    return resp.success;
}

bool TargetSessionManager::ActivateTarget(const TargetId& target_id) {
    std::ostringstream params;
    params << "{\"targetId\":\"" << target_id << "\"}";
    CdpResponse resp = connection_->SendCommand("Target.activateTarget", params.str());
    return resp.success;
}

std::vector<TargetInfo> TargetSessionManager::GetTargetList() const {
    std::lock_guard<std::mutex> lock(targets_mutex_);
    std::vector<TargetInfo> list;
    list.reserve(targets_.size());
    for (const auto& [_, info] : targets_) {
        list.push_back(info);
    }
    return list;
}

std::optional<TargetInfo> TargetSessionManager::GetTarget(const TargetId& target_id) const {
    std::lock_guard<std::mutex> lock(targets_mutex_);
    auto it = targets_.find(target_id);
    if (it != targets_.end()) {
        return it->second;
    }
    return std::nullopt;
}

std::optional<SessionId> TargetSessionManager::GetSessionForTarget(const TargetId& target_id) const {
    std::lock_guard<std::mutex> lock(targets_mutex_);
    auto it = target_to_session_.find(target_id);
    if (it != target_to_session_.end()) {
        return it->second;
    }
    return std::nullopt;
}

std::optional<TargetId> TargetSessionManager::GetTargetForSession(const SessionId& session_id) const {
    std::lock_guard<std::mutex> lock(targets_mutex_);
    auto it = session_to_target_.find(session_id);
    if (it != session_to_target_.end()) {
        return it->second;
    }
    return std::nullopt;
}

void TargetSessionManager::HandleTargetCreated(const CdpEvent& event) {
    std::string target_id = ExtractField(event.params_json, "targetId");
    std::string type = ExtractField(event.params_json, "type");
    std::string title = ExtractField(event.params_json, "title");
    std::string url = ExtractField(event.params_json, "url");

    if (!target_id.empty()) {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        TargetInfo info;
        info.target_id = target_id;
        info.type = type;
        info.title = title;
        info.url = url;
        targets_[target_id] = info;
    }
}

void TargetSessionManager::HandleTargetDestroyed(const CdpEvent& event) {
    std::string target_id = ExtractField(event.params_json, "targetId");
    if (!target_id.empty()) {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        auto s_it = target_to_session_.find(target_id);
        if (s_it != target_to_session_.end()) {
            session_to_target_.erase(s_it->second);
            target_to_session_.erase(s_it);
        }
        targets_.erase(target_id);
    }
}

void TargetSessionManager::HandleTargetInfoChanged(const CdpEvent& event) {
    std::string target_id = ExtractField(event.params_json, "targetId");
    if (!target_id.empty()) {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        auto it = targets_.find(target_id);
        if (it != targets_.end()) {
            it->second.title = ExtractField(event.params_json, "title");
            it->second.url = ExtractField(event.params_json, "url");
        }
    }
}

void TargetSessionManager::HandleAttachedToTarget(const CdpEvent& event) {
    std::string session_id = ExtractField(event.params_json, "sessionId");
    std::string target_id = ExtractField(event.params_json, "targetId");

    if (!session_id.empty() && !target_id.empty()) {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        session_to_target_[session_id] = target_id;
        target_to_session_[target_id] = session_id;
        if (targets_.find(target_id) != targets_.end()) {
            targets_[target_id].attached = true;
            targets_[target_id].session_id = session_id;
        }
    }
}

void TargetSessionManager::HandleDetachedFromTarget(const CdpEvent& event) {
    std::string session_id = ExtractField(event.params_json, "sessionId");
    if (!session_id.empty()) {
        std::lock_guard<std::mutex> lock(targets_mutex_);
        auto it = session_to_target_.find(session_id);
        if (it != session_to_target_.end()) {
            TargetId target_id = it->second;
            target_to_session_.erase(target_id);
            if (targets_.find(target_id) != targets_.end()) {
                targets_[target_id].attached = false;
                targets_[target_id].session_id = "";
            }
            session_to_target_.erase(it);
        }
    }
}

} // namespace hyper_vision_agent
