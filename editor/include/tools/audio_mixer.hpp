#pragma once

#include "core/timeline.hpp"
#include <vector>
#include <cstdint>

namespace HyperEditor {
namespace Tools {

struct AudioBuffer {
    int sampleRate = 48000;
    int channels = 2;
    std::vector<float> samples; // interleaved stereo L, R, L, R...
};

class AudioMixerTool {
public:
    AudioMixerTool() = default;
    ~AudioMixerTool() = default;

    // Mixes multiple audio buffers into a master audio buffer with auto-ducking for background music
    void mix(AudioBuffer& masterBuffer, 
             const std::vector<AudioBuffer>& trackBuffers,
             const std::vector<Core::AudioTrack>& trackConfigs,
             double totalDuration);

    // Calculates ducking envelope curve over time for background music tracks
    std::vector<float> calculateDuckingEnvelope(const std::vector<AudioBuffer>& voiceoverBuffers, 
                                               const std::vector<Core::AudioTrack>& voConfigs,
                                               int sampleRate, int totalSamples,
                                               double attenuation, double attackSec, double releaseSec);

    // Applies volume scaling and soft-clipping/limiter to prevent distortion
    static void applyLimiter(std::vector<float>& samples);
};

} // namespace Tools
} // namespace HyperEditor
