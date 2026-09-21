#include "tools/motion_zoom.hpp"
#include <cmath>
#include <algorithm>
#include <vector>

namespace HyperEditor {
namespace Tools {

void MotionZoomTool::sampleBilinear(const AVFrame* src, double u, double v, uint8_t* outRgba) const {
    int w = src->width;
    int h = src->height;

    double x = u * (w - 1);
    double y = v * (h - 1);

    int x0 = std::clamp(static_cast<int>(std::floor(x)), 0, w - 1);
    int y0 = std::clamp(static_cast<int>(std::floor(y)), 0, h - 1);
    int x1 = std::min(x0 + 1, w - 1);
    int y1 = std::min(y0 + 1, h - 1);

    double fx = x - x0;
    double fy = y - y0;

    const uint8_t* p00 = src->data[0] + y0 * src->linesize[0] + x0 * 4;
    const uint8_t* p10 = src->data[0] + y0 * src->linesize[0] + x1 * 4;
    const uint8_t* p01 = src->data[0] + y1 * src->linesize[0] + x0 * 4;
    const uint8_t* p11 = src->data[0] + y1 * src->linesize[0] + x1 * 4;

    for (int c = 0; c < 4; ++c) {
        double top = p00[c] * (1.0 - fx) + p10[c] * fx;
        double bottom = p01[c] * (1.0 - fx) + p11[c] * fx;
        outRgba[c] = static_cast<uint8_t>(std::clamp(top * (1.0 - fy) + bottom * fy, 0.0, 255.0));
    }
}

void MotionZoomTool::apply(AVFrame* dstFrame, const AVFrame* srcFrame, const Core::MotionZoomConfig& config, double progress) {
    if (!dstFrame || !srcFrame || !config.enabled) return;

    double t = std::clamp(progress, 0.0, 1.0);

    double curZoom = config.startZoom + (config.endZoom - config.startZoom) * t;
    double curPanX = config.startPanX + (config.endPanX - config.startPanX) * t;
    double curPanY = config.startPanY + (config.endPanY - config.startPanY) * t;

    curZoom = std::max(0.1, curZoom);

    int dstW = dstFrame->width;
    int dstH = dstFrame->height;

    // Viewport width and height in normalized source coords
    double viewNormW = 1.0 / curZoom;
    double viewNormH = 1.0 / curZoom;

    double minNormX = curPanX - viewNormW * 0.5;
    double minNormY = curPanY - viewNormH * 0.5;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < dstH; ++y) {
        uint8_t* dstRow = dstFrame->data[0] + y * dstFrame->linesize[0];
        double v = minNormY + (static_cast<double>(y) / dstH) * viewNormH;

        for (int x = 0; x < dstW; ++x) {
            double u = minNormX + (static_cast<double>(x) / dstW) * viewNormW;

            if (u < 0.0 || u > 1.0 || v < 0.0 || v > 1.0) {
                // Out of bounds - clamp edge
                u = std::clamp(u, 0.0, 1.0);
                v = std::clamp(v, 0.0, 1.0);
            }

            sampleBilinear(srcFrame, u, v, dstRow + x * 4);
        }
    }

    // Velocity-based motion blur
    double velX = (config.endPanX - config.startPanX) * (config.endZoom - config.startZoom);
    double velY = (config.endPanY - config.startPanY) * (config.endZoom - config.startZoom);
    if (std::hypot(velX, velY) > 0.02) {
        applyMotionBlur(dstFrame, velX * 50.0, velY * 50.0, 5);
    }
}

void MotionZoomTool::applyMotionBlur(AVFrame* frame, double deltaX, double deltaY, int samples) {
    if (!frame || samples <= 1) return;

    int w = frame->width;
    int h = frame->height;
    int linesize = frame->linesize[0];

    std::vector<uint8_t> copy(h * linesize);
    for (int y = 0; y < h; ++y) {
        std::copy(frame->data[0] + y * linesize, frame->data[0] + y * linesize + w * 4, copy.data() + y * linesize);
    }

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* dstRow = frame->data[0] + y * linesize;
        for (int x = 0; x < w; ++x) {
            int rSum = 0, gSum = 0, bSum = 0, aSum = 0;
            for (int s = 0; s < samples; ++s) {
                double frac = static_cast<double>(s) / (samples - 1) - 0.5;
                int sx = std::clamp(static_cast<int>(x + frac * deltaX), 0, w - 1);
                int sy = std::clamp(static_cast<int>(y + frac * deltaY), 0, h - 1);
                const uint8_t* p = copy.data() + sy * linesize + sx * 4;
                rSum += p[0];
                gSum += p[1];
                bSum += p[2];
                aSum += p[3];
            }
            dstRow[x * 4 + 0] = rSum / samples;
            dstRow[x * 4 + 1] = gSum / samples;
            dstRow[x * 4 + 2] = bSum / samples;
            dstRow[x * 4 + 3] = aSum / samples;
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
