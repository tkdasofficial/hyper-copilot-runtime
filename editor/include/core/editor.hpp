#pragma once

#include "core/timeline.hpp"
#include "core/ffmpeg_bridge.hpp"
#include "tools/keyframing.hpp"
#include "tools/masking.hpp"
#include "tools/overlays.hpp"
#include "tools/captions.hpp"
#include "tools/transitions.hpp"
#include "tools/audio_mixer.hpp"
#include "tools/color_grading.hpp"
#include "tools/motion_zoom.hpp"
#include "tools/speed_ramping.hpp"
#include "tools/chroma_key.hpp"
#include "tools/audio_effects.hpp"
#include "tools/frame_scaler.hpp"
#include "utils/memory.hpp"
#include "utils/logger.hpp"

#include <memory>
#include <vector>
#include <string>

namespace HyperEditor {
namespace Core {

// Advanced Headless Editor Orchestrator
class AdvancedHeadlessEditor {
public:
    AdvancedHeadlessEditor();
    ~AdvancedHeadlessEditor() = default;

    // Sets concurrency thread count (0 = auto-detect CPU cores)
    void setThreadCount(int threads);

    // Executes complete headless render for the provided Timeline configuration
    bool render(const Timeline& timeline);

private:
    // Core render pipeline stages
    bool renderVideoTrack(const Timeline& timeline, MediaEncoder& encoder);
    bool renderAudioTrack(const Timeline& timeline, MediaEncoder& encoder);

    // Single frame composition pipeline through active tools
    void composeFrame(AVFrame* masterCanvas, const Timeline& timeline, double currentTime, int64_t frameIndex);

    // The 12 Headless Editor Tools
    Tools::KeyframingTool keyframingTool_;
    Tools::MaskingTool maskingTool_;
    Tools::OverlaysTool overlaysTool_;
    Tools::CaptionsTool captionsTool_;
    Tools::TransitionsTool transitionsTool_;
    Tools::AudioMixerTool audioMixerTool_;
    Tools::ColorGradingTool colorGradingTool_;
    Tools::MotionZoomTool motionZoomTool_;
    Tools::SpeedRampingTool speedRampingTool_;
    Tools::ChromaKeyTool chromaKeyTool_;
    Tools::AudioEffectsTool audioEffectsTool_;
    Tools::FrameScalerTool frameScalerTool_;

    int threadCount_ = 0;
};

} // namespace Core
} // namespace HyperEditor
