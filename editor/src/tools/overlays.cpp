#include "tools/overlays.hpp"
#include <algorithm>
#include <cmath>

namespace HyperEditor {
namespace Tools {

uint8_t OverlaysTool::blendMultiply(uint8_t base, uint8_t blend) {
    return static_cast<uint8_t>((static_cast<int>(base) * static_cast<int>(blend)) / 255);
}

uint8_t OverlaysTool::blendScreen(uint8_t base, uint8_t blend) {
    return static_cast<uint8_t>(255 - ((255 - static_cast<int>(base)) * (255 - static_cast<int>(blend))) / 255);
}

uint8_t OverlaysTool::blendOverlay(uint8_t base, uint8_t blend) {
    if (base < 128) {
        return static_cast<uint8_t>((2 * static_cast<int>(base) * static_cast<int>(blend)) / 255);
    } else {
        return static_cast<uint8_t>(255 - (2 * (255 - static_cast<int>(base)) * (255 - static_cast<int>(blend))) / 255);
    }
}

uint8_t OverlaysTool::blendAdditive(uint8_t base, uint8_t blend) {
    return static_cast<uint8_t>(std::min(255, static_cast<int>(base) + static_cast<int>(blend)));
}

void OverlaysTool::blend(AVFrame* baseFrame, const AVFrame* overlayFrame, const Core::OverlayConfig& config) {
    if (!baseFrame || !overlayFrame || config.opacity <= 0.0) return;

    int baseW = baseFrame->width;
    int baseH = baseFrame->height;
    int overW = (config.width > 0) ? config.width : overlayFrame->width;
    int overH = (config.height > 0) ? config.height : overlayFrame->height;

    int dstX = config.posX;
    int dstY = config.posY;

    int startY = std::max(0, dstY);
    int endY = std::min(baseH, dstY + overH);
    int startX = std::max(0, dstX);
    int endX = std::min(baseW, dstX + overW);

    if (startX >= endX || startY >= endY) return;

    double globalOpacity = std::clamp(config.opacity, 0.0, 1.0);

    #pragma omp parallel for schedule(static)
    for (int y = startY; y < endY; ++y) {
        uint8_t* baseRow = baseFrame->data[0] + y * baseFrame->linesize[0];
        int srcY = (y - dstY) * overlayFrame->height / overH;
        const uint8_t* overRow = overlayFrame->data[0] + srcY * overlayFrame->linesize[0];

        for (int x = startX; x < endX; ++x) {
            int srcX = (x - dstX) * overlayFrame->width / overW;

            uint8_t sR = overRow[srcX * 4 + 0];
            uint8_t sG = overRow[srcX * 4 + 1];
            uint8_t sB = overRow[srcX * 4 + 2];
            uint8_t sA = overRow[srcX * 4 + 3];

            double alpha = (sA / 255.0) * globalOpacity;
            if (alpha <= 0.0) continue;

            uint8_t dR = baseRow[x * 4 + 0];
            uint8_t dG = baseRow[x * 4 + 1];
            uint8_t dB = baseRow[x * 4 + 2];
            uint8_t dA = baseRow[x * 4 + 3];

            uint8_t blendedR = sR;
            uint8_t blendedG = sG;
            uint8_t blendedB = sB;

            switch (config.mode) {
                case Core::BlendMode::Normal:
                    blendedR = sR;
                    blendedG = sG;
                    blendedB = sB;
                    break;
                case Core::BlendMode::Multiply:
                    blendedR = blendMultiply(dR, sR);
                    blendedG = blendMultiply(dG, sG);
                    blendedB = blendMultiply(dB, sB);
                    break;
                case Core::BlendMode::Screen:
                    blendedR = blendScreen(dR, sR);
                    blendedG = blendScreen(dG, sG);
                    blendedB = blendScreen(dB, sB);
                    break;
                case Core::BlendMode::Overlay:
                    blendedR = blendOverlay(dR, sR);
                    blendedG = blendOverlay(dG, sG);
                    blendedB = blendOverlay(dB, sB);
                    break;
                case Core::BlendMode::Additive:
                    blendedR = blendAdditive(dR, sR);
                    blendedG = blendAdditive(dG, sG);
                    blendedB = blendAdditive(dB, sB);
                    break;
            }

            // Alpha composite: out = blended * alpha + dst * (1 - alpha)
            baseRow[x * 4 + 0] = static_cast<uint8_t>(blendedR * alpha + dR * (1.0 - alpha));
            baseRow[x * 4 + 1] = static_cast<uint8_t>(blendedG * alpha + dG * (1.0 - alpha));
            baseRow[x * 4 + 2] = static_cast<uint8_t>(blendedB * alpha + dB * (1.0 - alpha));
            baseRow[x * 4 + 3] = static_cast<uint8_t>(std::min(255.0, dA + sA * globalOpacity));
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
