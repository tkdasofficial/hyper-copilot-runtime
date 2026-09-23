#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <sstream>
#include <cstring>
#include <algorithm>
#include "scene_builder.hpp"
#include "caption_renderer.hpp"
#include "ffmpeg_graph.hpp"

void printUsage() {
    std::cout << "HyperEditor — C++ Video Scene Builder & Subtitle Engine\n\n"
              << "Usage: hyper_editor [options]\n\n"
              << "Options:\n"
              << "  --help, -h                    Display this help message\n"
              << "  --scenes <file.json>          Input scene definition JSON\n"
              << "  --timeline, -t <file.json>    Timeline specification JSON (scenes/tracks)\n"
              << "  --audio <file.mp3>            Narration audio track\n"
              << "  --bgm <file.mp3>              Background music track (optional)\n"
              << "  --captions <file.ass>         Pre-existing ASS subtitles path to burn\n"
              << "  --words-json <file.json>      Word-level timestamps JSON from TTS\n"
              << "  --generate-captions           Generate and burn synchronized dynamic subtitles\n"
              << "  --caption-size <size>         Small (28/48px), Medium (42/72px), Large (56/96px)\n"
              << "  --caption-style <style>       Dynamic (Gold), Bold (Cyan), Minimal\n"
              << "  --output, -o <file.mp4>       Output video file (default: out.mp4)\n"
              << "  --width <pixels>              Target width (default: 1920)\n"
              << "  --height <pixels>             Target height (default: 1080)\n"
              << "  --fps <rate>                  Target frame rate (default: 60)\n"
              << "  --ken-burns[=bool]            Enable/disable dynamic camera motion (default: true)\n"
              << "  --motion-type <type>          dynamic, zoomin, zoomout, panleft, panright, panup, pandown, none\n"
              << "  --transition-type <type>      fade, wipeleft, wiperight, slideleft, slideright, circlecrop, dissolve, zoom\n"
              << "  --transition-duration <sec>   Duration of transitions in seconds (default: 0.4)\n"
              << "  --color-grading[=bool]        Cinematic color grading eq filter (default: true)\n"
              << "  --contrast <val>              Contrast adjustment (default: 1.05)\n"
              << "  --saturation <val>            Saturation adjustment (default: 1.10)\n"
              << "  --brightness <val>            Brightness adjustment (default: 0.02)\n"
              << "  --vignette[=bool]             Apply lens vignette effect (default: false)\n"
              << "  --dark-gradient[=bool]        Subtitle legibility dark gradient bar (default: true)\n"
              << "  --progress-bar[=bool]         Dynamic time-elapsed progress bar (default: false)\n"
              << "  --progress-bar-color <col>    Color of progress bar (default: white@0.85)\n"
              << "  --watermark <file.png>        Overlay watermark / logo image path\n"
              << "  --watermark-pos <pos>         top-right, top-left, bottom-right, bottom-left\n"
              << "  --watermark-opacity <val>     Opacity for watermark (default: 0.60)\n"
              << "  --speed-factor <val>          Playback speed factor (default: 1.0)\n"
              << "  --dry-run                     Generate and print filter graph without rendering\n"
              << "  --render                      Execute rendering immediately\n";
}

static bool parseBoolVal(const std::string& val, bool defaultVal = true) {
    std::string s = val;
    std::transform(s.begin(), s.end(), s.begin(), ::tolower);
    if (s == "1" || s == "true" || s == "yes" || s == "on") return true;
    if (s == "0" || s == "false" || s == "no" || s == "off") return false;
    return defaultVal;
}

// Lightweight JSON helper for parsing scenes array
// Expected format: [{"file": "path", "start": 0.0, "duration": 4.0, "trim_start": 0.0, "transition": "fade", "motion": "zoomin", "narration": "..."}, ...]
bool parseScenesFile(const std::string& path, hyper::SceneBuilder& builder) {
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "[HyperEditor] Warning: Could not open scenes file: " << path << std::endl;
        return false;
    }

    std::string content((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    size_t pos = 0;
    int sceneIndex = 0;

    while (pos < content.size()) {
        size_t fileKey = content.find("\"file\"", pos);
        if (fileKey == std::string::npos) {
            fileKey = content.find("\"path\"", pos);
        }
        if (fileKey == std::string::npos) break;

        size_t colon = content.find(":", fileKey);
        if (colon == std::string::npos) break;
        size_t q1 = content.find("\"", colon);
        if (q1 == std::string::npos) break;
        size_t q2 = content.find("\"", q1 + 1);
        if (q2 == std::string::npos) break;

        std::string filePath = content.substr(q1 + 1, q2 - q1 - 1);

        double duration = 4.0;
        double startTime = 0.0;
        double trimStart = 0.0;
        double transDur = 0.4;
        double speedFactor = 1.0;
        std::string trans = "fade";
        std::string motionStr = "none";
        std::string narr = "";

        // Find surrounding object boundaries or next fileKey
        size_t nextFileKey = content.find("\"file\"", q2);
        if (nextFileKey == std::string::npos) {
            nextFileKey = content.find("\"path\"", q2);
        }
        size_t limit = (nextFileKey != std::string::npos) ? nextFileKey : content.size();

        // Search for start / startTime
        size_t startPos = content.find("\"start\"", fileKey);
        if (startPos == std::string::npos || startPos >= limit) {
            startPos = content.find("\"startTime\"", fileKey);
        }
        if (startPos != std::string::npos && startPos < limit) {
            size_t c = content.find(":", startPos);
            if (c != std::string::npos) {
                startTime = std::stod(content.substr(c + 1));
            }
        }

        // Search for duration
        size_t durPos = content.find("\"duration\"", fileKey);
        if (durPos != std::string::npos && durPos < limit) {
            size_t c = content.find(":", durPos);
            if (c != std::string::npos) {
                duration = std::stod(content.substr(c + 1));
            }
        }

        // Search for trim_start / trimStart
        size_t trimPos = content.find("\"trim_start\"", fileKey);
        if (trimPos == std::string::npos || trimPos >= limit) {
            trimPos = content.find("\"trimStart\"", fileKey);
        }
        if (trimPos != std::string::npos && trimPos < limit) {
            size_t c = content.find(":", trimPos);
            if (c != std::string::npos) {
                trimStart = std::stod(content.substr(c + 1));
            }
        }

        // Search for speed_factor / speed
        size_t spdPos = content.find("\"speed_factor\"", fileKey);
        if (spdPos == std::string::npos || spdPos >= limit) {
            spdPos = content.find("\"speed\"", fileKey);
        }
        if (spdPos != std::string::npos && spdPos < limit) {
            size_t c = content.find(":", spdPos);
            if (c != std::string::npos) {
                speedFactor = std::stod(content.substr(c + 1));
            }
        }

        // Search for transition
        size_t transPos = content.find("\"transition\"", fileKey);
        if (transPos != std::string::npos && transPos < limit) {
            size_t tq1 = content.find("\"", transPos + 12);
            if (tq1 != std::string::npos && tq1 < limit) {
                size_t tq2 = content.find("\"", tq1 + 1);
                if (tq2 != std::string::npos && tq2 < limit) {
                    trans = content.substr(tq1 + 1, tq2 - tq1 - 1);
                }
            }
        }

        // Search for transition_duration
        size_t transDurPos = content.find("\"transition_duration\"", fileKey);
        if (transDurPos != std::string::npos && transDurPos < limit) {
            size_t c = content.find(":", transDurPos);
            if (c != std::string::npos) {
                transDur = std::stod(content.substr(c + 1));
            }
        }

        // Search for motion / ken_burns
        size_t motPos = content.find("\"motion\"", fileKey);
        if (motPos == std::string::npos || motPos >= limit) {
            motPos = content.find("\"ken_burns\"", fileKey);
        }
        if (motPos != std::string::npos && motPos < limit) {
            size_t mq1 = content.find("\"", motPos + 8);
            if (mq1 != std::string::npos && mq1 < limit) {
                size_t mq2 = content.find("\"", mq1 + 1);
                if (mq2 != std::string::npos && mq2 < limit) {
                    motionStr = content.substr(mq1 + 1, mq2 - mq1 - 1);
                }
            }
        }

        // Search for narration
        size_t narrPos = content.find("\"narration\"", fileKey);
        if (narrPos != std::string::npos && narrPos < limit) {
            size_t nq1 = content.find("\"", narrPos + 11);
            if (nq1 != std::string::npos && nq1 < limit) {
                size_t nq2 = content.find("\"", nq1 + 1);
                if (nq2 != std::string::npos && nq2 < limit) {
                    narr = content.substr(nq1 + 1, nq2 - nq1 - 1);
                }
            }
        }

        // Detect if image
        std::string lowerPath = filePath;
        std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);
        bool isImg = (lowerPath.find(".jpg") != std::string::npos ||
                      lowerPath.find(".jpeg") != std::string::npos ||
                      lowerPath.find(".png") != std::string::npos ||
                      lowerPath.find(".webp") != std::string::npos);

        hyper::TimelineClip clip;
        clip.id = "clip_" + std::to_string(sceneIndex);
        clip.file_path = filePath;
        clip.start_time = startTime;
        clip.duration = duration;
        clip.source_trim_start = trimStart;
        clip.speed_factor = (speedFactor > 0.05) ? speedFactor : 1.0;
        clip.motion = hyper::SceneBuilder::parseMotion(motionStr);
        clip.transition = hyper::SceneBuilder::parseTransition(trans);
        clip.transition_duration = transDur;
        clip.is_image = isImg;

        hyper::SceneSegment seg;
        seg.index = sceneIndex++;
        seg.start_time = startTime;
        seg.duration = duration;
        seg.narration_text = narr;
        seg.clips.push_back(clip);

        builder.addScene(seg);
        pos = q2 + 1;
    }

    std::cout << "[HyperEditor] Parsed " << sceneIndex << " timeline scenes from " << path << std::endl;
    return (sceneIndex > 0);
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage();
        return 0;
    }

    std::string scenesPath;
    std::string timelinePath;
    std::string audioPath;
    std::string bgmPath;
    std::string captionsPath;
    std::string wordsJsonPath;
    std::string outputPath = "out.mp4";
    int width = 1920;
    int height = 1080;
    int fps = 60;
    hyper::CaptionSize captionSize = hyper::CaptionSize::Medium;
    hyper::CaptionStyle captionStyle = hyper::CaptionStyle::Dynamic;
    bool generateCaptions = false;
    bool dryRun = false;
    bool doRender = true;

    hyper::FfmpegGraphConfig config;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            printUsage();
            return 0;
        } else if (arg == "--scenes" && i + 1 < argc) {
            scenesPath = argv[++i];
        } else if ((arg == "--timeline" || arg == "-t") && i + 1 < argc) {
            timelinePath = argv[++i];
        } else if (arg == "--audio" && i + 1 < argc) {
            audioPath = argv[++i];
        } else if (arg == "--bgm" && i + 1 < argc) {
            bgmPath = argv[++i];
        } else if (arg == "--captions" && i + 1 < argc) {
            captionsPath = argv[++i];
        } else if (arg == "--words-json" && i + 1 < argc) {
            wordsJsonPath = argv[++i];
        } else if (arg == "--generate-captions") {
            generateCaptions = true;
        } else if ((arg == "--output" || arg == "-o") && i + 1 < argc) {
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
        } else if (arg.rfind("--ken-burns=", 0) == 0) {
            config.ken_burns_enabled = parseBoolVal(arg.substr(12));
        } else if (arg == "--ken-burns") {
            if (i + 1 < argc && (std::string(argv[i+1]) == "true" || std::string(argv[i+1]) == "false")) {
                config.ken_burns_enabled = parseBoolVal(argv[++i]);
            } else {
                config.ken_burns_enabled = true;
            }
        } else if (arg == "--no-ken-burns") {
            config.ken_burns_enabled = false;
        } else if (arg == "--motion-type" && i + 1 < argc) {
            config.motion_type = argv[++i];
        } else if (arg == "--transition-type" && i + 1 < argc) {
            config.default_transition = hyper::SceneBuilder::parseTransition(argv[++i]);
        } else if (arg == "--transition-duration" && i + 1 < argc) {
            config.default_transition_duration = std::stod(argv[++i]);
        } else if (arg.rfind("--color-grading=", 0) == 0) {
            config.color_grading_enabled = parseBoolVal(arg.substr(16));
        } else if (arg == "--color-grading") {
            if (i + 1 < argc && (std::string(argv[i+1]) == "true" || std::string(argv[i+1]) == "false")) {
                config.color_grading_enabled = parseBoolVal(argv[++i]);
            } else {
                config.color_grading_enabled = true;
            }
        } else if (arg == "--no-color-grading") {
            config.color_grading_enabled = false;
        } else if (arg == "--contrast" && i + 1 < argc) {
            config.contrast = std::stod(argv[++i]);
        } else if (arg == "--saturation" && i + 1 < argc) {
            config.saturation = std::stod(argv[++i]);
        } else if (arg == "--brightness" && i + 1 < argc) {
            config.brightness = std::stod(argv[++i]);
        } else if (arg.rfind("--vignette=", 0) == 0) {
            config.vignette_enabled = parseBoolVal(arg.substr(11));
        } else if (arg == "--vignette") {
            if (i + 1 < argc && (std::string(argv[i+1]) == "true" || std::string(argv[i+1]) == "false")) {
                config.vignette_enabled = parseBoolVal(argv[++i]);
            } else {
                config.vignette_enabled = true;
            }
        } else if (arg == "--no-vignette") {
            config.vignette_enabled = false;
        } else if (arg.rfind("--dark-gradient=", 0) == 0) {
            config.dark_gradient_overlay = parseBoolVal(arg.substr(16));
        } else if (arg == "--dark-gradient") {
            if (i + 1 < argc && (std::string(argv[i+1]) == "true" || std::string(argv[i+1]) == "false")) {
                config.dark_gradient_overlay = parseBoolVal(argv[++i]);
            } else {
                config.dark_gradient_overlay = true;
            }
        } else if (arg == "--no-dark-gradient") {
            config.dark_gradient_overlay = false;
        } else if (arg.rfind("--progress-bar=", 0) == 0) {
            config.progress_bar_enabled = parseBoolVal(arg.substr(15));
        } else if (arg == "--progress-bar") {
            if (i + 1 < argc && (std::string(argv[i+1]) == "true" || std::string(argv[i+1]) == "false")) {
                config.progress_bar_enabled = parseBoolVal(argv[++i]);
            } else {
                config.progress_bar_enabled = true;
            }
        } else if (arg == "--no-progress-bar") {
            config.progress_bar_enabled = false;
        } else if (arg == "--progress-bar-color" && i + 1 < argc) {
            config.progress_bar_color = argv[++i];
        } else if (arg == "--watermark" && i + 1 < argc) {
            config.watermark_path = argv[++i];
        } else if (arg == "--watermark-pos" && i + 1 < argc) {
            config.watermark_position = argv[++i];
        } else if (arg == "--watermark-opacity" && i + 1 < argc) {
            config.watermark_opacity = std::stod(argv[++i]);
        } else if (arg == "--speed-factor" && i + 1 < argc) {
            config.global_speed_factor = std::stod(argv[++i]);
        } else if (arg == "--dry-run") {
            dryRun = true;
            doRender = false;
        } else if (arg == "--render") {
            doRender = true;
        }
    }

    hyper::SceneBuilder builder(width, height, fps);
    std::string activeSpecPath = !scenesPath.empty() ? scenesPath : timelinePath;
    if (!activeSpecPath.empty()) {
        parseScenesFile(activeSpecPath, builder);
    }

    // =========================================================================
    // C++ NATIVE SUBTITLE GENERATOR & BURN-IN ENGINE
    // =========================================================================
    bool shouldBuildCaptions = generateCaptions || captionsPath.empty();
    if (shouldBuildCaptions) {
        hyper::CaptionRenderer captionGen(width, height, captionSize, captionStyle);
        bool loaded = false;

        if (!wordsJsonPath.empty()) {
            std::cout << "[HyperEditor] C++ Subtitle Engine: Loading word timestamps from " << wordsJsonPath << "..." << std::endl;
            loaded = captionGen.loadFromWordsJson(wordsJsonPath);
        }

        if (!loaded && !builder.getScenes().empty()) {
            std::cout << "[HyperEditor] C++ Subtitle Engine: Synthesizing word timings from scene narrations..." << std::endl;
            loaded = captionGen.loadFromScenes(builder.getScenes());
        }

        if (loaded && captionGen.getWordCount() > 0) {
            // Determine destination ASS path
            std::string autoAssPath = "captions_rendered.ass";
            size_t slashPos = outputPath.find_last_of("/\\");
            if (slashPos != std::string::npos) {
                autoAssPath = outputPath.substr(0, slashPos + 1) + "captions_rendered.ass";
            } else {
                autoAssPath = "captions_rendered.ass";
            }

            if (captionGen.exportAssFile(autoAssPath)) {
                captionsPath = autoAssPath;
                std::cout << "[HyperEditor] C++ Subtitle Engine: Successfully prepared active karaoke captions: "
                          << captionsPath << " (Words: " << captionGen.getWordCount() << ")" << std::endl;
            }
        }
    }

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

    if (doRender && !activeSpecPath.empty()) {
        std::cout << "[HyperEditor] Starting video render -> " << outputPath
                  << " (Width: " << width << ", Height: " << height
                  << ", KenBurns: " << (config.ken_burns_enabled ? config.motion_type : "off")
                  << ", Transition: " << hyper::SceneBuilder::transitionToString(config.default_transition)
                  << ", ColorGrading: " << (config.color_grading_enabled ? "on" : "off")
                  << ", Captions: " << (config.burn_captions ? captionsPath : "None") << ")" << std::endl;
        return graph.execute();
    }

    return 0;
}
