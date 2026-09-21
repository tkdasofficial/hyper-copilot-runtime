#include "tools/frame_scaler.hpp"
#include <algorithm>
#include <cmath>

namespace HyperEditor {
namespace Tools {

FrameScalerTool::~FrameScalerTool() {
    if (swsCtx_) {
        sws_freeContext(swsCtx_);
        swsCtx_ = nullptr;
    }
}

void FrameScalerTool::computeFitRect(int srcW, int srcH, int dstW, int dstH, Core::ScaleMode mode,
                                    int& outSrcX, int& outSrcY, int& outSrcW, int& outSrcH,
                                    int& outDstX, int& outDstY, int& outDstW, int& outDstH) {
    outSrcX = 0;
    outSrcY = 0;
    outSrcW = srcW;
    outSrcH = srcH;

    outDstX = 0;
    outDstY = 0;
    outDstW = dstW;
    outDstH = dstH;

    if (mode == Core::ScaleMode::Stretch) {
        return;
    }

    double srcAspect = static_cast<double>(srcW) / srcH;
    double dstAspect = static_cast<double>(dstW) / dstH;

    if (mode == Core::ScaleMode::Letterbox) {
        // Fit inside dst, black bars
        if (srcAspect > dstAspect) {
            // Wider than dst: pillarbox vertically (top/bottom black bars)
            outDstW = dstW;
            outDstH = static_cast<int>(dstW / srcAspect);
            outDstX = 0;
            outDstY = (dstH - outDstH) / 2;
        } else {
            // Taller than dst: pillarbox horizontally (left/right bars)
            outDstH = dstH;
            outDstW = static_cast<int>(dstH * srcAspect);
            outDstY = 0;
            outDstX = (dstW - outDstW) / 2;
        }
    } else if (mode == Core::ScaleMode::SmartCrop) {
        // Fill dst completely, center crop source
        if (srcAspect > dstAspect) {
            // Source is wider, crop horizontal edges
            outSrcH = srcH;
            outSrcW = static_cast<int>(srcH * dstAspect);
            outSrcY = 0;
            outSrcX = (srcW - outSrcW) / 2;
        } else {
            // Source is taller, crop vertical edges
            outSrcW = srcW;
            outSrcH = static_cast<int>(srcW / dstAspect);
            outSrcX = 0;
            outSrcY = (srcH - outSrcH) / 2;
        }
        outDstX = 0;
        outDstY = 0;
        outDstW = dstW;
        outDstH = dstH;
    }
}

void FrameScalerTool::scale(AVFrame* dstFrame, const AVFrame* srcFrame, const Core::FrameScalerConfig& config, uint32_t bgColor) {
    if (!dstFrame || !srcFrame) return;

    int srcW = srcFrame->width;
    int srcH = srcFrame->height;
    int dstW = dstFrame->width;
    int dstH = dstFrame->height;

    int srcX, srcY, cropW, cropH;
    int dstX, dstY, fitW, fitH;

    computeFitRect(srcW, srcH, dstW, dstH, config.mode,
                   srcX, srcY, cropW, cropH,
                   dstX, dstY, fitW, fitH);

    // Fill background color
    uint8_t bgR = (bgColor >> 24) & 0xFF;
    uint8_t bgG = (bgColor >> 16) & 0xFF;
    uint8_t bgB = (bgColor >> 8) & 0xFF;
    uint8_t bgA = bgColor & 0xFF;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < dstH; ++y) {
        uint8_t* row = dstFrame->data[0] + y * dstFrame->linesize[0];
        for (int x = 0; x < dstW; ++x) {
            row[x * 4 + 0] = bgR;
            row[x * 4 + 1] = bgG;
            row[x * 4 + 2] = bgB;
            row[x * 4 + 3] = bgA;
        }
    }

    // Allocate or update SwsContext for high quality bicubic scaling
    if (!swsCtx_ || lastSrcW_ != cropW || lastSrcH_ != cropH || lastDstW_ != fitW || lastDstH_ != fitH) {
        if (swsCtx_) sws_freeContext(swsCtx_);
        swsCtx_ = sws_getContext(cropW, cropH, AV_PIX_FMT_RGBA,
                                 fitW, fitH, AV_PIX_FMT_RGBA,
                                 SWS_BICUBIC, nullptr, nullptr, nullptr);
        lastSrcW_ = cropW;
        lastSrcH_ = cropH;
        lastDstW_ = fitW;
        lastDstH_ = fitH;
    }

    if (!swsCtx_) return;

    // Temporary buffer or direct slice
    const uint8_t* srcSlice[4] = {
        srcFrame->data[0] + srcY * srcFrame->linesize[0] + srcX * 4,
        nullptr, nullptr, nullptr
    };
    int srcStride[4] = { srcFrame->linesize[0], 0, 0, 0 };

    uint8_t* dstSlice[4] = {
        dstFrame->data[0] + dstY * dstFrame->linesize[0] + dstX * 4,
        nullptr, nullptr, nullptr
    };
    int dstStride[4] = { dstFrame->linesize[0], 0, 0, 0 };

    sws_scale(swsCtx_, srcSlice, srcStride, 0, cropH, dstSlice, dstStride);
}

} // namespace Tools
} // namespace HyperEditor
