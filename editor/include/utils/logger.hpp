#pragma once

#include <string>
#include <sstream>
#include <iostream>
#include <mutex>
#include <chrono>
#include <iomanip>

namespace HyperEditor {
namespace Utils {

enum class LogLevel {
    DEBUG = 0,
    INFO = 1,
    WARN = 2,
    ERROR = 3
};

class Logger {
public:
    static Logger& instance();

    void setLevel(LogLevel level);
    LogLevel getLevel() const;

    void log(LogLevel level, const std::string& component, const std::string& message);
    void progress(const std::string& task, int current, int total, double fps = 0.0);

    template<typename... Args>
    void debug(const std::string& component, Args&&... args) {
        logFormat(LogLevel::DEBUG, component, std::forward<Args>(args)...);
    }

    template<typename... Args>
    void info(const std::string& component, Args&&... args) {
        logFormat(LogLevel::INFO, component, std::forward<Args>(args)...);
    }

    template<typename... Args>
    void warn(const std::string& component, Args&&... args) {
        logFormat(LogLevel::WARN, component, std::forward<Args>(args)...);
    }

    template<typename... Args>
    void error(const std::string& component, Args&&... args) {
        logFormat(LogLevel::ERROR, component, std::forward<Args>(args)...);
    }

private:
    Logger() : currentLevel_(LogLevel::INFO) {}
    ~Logger() = default;
    Logger(const Logger&) = delete;
    Logger& operator=(const Logger&) = delete;

    template<typename... Args>
    void logFormat(LogLevel level, const std::string& component, Args&&... args) {
        if (level < currentLevel_) return;
        std::ostringstream oss;
        (oss << ... << args);
        log(level, component, oss.str());
    }

    std::string levelToString(LogLevel level) const;
    std::string levelToColor(LogLevel level) const;

    LogLevel currentLevel_;
    std::mutex mutex_;
};

#define LOG_DEBUG(comp, ...) HyperEditor::Utils::Logger::instance().debug(comp, __VA_ARGS__)
#define LOG_INFO(comp, ...)  HyperEditor::Utils::Logger::instance().info(comp, __VA_ARGS__)
#define LOG_WARN(comp, ...)  HyperEditor::Utils::Logger::instance().warn(comp, __VA_ARGS__)
#define LOG_ERROR(comp, ...) HyperEditor::Utils::Logger::instance().error(comp, __VA_ARGS__)

} // namespace Utils
} // namespace HyperEditor
