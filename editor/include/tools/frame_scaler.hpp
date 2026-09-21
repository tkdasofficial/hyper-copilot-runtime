#pragma once

#include "core/timeline.hpp"
#include "utils/memory.hpp"
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
#include <libswscale/swscale.h>
}

namespace HyperEditor {
namespace Tools {

class FrameScalerTool {
public:
    FrameScalerTool() = default;
    ~FrameScalerTool();

    // Scales srcFrame to dstFrame adhering to the specified target dimensions and scaling mode (Letterbox, SmartCrop, Stretch)
    void scale(AVFrame* dstFrame, const AVFrame* srcFrame, const Core::FrameScalerConfig& config, uint32_t bgColor = 0x000000FF);

    // Determines optimal crop / viewport coordinates for aspect ratio conversions (16:9, 9:16, 1:1)
    static void computeFitRect(int srcW, int srcH, int dstW, int dstH, Core::ScaleMode mode,
                               int& outSrcX, int& outSrcY, int& outSrcW, int& outSrcH,
                               int& outDstX, int& outDstY, int& outDstW, int& outDstH);

private:
    SwsContext* swsCtx_ = nullptr;
    int lastSrcW_ = 0;
    int lastSrcH_ = 0;
    int lastDstW_ = 0;
    int lastDstH_ = 0;
};

} // namespace Tools
} // namespace HyperEditor
