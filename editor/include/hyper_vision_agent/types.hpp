#ifndef HYPER_VISION_AGENT_TYPES_HPP
#define HYPER_VISION_AGENT_TYPES_HPP

#include <string>
#include <vector>
#include <unordered_map>
#include <functional>
#include <memory>
#include <chrono>
#include <stdexcept>
#include <optional>
#include <cstdint>
#include <sstream>

namespace hyper_vision_agent {

// Engine Version and Identification
constexpr const char* ENGINE_NAME = "Hyper Vision Agent";
constexpr const char* ENGINE_VERSION = "1.0.0-core";

// Typedef aliases
using SessionId = std::string;
using TargetId = std::string;
using CommandId = uint64_t;

// Custom Exceptions
class EngineException : public std::runtime_error {
public:
    explicit EngineException(const std::string& msg) 
        : std::runtime_error("[HyperVisionAgent] " + msg) {}
};

class ProcessException : public EngineException {
public:
    explicit ProcessException(const std::string& msg) 
        : EngineException("Process Error: " + msg) {}
};

class CdpException : public EngineException {
public:
    int error_code;
    explicit CdpException(const std::string& msg, int code = -1) 
        : EngineException("CDP Error (" + std::to_string(code) + "): " + msg), error_code(code) {}
};

class TimeoutException : public EngineException {
public:
    explicit TimeoutException(const std::string& msg) 
        : EngineException("Timeout: " + msg) {}
};

// Process Configuration & State
struct LaunchConfig {
    std::string executable_path = "";  // Empty = auto-detect chromium / google-chrome
    int remote_debugging_port = 0;     // 0 = auto-assign ephemeral port
    std::string user_data_dir = "";    // Empty = isolated temp directory in /tmp
    bool headless = true;
    bool disable_gpu = true;
    bool no_sandbox = true;
    int window_width = 1920;
    int window_height = 1080;
    std::vector<std::string> extra_flags = {};
    std::chrono::milliseconds launch_timeout{10000};
};

struct ProcessStatus {
    pid_t pid = -1;
    int port = 0;
    std::string web_socket_debugger_url = "";
    std::string user_data_dir = "";
    bool is_running = false;
    std::chrono::steady_clock::time_point start_time;
};

// CDP Message Structures
struct CdpMessage {
    CommandId id = 0;
    std::string method = "";
    std::string params_json = "{}";
    std::string session_id = "";
};

struct CdpResponse {
    CommandId id = 0;
    bool success = false;
    std::string result_json = "{}";
    std::string error_message = "";
    int error_code = 0;
    std::string raw_json = "";
};

struct CdpEvent {
    std::string method = "";
    std::string params_json = "{}";
    std::string session_id = "";
    std::chrono::system_clock::time_point timestamp;
};

// Automation Specific Structures
struct NavigationResult {
    bool success = false;
    std::string url = "";
    int http_status = 200;
    std::string frame_id = "";
    std::chrono::milliseconds elapsed_time{0};
};

struct EvalResult {
    bool success = false;
    std::string type = "";
    std::string value_string = "";
    double value_number = 0.0;
    bool value_boolean = false;
    std::string raw_result_json = "";
    std::string error_description = "";
};

struct BoxModel {
    double x = 0.0;
    double y = 0.0;
    double width = 0.0;
    double height = 0.0;
};

struct ElementCoordinates {
    double x = 0.0;
    double y = 0.0;
    bool visible = false;
};

// Callback Signatures
using EventCallback = std::function<void(const CdpEvent&)>;
using MessageCallback = std::function<void(const std::string& raw_message)>;

} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_TYPES_HPP
