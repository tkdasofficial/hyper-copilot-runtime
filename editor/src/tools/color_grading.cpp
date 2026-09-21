#include "tools/color_grading.hpp"
#include "utils/logger.hpp"
#include <fstream>
#include <sstream>
#include <cmath>
#include <algorithm>

namespace HyperEditor {
namespace Tools {

bool ColorGradingTool::loadLUT(const std::string& lutFilePath, LUT3D& outLut) {
    std::ifstream file(lutFilePath);
    if (!file.is_open()) {
        LOG_WARN("ColorGradingTool", "Could not open LUT file: ", lutFilePath);
        return false;
    }

    std::string line;
    int size = 0;
    std::vector<float> table;

    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') continue;

        std::stringstream ss(line);
        std::string token;
        ss >> token;

        if (token == "LUT_3D_SIZE") {
            ss >> size;
            table.reserve(size * size * size * 3);
        } else if (size > 0) {
            float r = 0.0f, g = 0.0f, b = 0.0f;
            try {
                r = std::stof(token);
                if (ss >> g >> b) {
                    table.push_back(r);
                    table.push_back(g);
                    table.push_back(b);
                }
            } catch (...) {
                // ignore non-numeric comment lines
            }
        }
    }

    if (size > 0 && table.size() == static_cast<size_t>(size * size * size * 3)) {
        outLut.size = size;
        outLut.data = std::move(table);
        LOG_INFO("ColorGradingTool", "Loaded 3D LUT of size ", size, "^3 from ", lutFilePath);
        return true;
    }

    LOG_ERROR("ColorGradingTool", "Invalid or incomplete LUT .cube format in ", lutFilePath);
    return false;
}

void ColorGradingTool::applyTrilinearLUT(const LUT3D& lut, float r, float g, float b, float& outR, float& outG, float& outB) {
    int s = lut.size;
    if (s <= 1) {
        outR = r; outG = g; outB = b;
        return;
    }

    float maxIdx = static_cast<float>(s - 1);
    float rx = std::clamp(r * maxIdx, 0.0f, maxIdx);
    float gy = std::clamp(g * maxIdx, 0.0f, maxIdx);
    float bz = std::clamp(b * maxIdx, 0.0f, maxIdx);

    int x0 = static_cast<int>(rx);
    int y0 = static_cast<int>(gy);
    int z0 = static_cast<int>(bz);
    int x1 = std::min(x0 + 1, s - 1);
    int y1 = std::min(y0 + 1, s - 1);
    int z1 = std::min(z0 + 1, s - 1);

    float fx = rx - x0;
    float fy = gy - y0;
    float fz = bz - z0;

    auto getSample = [&](int x, int y, int z) -> const float* {
        size_t idx = (z * s * s + y * s + x) * 3;
        return &lut.data[idx];
    };

    const float* c000 = getSample(x0, y0, z0);
    const float* c100 = getSample(x1, y0, z0);
    const float* c010 = getSample(x0, y1, z0);
    const float* c110 = getSample(x1, y1, z0);
    const float* c001 = getSample(x0, y0, z1);
    const float* c101 = getSample(x1, y0, z1);
    const float* c011 = getSample(x0, y1, z1);
    const float* c111 = getSample(x1, y1, z1);

    float out[3];
    for (int i = 0; i < 3; ++i) {
        float c00 = c000[i] * (1.0f - fx) + c100[i] * fx;
        float c10 = c010[i] * (1.0f - fx) + c110[i] * fx;
        float c01 = c001[i] * (1.0f - fx) + c101[i] * fx;
        float c11 = c011[i] * (1.0f - fx) + c111[i] * fx;

        float c0 = c00 * (1.0f - fy) + c10 * fy;
        float c1 = c01 * (1.0f - fy) + c11 * fy;

        out[i] = c0 * (1.0f - fz) + c1 * fz;
    }

    outR = out[0];
    outG = out[1];
    outB = out[2];
}

void ColorGradingTool::process(AVFrame* frame, const Core::ColorGradingConfig& config) {
    if (!frame) return;

    bool hasLut = false;
    if (!config.lutPath.empty()) {
        if (config.lutPath != cachedLutPath_) {
            if (loadLUT(config.lutPath, cachedLut_)) {
                cachedLutPath_ = config.lutPath;
                hasLut = true;
            }
        } else if (cachedLut_.size > 0) {
            hasLut = true;
        }
    }

    bool hasGrading = (std::abs(config.brightness) > 1e-4 || 
                       std::abs(config.contrast - 1.0) > 1e-4 ||
                       std::abs(config.saturation - 1.0) > 1e-4 ||
                       std::abs(config.exposure) > 1e-4);

    if (!hasLut && !hasGrading) return;

    float exposureMult = std::pow(2.0f, static_cast<float>(config.exposure));
    float brightness = static_cast<float>(config.brightness);
    float contrast = static_cast<float>(config.contrast);
    float saturation = static_cast<float>(config.saturation);

    int w = frame->width;
    int h = frame->height;
    int linesize = frame->linesize[0];

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* row = frame->data[0] + y * linesize;
        for (int x = 0; x < w; ++x) {
            float r = row[x * 4 + 0] / 255.0f;
            float g = row[x * 4 + 1] / 255.0f;
            float b = row[x * 4 + 2] / 255.0f;

            // 1. Exposure
            r *= exposureMult;
            g *= exposureMult;
            b *= exposureMult;

            // 2. Brightness
            r += brightness;
            g += brightness;
            b += brightness;

            // 3. Contrast
            r = (r - 0.5f) * contrast + 0.5f;
            g = (g - 0.5f) * contrast + 0.5f;
            b = (b - 0.5f) * contrast + 0.5f;

            // 4. Saturation
            float luma = 0.2126f * r + 0.7152f * g + 0.0722f * b;
            r = luma + (r - luma) * saturation;
            g = luma + (g - luma) * saturation;
            b = luma + (b - luma) * saturation;

            r = std::clamp(r, 0.0f, 1.0f);
            g = std::clamp(g, 0.0f, 1.0f);
            b = std::clamp(b, 0.0f, 1.0f);

            // 5. 3D LUT Transform
            if (hasLut) {
                float lutR, lutG, lutB;
                applyTrilinearLUT(cachedLut_, r, g, b, lutR, lutG, lutB);
                r = std::clamp(lutR, 0.0f, 1.0f);
                g = std::clamp(lutG, 0.0f, 1.0f);
                b = std::clamp(lutB, 0.0f, 1.0f);
            }

            row[x * 4 + 0] = static_cast<uint8_t>(r * 255.0f + 0.5f);
            row[x * 4 + 1] = static_cast<uint8_t>(g * 255.0f + 0.5f);
            row[x * 4 + 2] = static_cast<uint8_t>(b * 255.0f + 0.5f);
        }
    }
}

} // namespace Tools
} // namespace HyperEditor
