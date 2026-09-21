#include "tools/masking.hpp"
#include <cmath>
#include <algorithm>

namespace HyperEditor {
namespace Tools {

void MaskingTool::applyMask(AVFrame* frame, const Core::MaskConfig& config) {
    if (!frame || config.type == Core::MaskType::None) return;

    int width = frame->width;
    int height = frame->height;
    int linesize = frame->linesize[0];
    uint8_t* data = frame->data[0];

    switch (config.type) {
        case Core::MaskType::Rectangular:
            applyRectangularMask(data, width, height, linesize, config);
            break;
        case Core::MaskType::Elliptical:
            applyEllipticalMask(data, width, height, linesize, config);
            break;
        case Core::MaskType::Linear:
            applyLinearMask(data, width, height, linesize, config);
            break;
        case Core::MaskType::None:
            break;
    }
}

void MaskingTool::applyRectangularMask(uint8_t* data, int width, int height, int linesize, const Core::MaskConfig& config) {
    double rx = config.x * width;
    double ry = config.y * height;
    double rw = config.width * width;
    double rh = config.height * height;
    double featherPx = std::max(1.0, config.feather * std::min(width, height) * 0.5);

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < height; ++y) {
        uint8_t* row = data + y * linesize;
        for (int x = 0; x < width; ++x) {
            double dx = 0.0;
            if (x < rx) dx = rx - x;
            else if (x > rx + rw) dx = x - (rx + rw);

            double dy = 0.0;
            if (y < ry) dy = ry - y;
            else if (y > ry + rh) dy = y - (ry + rh);

            double dist = std::sqrt(dx * dx + dy * dy);
            double alphaFactor = 1.0;
            if (dist > featherPx) {
                alphaFactor = 0.0;
            } else if (dist > 0.0) {
                alphaFactor = 1.0 - (dist / featherPx);
            }

            if (config.invert) {
                alphaFactor = 1.0 - alphaFactor;
            }

            // RGBA pixel, alpha is index 3
            uint8_t currentA = row[x * 4 + 3];
            row[x * 4 + 3] = static_cast<uint8_t>(std::clamp(currentA * alphaFactor, 0.0, 255.0));
        }
    }
}

void MaskingTool::applyEllipticalMask(uint8_t* data, int width, int height, int linesize, const Core::MaskConfig& config) {
    double cx = (config.x + config.width * 0.5) * width;
    double cy = (config.y + config.height * 0.5) * height;
    double rx = std::max(1.0, config.width * 0.5 * width);
    double ry = std::max(1.0, config.height * 0.5 * height);
    double feather = std::max(0.001, config.feather);

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < height; ++y) {
        uint8_t* row = data + y * linesize;
        for (int x = 0; x < width; ++x) {
            double nx = (x - cx) / rx;
            double ny = (y - cy) / ry;
            double normDist = std::sqrt(nx * nx + ny * ny);

            double alphaFactor = 1.0;
            if (normDist > 1.0 + feather) {
                alphaFactor = 0.0;
            } else if (normDist > 1.0) {
                alphaFactor = 1.0 - ((normDist - 1.0) / feather);
            }

            if (config.invert) {
                alphaFactor = 1.0 - alphaFactor;
            }

            uint8_t currentA = row[x * 4 + 3];
            row[x * 4 + 3] = static_cast<uint8_t>(std::clamp(currentA * alphaFactor, 0.0, 255.0));
        }
    }
}

void MaskingTool::applyLinearMask(uint8_t* data, int width, int height, int linesize, const Core::MaskConfig& config) {
    double angleRad = config.angle * (M_PI / 180.0);
    double dirX = std::cos(angleRad);
    double dirY = std::sin(angleRad);

    double cx = config.x * width;
    double cy = config.y * height;
    double length = std::max(1.0, config.width * std::max(width, height));
    double feather = std::max(1.0, config.feather * length);

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < height; ++y) {
        uint8_t* row = data + y * linesize;
        for (int x = 0; x < width; ++x) {
            double proj = (x - cx) * dirX + (y - cy) * dirY;
            double alphaFactor = 1.0;
            if (proj < 0.0) {
                alphaFactor = 1.0;
            } else if (proj > feather) {
                alphaFactor = 0.0;
            } else {
                alphaFactor = 1.0 - (proj / feather);
            }

            if (config.invert) {
                alphaFactor = 1.0 - alphaFactor;
            }

            uint8_t currentA = row[x * 4 + 3];
            row[x * 4 + 3] = static_cast<uint8_t>(std::clamp(currentA * alphaFactor, 0.0, 255.0));
        }
    }
}

void MaskingTool::applyAlphaCutout(AVFrame* targetFrame, const AVFrame* alphaMaskFrame) {
    if (!targetFrame || !alphaMaskFrame) return;

    int w = std::min(targetFrame->width, alphaMaskFrame->width);
    int h = std::min(targetFrame->height, alphaMaskFrame->height);

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* dst = targetFrame->data[0] + y * targetFrame->linesize[0];
        const uint8_t* mask = alphaMaskFrame->data[0] + y * alphaMaskFrame->linesize[0];
        for (int x = 0; x < w; ++x) {
            uint8_t maskA = mask[x * 4 + 3];
            uint8_t curA = dst[x * 4 + 3];
            dst[x * 4 + 3] = static_cast<uint8_t>((curA * maskA) / 255);
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
