#pragma once

#include "core/timeline.hpp"
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
}

namespace HyperEditor {
namespace Tools {

class ChromaKeyTool {
public:
    ChromaKeyTool() = default;
    ~ChromaKeyTool() = default;

    // Removes green/blue screen background and generates softened alpha channel mask
    void process(AVFrame* frame, const Core::ChromaKeyConfig& config);

    // Suppresses color spill on foreground edges
    void applyDespill(uint8_t& r, uint8_t& g, uint8_t& b, uint8_t keyR, uint8_t keyG, uint8_t keyB);
};

} // namespace Tools
} // namespace HyperEditor
