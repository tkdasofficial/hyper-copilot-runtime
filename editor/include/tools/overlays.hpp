#pragma once

#include "core/timeline.hpp"
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
}

namespace HyperEditor {
namespace Tools {

class OverlaysTool {
public:
    OverlaysTool() = default;
    ~OverlaysTool() = default;

    // Blends source overlay frame onto base canvas frame using the specified blend mode, opacity, and position
    void blend(AVFrame* baseFrame, const AVFrame* overlayFrame, const Core::OverlayConfig& config);

    // Pixel math helpers for blend modes (normalized 0..1 or 0..255)
    static uint8_t blendMultiply(uint8_t base, uint8_t blend);
    static uint8_t blendScreen(uint8_t base, uint8_t blend);
    static uint8_t blendOverlay(uint8_t base, uint8_t blend);
    static uint8_t blendAdditive(uint8_t base, uint8_t blend);
};

} // namespace Tools
} // namespace HyperEditor
