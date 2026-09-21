#pragma once

#include "core/timeline.hpp"
#include <vector>

namespace HyperEditor {
namespace Tools {

struct KeyframeState {
    double posX = 0.0;
    double posY = 0.0;
    double scaleX = 1.0;
    double scaleY = 1.0;
    double rotation = 0.0; // degrees
    double opacity = 1.0;  // 0.0 to 1.0
};

class KeyframingTool {
public:
    KeyframingTool() = default;
    ~KeyframingTool() = default;

    // Evaluates interpolated transformation state at given time t (in seconds)
    KeyframeState evaluate(const std::vector<Core::Keyframe>& keyframes, double currentTime) const;

    // Easing mathematical functions
    static double linear(double t);
    static double easeIn(double t);
    static double easeOut(double t);
    static double easeInOut(double t);
    static double cubicBezier(double t, double x1, double y1, double x2, double y2);

private:
    static double solveBezierT(double x, double x1, double x2);
    static double evaluateBezierCoord(double t, double c1, double c2);
};

} // namespace Tools
} // namespace HyperEditor
