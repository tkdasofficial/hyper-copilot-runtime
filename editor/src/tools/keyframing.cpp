#include "tools/keyframing.hpp"
#include <cmath>
#include <algorithm>

namespace HyperEditor {
namespace Tools {

double KeyframingTool::linear(double t) {
    return std::clamp(t, 0.0, 1.0);
}

double KeyframingTool::easeIn(double t) {
    t = std::clamp(t, 0.0, 1.0);
    return t * t;
}

double KeyframingTool::easeOut(double t) {
    t = std::clamp(t, 0.0, 1.0);
    return t * (2.0 - t);
}

double KeyframingTool::easeInOut(double t) {
    t = std::clamp(t, 0.0, 1.0);
    return t < 0.5 ? 2.0 * t * t : -1.0 + (4.0 - 2.0 * t) * t;
}

double KeyframingTool::evaluateBezierCoord(double t, double c1, double c2) {
    // Standard cubic bezier with P0=0, P1=c1, P2=c2, P3=1
    // B(t) = 3*(1-t)^2*t*c1 + 3*(1-t)*t^2*c2 + t^3
    double oneMinusT = 1.0 - t;
    return 3.0 * oneMinusT * oneMinusT * t * c1 +
           3.0 * oneMinusT * t * t * c2 +
           t * t * t;
}

double KeyframingTool::solveBezierT(double x, double x1, double x2) {
    // Newton-Raphson approximation for parameter t given x
    double t = x;
    for (int i = 0; i < 8; ++i) {
        double currentX = evaluateBezierCoord(t, x1, x2) - x;
        if (std::abs(currentX) < 1e-5) return t;

        // Derivative dB/dt
        double oneMinusT = 1.0 - t;
        double dX = 3.0 * oneMinusT * oneMinusT * x1 +
                    6.0 * oneMinusT * t * (x2 - x1) +
                    3.0 * t * t * (1.0 - x2);
        if (std::abs(dX) < 1e-6) break;
        t -= currentX / dX;
        t = std::clamp(t, 0.0, 1.0);
    }
    return t;
}

double KeyframingTool::cubicBezier(double t, double x1, double y1, double x2, double y2) {
    t = std::clamp(t, 0.0, 1.0);
    double solvedT = solveBezierT(t, x1, x2);
    return evaluateBezierCoord(solvedT, y1, y2);
}

KeyframeState KeyframingTool::evaluate(const std::vector<Core::Keyframe>& keyframes, double currentTime) const {
    if (keyframes.empty()) {
        return KeyframeState{0.0, 0.0, 1.0, 1.0, 0.0, 1.0};
    }

    if (keyframes.size() == 1 || currentTime <= keyframes.front().time) {
        const auto& kf = keyframes.front();
        return KeyframeState{kf.posX, kf.posY, kf.scaleX, kf.scaleY, kf.rotation, kf.opacity};
    }

    if (currentTime >= keyframes.back().time) {
        const auto& kf = keyframes.back();
        return KeyframeState{kf.posX, kf.posY, kf.scaleX, kf.scaleY, kf.rotation, kf.opacity};
    }

    // Find bounding keyframes
    size_t nextIdx = 1;
    while (nextIdx < keyframes.size() && keyframes[nextIdx].time < currentTime) {
        nextIdx++;
    }

    const auto& kf1 = keyframes[nextIdx - 1];
    const auto& kf2 = keyframes[nextIdx];

    double dt = kf2.time - kf1.time;
    double progress = (dt > 1e-6) ? (currentTime - kf1.time) / dt : 0.0;
    progress = std::clamp(progress, 0.0, 1.0);

    double eased = progress;
    switch (kf1.easing) {
        case Core::EasingType::Linear:
            eased = linear(progress);
            break;
        case Core::EasingType::EaseIn:
            eased = easeIn(progress);
            break;
        case Core::EasingType::EaseOut:
            eased = easeOut(progress);
            break;
        case Core::EasingType::EaseInOut:
            eased = easeInOut(progress);
            break;
        case Core::EasingType::Bezier:
            eased = cubicBezier(progress, kf1.cp1X, kf1.cp1Y, kf1.cp2X, kf1.cp2Y);
            break;
    }

    KeyframeState result;
    result.posX = kf1.posX + (kf2.posX - kf1.posX) * eased;
    result.posY = kf1.posY + (kf2.posY - kf1.posY) * eased;
    result.scaleX = kf1.scaleX + (kf2.scaleX - kf1.scaleX) * eased;
    result.scaleY = kf1.scaleY + (kf2.scaleY - kf1.scaleY) * eased;
    result.rotation = kf1.rotation + (kf2.rotation - kf1.rotation) * eased;
    result.opacity = kf1.opacity + (kf2.opacity - kf1.opacity) * eased;
    result.opacity = std::clamp(result.opacity, 0.0, 1.0);

    return result;
}

} // namespace Tools
} // namespace HyperEditor
