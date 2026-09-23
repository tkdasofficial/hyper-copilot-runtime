#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <sstream>
#include <cstring>
#include <cstdlib>
#include "scene_builder.hpp"
#include "caption_renderer.hpp"
#include "ffmpeg_graph.hpp"
#include "pipeline_runner.hpp"
#include "drive_exporter.hpp"

void printUsage() {
    std::cout << "HyperEditor — Pure C++ Video Scene Builder & Pipeline Engine\n\n"
              << "Usage: hyper_editor [options]\n\n"
              << "Execution Modes:\n"
              << "  --pipeline                    Execute complete end-to-end video pipeline\n"
              << "  --export-drive <file.mp4>     Export rendered video to Google Drive\n"
              << "  --render                      Render scene graph directly\n"
              << "  --dry-run                     Generate and print filter graph without rendering\n\n"
              << "Scene Graph Options:\n"
              << "  --scenes <file.json>          Input scene definition JSON\n"
              << "  --audio <file.mp3>            Narration audio track\n"
              << "  --bgm <file.mp3>              Background music track (optional)\n"
              << "  --captions <file.ass>         Burn-in ASS captions path\n"
              << "  --output <file.mp4>           Output video file (default: out.mp4)\n"
              << "  --width <pixels>              Target width (default: 1920)\n"
              << "  --height <pixels>             Target height (default: 1080)\n"
              << "  --fps <rate>                  Target frame rate (default: 60)\n"
              << "  --caption-size <size>         Small (28px@1080p), Medium (42px@1080p), Large (56px@1080p)\n"
              << "  --caption-style <style>       Dynamic, Bold, Minimal\n";
}

bool parseScenesFile(const std::string& path, hyper::SceneBuilder& builder) {
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "[HyperEditor] Warning: Could not open scenes file: " << path << std::endl;
        return false;
    }

    std::string content((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    size_t pos = 0;
    int sceneIndex = 0;

    while ((pos = content.find("file", pos)) != std::string::npos) {
        size_t quoteStart = content.find("\"", pos + 4);
        if (quoteStart == std::string::npos) break;
        quoteStart = content.find("\"", quoteStart + 1);
        if (quoteStart == std::string::npos) break;
        size_t quoteEnd = content.find("\"", quoteStart + 1);
        if (quoteEnd == std::string::npos) break;

        std::string filePath = content.substr(quoteStart + 1, quoteEnd - quoteStart - 1);

        double duration = 4.0;
        double trimStart = 0.0;
        double transDur = 0.4;
        std::string trans = "fade";

        size_t durPos = content.find("duration", pos);
        if (durPos != std::string::npos && durPos < content.find("file", quoteEnd)) {
            size_t colon = content.find(":", durPos);
            if (colon != std::string::npos) {
                duration = std::stod(content.substr(colon + 1));
            }
        }

        size_t trimPos = content.find("trim_start", pos);
        if (trimPos != std::string::npos && trimPos < content.find("file", quoteEnd)) {
            size_t colon = content.find(":", trimPos);
            if (colon != std::string::npos) {
                trimStart = std::stod(content.substr(colon + 1));
            }
        }

        size_t transPos = content.find("transition", pos);
        if (transPos != std::string::npos && transPos < content.find("file", quoteEnd)) {
            size_t q1 = content.find("\"", transPos + 10);
            if (q1 != std::string::npos) {
                size_t q2 = content.find("\"", q1 + 1);
                if (q2 != std::string::npos) {
                    trans = content.substr(q1 + 1, q2 - q1 - 1);
                }
            }
        }

        hyper::TimelineClip clip;
        clip.id = "clip_" + std::to_string(sceneIndex);
        clip.file_path = filePath;
        clip.duration = duration;
        clip.source_trim_start = trimStart;
        clip.transition = hyper::SceneBuilder::parseTransition(trans);
        clip.transition_duration = transDur;

        hyper::SceneSegment seg;
        seg.index = sceneIndex++;
        seg.duration = duration;
        seg.clips.push_back(clip);

        builder.addScene(seg);
        pos = quoteEnd + 1;
    }

    return true;
}

int main(int argc, char* argv[]) {
    // Check if pipeline execution was requested or automatically triggered
    bool runPipeline = false;
    std::string driveExportFile;

    std::string execName = (argc > 0 && argv[0]) ? argv[0] : "";
    if (execName.find("hyper_drive_export") != std::string::npos) {
        driveExportFile = (argc > 1) ? argv[1] : "rendered_video.mp4";
    } else if (execName.find("hyper_pipeline") != std::string::npos || execName.find("hyper_long_form") != std::string::npos) {
        runPipeline = true;
    }

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--pipeline" || arg == "--auto") {
            runPipeline = true;
        } else if (arg == "--export-drive" && i + 1 < argc) {
            driveExportFile = argv[++i];
        }
    }

    // Direct Google Drive export action
    if (!driveExportFile.empty()) {
        const char* vid = std::getenv("VIDEO_ID");
        const char* prompt = std::getenv("PROMPT");
        std::string vIdStr = vid ? vid : "video_export";
        std::string titleStr = prompt ? prompt : "AI Video";
        hyper::DriveExportResult res = hyper::DriveExporter::exportFile(driveExportFile, vIdStr, titleStr);
        return res.success ? 0 : 1;
    }

    // If --pipeline requested, or if PROMPT/VIDEO_ID environment variables are set and no --scenes flag
    const char* promptEnv = std::getenv("PROMPT");
    const char* vidEnv = std::getenv("VIDEO_ID");
    bool hasScenesArg = false;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--scenes") {
            hasScenesArg = true;
            break;
        }
    }

    if (runPipeline || ((promptEnv || vidEnv) && !hasScenesArg)) {
        hyper::PipelineConfig cfg = hyper::PipelineRunner::parseEnvAndArgs(argc, argv);
        return hyper::PipelineRunner::run(cfg);
    }

    if (argc < 2) {
        printUsage();
        return 0;
    }

    std::string scenesPath;
    std::string audioPath;
    std::string bgmPath;
    std::string captionsPath;
    std::string outputPath = "out.mp4";
    int width = 1920;
    int height = 1080;
    int fps = 60;
    hyper::CaptionSize captionSize = hyper::CaptionSize::Medium;
    hyper::CaptionStyle captionStyle = hyper::CaptionStyle::Dynamic;
    bool dryRun = false;
    bool doRender = true;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            printUsage();
            return 0;
        } else if (arg == "--scenes" && i + 1 < argc) {
            scenesPath = argv[++i];
        } else if (arg == "--audio" && i + 1 < argc) {
            audioPath = argv[++i];
        } else if (arg == "--bgm" && i + 1 < argc) {
            bgmPath = argv[++i];
        } else if (arg == "--captions" && i + 1 < argc) {
            captionsPath = argv[++i];
        } else if (arg == "--output" && i + 1 < argc) {
            outputPath = argv[++i];
        } else if (arg == "--width" && i + 1 < argc) {
            width = std::stoi(argv[++i]);
        } else if (arg == "--height" && i + 1 < argc) {
            height = std::stoi(argv[++i]);
        } else if (arg == "--fps" && i + 1 < argc) {
            fps = std::stoi(argv[++i]);
        } else if (arg == "--caption-size" && i + 1 < argc) {
            captionSize = hyper::CaptionRenderer::parseSize(argv[++i]);
        } else if (arg == "--caption-style" && i + 1 < argc) {
            captionStyle = hyper::CaptionRenderer::parseStyle(argv[++i]);
        } else if (arg == "--dry-run") {
            dryRun = true;
            doRender = false;
        } else if (arg == "--render") {
            doRender = true;
        }
    }

    hyper::SceneBuilder builder(width, height, fps);
    if (!scenesPath.empty()) {
        parseScenesFile(scenesPath, builder);
    }

    hyper::FfmpegGraphConfig config;
    config.narration_audio_path = audioPath;
    config.bgm_audio_path = bgmPath;
    config.captions_ass_path = captionsPath;
    config.output_path = outputPath;
    config.burn_captions = !captionsPath.empty();

    hyper::FfmpegGraph graph(builder, config);

    if (dryRun) {
        std::cout << "[HyperEditor] Filter Complex String:\n"
                  << graph.buildFilterComplex() << "\n\n"
                  << "[HyperEditor] Full Command Line:\n"
                  << graph.buildCommandLine() << std::endl;
        return 0;
    }

    if (doRender && !scenesPath.empty()) {
        return graph.execute();
    }

    return 0;
}
