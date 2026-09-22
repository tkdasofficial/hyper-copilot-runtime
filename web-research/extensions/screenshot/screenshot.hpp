#ifndef HYPER_VISION_AGENT_EXT_SCREENSHOT_HPP
#define HYPER_VISION_AGENT_EXT_SCREENSHOT_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/page.hpp"
#include <string>
#include <vector>
#include <cstdint>
#include <optional>

namespace hyper_vision_agent {
namespace extensions {

enum class ImageFormat {
    PNG,
    JPEG,
    WEBP
};

struct ScreenshotOptions {
    ImageFormat format = ImageFormat::PNG;
    int quality = 90; // 1-100, applied for JPEG and WEBP
    std::string output_path = ""; // if non-empty, saves image to this path
    bool from_surface = true;
    double scale = 1.0;
    bool capture_beyond_viewport = true;
};

struct ScreenshotResult {
    bool success = false;
    std::string format_str = "png";
    std::string base64_data = "";
    std::vector<uint8_t> binary_data;
    double width = 0.0;
    double height = 0.0;
    std::string file_path = "";
    std::string error_message = "";
};

class Screenshot {
public:
    Screenshot() = default;
    ~Screenshot() = default;

    // Viewport Screenshot
    static ScreenshotResult CaptureViewport(Page& page, const ScreenshotOptions& options = ScreenshotOptions{});

    // Full-Page Scrolling Screenshot
    static ScreenshotResult CaptureFullPage(Page& page, const ScreenshotOptions& options = ScreenshotOptions{});

    // CSS Selector Element Cropping Screenshot
    static ScreenshotResult CaptureElement(Page& page, const std::string& selector, const ScreenshotOptions& options = ScreenshotOptions{});

    // File Persistence Helper
    static bool SaveToFile(const ScreenshotResult& result, const std::string& file_path);

    // Helpers
    static std::string FormatToString(ImageFormat fmt);
    static ImageFormat StringToFormat(const std::string& fmt_str);
};

} // namespace extensions
} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_EXT_SCREENSHOT_HPP
