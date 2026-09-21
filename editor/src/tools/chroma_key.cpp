#include "tools/chroma_key.hpp"
#include <cmath>
#include <algorithm>

namespace HyperEditor {
namespace Tools {

void ChromaKeyTool::applyDespill(uint8_t& r, uint8_t& g, uint8_t& b, uint8_t keyR, uint8_t keyG, uint8_t keyB) {
    if (keyG > keyR && keyG > keyB) {
        // Green despill: clamp green to average or max of red and blue
        uint8_t limit = static_cast<uint8_t>((r + b) / 2);
        if (g > limit) {
            g = limit;
        }
    } else if (keyB > keyR && keyB > keyG) {
        // Blue despill: clamp blue to average of red and green
        uint8_t limit = static_cast<uint8_t>((r + g) / 2);
        if (b > limit) {
            b = limit;
        }
    }
}

void ChromaKeyTool::process(AVFrame* frame, const Core::ChromaKeyConfig& config) {
    if (!frame || !config.enabled) return;

    int w = frame->width;
    int h = frame->height;
    int linesize = frame->linesize[0];

    float keyR = config.keyR / 255.0f;
    float keyG = config.keyG / 255.0f;
    float keyB = config.keyB / 255.0f;

    float tolerance = static_cast<float>(config.tolerance);
    float softness = std::max(0.001f, static_cast<float>(config.edgeSoftness));

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* row = frame->data[0] + y * linesize;
        for (int x = 0; x < w; ++x) {
            float r = row[x * 4 + 0] / 255.0f;
            float g = row[x * 4 + 1] / 255.0f;
            float b = row[x * 4 + 2] / 255.0f;

            // Normalized Euclidean distance in RGB color cube
            float dr = r - keyR;
            float dg = g - keyG;
            float db = b - keyB;
            float dist = std::sqrt(dr * dr + dg * dg + db * db) / 1.73205f; // sqrt(3)

            float alpha = 1.0f;
            if (dist < tolerance) {
                alpha = 0.0f;
            } else if (dist < tolerance + softness) {
                alpha = (dist - tolerance) / softness;
            }

            // Foreground despill on partial transparent edge pixels
            if (alpha < 0.99f && alpha > 0.0f) {
                applyDespill(row[x * 4 + 0], row[x * 4 + 1], row[x * 4 + 2], 
                             config.keyR, config.keyG, config.keyB);
            }

            uint8_t origA = row[x * 4 + 3];
            row[x * 4 + 3] = static_cast<uint8_t>(std::clamp(origA * alpha, 0.0f, 255.0f));
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
