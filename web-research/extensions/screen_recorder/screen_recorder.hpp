#ifndef HYPER_VISION_AGENT_EXT_SCREEN_RECORDER_HPP
#define HYPER_VISION_AGENT_EXT_SCREEN_RECORDER_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/page.hpp"
#include <string>
#include <memory>
#include <atomic>
#include <mutex>
#include <chrono>
#include <vector>
#include <cstdio>
#include <functional>

namespace hyper_vision_agent {
namespace extensions {

struct ScreenRecorderConfig {
    std::string output_file = "recording.mp4";
    int width = 1920;
    int height = 1080;
    int fps = 30;
    std::string format = "png"; // "png" or "jpeg"
    int quality = 90;
    std::string video_codec = "libx264";
    std::string pixel_format = "yuv420p";
    std::string preset = "ultrafast";
    int crf = 23;
    bool enable_raw_dump_fallback = true;
    std::string raw_dump_dir = "/tmp/hva_screencast_frames";
};

struct ScreenRecorderStats {
    uint64_t total_frames{0};
    uint64_t dropped_frames{0};
    uint64_t bytes_written{0};
    double duration_seconds{0.0};
    bool is_recording{false};
    std::string output_path{""};
};

using FrameCallback = std::function<void(const std::vector<uint8_t>& frame_data, uint64_t timestamp)>;

class ScreenRecorder {
public:
    ScreenRecorder();
    ~ScreenRecorder();

    // Prevent copies
    ScreenRecorder(const ScreenRecorder&) = delete;
    ScreenRecorder& operator=(const ScreenRecorder&) = delete;

    // Core Native Methods
    bool start_recording(std::shared_ptr<Page> page, const ScreenRecorderConfig& config = ScreenRecorderConfig{});
    bool stop_recording();
    bool push_frame(const std::string& base64_data, uint64_t timestamp = 0);
    bool push_frame(const std::vector<uint8_t>& binary_data, uint64_t timestamp = 0);

    // Frame Hooks
    void set_frame_listener(FrameCallback callback);

    // Status and Telemetry
    bool is_recording() const { return is_recording_.load(); }
    ScreenRecorderStats get_stats() const;

private:
    bool open_ffmpeg_pipe();
    void close_ffmpeg_pipe();

    std::shared_ptr<Page> page_{nullptr};
    ScreenRecorderConfig config_;
    std::atomic<bool> is_recording_{false};
    FILE* ffmpeg_pipe_{nullptr};
    mutable std::mutex recorder_mutex_;
    ScreenRecorderStats stats_;
    std::chrono::steady_clock::time_point start_time_;
    FrameCallback frame_listener_{nullptr};
    bool using_pipe_{false};
};

} // namespace extensions
} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_EXT_SCREEN_RECORDER_HPP
