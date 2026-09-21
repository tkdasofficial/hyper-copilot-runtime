#include "core/editor.hpp"
#include "utils/logger.hpp"
#include "utils/memory.hpp"
#include <chrono>
#include <thread>
#include <filesystem>
#include <map>
#include <algorithm>
#include <cstring>

namespace HyperEditor {
namespace Core {

AdvancedHeadlessEditor::AdvancedHeadlessEditor() {
    threadCount_ = static_cast<int>(std::thread::hardware_concurrency());
    if (threadCount_ <= 0) threadCount_ = 4;
}

void AdvancedHeadlessEditor::setThreadCount(int threads) {
    if (threads > 0) {
        threadCount_ = threads;
    }
}

bool AdvancedHeadlessEditor::render(const Timeline& timeline) {
    LOG_INFO("AdvancedHeadlessEditor", "=======================================================");
    LOG_INFO("AdvancedHeadlessEditor", "  STARTING ADVANCED HEADLESS EDITOR RENDERING PIPELINE  ");
    LOG_INFO("AdvancedHeadlessEditor", "=======================================================");
    LOG_INFO("AdvancedHeadlessEditor", "Target Output: ", timeline.outputPath);
    LOG_INFO("AdvancedHeadlessEditor", "Resolution: ", timeline.width, "x", timeline.height, 
             " @ ", timeline.fps, " FPS | Duration: ", timeline.duration, "s");
    LOG_INFO("AdvancedHeadlessEditor", "Active Threads: ", threadCount_);

    auto startTime = std::chrono::steady_clock::now();

    MediaEncoder encoder;
    if (!encoder.initialize(timeline.outputPath, timeline.width, timeline.height, 
                            timeline.fps, timeline.sampleRate, timeline.channels)) {
        LOG_ERROR("AdvancedHeadlessEditor", "Failed to initialize master MediaEncoder");
        return false;
    }

    // 1. Render Video Track Frames
    LOG_INFO("AdvancedHeadlessEditor", "Stage 1/2: Processing and Encoding Video Frame Composition...");
    if (!renderVideoTrack(timeline, encoder)) {
        LOG_ERROR("AdvancedHeadlessEditor", "Video rendering pipeline failed");
        return false;
    }

    // 2. Render and Mix Audio Tracks
    LOG_INFO("AdvancedHeadlessEditor", "Stage 2/2: Mixing Audio Tracks and Auto-Ducking...");
    if (!renderAudioTrack(timeline, encoder)) {
        LOG_WARN("AdvancedHeadlessEditor", "Audio track rendering encountered warnings");
    }

    // 3. Finalize Master MP4 File
    if (!encoder.finalize()) {
        LOG_ERROR("AdvancedHeadlessEditor", "Failed to finalize output container");
        return false;
    }

    auto endTime = std::chrono::steady_clock::now();
    double elapsedSec = std::chrono::duration<double>(endTime - startTime).count();
    int64_t totalFrames = static_cast<int64_t>(timeline.duration * timeline.fps);
    double renderFps = (elapsedSec > 0.0) ? (totalFrames / elapsedSec) : 0.0;

    LOG_INFO("AdvancedHeadlessEditor", "=======================================================");
    LOG_INFO("AdvancedHeadlessEditor", "  ADVANCED HEADLESS EDITOR RENDERING COMPLETE!         ");
    LOG_INFO("AdvancedHeadlessEditor", "=======================================================");
    LOG_INFO("AdvancedHeadlessEditor", "Render Time: ", elapsedSec, "s (", renderFps, " fps)");
    if (std::filesystem::exists(timeline.outputPath)) {
        auto fileSize = std::filesystem::file_size(timeline.outputPath);
        LOG_INFO("AdvancedHeadlessEditor", "Master Output File: ", timeline.outputPath, 
                 " (", fileSize / (1024 * 1024), " MB)");
    }

    return true;
}

bool AdvancedHeadlessEditor::renderVideoTrack(const Timeline& timeline, MediaEncoder& encoder) {
    int totalFrames = static_cast<int>(timeline.duration * timeline.fps);
    if (totalFrames <= 0) totalFrames = 1;

    // Cache opened decoders per unique file path
    std::map<std::string, std::unique_ptr<VideoDecoder>> decoders;
    for (const auto& clip : timeline.videoClips) {
        if (!clip.filePath.empty() && std::filesystem::exists(clip.filePath)) {
            if (decoders.find(clip.filePath) == decoders.end()) {
                auto dec = std::make_unique<VideoDecoder>();
                if (dec->open(clip.filePath, timeline.width, timeline.height)) {
                    decoders[clip.filePath] = std::move(dec);
                }
            }
        }
    }

    auto masterCanvas = Utils::makeVideoFrame(timeline.width, timeline.height, AV_PIX_FMT_RGBA);
    auto clipBuffer = Utils::makeVideoFrame(timeline.width, timeline.height, AV_PIX_FMT_RGBA);
    auto tempBuffer = Utils::makeVideoFrame(timeline.width, timeline.height, AV_PIX_FMT_RGBA);

    auto renderStart = std::chrono::steady_clock::now();

    for (int frameIdx = 0; frameIdx < totalFrames; ++frameIdx) {
        double currentTime = static_cast<double>(frameIdx) / timeline.fps;

        // Clear Canvas with Background Color
        uint8_t bgR = (timeline.backgroundColor >> 24) & 0xFF;
        uint8_t bgG = (timeline.backgroundColor >> 16) & 0xFF;
        uint8_t bgB = (timeline.backgroundColor >> 8) & 0xFF;
        uint8_t bgA = timeline.backgroundColor & 0xFF;

        #pragma omp parallel for schedule(static)
        for (int y = 0; y < timeline.height; ++y) {
            uint8_t* row = masterCanvas->data[0] + y * masterCanvas->linesize[0];
            for (int x = 0; x < timeline.width; ++x) {
                row[x * 4 + 0] = bgR;
                row[x * 4 + 1] = bgG;
                row[x * 4 + 2] = bgB;
                row[x * 4 + 3] = bgA;
            }
        }

        // Gather and sort active clips at this timestamp by trackIndex
        std::vector<const Clip*> activeClips;
        for (const auto& clip : timeline.videoClips) {
            if (currentTime >= clip.startTime && currentTime <= (clip.startTime + clip.duration)) {
                activeClips.push_back(&clip);
            }
        }
        std::sort(activeClips.begin(), activeClips.end(), [](const Clip* a, const Clip* b) {
            return a->trackIndex < b->trackIndex;
        });

        // If no video clips are active on the timeline, generate synthetic visual backdrop
        if (activeClips.empty()) {
            SyntheticMediaGenerator::generateVideoFrame(masterCanvas.get(), currentTime, 0);
        }

        for (const Clip* clip : activeClips) {
            double clipTime = currentTime - clip->startTime;
            double sourceTime = speedRampingTool_.mapTimelineToSourceTime(
                clip->speedRamping, clipTime, clip->sourceOffset);

            // Fetch video frame from file or synthetic generator
            bool frameFetched = false;
            auto it = decoders.find(clip->filePath);
            if (it != decoders.end() && it->second) {
                frameFetched = it->second->getFrameAt(sourceTime, clipBuffer.get());
            }

            if (!frameFetched) {
                // Synthetic procedural pattern
                int pattern = clip->chromaKey.enabled ? 1 : 0;
                SyntheticMediaGenerator::generateVideoFrame(clipBuffer.get(), sourceTime, pattern);
            }

            // 1. Frame Scaler Tool (Aspect ratio scaling & smart crop)
            frameScalerTool_.scale(tempBuffer.get(), clipBuffer.get(), clip->frameScaler, timeline.backgroundColor);

            // 2. Chroma Key Tool
            if (clip->chromaKey.enabled) {
                chromaKeyTool_.process(tempBuffer.get(), clip->chromaKey);
            }

            // 3. Color Grading & 3D LUT Tool
            colorGradingTool_.process(tempBuffer.get(), clip->colorGrading);

            // 4. Motion Zoom (Ken Burns) Tool
            if (clip->motionZoom.enabled) {
                double progress = clip->duration > 0.0 ? (clipTime / clip->duration) : 0.0;
                motionZoomTool_.apply(clipBuffer.get(), tempBuffer.get(), clip->motionZoom, progress);
                // Copy result back to tempBuffer
                for (int y = 0; y < timeline.height; ++y) {
                    std::memcpy(tempBuffer->data[0] + y * tempBuffer->linesize[0],
                                clipBuffer->data[0] + y * clipBuffer->linesize[0],
                                timeline.width * 4);
                }
            }

            // 5. Masking Tool
            if (clip->mask.type != MaskType::None) {
                maskingTool_.applyMask(tempBuffer.get(), clip->mask);
            }

            // 6. Keyframing Tool
            OverlayConfig currentOverlay = clip->overlay;
            if (!clip->keyframes.empty()) {
                auto kfState = keyframingTool_.evaluate(clip->keyframes, clipTime);
                currentOverlay.posX = static_cast<int>(kfState.posX);
                currentOverlay.posY = static_cast<int>(kfState.posY);
                currentOverlay.opacity = kfState.opacity;
                if (kfState.scaleX > 0.0 && kfState.scaleY > 0.0) {
                    currentOverlay.width = static_cast<int>(timeline.width * kfState.scaleX);
                    currentOverlay.height = static_cast<int>(timeline.height * kfState.scaleY);
                }
            }

            // 7. Transitions Tool
            if (clip->transitionIn.type != TransitionType::None && clipTime < clip->transitionIn.duration) {
                double transProgress = clipTime / clip->transitionIn.duration;
                transitionsTool_.renderTransition(tempBuffer.get(), masterCanvas.get(), tempBuffer.get(),
                                                  clip->transitionIn.type, transProgress);
            } else if (clip->transitionOut.type != TransitionType::None && 
                       clipTime > (clip->duration - clip->transitionOut.duration)) {
                double transProgress = (clipTime - (clip->duration - clip->transitionOut.duration)) / 
                                        clip->transitionOut.duration;
                transitionsTool_.renderTransition(tempBuffer.get(), tempBuffer.get(), masterCanvas.get(),
                                                  clip->transitionOut.type, transProgress);
            }

            // 8. Overlays & Blending Tool
            overlaysTool_.blend(masterCanvas.get(), tempBuffer.get(), currentOverlay);
        }

        // 9. Dynamic Captions Tool (word-by-word highlights, neon glow)
        captionsTool_.render(masterCanvas.get(), timeline.captions, currentTime);

        // Encode Frame to MP4 Container
        encoder.encodeVideoFrame(masterCanvas.get(), frameIdx);

        if (frameIdx % 15 == 0 || frameIdx == totalFrames - 1) {
            auto now = std::chrono::steady_clock::now();
            double curElapsed = std::chrono::duration<double>(now - renderStart).count();
            double curFps = (curElapsed > 0.0) ? (frameIdx + 1) / curElapsed : 0.0;
            Utils::Logger::instance().progress("Rendering Video", frameIdx + 1, totalFrames, curFps);
        }
    }

    return true;
}

bool AdvancedHeadlessEditor::renderAudioTrack(const Timeline& timeline, MediaEncoder& encoder) {
    std::vector<Tools::AudioBuffer> trackBuffers;
    std::vector<AudioTrack> validTracks;

    for (const auto& track : timeline.audioTracks) {
        Tools::AudioBuffer buf;
        buf.sampleRate = timeline.sampleRate;
        buf.channels = timeline.channels;

        bool loaded = false;
        if (!track.filePath.empty() && std::filesystem::exists(track.filePath)) {
            AudioDecoder dec;
            if (dec.open(track.filePath, timeline.sampleRate, timeline.channels)) {
                loaded = dec.decodeAll(buf);
            }
        }

        if (!loaded) {
            // Generate synthetic clean test audio tone for testing
            double trackDur = (track.duration > 0.0) ? track.duration : timeline.duration;
            double toneFreq = track.isVoiceover ? 800.0 : 220.0; // higher tone for voiceover, lower for BGM
            SyntheticMediaGenerator::generateAudioTrack(buf, trackDur, toneFreq);
        }

        // Apply Audio Effects & EQ Tool
        audioEffectsTool_.process(buf.samples, buf.channels, buf.sampleRate, track.effects);

        trackBuffers.push_back(std::move(buf));
        validTracks.push_back(track);
    }

    // If no explicit audio tracks were provided, generate synthetic master audio
    if (trackBuffers.empty()) {
        Tools::AudioBuffer defaultBgm;
        SyntheticMediaGenerator::generateAudioTrack(defaultBgm, timeline.duration, 440.0);
        trackBuffers.push_back(defaultBgm);

        AudioTrack defTrack;
        defTrack.id = "default_bgm";
        defTrack.duration = timeline.duration;
        defTrack.volume = 0.5;
        validTracks.push_back(defTrack);
    }

    // Mix Tracks with Auto-Ducking Tool
    Tools::AudioBuffer masterAudio;
    masterAudio.sampleRate = timeline.sampleRate;
    masterAudio.channels = timeline.channels;

    audioMixerTool_.mix(masterAudio, trackBuffers, validTracks, timeline.duration);

    // Encode to AAC
    return encoder.encodeAudioBuffer(masterAudio);
}

} // namespace Core
} // namespace HyperEditor
