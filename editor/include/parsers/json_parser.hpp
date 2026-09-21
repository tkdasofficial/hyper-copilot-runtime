#pragma once

#include "core/timeline.hpp"
#include <string>
#include <nlohmann/json.hpp>

namespace HyperEditor {
namespace Parsers {

class JsonParser {
public:
    JsonParser() = default;
    ~JsonParser() = default;

    // Parses JSON file from disk into Core::Timeline
    static bool parseFile(const std::string& filePath, Core::Timeline& outTimeline);

    // Parses JSON string representation into Core::Timeline
    static bool parseString(const std::string& jsonContent, Core::Timeline& outTimeline);

private:
    static void parseTimelineSettings(const nlohmann::json& j, Core::Timeline& outTimeline);
    static void parseClips(const nlohmann::json& j, Core::Timeline& outTimeline);
    static void parseAudioTracks(const nlohmann::json& j, Core::Timeline& outTimeline);
    static void parseCaptions(const nlohmann::json& j, Core::Timeline& outTimeline);

    static Core::Keyframe parseKeyframe(const nlohmann::json& j);
    static Core::MaskConfig parseMask(const nlohmann::json& j);
    static Core::OverlayConfig parseOverlay(const nlohmann::json& j);
    static Core::TransitionConfig parseTransition(const nlohmann::json& j);
    static Core::ColorGradingConfig parseColorGrading(const nlohmann::json& j);
    static Core::MotionZoomConfig parseMotionZoom(const nlohmann::json& j);
    static Core::SpeedRampingConfig parseSpeedRamping(const nlohmann::json& j);
    static Core::ChromaKeyConfig parseChromaKey(const nlohmann::json& j);
    static Core::FrameScalerConfig parseFrameScaler(const nlohmann::json& j);
    static Core::AudioEffectsConfig parseAudioEffects(const nlohmann::json& j);
};

} // namespace Parsers
} // namespace HyperEditor
