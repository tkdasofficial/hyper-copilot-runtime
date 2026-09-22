#include "screen_recorder.hpp"
#include "../common/base64.hpp"
#include <iostream>
#include <sstream>
#include <fstream>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace hyper_vision_agent {
namespace extensions {

static std::string ExtractJsonField(const std::string& json, const std::string& key) {
    std::string pattern = "\"" + key + "\":";
    size_t pos = json.find(pattern);
    if (pos == std::string::npos) return "";

    pos += pattern.length();
    while (pos < json.length() && (json[pos] == ' ' || json[pos] == '\t')) pos++;

    if (pos < json.length() && json[pos] == '"') {
        size_t end_quote = json.find('"', pos + 1);
        if (end_quote != std::string::npos) {
            return json.substr(pos + 1, end_quote - pos - 1);
        }
    } else {
        size_t end_delim = json.find_first_of(",}\n", pos);
        if (end_delim != std::string::npos) {
            return json.substr(pos, end_delim - pos);
        }
    }
    return "";
}

ScreenRecorder::ScreenRecorder() = default;

ScreenRecorder::~ScreenRecorder() {
    if (is_recording_.load()) {
        stop_recording();
    }
}

bool ScreenRecorder::open_ffmpeg_pipe() {
    std::stringstream cmd;
    std::string codec_input = (config_.format == "jpeg" || config_.format == "jpg") ? "mjpeg" : "png";

    // Check if ffmpeg exists
    if (system("which ffmpeg > /dev/null 2>&1") != 0) {
        std::cerr << "[ScreenRecorder] Notice: 'ffmpeg' executable not found in PATH. Enabling raw frame fallback mode.\n";
        using_pipe_ = false;
        if (config_.enable_raw_dump_fallback) {
            mkdir(config_.raw_dump_dir.c_str(), 0755);
        }
        return true;
    }

    cmd << "ffmpeg -y -f image2pipe "
        << "-vcodec " << codec_input << " "
        << "-r " << config_.fps << " "
        << "-i - "
        << "-c:v " << config_.video_codec << " "
        << "-pix_fmt " << config_.pixel_format << " "
        << "-preset " << config_.preset << " "
        << "-crf " << config_.crf << " "
        << config_.output_file << " 2>/dev/null";

    ffmpeg_pipe_ = popen(cmd.str().c_str(), "w");
    if (!ffmpeg_pipe_) {
        std::cerr << "[ScreenRecorder] Warning: Failed to spawn FFmpeg pipe. Falling back to frame buffer.\n";
        using_pipe_ = false;
        return false;
    }

    using_pipe_ = true;
    return true;
}

void ScreenRecorder::close_ffmpeg_pipe() {
    if (ffmpeg_pipe_) {
        pclose(ffmpeg_pipe_);
        ffmpeg_pipe_ = nullptr;
    }
    using_pipe_ = false;
}

bool ScreenRecorder::start_recording(std::shared_ptr<Page> page, const ScreenRecorderConfig& config) {
    std::lock_guard<std::mutex> lock(recorder_mutex_);
    if (is_recording_.load()) {
        std::cerr << "[ScreenRecorder] Error: Recording already active.\n";
        return false;
    }

    if (!page) {
        std::cerr << "[ScreenRecorder] Error: Invalid Page pointer.\n";
        return false;
    }

    page_ = page;
    config_ = config;
    stats_ = ScreenRecorderStats{};
    stats_.output_path = config_.output_file;
    stats_.is_recording = true;
    start_time_ = std::chrono::steady_clock::now();

    open_ffmpeg_pipe();

    // Subscribe to Page.screencastFrame events on connection
    auto conn = page_->GetConnection();
    if (!conn) {
        std::cerr << "[ScreenRecorder] Error: CdpConnection unavailable.\n";
        close_ffmpeg_pipe();
        return false;
    }

    conn->SubscribeEvent("Page.screencastFrame", [this](const CdpEvent& ev) {
        if (!is_recording_.load()) return;

        std::string data_b64 = ExtractJsonField(ev.params_json, "data");
        std::string frame_session_id_str = ExtractJsonField(ev.params_json, "sessionId");

        // Acknowledge frame to CDP immediately to receive continuous flow
        if (!frame_session_id_str.empty() && page_) {
            std::string ack_params = "{\"sessionId\":" + frame_session_id_str + "}";
            auto c = page_->GetConnection();
            if (c) {
                try {
                    c->SendCommandAsync("Page.screencastFrameAck", ack_params, page_->GetSessionId());
                } catch (...) {}
            }
        }

        if (!data_b64.empty()) {
            this->push_frame(data_b64);
        }
    });

    // Send Page.startScreencast CDP command
    std::stringstream params;
    params << "{"
           << "\"format\":\"" << config_.format << "\","
           << "\"quality\":" << config_.quality << ","
           << "\"maxWidth\":" << config_.width << ","
           << "\"maxHeight\":" << config_.height << ","
           << "\"everyNthFrame\":1"
           << "}";

    auto resp = page_->GetDispatcher()->Dispatch("Page.startScreencast", params.str(), page_->GetSessionId());
    if (!resp.success) {
        std::cerr << "[ScreenRecorder] Warning: Page.startScreencast command returned error: " << resp.error_message << "\n";
    }

    is_recording_.store(true);
    return true;
}

bool ScreenRecorder::stop_recording() {
    std::lock_guard<std::mutex> lock(recorder_mutex_);
    if (!is_recording_.load()) {
        return false;
    }

    is_recording_.store(false);

    if (page_) {
        // Stop CDP screencast
        auto conn = page_->GetConnection();
        if (conn) {
            conn->UnsubscribeEvent("Page.screencastFrame");
        }
        page_->GetDispatcher()->Dispatch("Page.stopScreencast", "{}", page_->GetSessionId());
    }

    close_ffmpeg_pipe();

    auto now = std::chrono::steady_clock::now();
    stats_.duration_seconds = std::chrono::duration<double>(now - start_time_).count();
    stats_.is_recording = false;

    return true;
}

bool ScreenRecorder::push_frame(const std::string& base64_data, uint64_t timestamp) {
    std::vector<uint8_t> binary = utils::Base64Decode(base64_data);
    return push_frame(binary, timestamp);
}

bool ScreenRecorder::push_frame(const std::vector<uint8_t>& binary_data, uint64_t timestamp) {
    std::lock_guard<std::mutex> lock(recorder_mutex_);
    if (!is_recording_.load() || binary_data.empty()) {
        stats_.dropped_frames++;
        return false;
    }

    if (using_pipe_ && ffmpeg_pipe_) {
        size_t written = fwrite(binary_data.data(), 1, binary_data.size(), ffmpeg_pipe_);
        fflush(ffmpeg_pipe_);
        if (written == binary_data.size()) {
            stats_.total_frames++;
            stats_.bytes_written += written;
        } else {
            stats_.dropped_frames++;
        }
    } else {
        // Fallback: save frames to raw dump dir if requested
        if (config_.enable_raw_dump_fallback) {
            std::stringstream fname;
            fname << config_.raw_dump_dir << "/frame_" << stats_.total_frames << "." << config_.format;
            std::ofstream out(fname.str(), std::ios::binary);
            if (out.is_open()) {
                out.write(reinterpret_cast<const char*>(binary_data.data()), binary_data.size());
                out.close();
            }
        }
        stats_.total_frames++;
        stats_.bytes_written += binary_data.size();
    }

    if (frame_listener_) {
        frame_listener_(binary_data, timestamp);
    }

    return true;
}

void ScreenRecorder::set_frame_listener(FrameCallback callback) {
    std::lock_guard<std::mutex> lock(recorder_mutex_);
    frame_listener_ = std::move(callback);
}

ScreenRecorderStats ScreenRecorder::get_stats() const {
    std::lock_guard<std::mutex> lock(recorder_mutex_);
    auto s = stats_;
    if (is_recording_.load()) {
        auto now = std::chrono::steady_clock::now();
        s.duration_seconds = std::chrono::duration<double>(now - start_time_).count();
    }
    return s;
}

} // namespace extensions
} // namespace hyper_vision_agent
