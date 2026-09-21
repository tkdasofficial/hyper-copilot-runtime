#include "tools/audio_effects.hpp"
#include <cmath>
#include <algorithm>

namespace HyperEditor {
namespace Tools {

BiquadCoeffs AudioEffectsTool::makeHighPass(double cutoffHz, double sampleRate, double q) {
    BiquadCoeffs c;
    double w0 = 2.0 * M_PI * cutoffHz / sampleRate;
    double alpha = std::sin(w0) / (2.0 * q);
    double cosw0 = std::cos(w0);

    double a0 = 1.0 + alpha;
    c.b0 = ((1.0 + cosw0) / 2.0) / a0;
    c.b1 = (-(1.0 + cosw0)) / a0;
    c.b2 = ((1.0 + cosw0) / 2.0) / a0;
    c.a1 = (-2.0 * cosw0) / a0;
    c.a2 = (1.0 - alpha) / a0;
    return c;
}

BiquadCoeffs AudioEffectsTool::makeLowPass(double cutoffHz, double sampleRate, double q) {
    BiquadCoeffs c;
    double w0 = 2.0 * M_PI * cutoffHz / sampleRate;
    double alpha = std::sin(w0) / (2.0 * q);
    double cosw0 = std::cos(w0);

    double a0 = 1.0 + alpha;
    c.b0 = ((1.0 - cosw0) / 2.0) / a0;
    c.b1 = (1.0 - cosw0) / a0;
    c.b2 = ((1.0 - cosw0) / 2.0) / a0;
    c.a1 = (-2.0 * cosw0) / a0;
    c.a2 = (1.0 - alpha) / a0;
    return c;
}

BiquadCoeffs AudioEffectsTool::makePeakingEQ(double centerHz, double gainDb, double sampleRate, double q) {
    BiquadCoeffs c;
    double A = std::pow(10.0, gainDb / 40.0);
    double w0 = 2.0 * M_PI * centerHz / sampleRate;
    double alpha = std::sin(w0) / (2.0 * q);
    double cosw0 = std::cos(w0);

    double a0 = 1.0 + alpha / A;
    c.b0 = (1.0 + alpha * A) / a0;
    c.b1 = (-2.0 * cosw0) / a0;
    c.b2 = (1.0 - alpha * A) / a0;
    c.a1 = (-2.0 * cosw0) / a0;
    c.a2 = (1.0 - alpha / A) / a0;
    return c;
}

BiquadCoeffs AudioEffectsTool::makeLowShelf(double cutoffHz, double gainDb, double sampleRate) {
    BiquadCoeffs c;
    double A = std::pow(10.0, gainDb / 40.0);
    double w0 = 2.0 * M_PI * cutoffHz / sampleRate;
    double cosw0 = std::cos(w0);
    double sinw0 = std::sin(w0);
    double alpha = sinw0 / 2.0 * std::sqrt((A + 1.0 / A) * (1.0 / 0.7071 - 1.0) + 2.0);

    double a0 = (A + 1.0) + (A - 1.0) * cosw0 + 2.0 * std::sqrt(A) * alpha;
    c.b0 = (A * ((A + 1.0) - (A - 1.0) * cosw0 + 2.0 * std::sqrt(A) * alpha)) / a0;
    c.b1 = (2.0 * A * ((A - 1.0) - (A + 1.0) * cosw0)) / a0;
    c.b2 = (A * ((A + 1.0) - (A - 1.0) * cosw0 - 2.0 * std::sqrt(A) * alpha)) / a0;
    c.a1 = (-2.0 * ((A - 1.0) + (A + 1.0) * cosw0)) / a0;
    c.a2 = ((A + 1.0) + (A - 1.0) * cosw0 - 2.0 * std::sqrt(A) * alpha) / a0;
    return c;
}

BiquadCoeffs AudioEffectsTool::makeHighShelf(double cutoffHz, double gainDb, double sampleRate) {
    BiquadCoeffs c;
    double A = std::pow(10.0, gainDb / 40.0);
    double w0 = 2.0 * M_PI * cutoffHz / sampleRate;
    double cosw0 = std::cos(w0);
    double sinw0 = std::sin(w0);
    double alpha = sinw0 / 2.0 * std::sqrt((A + 1.0 / A) * (1.0 / 0.7071 - 1.0) + 2.0);

    double a0 = (A + 1.0) - (A - 1.0) * cosw0 + 2.0 * std::sqrt(A) * alpha;
    c.b0 = (A * ((A + 1.0) + (A - 1.0) * cosw0 + 2.0 * std::sqrt(A) * alpha)) / a0;
    c.b1 = (-2.0 * A * ((A - 1.0) + (A + 1.0) * cosw0)) / a0;
    c.b2 = (A * ((A + 1.0) + (A - 1.0) * cosw0 - 2.0 * std::sqrt(A) * alpha)) / a0;
    c.a1 = (2.0 * ((A - 1.0) - (A + 1.0) * cosw0)) / a0;
    c.a2 = ((A + 1.0) - (A - 1.0) * cosw0 - 2.0 * std::sqrt(A) * alpha) / a0;
    return c;
}

void AudioEffectsTool::applyBiquad(std::vector<float>& samples, int channels, const BiquadCoeffs& coeffs) {
    if (channels <= 0 || samples.empty()) return;
    std::vector<BiquadState> states(channels);

    size_t numFrames = samples.size() / channels;
    for (size_t f = 0; f < numFrames; ++f) {
        for (int c = 0; c < channels; ++c) {
            double in = samples[f * channels + c];
            double out = coeffs.b0 * in + states[c].z1;
            states[c].z1 = coeffs.b1 * in - coeffs.a1 * out + states[c].z2;
            states[c].z2 = coeffs.b2 * in - coeffs.a2 * out;
            samples[f * channels + c] = static_cast<float>(out);
        }
    }
}

void AudioEffectsTool::applyNoiseGate(std::vector<float>& samples, int channels, int sampleRate, double thresholdDb) {
    if (channels <= 0 || samples.empty() || thresholdDb < -80.0) return;

    double thresholdLin = std::pow(10.0, thresholdDb / 20.0);
    double envelope = 0.0;
    double attackCoeff = std::exp(-1.0 / (0.005 * sampleRate)); // 5ms attack
    double releaseCoeff = std::exp(-1.0 / (0.050 * sampleRate)); // 50ms release

    size_t numFrames = samples.size() / channels;
    for (size_t f = 0; f < numFrames; ++f) {
        double framePeak = 0.0;
        for (int c = 0; c < channels; ++c) {
            framePeak = std::max(framePeak, static_cast<double>(std::abs(samples[f * channels + c])));
        }

        if (framePeak > envelope) {
            envelope = attackCoeff * envelope + (1.0 - attackCoeff) * framePeak;
        } else {
            envelope = releaseCoeff * envelope + (1.0 - releaseCoeff) * framePeak;
        }

        double gain = (envelope > thresholdLin) ? 1.0 : (envelope / thresholdLin) * (envelope / thresholdLin);
        for (int c = 0; c < channels; ++c) {
            samples[f * channels + c] *= static_cast<float>(gain);
        }
    }
}

void AudioEffectsTool::applyPitchShift(std::vector<float>& samples, int channels, int sampleRate, double semitones) {
    (void)sampleRate;
    if (std::abs(semitones) < 0.01 || samples.empty() || channels <= 0) return;

    // Pitch shift ratio: 2^(semitones / 12)
    double ratio = std::pow(2.0, semitones / 12.0);

    // High quality linear pitch resampler
    size_t inFrames = samples.size() / channels;
    std::vector<float> resampled;
    resampled.reserve(samples.size());

    double pos = 0.0;
    while (pos < inFrames - 1) {
        size_t idx0 = static_cast<size_t>(pos);
        size_t idx1 = idx0 + 1;
        float frac = static_cast<float>(pos - idx0);

        for (int c = 0; c < channels; ++c) {
            float s0 = samples[idx0 * channels + c];
            float s1 = samples[idx1 * channels + c];
            resampled.push_back(s0 + frac * (s1 - s0));
        }
        pos += ratio;
    }

    // Pad or fit to original sample count to preserve sync
    samples.assign(samples.size(), 0.0f);
    size_t copyCount = std::min(samples.size(), resampled.size());
    std::copy(resampled.begin(), resampled.begin() + copyCount, samples.begin());
}

void AudioEffectsTool::process(std::vector<float>& samples, int channels, int sampleRate, 
                               const Core::AudioEffectsConfig& config) {
    if (samples.empty() || channels <= 0) return;

    // 1. High Pass Filter
    if (config.highPassHz > 20.0 && config.highPassHz < sampleRate * 0.45) {
        auto hpf = makeHighPass(config.highPassHz, sampleRate);
        applyBiquad(samples, channels, hpf);
    }

    // 2. Low Pass Filter
    if (config.lowPassHz > 20.0 && config.lowPassHz < sampleRate * 0.45) {
        auto lpf = makeLowPass(config.lowPassHz, sampleRate);
        applyBiquad(samples, channels, lpf);
    }

    // 3. 3-Band Equalizer (Low Shelf, Mid Peak, High Shelf)
    if (std::abs(config.eqLowDb) > 0.1) {
        auto eqL = makeLowShelf(150.0, config.eqLowDb, sampleRate);
        applyBiquad(samples, channels, eqL);
    }
    if (std::abs(config.eqMidDb) > 0.1) {
        auto eqM = makePeakingEQ(1200.0, config.eqMidDb, sampleRate, 1.0);
        applyBiquad(samples, channels, eqM);
    }
    if (std::abs(config.eqHighDb) > 0.1) {
        auto eqH = makeHighShelf(6000.0, config.eqHighDb, sampleRate);
        applyBiquad(samples, channels, eqH);
    }

    // 4. Noise Gate
    if (config.noiseGateThresholdDb > -80.0) {
        applyNoiseGate(samples, channels, sampleRate, config.noiseGateThresholdDb);
    }

    // 5. Pitch Shifting
    if (std::abs(config.pitchShiftSemitones) > 0.05) {
        applyPitchShift(samples, channels, sampleRate, config.pitchShiftSemitones);
    }
}

} // namespace Tools
} // namespace HyperEditor
