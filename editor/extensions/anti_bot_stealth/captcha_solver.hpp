#ifndef HYPER_VISION_AGENT_EXT_CAPTCHA_SOLVER_HPP
#define HYPER_VISION_AGENT_EXT_CAPTCHA_SOLVER_HPP

#include "stealth.hpp"
#include <string>
#include <chrono>

namespace hyper_vision_agent {
namespace extensions {

enum class CaptchaType {
    NONE,
    CLOUDFLARE_TURNSTILE,
    RECAPTCHA_V2,
    HCAPTCHA
};

struct CaptchaDetectResult {
    CaptchaType type = CaptchaType::NONE;
    bool detected = false;
    std::string selector = "";
    Point2D center_coords{0.0, 0.0};
    std::string frame_url = "";
};

struct CaptchaSolveResult {
    bool success = false;
    CaptchaType type = CaptchaType::NONE;
    std::string token = "";
    std::chrono::milliseconds elapsed_time{0};
    std::string error_message = "";
};

class CaptchaSolver {
public:
    // Scans page for active Cloudflare Turnstile, reCAPTCHA, or hCaptcha widgets
    static CaptchaDetectResult DetectCaptcha(Page& page);

    // Automatically dispatches human-like interactions to solve detected challenge
    static CaptchaSolveResult Solve(Page& page, std::chrono::milliseconds timeout = std::chrono::milliseconds(15000));

    // Specific Turnstile click handler
    static bool HandleTurnstile(Page& page, std::chrono::milliseconds timeout = std::chrono::milliseconds(15000));

    // Specific "I am not a robot" reCAPTCHA v2 click handler
    static bool HandleRecaptcha(Page& page, std::chrono::milliseconds timeout = std::chrono::milliseconds(15000));
};

} // namespace extensions
} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_EXT_CAPTCHA_SOLVER_HPP
