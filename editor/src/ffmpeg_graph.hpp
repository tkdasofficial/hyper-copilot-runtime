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
    std::string output_path = "out.mp4";
    bool burn_captions = true;
    bool duck_bgm = true;

    // Ken Burns Motion & Camera Effects
    bool ken_burns_enabled = true;
    std::string motion_type = "dynamic"; // "dynamic", "zoomin", "zoomout", "panleft", "panright", "panup", "pandown", "none"

    // Transitions
    TransitionType default_transition = TransitionType::Crossfade;
    double default_transition_duration = 0.4;

    // Visual Filters & Color Grading
    bool color_grading_enabled = true;
    double contrast = 1.05;
    double saturation = 1.10;
    double brightness = 0.02;

    bool vignette_enabled = false;
    bool dark_gradient_overlay = true; // semi-transparent dark gradient bar at lower third for subtitle legibility

    // Overlay Features
    bool progress_bar_enabled = false;
    std::string progress_bar_color = "white@0.85";
    int progress_bar_height = 8;

    std::string watermark_path;
    std::string watermark_position = "top-right"; // "top-right", "top-left", "bottom-right", "bottom-left"
    double watermark_opacity = 0.60;

    // Speed Adjustment
    double global_speed_factor = 1.0;

    // Output Encoding
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

    const FfmpegGraphConfig& getConfig() const { return m_config; }
    void setConfig(const FfmpegGraphConfig& config) { m_config = config; }

private:
    SceneBuilder m_builder;
    FfmpegGraphConfig m_config;
};

} // namespace hyper
