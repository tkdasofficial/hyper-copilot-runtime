#include "ffmpeg_graph.hpp"
#include <sstream>
#include <iomanip>
#include <cstdlib>
#include <iostream>
#include <cctype>
#include <algorithm>

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

    // Step 1: Preprocess each video input: speed, trim, ken burns / scale & crop, fps, format
    for (size_t i = 0; i < clips.size(); ++i) {
        const auto& c = clips[i];
        double speed = (c.speed_factor > 0.05) ? c.speed_factor : m_config.global_speed_factor;
        if (speed <= 0.05) speed = 1.0;
        double srcDuration = c.duration * speed;

        fc << "[" << i << ":v]"
           << "trim=start=" << std::fixed << std::setprecision(2) << c.source_trim_start
           << ":duration=" << std::fixed << std::setprecision(2) << srcDuration << ",";

        if (std::abs(speed - 1.0) > 0.01) {
            fc << "setpts=" << std::fixed << std::setprecision(4) << (1.0 / speed) << "*(PTS-STARTPTS),";
        } else {
            fc << "setpts=PTS-STARTPTS,";
        }

        // Determine Ken Burns Camera Motion
        CameraMotion motion = c.motion;
        if (motion == CameraMotion::None && m_config.ken_burns_enabled) {
            if (m_config.motion_type == "dynamic") {
                int mod = static_cast<int>(i % 4);
                if (mod == 0) motion = CameraMotion::ZoomIn;
                else if (mod == 1) motion = CameraMotion::PanLeft;
                else if (mod == 2) motion = CameraMotion::ZoomOut;
                else motion = CameraMotion::PanRight;
            } else {
                motion = SceneBuilder::parseMotion(m_config.motion_type);
            }
        }

        // Apply camera motion with smooth subpixel scaling
        if (motion == CameraMotion::ZoomIn) {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ","
               << "zoompan=z='min(zoom+0.0015,1.25)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=" << W << "x" << H << ":fps=" << FPS << ",";
        } else if (motion == CameraMotion::ZoomOut) {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ","
               << "zoompan=z='if(lte(on,1),1.25,max(1.001,zoom-0.0015))':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=" << W << "x" << H << ":fps=" << FPS << ",";
        } else if (motion == CameraMotion::PanLeft) {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ","
               << "zoompan=z=1.2:d=1:x='if(lte(on,1),(iw-iw/zoom),max(0,x-2))':y='ih/2-(ih/zoom/2)':s=" << W << "x" << H << ":fps=" << FPS << ",";
        } else if (motion == CameraMotion::PanRight) {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ","
               << "zoompan=z=1.2:d=1:x='if(lte(on,1),0,min(iw-iw/zoom,x+2))':y='ih/2-(ih/zoom/2)':s=" << W << "x" << H << ":fps=" << FPS << ",";
        } else if (motion == CameraMotion::PanUp) {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ","
               << "zoompan=z=1.2:d=1:x='iw/2-(iw/zoom/2)':y='if(lte(on,1),(ih-ih/zoom),max(0,y-2))':s=" << W << "x" << H << ":fps=" << FPS << ",";
        } else if (motion == CameraMotion::PanDown) {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ","
               << "zoompan=z=1.2:d=1:x='iw/2-(iw/zoom/2)':y='if(lte(on,1),0,min(ih-ih/zoom,y+2))':s=" << W << "x" << H << ":fps=" << FPS << ",";
        } else {
            fc << "scale=" << W << ":" << H << ":force_original_aspect_ratio=increase,crop=" << W << ":" << H << ",";
        }

        fc << "setsar=1,fps=" << FPS << ",format=yuv420p[v" << i << "];";
    }

    // Step 2: Transition chain (xfade)
    std::string currentStream = "[v0]";
    double currentTotalDuration = clips[0].duration;

    if (clips.size() > 1) {
        for (size_t i = 1; i < clips.size(); ++i) {
            TransitionType trans = (clips[i].transition != TransitionType::None) ? clips[i].transition : m_config.default_transition;
            double transDur = (clips[i].transition_duration > 0.05) ? clips[i].transition_duration : m_config.default_transition_duration;

            // Clamp transition duration so it cannot exceed clip duration or current accumulated duration
            if (transDur >= clips[i].duration) {
                transDur = std::max(0.1, clips[i].duration * 0.3);
            }
            if (transDur >= currentTotalDuration) {
                transDur = std::max(0.1, currentTotalDuration * 0.3);
            }

            double offset = currentTotalDuration - transDur;
            std::string transType = SceneBuilder::transitionToString(trans);
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

    // Step 3: Visual Filters, Color Grading, Gradient Overlay, Subtitles, and Progress Bar
    std::vector<std::string> postFilters;

    // Cinematic Color Grading
    if (m_config.color_grading_enabled) {
        std::ostringstream oss;
        oss << "eq=contrast=" << std::fixed << std::setprecision(2) << m_config.contrast
            << ":saturation=" << std::fixed << std::setprecision(2) << m_config.saturation
            << ":brightness=" << std::fixed << std::setprecision(2) << m_config.brightness;
        postFilters.push_back(oss.str());
    }

    // Subtle Vignette Filter
    if (m_config.vignette_enabled) {
        postFilters.push_back("vignette=angle=PI/5");
    }

    // Semi-transparent Dark Gradient / Bar for Subtitle Legibility
    if (m_config.dark_gradient_overlay && m_config.burn_captions && !m_config.captions_ass_path.empty()) {
        postFilters.push_back("drawbox=x=0:y=ih*0.70:w=iw:h=ih*0.30:color=black@0.40:t=fill");
    }

    // Subtitle Burn-in
    if (m_config.burn_captions && !m_config.captions_ass_path.empty()) {
        std::string escapedPath;
        for (char ch : m_config.captions_ass_path) {
            if (ch == ':' || ch == '\\' || ch == '\'') {
                escapedPath += '\\';
            }
            escapedPath += ch;
        }
        postFilters.push_back("ass='" + escapedPath + "'");
    }

    // Sleek Progress Bar
    if (m_config.progress_bar_enabled && currentTotalDuration > 0.5) {
        int pbH = (m_config.progress_bar_height > 0) ? m_config.progress_bar_height : 8;
        std::ostringstream pbOss;
        pbOss << "drawbox=x=0:y=ih-" << pbH << ":w=iw:h=" << pbH << ":color=black@0.4:t=fill,"
              << "drawbox=x=0:y=ih-" << pbH << ":w='iw*t/" << std::fixed << std::setprecision(2) << currentTotalDuration
              << "':h=" << pbH << ":color=" << m_config.progress_bar_color << ":t=fill";
        postFilters.push_back(pbOss.str());
    }

    bool hasWatermark = !m_config.watermark_path.empty();
    std::string vMasterStream = hasWatermark ? "[vmaster]" : "[vout]";

    if (!postFilters.empty()) {
        std::string chained;
        for (size_t k = 0; k < postFilters.size(); ++k) {
            if (k > 0) chained += ",";
            chained += postFilters[k];
        }
        fc << currentStream << chained << vMasterStream;
    } else {
        fc << currentStream << "null" << vMasterStream;
    }

    // Step 4: Watermark / Logo Overlay
    if (hasWatermark) {
        int wmInputIndex = static_cast<int>(clips.size())
                         + (!m_config.narration_audio_path.empty() ? 1 : 0)
                         + (!m_config.bgm_audio_path.empty() ? 1 : 0);
        int maxWmW = std::max(60, static_cast<int>(W * 0.16));

        fc << ";[" << wmInputIndex << ":v]format=rgba,colorchannelmixer=aa="
           << std::fixed << std::setprecision(2) << m_config.watermark_opacity
           << ",scale=w='min(iw," << maxWmW << ")':h=-1[wm];";

        std::string pos = "x=main_w-overlay_w-30:y=30"; // default top-right
        if (m_config.watermark_position == "top-left") {
            pos = "x=30:y=30";
        } else if (m_config.watermark_position == "bottom-right") {
            pos = "x=main_w-overlay_w-30:y=main_h-overlay_h-30";
        } else if (m_config.watermark_position == "bottom-left") {
            pos = "x=30:y=main_h-overlay_h-30";
        }

        fc << vMasterStream << "[wm]overlay=" << pos << ":shortest=1[vout]";
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
    bool hasWatermark = !m_config.watermark_path.empty();

    if (hasNarration) {
        args.push_back("-i");
        args.push_back(m_config.narration_audio_path);
    }
    if (hasBgm) {
        args.push_back("-i");
        args.push_back(m_config.bgm_audio_path);
    }

    // Add watermark input (with -loop 1)
    if (hasWatermark) {
        args.push_back("-loop");
        args.push_back("1");
        args.push_back("-i");
        args.push_back(m_config.watermark_path);
    }

    // Filter complex construction
    std::string videoFc = buildFilterComplex();
    std::string fullFc = videoFc;
    bool hasCustomAudioMap = false;

    double globalSpeed = m_config.global_speed_factor;
    if (globalSpeed <= 0.05) globalSpeed = 1.0;

    if (hasNarration && hasBgm) {
        std::ostringstream audioOss;
        if (std::abs(globalSpeed - 1.0) > 0.01) {
            audioOss << "[" << audioInputIndex << ":a]atempo=" << std::fixed << std::setprecision(2) << globalSpeed << ",volume=1.0[anarr];";
        } else {
            audioOss << "[" << audioInputIndex << ":a]volume=1.0[anarr];";
        }
        audioOss << "[" << (audioInputIndex + 1) << ":a]volume=0.15[abgm];"
                 << "[anarr][abgm]amix=inputs=2:duration=first:dropout_transition=2[aout]";
        if (!fullFc.empty()) fullFc += ";" + audioOss.str();
        else fullFc = audioOss.str();
        hasCustomAudioMap = true;
    } else if (hasNarration && std::abs(globalSpeed - 1.0) > 0.01) {
        std::ostringstream audioOss;
        audioOss << "[" << audioInputIndex << ":a]atempo=" << std::fixed << std::setprecision(2) << globalSpeed << "[aout]";
        if (!fullFc.empty()) fullFc += ";" + audioOss.str();
        else fullFc = audioOss.str();
        hasCustomAudioMap = true;
    }

    if (!fullFc.empty()) {
        args.push_back("-filter_complex");
        args.push_back(fullFc);
        args.push_back("-map");
        args.push_back("[vout]");
    } else if (!clips.empty()) {
        args.push_back("-map");
        args.push_back("0:v");
    }

    // Audio stream mapping
    if (hasCustomAudioMap) {
        args.push_back("-map");
        args.push_back("[aout]");
    } else if (hasNarration) {
        args.push_back("-map");
        args.push_back(std::to_string(audioInputIndex) + ":a:0");
    }

    // Codec & Quality settings
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

static std::string escapeShellArg(const std::string& arg) {
    if (arg.empty()) return "''";
    bool needsQuotes = false;
    for (char c : arg) {
        if (!isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_' && c != '.' && c != '/' && c != ':') {
            needsQuotes = true;
            break;
        }
    }
    if (!needsQuotes) return arg;

    // Standard POSIX single-quote escaping: replace ' with '\''
    std::string escaped = "'";
    for (char c : arg) {
        if (c == '\'') {
            escaped += "'\\''";
        } else {
            escaped += c;
        }
    }
    escaped += "'";
    return escaped;
}

std::string FfmpegGraph::buildCommandLine() const {
    auto args = buildCommandArgs();
    std::ostringstream cmd;
    for (size_t i = 0; i < args.size(); ++i) {
        if (i > 0) cmd << " ";
        cmd << escapeShellArg(args[i]);
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
