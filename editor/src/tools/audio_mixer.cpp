#include "tools/audio_mixer.hpp"
#include <cmath>
#include <algorithm>

namespace HyperEditor {
namespace Tools {

std::vector<float> AudioMixerTool::calculateDuckingEnvelope(
    const std::vector<AudioBuffer>& voiceoverBuffers, 
    const std::vector<Core::AudioTrack>& voConfigs,
    int sampleRate, int totalSamples,
    double attenuation, double attackSec, double releaseSec) {

    std::vector<float> envelope(totalSamples, 1.0f);
    if (voiceoverBuffers.empty()) return envelope;

    // Detect voice activity mask per sample
    std::vector<bool> activeMask(totalSamples, false);
    for (size_t i = 0; i < voiceoverBuffers.size(); ++i) {
        const auto& buf = voiceoverBuffers[i];
        const auto& cfg = voConfigs[i];
        if (!cfg.isVoiceover) continue;

        int startIdx = static_cast<int>(cfg.startTime * sampleRate);
        int numFrames = static_cast<int>(buf.samples.size() / buf.channels);

        for (int f = 0; f < numFrames && (startIdx + f) < totalSamples; ++f) {
            float energy = 0.0f;
            for (int c = 0; c < buf.channels; ++c) {
                float s = buf.samples[f * buf.channels + c];
                energy += s * s;
            }
            // If energy exceeds silent threshold (-45dB) or clip is declared active
            if (energy > 0.0001f) {
                activeMask[startIdx + f] = true;
            }
        }
    }

    // Apply attack and release smoothing to ducking envelope
    float currentGain = 1.0f;
    float targetGain = 1.0f;
    float attackRate = (attackSec > 0.001) ? static_cast<float>(1.0 / (attackSec * sampleRate)) : 1.0f;
    float releaseRate = (releaseSec > 0.001) ? static_cast<float>(1.0 / (releaseSec * sampleRate)) : 1.0f;
    float minGain = static_cast<float>(attenuation);

    for (int i = 0; i < totalSamples; ++i) {
        if (activeMask[i]) {
            targetGain = minGain;
        } else {
            targetGain = 1.0f;
        }

        if (currentGain > targetGain) {
            currentGain = std::max(targetGain, currentGain - attackRate);
        } else if (currentGain < targetGain) {
            currentGain = std::min(targetGain, currentGain + releaseRate);
        }

        envelope[i] = currentGain;
    }

    return envelope;
}

void AudioMixerTool::mix(AudioBuffer& masterBuffer, 
                        const std::vector<AudioBuffer>& trackBuffers,
                        const std::vector<Core::AudioTrack>& trackConfigs,
                        double totalDuration) {
    int sampleRate = masterBuffer.sampleRate;
    int channels = masterBuffer.channels;
    int totalFrames = static_cast<int>(totalDuration * sampleRate);
    int totalSamples = totalFrames * channels;

    masterBuffer.samples.assign(totalSamples, 0.0f);

    // Identify voiceover tracks and background music tracks
    std::vector<AudioBuffer> voBuffers;
    std::vector<Core::AudioTrack> voConfigs;
    for (size_t i = 0; i < trackBuffers.size() && i < trackConfigs.size(); ++i) {
        if (trackConfigs[i].isVoiceover) {
            voBuffers.push_back(trackBuffers[i]);
            voConfigs.push_back(trackConfigs[i]);
        }
    }

    // Mix each track
    for (size_t i = 0; i < trackBuffers.size() && i < trackConfigs.size(); ++i) {
        const auto& buf = trackBuffers[i];
        const auto& cfg = trackConfigs[i];

        int startFrame = static_cast<int>(cfg.startTime * sampleRate);
        int trackFrames = buf.samples.size() / buf.channels;
        int framesToMix = std::min(trackFrames, totalFrames - startFrame);
        if (framesToMix <= 0) continue;

        std::vector<float> duckEnvelope;
        if (cfg.duckOnVoiceover && !voBuffers.empty()) {
            duckEnvelope = calculateDuckingEnvelope(
                voBuffers, voConfigs, sampleRate, framesToMix,
                cfg.duckingAttenuation, cfg.duckingAttackSec, cfg.duckingReleaseSec);
        }

        float vol = static_cast<float>(cfg.volume);

        #pragma omp parallel for schedule(static)
        for (int f = 0; f < framesToMix; ++f) {
            int masterFrameIdx = startFrame + f;
            if (masterFrameIdx >= totalFrames) continue;

            float gain = vol;
            if (!duckEnvelope.empty()) {
                gain *= duckEnvelope[f];
            }

            for (int c = 0; c < channels; ++c) {
                int srcChannel = (c < buf.channels) ? c : 0;
                float srcSample = buf.samples[f * buf.channels + srcChannel];
                masterBuffer.samples[masterFrameIdx * channels + c] += srcSample * gain;
            }
        }
    }

    // Apply master limiter / soft-clipper
    applyLimiter(masterBuffer.samples);
}

void AudioMixerTool::applyLimiter(std::vector<float>& samples) {
    #pragma omp parallel for schedule(static)
    for (size_t i = 0; i < samples.size(); ++i) {
        float x = samples[i];
        // Soft clipping curve: fast approximation of tanh(x)
        if (x > 1.0f) {
            samples[i] = 1.0f - std::exp(-x);
        } else if (x < -1.0f) {
            samples[i] = -1.0f + std::exp(x);
        } else {
            samples[i] = x;
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
