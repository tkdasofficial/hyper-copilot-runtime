#pragma once

#include "core/timeline.hpp"
#include <string>
#include <vector>
#include <memory>
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
}

namespace HyperEditor {
namespace Tools {

struct LUT3D {
    int size = 0;
    std::vector<float> data; // size * size * size * 3 floats
};

class ColorGradingTool {
public:
    ColorGradingTool() = default;
    ~ColorGradingTool() = default;

    // Applies full color grading pipeline (exposure, brightness, contrast, saturation, and 3D LUT)
    void process(AVFrame* frame, const Core::ColorGradingConfig& config);

    // Loads a standard .cube 3D LUT file
    bool loadLUT(const std::string& lutFilePath, LUT3D& outLut);

    // Trilinear interpolation on 3D LUT
    static void applyTrilinearLUT(const LUT3D& lut, float r, float g, float b, float& outR, float& outG, float& outB);

private:
    std::string cachedLutPath_;
    LUT3D cachedLut_;
};

} // namespace Tools
} // namespace HyperEditor
