#include "utils/logger.hpp"

namespace HyperEditor {
namespace Utils {

Logger& Logger::instance() {
    static Logger inst;
    return inst;
}

void Logger::setLevel(LogLevel level) {
    std::lock_guard<std::mutex> lock(mutex_);
    currentLevel_ = level;
}

LogLevel Logger::getLevel() const {
    return currentLevel_;
}

std::string Logger::levelToString(LogLevel level) const {
    switch (level) {
        case LogLevel::DEBUG: return "DEBUG";
        case LogLevel::INFO:  return "INFO ";
        case LogLevel::WARN:  return "WARN ";
        case LogLevel::ERROR: return "ERROR";
    }
    return "UNKNOWN";
}

std::string Logger::levelToColor(LogLevel level) const {
    switch (level) {
        case LogLevel::DEBUG: return "\033[36m"; // Cyan
        case LogLevel::INFO:  return "\033[32m"; // Green
        case LogLevel::WARN:  return "\033[33m"; // Yellow
        case LogLevel::ERROR: return "\033[31m"; // Red
    }
    return "\033[0m";
}

void Logger::log(LogLevel level, const std::string& component, const std::string& message) {
    if (level < currentLevel_) return;

    std::lock_guard<std::mutex> lock(mutex_);

    auto now = std::chrono::system_clock::now();
    auto in_time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;

    std::tm bt{};
#if defined(_WIN32)
    localtime_s(&bt, &in_time_t);
#else
    localtime_r(&in_time_t, &bt);
#endif

    std::cout << "\033[90m[" 
              << std::put_time(&bt, "%H:%M:%S") 
              << '.' << std::setfill('0') << std::setw(3) << ms.count()
              << "]\033[0m "
              << levelToColor(level) << "[" << levelToString(level) << "]\033[0m "
              << "\033[35m[" << component << "]\033[0m "
              << message << "\033[0m\n";
    std::cout.flush();
}

void Logger::progress(const std::string& task, int current, int total, double fps) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (total <= 0) total = 1;
    float pct = static_cast<float>(current) / static_cast<float>(total);
    int barWidth = 36;
    int pos = static_cast<int>(barWidth * pct);

    std::cout << "\r\033[K\033[34m[" << task << "]\033[0m [";
    for (int i = 0; i < barWidth; ++i) {
        if (i < pos) std::cout << "\033[32m=\033[0m";
        else if (i == pos) std::cout << "\033[32m>\033[0m";
        else std::cout << " ";
    }
    std::cout << "] " << std::fixed << std::setprecision(1) << (pct * 100.0f) << "% ("
              << current << "/" << total << ")";
    if (fps > 0.0) {
        std::cout << " @ " << std::fixed << std::setprecision(1) << fps << " fps";
    }
    if (current >= total) {
        std::cout << " \033[32m[DONE]\033[0m\n";
    }
    std::cout.flush();
}

} // namespace Utils
} // namespace HyperEditor
