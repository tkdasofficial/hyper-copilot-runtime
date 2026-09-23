#ifndef HYPER_UTILS_HPP
#define HYPER_UTILS_HPP

#include <string>
#include <vector>
#include <sstream>
#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <fstream>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#else
#include <unistd.h>
#endif

namespace hyper {

inline std::string getEnv(const std::string& key, const std::string& defaultVal = "") {
    const char* val = std::getenv(key.c_str());
    if (!val || std::string(val).empty()) {
        return defaultVal;
    }
    std::string s(val);
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return defaultVal;
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

inline std::string trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

inline std::string toLower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), ::tolower);
    return s;
}

inline bool fileExists(const std::string& path) {
    struct stat buffer;
    return (stat(path.c_str(), &buffer) == 0);
}

inline size_t getFileSize(const std::string& path) {
    struct stat buffer;
    if (stat(path.c_str(), &buffer) == 0) {
        return static_cast<size_t>(buffer.st_size);
    }
    return 0;
}

inline bool executeCommand(const std::string& cmd, std::string* output = nullptr) {
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) {
        std::cerr << "[Command Error] Failed to popen: " << cmd << std::endl;
        return false;
    }
    char buffer[512];
    std::string result;
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result += buffer;
    }
    int code = pclose(pipe);
    if (output) {
        *output = result;
    }
    return (code == 0);
}

inline std::string sanitizeFilename(const std::string& name) {
    std::string clean = "";
    for (char c : name) {
        if (std::isalnum(static_cast<unsigned char>(c)) || c == ' ' || c == '-' || c == '_') {
            clean += c;
        }
    }
    if (clean.empty()) clean = "rendered_video";
    std::replace(clean.begin(), clean.end(), ' ', '_');
    if (clean.size() > 60) clean = clean.substr(0, 60);
    return clean + ".mp4";
}

} // namespace hyper

#endif // HYPER_UTILS_HPP
