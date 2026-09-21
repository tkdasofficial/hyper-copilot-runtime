#pragma once

#include "core/timeline.hpp"
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
}

namespace HyperEditor {
namespace Tools {

class MotionZoomTool {
public:
    MotionZoomTool() = default;
    ~MotionZoomTool() = default;

    // Applies Ken Burns pan, scan, and dynamic zoom transformation onto dstFrame sampled from srcFrame
    void apply(AVFrame* dstFrame, const AVFrame* srcFrame, const Core::MotionZoomConfig& config, double progress);

    // Applies camera motion blur based on velocity delta between subframes
    void applyMotionBlur(AVFrame* frame, double deltaX, double deltaY, int samples = 5);

private:
    void sampleBilinear(const AVFrame* src, double u, double v, uint8_t* outRgba) const;
};

} // namespace Tools
} // namespace HyperEditor
