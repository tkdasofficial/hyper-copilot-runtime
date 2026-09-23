#pragma once

#include "scene_builder.hpp"
#include "caption_renderer.hpp"
#include <string>
#include <vector>

namespace hyper {

struct FfmpegGraphConfig {
    std::string narration_audio_path;
    std::string bgm_audio_path;
    std::string captions_ass_path;
    std::string output_path;
    bool burn_captions = true;
    bool duck_bgm = true;
    std::string video_codec = "libx264";
    std::string preset = "veryfast";
    int crf = 20;
    std::string audio_codec = "aac";
    std::string audio_bitrate = "192k";
};

class FfmpegGraph {
public:
    FfmpegGraph(const SceneBuilder& builder, const FfmpegGraphConfig& config);

    // Builds the complete FFmpeg command arguments
    std::vector<std::string> buildCommandArgs() const;

    // Builds single-line bash-executable FFmpeg command
    std::string buildCommandLine() const;

    // Builds the complex filter graph string (-filter_complex)
    std::string buildFilterComplex() const;

    // Executes the FFmpeg rendering process synchronously
    int execute() const;

private:
    SceneBuilder m_builder;
    FfmpegGraphConfig m_config;
};

} // namespace hyper
