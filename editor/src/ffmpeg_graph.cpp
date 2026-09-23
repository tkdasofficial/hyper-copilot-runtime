#include "ffmpeg_graph.hpp"
#include <sstream>
#include <iomanip>
#include <cstdlib>
#include <iostream>

namespace hyper {

FfmpegGraph::FfmpegGraph(const SceneBuilder& builder, const FfmpegGraphConfig& config)
    : m_builder(builder), m_config(config) {
}

std::string FfmpegGraph::buildFilterComplex() const {
    auto clips = m_builder.getFlattenedClips();
    if (clips.empty()) {
        return "";
    }

    int W = m_builder.getWidth();
    int H = m_builder.getHeight();
    int FPS = m_builder.getFps();

    std::ostringstream fc;

    // Step 1: Preprocess each video input: trim, scale, crop, setpts, fps, format
    for (size_t i = 0; i < clips.size(); ++i) {
        const auto& c = clips[i];
        fc << "[" << i << ":v]"
           << "trim=start=" << std::fixed << std::setprecision(2) << c.source_trim_start
           << ":duration=" << c.duration << ","
           << "setpts=PTS-STARTPTS,"
           << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,"
           << "crop=" << W << ":" << H << ","
           << "setsar=1,"
           << "fps=" << FPS << ","
           << "format=yuv420p[v" << i << "];";
    }

    // Step 2: Transition chain
    std::string currentStream = "[v0]";
    if (clips.size() == 1) {
        currentStream = "[v0]";
    } else {
        double currentTotalDuration = clips[0].duration;
        for (size_t i = 1; i < clips.size(); ++i) {
            double transDur = clips[i].transition_duration > 0.05 ? clips[i].transition_duration : 0.4;
            // Prevent transition duration from exceeding clip duration
            if (transDur >= clips[i].duration) {
                transDur = std::max(0.1, clips[i].duration * 0.3);
            }
            if (transDur >= currentTotalDuration) {
                transDur = std::max(0.1, currentTotalDuration * 0.3);
            }

            double offset = currentTotalDuration - transDur;
            std::string transType = SceneBuilder::transitionToString(clips[i].transition);
            std::string nextStream = "[vx" + std::to_string(i) + "]";

            fc << currentStream << "[v" << i << "]"
               << "xfade=transition=" << transType
               << ":duration=" << std::fixed << std::setprecision(2) << transDur
               << ":offset=" << std::fixed << std::setprecision(2) << offset
               << nextStream << ";";

            currentStream = nextStream;
            currentTotalDuration = offset + clips[i].duration;
        }
    }

    // Step 3: Burn-in subtitles directly onto the final composite video stream
    std::string finalVideoStream = "[vout]";
    if (m_config.burn_captions && !m_config.captions_ass_path.empty()) {
        std::string escapedPath;
        for (char ch : m_config.captions_ass_path) {
            if (ch == ':' || ch == '\\' || ch == '\'') {
                escapedPath += '\\';
            }
            escapedPath += ch;
        }
        fc << currentStream << "ass='" << escapedPath << "'" << finalVideoStream;
    } else {
        // Pass-through without subtitle filter
        fc << currentStream << "copy" << finalVideoStream;
    }

    return fc.str();
}

std::vector<std::string> FfmpegGraph::buildCommandArgs() const {
    std::vector<std::string> args;
    args.push_back("ffmpeg");
    args.push_back("-y"); // overwrite output

    auto clips = m_builder.getFlattenedClips();
    // Add all distinct video inputs
    for (const auto& c : clips) {
        args.push_back("-i");
        args.push_back(c.file_path);
    }

    // Add audio inputs
    int audioInputIndex = static_cast<int>(clips.size());
    bool hasNarration = !m_config.narration_audio_path.empty();
    bool hasBgm = !m_config.bgm_audio_path.empty();

    if (hasNarration) {
        args.push_back("-i");
        args.push_back(m_config.narration_audio_path);
    }
    if (hasBgm) {
        args.push_back("-i");
        args.push_back(m_config.bgm_audio_path);
    }

    // Filter complex
    std::string fc = buildFilterComplex();
    if (!fc.empty()) {
        args.push_back("-filter_complex");
        args.push_back(fc);
        args.push_back("-map");
        args.push_back("[vout]");
    } else if (!clips.empty()) {
        args.push_back("-map");
        args.push_back("0:v");
    }

    // Audio mapping
    if (hasNarration && hasBgm) {
        // Mix narration and BGM with sidechain or volume ducking
        std::string audioFilter = "[" + std::to_string(audioInputIndex) + ":a]volume=1.0[anarr];"
                                + "[" + std::to_string(audioInputIndex + 1) + ":a]volume=0.15[abgm];"
                                + "[anarr][abgm]amix=inputs=2:duration=first:dropout_transition=2[aout]";
        args.push_back("-filter_complex");
        args.back() = fc.empty() ? audioFilter : (fc + ";" + audioFilter);
        args.push_back("-map");
        args.push_back("[aout]");
    } else if (hasNarration) {
        args.push_back("-map");
        args.push_back(std::to_string(audioInputIndex) + ":a:0");
    }

    // Codec settings
    args.push_back("-threads");
    args.push_back("2");
    args.push_back("-c:v");
    args.push_back(m_config.video_codec);
    args.push_back("-preset");
    args.push_back(m_config.preset.empty() ? "veryfast" : m_config.preset);
    args.push_back("-crf");
    args.push_back(std::to_string(m_config.crf));
    args.push_back("-c:a");
    args.push_back(m_config.audio_codec);
    args.push_back("-b:a");
    args.push_back(m_config.audio_bitrate);
    args.push_back("-pix_fmt");
    args.push_back("yuv420p");
    args.push_back("-movflags");
    args.push_back("+faststart");
    args.push_back("-shortest");

    args.push_back(m_config.output_path);

    return args;
}

std::string FfmpegGraph::buildCommandLine() const {
    auto args = buildCommandArgs();
    std::ostringstream cmd;
    for (size_t i = 0; i < args.size(); ++i) {
        if (i > 0) cmd << " ";
        // Quote arguments containing spaces or special shell characters
        if (args[i].find(' ') != std::string::npos || args[i].find(';') != std::string::npos ||
            args[i].find('[') != std::string::npos || args[i].find(']') != std::string::npos ||
            args[i].find('\'') != std::string::npos) {
            cmd << "\"" << args[i] << "\"";
        } else {
            cmd << args[i];
        }
    }
    return cmd.str();
}

int FfmpegGraph::execute() const {
    std::string cmd = buildCommandLine();
    std::cout << "[HyperEditor] Executing FFmpeg Render Pipeline:\n" << cmd << std::endl;
    int ret = std::system(cmd.c_str());
    return ret;
}

} // namespace hyper
