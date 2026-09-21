#include "tools/speed_ramping.hpp"
#include <algorithm>
#include <cmath>

namespace HyperEditor {
namespace Tools {

double SpeedRampingTool::getSpeedAt(const Core::SpeedRampingConfig& config, double timelineTime) const {
    if (!config.enabled || config.points.empty()) return 1.0;

    if (timelineTime <= config.points.front().time) {
        return std::clamp(config.points.front().speedMultiplier, 0.05, 20.0);
    }
    if (timelineTime >= config.points.back().time) {
        return std::clamp(config.points.back().speedMultiplier, 0.05, 20.0);
    }

    size_t nextIdx = 1;
    while (nextIdx < config.points.size() && config.points[nextIdx].time < timelineTime) {
        nextIdx++;
    }

    const auto& p1 = config.points[nextIdx - 1];
    const auto& p2 = config.points[nextIdx];

    double dt = p2.time - p1.time;
    double t = (dt > 1e-6) ? (timelineTime - p1.time) / dt : 0.0;
    // Smoothstep interpolation for acceleration/deceleration curves
    double smoothT = t * t * (3.0 - 2.0 * t);

    double speed = p1.speedMultiplier + (p2.speedMultiplier - p1.speedMultiplier) * smoothT;
    return std::clamp(speed, 0.05, 20.0);
}

double SpeedRampingTool::mapTimelineToSourceTime(const Core::SpeedRampingConfig& config, double timelineTime, double sourceOffset) const {
    if (!config.enabled || config.points.empty()) {
        return sourceOffset + timelineTime;
    }

    // Numerical integration of speed curve using trapezoidal rule with small time steps
    double step = 0.01; // 10ms step
    double accumulatedSourceTime = 0.0;
    double curT = 0.0;

    while (curT + step <= timelineTime) {
        double s1 = getSpeedAt(config, curT);
        double s2 = getSpeedAt(config, curT + step);
        accumulatedSourceTime += 0.5 * (s1 + s2) * step;
        curT += step;
    }

    if (curT < timelineTime) {
        double rem = timelineTime - curT;
        double s1 = getSpeedAt(config, curT);
        double s2 = getSpeedAt(config, timelineTime);
        accumulatedSourceTime += 0.5 * (s1 + s2) * rem;
    }

    return sourceOffset + accumulatedSourceTime;
}

void SpeedRampingTool::stretchAudioSamples(const std::vector<float>& inSamples, int channels, int sampleRate, 
                                          double speedFactor, std::vector<float>& outSamples) {
    if (inSamples.empty() || channels <= 0) return;
    if (std::abs(speedFactor - 1.0) < 1e-3) {
        outSamples = inSamples;
        return;
    }

    // Overlap-Add (OLA) time-scale modification algorithm without pitch shift
    // Frame size ~30ms, overlap 50%
    int windowSize = (sampleRate * 30) / 1000;
    if (windowSize % 2 != 0) windowSize++;
    int hopIn = windowSize / 2;
    int hopOut = static_cast<int>(hopIn / speedFactor);
    if (hopOut < 1) hopOut = 1;

    size_t inFrames = inSamples.size() / channels;
    size_t outFrames = static_cast<size_t>(inFrames / speedFactor);
    outSamples.assign(outFrames * channels, 0.0f);
    std::vector<float> weightSum(outFrames, 0.0f);

    // Hanning window
    std::vector<float> window(windowSize);
    for (int i = 0; i < windowSize; ++i) {
        window[i] = 0.5f * (1.0f - std::cos(2.0f * M_PI * i / (windowSize - 1)));
    }

    size_t inPos = 0;
    size_t outPos = 0;

    while (inPos + windowSize < inFrames && outPos + windowSize < outFrames) {
        for (int i = 0; i < windowSize; ++i) {
            float w = window[i];
            for (int c = 0; c < channels; ++c) {
                outSamples[(outPos + i) * channels + c] += inSamples[(inPos + i) * channels + c] * w;
            }
            weightSum[outPos + i] += w;
        }
        inPos += hopIn;
        outPos += hopOut;
    }

    // Normalize weights
    for (size_t f = 0; f < outFrames; ++f) {
        float norm = weightSum[f];
        if (norm > 1e-4f) {
            for (int c = 0; c < channels; ++c) {
                outSamples[f * channels + c] /= norm;
            }
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
