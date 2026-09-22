#include "hyper_vision_agent/process_launcher.hpp"
#include <iostream>
#include <sstream>
#include <fstream>
#include <chrono>
#include <thread>
#include <cstring>
#include <cstdlib>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <signal.h>
#include <fcntl.h>
#include <filesystem>

namespace hyper_vision_agent {

namespace fs = std::filesystem;

ProcessLauncher::ProcessLauncher(LaunchConfig config)
    : config_(std::move(config)) {
    if (config_.executable_path.empty()) {
        config_.executable_path = DiscoverChromiumBinary();
    }
}

ProcessLauncher::~ProcessLauncher() {
    if (is_running_) {
        Terminate();
    }
    CleanupProfileDirectory();
}

ProcessLauncher::ProcessLauncher(ProcessLauncher&& other) noexcept {
    std::lock_guard<std::mutex> lock(other.process_mutex_);
    config_ = std::move(other.config_);
    status_ = std::move(other.status_);
    is_running_.store(other.is_running_.load());
    other.is_running_ = false;
    other.status_.pid = -1;
}

ProcessLauncher& ProcessLauncher::operator=(ProcessLauncher&& other) noexcept {
    if (this != &other) {
        if (is_running_) {
            Terminate();
        }
        std::scoped_lock lock(process_mutex_, other.process_mutex_);
        config_ = std::move(other.config_);
        status_ = std::move(other.status_);
        is_running_.store(other.is_running_.load());
        other.is_running_ = false;
        other.status_.pid = -1;
    }
    return *this;
}

std::string ProcessLauncher::DiscoverChromiumBinary() {
    const std::vector<std::string> candidates = {
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    };

    for (const auto& path : candidates) {
        if (access(path.c_str(), X_OK) == 0) {
            return path;
        }
    }
    return "/usr/bin/chromium";
}

int ProcessLauncher::FindAvailablePort() {
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) {
        return 9222;
    }

    struct sockaddr_in serv_addr;
    std::memset(&serv_addr, 0, sizeof(serv_addr));
    serv_addr.sin_family = AF_INET;
    serv_addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    serv_addr.sin_port = htons(0); // auto-assign

    if (bind(sock, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) < 0) {
        close(sock);
        return 9222;
    }

    socklen_t len = sizeof(serv_addr);
    if (getsockname(sock, (struct sockaddr*)&serv_addr, &len) == -1) {
        close(sock);
        return 9222;
    }

    int port = ntohs(serv_addr.sin_port);
    close(sock);
    return port;
}

std::vector<std::string> ProcessLauncher::BuildArgumentList() const {
    std::vector<std::string> args;
    args.push_back(config_.executable_path);

    if (config_.headless) {
        args.push_back("--headless=new");
    }
    args.push_back("--remote-debugging-port=" + std::to_string(status_.port));
    args.push_back("--remote-allow-origins=*");

    if (!status_.user_data_dir.empty()) {
        args.push_back("--user-data-dir=" + status_.user_data_dir);
    }

    if (config_.no_sandbox) {
        args.push_back("--no-sandbox");
        args.push_back("--disable-setuid-sandbox");
    }

    if (config_.disable_gpu) {
        args.push_back("--disable-gpu");
        args.push_back("--disable-software-rasterizer");
    }

    // High performance stateless flags
    args.push_back("--no-zygote");
    args.push_back("--disable-crash-reporter");
    args.push_back("--disable-breakpad");
    args.push_back("--disable-dev-shm-usage");
    args.push_back("--disable-background-networking");
    args.push_back("--disable-default-apps");
    args.push_back("--disable-extensions");
    args.push_back("--disable-sync");
    args.push_back("--disable-translate");
    args.push_back("--hide-scrollbars");
    args.push_back("--metrics-recording-only");
    args.push_back("--mute-audio");
    args.push_back("--no-first-run");
    args.push_back("--safebrowsing-disable-auto-update");
    args.push_back("--window-size=" + std::to_string(config_.window_width) + "," + std::to_string(config_.window_height));

    for (const auto& flag : config_.extra_flags) {
        args.push_back(flag);
    }

    args.push_back("about:blank");
    return args;
}

bool ProcessLauncher::Launch() {
    std::lock_guard<std::mutex> lock(process_mutex_);

    if (is_running_) {
        return true;
    }

    // Assign port
    if (config_.remote_debugging_port == 0) {
        status_.port = FindAvailablePort();
    } else {
        status_.port = config_.remote_debugging_port;
    }

    // Isolated user-data-dir
    if (config_.user_data_dir.empty()) {
        char dir_template[] = "/tmp/hyper_vision_agent_profile_XXXXXX";
        char* created = mkdtemp(dir_template);
        if (created) {
            status_.user_data_dir = created;
        } else {
            status_.user_data_dir = "/tmp/hyper_vision_agent_profile_" + std::to_string(getpid());
            fs::create_directories(status_.user_data_dir);
        }
    } else {
        status_.user_data_dir = config_.user_data_dir;
        fs::create_directories(status_.user_data_dir);
    }

    std::vector<std::string> args = BuildArgumentList();
    std::vector<char*> c_args;
    c_args.reserve(args.size() + 1);
    for (auto& arg : args) {
        c_args.push_back(const_cast<char*>(arg.c_str()));
    }
    c_args.push_back(nullptr);

    pid_t pid = fork();
    if (pid < 0) {
        throw ProcessException("Failed to fork child process for Chromium execution");
    }

    if (pid == 0) {
        // Child process
        // Redirect stdio to /dev/null unless debugging
        int null_fd = open("/dev/null", O_RDWR);
        if (null_fd >= 0) {
            dup2(null_fd, STDIN_FILENO);
            dup2(null_fd, STDOUT_FILENO);
            dup2(null_fd, STDERR_FILENO);
            close(null_fd);
        }

        execvp(c_args[0], c_args.data());
        // If execvp fails
        std::exit(127);
    }

    // Parent process
    status_.pid = pid;
    status_.start_time = std::chrono::steady_clock::now();
    status_.is_running = true;
    is_running_ = true;

    // Wait for debugger port to be open & responsive
    if (!WaitForDebuggerReady(config_.launch_timeout)) {
        Terminate();
        throw ProcessException("Timed out waiting for Chromium CDP endpoint on port " + std::to_string(status_.port));
    }

    return true;
}

bool ProcessLauncher::WaitForDebuggerReady(std::chrono::milliseconds timeout) {
    auto deadline = std::chrono::steady_clock::now() + timeout;

    while (std::chrono::steady_clock::now() < deadline) {
        int sock = socket(AF_INET, SOCK_STREAM, 0);
        if (sock >= 0) {
            struct sockaddr_in serv_addr;
            std::memset(&serv_addr, 0, sizeof(serv_addr));
            serv_addr.sin_family = AF_INET;
            serv_addr.sin_port = htons(status_.port);
            inet_pton(AF_INET, "127.0.0.1", &serv_addr.sin_addr);

            if (connect(sock, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) == 0) {
                // Set short socket timeout so recv doesn't hang on persistent HTTP connections
                struct timeval tv;
                tv.tv_sec = 0;
                tv.tv_usec = 300000; // 300ms
                setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));

                // Connected! Send HTTP request for /json/version
                std::string req = "GET /json/version HTTP/1.1\r\nHost: 127.0.0.1:" + std::to_string(status_.port) + "\r\nConnection: close\r\n\r\n";
                send(sock, req.c_str(), req.length(), 0);

                char buffer[4096];
                std::string response;
                ssize_t bytes_read = 0;
                while ((bytes_read = recv(sock, buffer, sizeof(buffer) - 1, 0)) > 0) {
                    buffer[bytes_read] = '\0';
                    response += buffer;
                    if (response.find("\"webSocketDebuggerUrl\"") != std::string::npos) {
                        break;
                    }
                }
                close(sock);

                // Extract webSocketDebuggerUrl
                const std::string ws_key = "\"webSocketDebuggerUrl\": \"";
                size_t pos = response.find(ws_key);
                if (pos != std::string::npos) {
                    size_t start = pos + ws_key.length();
                    size_t end = response.find("\"", start);
                    if (end != std::string::npos) {
                        status_.web_socket_debugger_url = response.substr(start, end - start);
                        return true;
                    }
                }
            } else {
                close(sock);
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    return false;
}

bool ProcessLauncher::IsRunning() const {
    if (!is_running_ || status_.pid <= 0) {
        return false;
    }
    int status = 0;
    pid_t result = waitpid(status_.pid, &status, WNOHANG);
    if (result == 0) {
        return true; // Still running
    }
    return false;
}

void ProcessLauncher::Terminate(std::chrono::milliseconds timeout) {
    std::lock_guard<std::mutex> lock(process_mutex_);
    if (!is_running_ || status_.pid <= 0) {
        return;
    }

    // Try graceful SIGTERM first
    kill(status_.pid, SIGTERM);

    auto deadline = std::chrono::steady_clock::now() + timeout;
    bool exited = false;
    while (std::chrono::steady_clock::now() < deadline) {
        int status = 0;
        pid_t result = waitpid(status_.pid, &status, WNOHANG);
        if (result == status_.pid) {
            exited = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    if (!exited) {
        // Force kill with SIGKILL
        kill(status_.pid, SIGKILL);
        waitpid(status_.pid, nullptr, 0);
    }

    is_running_ = false;
    status_.is_running = false;
    status_.pid = -1;
    CleanupProfileDirectory();
}

void ProcessLauncher::Kill() {
    std::lock_guard<std::mutex> lock(process_mutex_);
    if (status_.pid > 0) {
        kill(status_.pid, SIGKILL);
        waitpid(status_.pid, nullptr, 0);
    }
    is_running_ = false;
    status_.is_running = false;
    status_.pid = -1;
    CleanupProfileDirectory();
}

void ProcessLauncher::CleanupProfileDirectory() {
    if (!status_.user_data_dir.empty() && fs::exists(status_.user_data_dir)) {
        try {
            fs::remove_all(status_.user_data_dir);
        } catch (...) {
            // Suppress cleanup error
        }
    }
}

} // namespace hyper_vision_agent
