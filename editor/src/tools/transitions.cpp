#include "tools/transitions.hpp"
#include <algorithm>
#include <cmath>
#include <vector>
#include <cstring>

namespace HyperEditor {
namespace Tools {

void TransitionsTool::renderTransition(AVFrame* dstFrame, const AVFrame* frameA, const AVFrame* frameB, 
                                      Core::TransitionType type, double progress) {
    if (!dstFrame || !frameA || !frameB) return;
    double t = std::clamp(progress, 0.0, 1.0);

    switch (type) {
        case Core::TransitionType::Crossfade:
            renderCrossfade(dstFrame, frameA, frameB, t);
            break;
        case Core::TransitionType::ZoomIn:
            renderZoom(dstFrame, frameA, frameB, t, true);
            break;
        case Core::TransitionType::ZoomOut:
            renderZoom(dstFrame, frameA, frameB, t, false);
            break;
        case Core::TransitionType::WipeLeft:
            renderWipe(dstFrame, frameA, frameB, t, -1, 0);
            break;
        case Core::TransitionType::WipeRight:
            renderWipe(dstFrame, frameA, frameB, t, 1, 0);
            break;
        case Core::TransitionType::WipeUp:
            renderWipe(dstFrame, frameA, frameB, t, 0, -1);
            break;
        case Core::TransitionType::WipeDown:
            renderWipe(dstFrame, frameA, frameB, t, 0, 1);
            break;
        case Core::TransitionType::GaussianBlur:
            renderGaussianBlur(dstFrame, frameA, frameB, t);
            break;
        case Core::TransitionType::None:
            // Immediate cut at 0.5
            const AVFrame* src = (t < 0.5) ? frameA : frameB;
            for (int y = 0; y < dstFrame->height; ++y) {
                std::memcpy(dstFrame->data[0] + y * dstFrame->linesize[0],
                            src->data[0] + y * src->linesize[0],
                            dstFrame->width * 4);
            }
            break;
    }
}

void TransitionsTool::renderCrossfade(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t) {
    int w = dst->width;
    int h = dst->height;
    double invT = 1.0 - t;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* d = dst->data[0] + y * dst->linesize[0];
        const uint8_t* pA = a->data[0] + y * a->linesize[0];
        const uint8_t* pB = b->data[0] + y * b->linesize[0];
        for (int x = 0; x < w * 4; ++x) {
            d[x] = static_cast<uint8_t>(pA[x] * invT + pB[x] * t);
        }
    }
}

void TransitionsTool::renderZoom(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t, bool zoomIn) {
    int w = dst->width;
    int h = dst->height;

    // In Zoom-In: A zooms in from 1.0 to 1.8 while fading out; B starts at 0.5 and zooms to 1.0 while fading in.
    double scaleA = zoomIn ? (1.0 + t * 0.8) : (1.0 - t * 0.5);
    double scaleB = zoomIn ? (0.6 + t * 0.4) : (1.5 - t * 0.5);
    double fadeB = t;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* d = dst->data[0] + y * dst->linesize[0];

        // Sample frame A
        double srcAY = (y - h * 0.5) / scaleA + h * 0.5;
        // Sample frame B
        double srcBY = (y - h * 0.5) / scaleB + h * 0.5;

        for (int x = 0; x < w; ++x) {
            double srcAX = (x - w * 0.5) / scaleA + w * 0.5;
            double srcBX = (x - w * 0.5) / scaleB + w * 0.5;

            int ax = std::clamp(static_cast<int>(srcAX), 0, w - 1);
            int ay = std::clamp(static_cast<int>(srcAY), 0, h - 1);
            int bx = std::clamp(static_cast<int>(srcBX), 0, w - 1);
            int by = std::clamp(static_cast<int>(srcBY), 0, h - 1);

            const uint8_t* pixA = a->data[0] + ay * a->linesize[0] + ax * 4;
            const uint8_t* pixB = b->data[0] + by * b->linesize[0] + bx * 4;

            for (int c = 0; c < 4; ++c) {
                d[x * 4 + c] = static_cast<uint8_t>(pixA[c] * (1.0 - fadeB) + pixB[c] * fadeB);
            }
        }
    }
}

void TransitionsTool::renderWipe(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t, int dirX, int dirY) {
    int w = dst->width;
    int h = dst->height;
    double feather = 0.05; // 5% feather edge

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* d = dst->data[0] + y * dst->linesize[0];
        const uint8_t* pA = a->data[0] + y * a->linesize[0];
        const uint8_t* pB = b->data[0] + y * b->linesize[0];

        for (int x = 0; x < w; ++x) {
            double coord = 0.0;
            if (dirX == 1) { // Left to right
                coord = static_cast<double>(x) / w;
            } else if (dirX == -1) { // Right to left
                coord = 1.0 - static_cast<double>(x) / w;
            } else if (dirY == 1) { // Top to bottom
                coord = static_cast<double>(y) / h;
            } else if (dirY == -1) { // Bottom to top
                coord = 1.0 - static_cast<double>(y) / h;
            }

            double factor = 0.0;
            if (coord < t - feather) {
                factor = 1.0;
            } else if (coord > t + feather) {
                factor = 0.0;
            } else {
                factor = (t + feather - coord) / (2.0 * feather);
            }

            for (int c = 0; c < 4; ++c) {
                d[x * 4 + c] = static_cast<uint8_t>(pA[x * 4 + c] * (1.0 - factor) + pB[x * 4 + c] * factor);
            }
        }
    }
}

void TransitionsTool::applyBoxBlur(uint8_t* dst, const uint8_t* src, int w, int h, int linesize, int radius) {
    if (radius <= 0) {
        for (int y = 0; y < h; ++y) {
            std::memcpy(dst + y * linesize, src + y * linesize, w * 4);
        }
        return;
    }

    std::vector<uint8_t> temp(h * linesize);

    // Horizontal pass
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        const uint8_t* srcRow = src + y * linesize;
        uint8_t* tmpRow = temp.data() + y * linesize;

        for (int x = 0; x < w; ++x) {
            int rSum = 0, gSum = 0, bSum = 0, aSum = 0;
            int count = 0;
            for (int k = -radius; k <= radius; ++k) {
                int px = std::clamp(x + k, 0, w - 1);
                rSum += srcRow[px * 4 + 0];
                gSum += srcRow[px * 4 + 1];
                bSum += srcRow[px * 4 + 2];
                aSum += srcRow[px * 4 + 3];
                count++;
            }
            tmpRow[x * 4 + 0] = rSum / count;
            tmpRow[x * 4 + 1] = gSum / count;
            tmpRow[x * 4 + 2] = bSum / count;
            tmpRow[x * 4 + 3] = aSum / count;
        }
    }

    // Vertical pass
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* dstRow = dst + y * linesize;
        for (int x = 0; x < w; ++x) {
            int rSum = 0, gSum = 0, bSum = 0, aSum = 0;
            int count = 0;
            for (int k = -radius; k <= radius; ++k) {
                int py = std::clamp(y + k, 0, h - 1);
                const uint8_t* tmpPix = temp.data() + py * linesize + x * 4;
                rSum += tmpPix[0];
                gSum += tmpPix[1];
                bSum += tmpPix[2];
                aSum += tmpPix[3];
                count++;
            }
            dstRow[x * 4 + 0] = rSum / count;
            dstRow[x * 4 + 1] = gSum / count;
            dstRow[x * 4 + 2] = bSum / count;
            dstRow[x * 4 + 3] = aSum / count;
        }
    }
}

void TransitionsTool::renderGaussianBlur(AVFrame* dst, const AVFrame* a, const AVFrame* b, double t) {
    int w = dst->width;
    int h = dst->height;
    int linesize = dst->linesize[0];

    // Peak blur at t = 0.5
    int maxRadius = 14;
    int radiusA = static_cast<int>((1.0 - t) * maxRadius);
    int radiusB = static_cast<int>(t * maxRadius);

    std::vector<uint8_t> blurA(h * linesize);
    std::vector<uint8_t> blurB(h * linesize);

    applyBoxBlur(blurA.data(), a->data[0], w, h, linesize, radiusA);
    applyBoxBlur(blurB.data(), b->data[0], w, h, linesize, radiusB);

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* d = dst->data[0] + y * linesize;
        const uint8_t* pA = blurA.data() + y * linesize;
        const uint8_t* pB = blurB.data() + y * linesize;
        for (int x = 0; x < w * 4; ++x) {
            d[x] = static_cast<uint8_t>(pA[x] * (1.0 - t) + pB[x] * t);
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
