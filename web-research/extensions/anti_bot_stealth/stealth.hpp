#ifndef HYPER_VISION_AGENT_EXT_STEALTH_HPP
#define HYPER_VISION_AGENT_EXT_STEALTH_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/page.hpp"
#include <string>
#include <vector>
#include <chrono>

namespace hyper_vision_agent {
namespace extensions {

struct Point2D {
    double x = 0.0;
    double y = 0.0;
};

struct StealthConfig {
    bool hide_webdriver = true;
    bool mock_plugins = true;
    bool mock_chrome_runtime = true;
    bool mock_webgl = true;
    bool mock_audio_context = true;
    bool mock_permissions = true;
    std::vector<std::string> languages = {"en-US", "en"};
    std::string webgl_vendor = "Intel Inc.";
    std::string webgl_renderer = "Intel(R) Iris(R) Xe Graphics";
    int hardware_concurrency = 8;
    int device_memory = 8;
};

class Stealth {
public:
    Stealth() = default;
    ~Stealth() = default;

    // Injects fingerprint modifications via Page.addScriptToEvaluateOnNewDocument
    static bool Apply(Page& page, const StealthConfig& config = StealthConfig{});

    // Returns Javascript payload string for stealth evaluation
    static std::string GenerateStealthScript(const StealthConfig& config);

    // C-Spline (Cubic Hermite/Bezier) human-like trajectory generation
    static std::vector<Point2D> CalculateHumanTrajectory(
        Point2D start, 
        Point2D end, 
        int steps = 25, 
        double curvature = 0.2
    );

    // Moves mouse along human C-Spline trajectory to (target_x, target_y)
    static bool HumanMoveTo(
        Page& page, 
        double target_x, 
        double target_y, 
        int steps = 25, 
        int total_duration_ms = 350
    );

    // Performs human-like curved movement followed by natural click
    static bool HumanClick(
        Page& page, 
        const std::string& selector, 
        int duration_ms = 350
    );

    static bool HumanClickAt(
        Page& page, 
        double x, 
        double y, 
        int duration_ms = 350
    );
};

} // namespace extensions
} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_EXT_STEALTH_HPP
