#pragma once

#include "core/timeline.hpp"
#include <vector>

namespace HyperEditor {
namespace Tools {

// Biquad filter coefficients (Direct Form II Transposed)
struct BiquadCoeffs {
    double b0 = 1.0, b1 = 0.0, b2 = 0.0;
    double a1 = 0.0, a2 = 0.0;
};

struct BiquadState {
    double z1 = 0.0;
    double z2 = 0.0;
};

class AudioEffectsTool {
public:
    AudioEffectsTool() = default;
    ~AudioEffectsTool() = default;

    // Applies complete chain: High/Low pass, Noise Gate, 3-Band EQ, Pitch/Tempo processing
    void process(std::vector<float>& samples, int channels, int sampleRate, 
                 const Core::AudioEffectsConfig& config);

    // Filter coefficient generators
    static BiquadCoeffs makeHighPass(double cutoffHz, double sampleRate, double q = 0.7071);
    static BiquadCoeffs makeLowPass(double cutoffHz, double sampleRate, double q = 0.7071);
    static BiquadCoeffs makePeakingEQ(double centerHz, double gainDb, double sampleRate, double q = 1.0);
    static BiquadCoeffs makeLowShelf(double cutoffHz, double gainDb, double sampleRate);
    static BiquadCoeffs makeHighShelf(double cutoffHz, double gainDb, double sampleRate);

    // Applies biquad filter in-place to interleaved audio
    static void applyBiquad(std::vector<float>& samples, int channels, const BiquadCoeffs& coeffs);

    // Applies noise gate to silence low-level background noise
    static void applyNoiseGate(std::vector<float>& samples, int channels, int sampleRate, double thresholdDb);

    // Applies pitch shift in semitones (-12 to +12)
    static void applyPitchShift(std::vector<float>& samples, int channels, int sampleRate, double semitones);
};

} // namespace Tools
} // namespace HyperEditor
