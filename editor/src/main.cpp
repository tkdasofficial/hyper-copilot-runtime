#include "core/editor.hpp"
#include "parsers/json_parser.hpp"
#include "utils/logger.hpp"

#include <iostream>
#include <string>
#include <vector>
#include <filesystem>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <cstring>
#include <csignal>

static volatile bool g_running = true;
void sigHandler(int) {
    g_running = false;
}

int runServer(int port) {
    signal(SIGINT, sigHandler);
    signal(SIGTERM, sigHandler);

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        std::cerr << "Failed to create socket\n";
        return 1;
    }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in address;
    std::memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr*)&address, sizeof(address)) < 0) {
        std::cerr << "Failed to bind to port " << port << "\n";
        close(server_fd);
        return 1;
    }

    if (listen(server_fd, 10) < 0) {
        std::cerr << "Failed to listen on socket\n";
        close(server_fd);
        return 1;
    }

    std::cout << "\033[1m\033[32m[HyperEditor Daemon]\033[0m Native C++ Headless Service listening on port " << port << "\n";
    std::cout << "[HyperEditor Daemon] Pure C++ Native Engine (Zero Web/UI files).\n";

    while (g_running) {
        struct sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(server_fd, (struct sockaddr*)&client_addr, &client_len);
        if (client_fd < 0) {
            if (!g_running) break;
            continue;
        }

        char buffer[2048] = {0};
        ssize_t bytesRead = read(client_fd, buffer, sizeof(buffer) - 1);
        (void)bytesRead;

        const char* body = 
            "Hyper Editor Agent: Pure C++ Native Headless Video & Audio Editor Engine.\n"
            "Architecture: 100% Native C++17/20 (FFmpeg C-APIs, FreeType2, HarfBuzz, OpenMP, CMake).\n"
            "Zero UI, TypeScript, JavaScript, HTML, or CSS files.\n"
            "CLI executable: ./build/hyper_editor --timeline <path_to_json> -o <output.mp4>\n";

        std::string response = 
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "Content-Length: " + std::to_string(std::strlen(body)) + "\r\n"
            "Connection: close\r\n\r\n" + std::string(body);

        ssize_t bytesWritten = write(client_fd, response.c_str(), response.size());
        (void)bytesWritten;
        close(client_fd);
    }

    close(server_fd);
    std::cout << "[HyperEditor Daemon] Shutdown complete.\n";
    return 0;
}

void printUsage(const char* progName) {
    std::cout << "\033[1m\033[35mHyper Editor Agent - Advanced Headless Editor\033[0m\n"
              << "High-performance modular headless C++ video editing tool\n\n"
              << "\033[1mUsage:\033[0m\n"
              << "  " << progName << " --timeline <path_to_json> [options]\n"
              << "  " << progName << " --serve [port]\n\n"
              << "\033[1mOptions:\033[0m\n"
              << "  --timeline, -t <file>    Path to input timeline JSON configuration (Required for rendering)\n"
              << "  --output, -o <file>      Override output master MP4 file path\n"
              << "  --threads, -j <N>        Number of rendering worker threads (Default: auto)\n"
              << "  --serve, -s [port]       Run native C++ headless daemon on port (Default: 3000)\n"
              << "  --verbose, -v            Enable verbose debug logs\n"
              << "  --help, -h               Show this help message and exit\n\n"
              << "\033[1mExample:\033[0m\n"
              << "  " << progName << " --timeline sample_timeline.json --output render_output.mp4\n"
              << "  " << progName << " --serve 3000\n\n";
}

int main(int argc, char* argv[]) {
    std::string timelinePath;
    std::string outputPathOverride;
    int threadCount = 0;
    bool verbose = false;
    bool serveMode = false;
    int servePort = 3000;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--timeline" || arg == "-t") {
            if (i + 1 < argc) timelinePath = argv[++i];
        } else if (arg == "--output" || arg == "-o") {
            if (i + 1 < argc) outputPathOverride = argv[++i];
        } else if (arg == "--threads" || arg == "-j") {
            if (i + 1 < argc) threadCount = std::stoi(argv[++i]);
        } else if (arg == "--serve" || arg == "-s") {
            serveMode = true;
            if (i + 1 < argc && argv[i + 1][0] != '-') {
                try {
                    servePort = std::stoi(argv[++i]);
                } catch (...) {}
            }
        } else if (arg == "--port") {
            if (i + 1 < argc) {
                try {
                    servePort = std::stoi(argv[++i]);
                } catch (...) {}
            }
        } else if (arg == "--verbose" || arg == "-v") {
            verbose = true;
        } else if (arg == "--help" || arg == "-h") {
            printUsage(argv[0]);
            return 0;
        }
    }

    if (serveMode) {
        return runServer(servePort);
    }

    if (verbose) {
        HyperEditor::Utils::Logger::instance().setLevel(HyperEditor::Utils::LogLevel::DEBUG);
    }

    if (timelinePath.empty()) {
        LOG_ERROR("Main", "Missing required --timeline parameter.");
        printUsage(argv[0]);
        return 1;
    }

    if (!std::filesystem::exists(timelinePath)) {
        LOG_ERROR("Main", "Timeline file does not exist: ", timelinePath);
        return 1;
    }

    LOG_INFO("Main", "Parsing timeline specification: ", timelinePath);
    HyperEditor::Core::Timeline timeline;
    if (!HyperEditor::Parsers::JsonParser::parseFile(timelinePath, timeline)) {
        LOG_ERROR("Main", "Failed to parse timeline JSON file.");
        return 1;
    }

    if (!outputPathOverride.empty()) {
        timeline.outputPath = outputPathOverride;
    }

    HyperEditor::Core::AdvancedHeadlessEditor editor;
    if (threadCount > 0) {
        editor.setThreadCount(threadCount);
    }

    bool success = editor.render(timeline);
    if (!success) {
        LOG_ERROR("Main", "Advanced Headless Editor rendering failed.");
        return 1;
    }

    LOG_INFO("Main", "Execution finished successfully.");
    return 0;
}
