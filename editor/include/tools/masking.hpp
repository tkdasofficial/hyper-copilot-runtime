#pragma once

#include "core/timeline.hpp"
#include "utils/memory.hpp"
#include <cstdint>

namespace HyperEditor {
namespace Tools {

class MaskingTool {
public:
    MaskingTool() = default;
    ~MaskingTool() = default;

    // Applies shape mask directly to the alpha channel of an RGBA AVFrame
    void applyMask(AVFrame* frame, const Core::MaskConfig& config);

    // Applies a custom alpha mask frame (grayscale or alpha channel) onto target frame
    void applyAlphaCutout(AVFrame* targetFrame, const AVFrame* alphaMaskFrame);

private:
    void applyRectangularMask(uint8_t* data, int width, int height, int linesize, const Core::MaskConfig& config);
    void applyEllipticalMask(uint8_t* data, int width, int height, int linesize, const Core::MaskConfig& config);
    void applyLinearMask(uint8_t* data, int width, int height, int linesize, const Core::MaskConfig& config);
};

} // namespace Tools
} // namespace HyperEditor
