#pragma once

#include "core/timeline.hpp"
#include <vector>

namespace HyperEditor {
namespace Tools {

class SpeedRampingTool {
public:
    SpeedRampingTool() = default;
    ~SpeedRampingTool() = default;

    // Evaluates the current speed multiplier at timeline progress t
    double getSpeedAt(const Core::SpeedRampingConfig& config, double timelineTime) const;

    // Calculates the source timestamp corresponding to the given timeline timestamp by integrating the speed curve
    double mapTimelineToSourceTime(const Core::SpeedRampingConfig& config, double timelineTime, double sourceOffset = 0.0) const;

    // Time-stretching for audio samples preserving pitch using SOLA / linear overlap-add
    void stretchAudioSamples(const std::vector<float>& inSamples, int channels, int sampleRate, 
                            double speedFactor, std::vector<float>& outSamples);
};

} // namespace Tools
} // namespace HyperEditor
