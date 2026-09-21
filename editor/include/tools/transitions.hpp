#pragma once

#include "core/timeline.hpp"
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
}

namespace HyperEditor {
namespace Tools {

class TransitionsTool {
public:
    TransitionsTool() = default;
    ~TransitionsTool() = default;

    // Renders transition blending from outgoing frame (frameA) to incoming frame (frameB)
    // progress is 0.0 (fully frameA) to 1.0 (fully frameB)
    void renderTransition(AVFrame* dstFrame, const AVFrame* frameA, const AVFrame* frameB, 
                          Core::TransitionType type, double progress);

private:
    void renderCrossfade(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t);
    void renderZoom(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t, bool zoomIn);
    void renderWipe(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t, int dirX, int dirY);
    void renderGaussianBlur(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t);
    void applyBoxBlur(uint8_t* dst, const uint8_t* src, int w, int h, int linesize, int radius);
};

} // namespace Tools
} // namespace HyperEditor
