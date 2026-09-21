#pragma once

#include "core/timeline.hpp"
#include <string>
#include <vector>
#include <memory>
#include <mutex>
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
}

#include <ft2build.h>
#include FT_FREETYPE_H
#include <hb.h>
#include <hb-ft.h>

namespace HyperEditor {
namespace Tools {

class CaptionsTool {
public:
    CaptionsTool();
    ~CaptionsTool();

    // Initializes FreeType library
    bool init();

    // Renders active captions onto the RGBA frame for the given timestamp
    void render(AVFrame* frame, const std::vector<Core::CaptionItem>& captions, double currentTime);

private:
    void renderCaptionItem(AVFrame* frame, const Core::CaptionItem& item, double currentTime);
    void renderTextWithGlow(AVFrame* frame, int startX, int startY, const std::string& text, 
                            uint32_t textColor, uint32_t glowColor, int glowRadius, double scale, FT_Face face);
    void applyNeonGlow(AVFrame* frame, int x, int y, int w, int h, uint32_t glowColor, int radius);

    FT_Library ftLibrary_ = nullptr;
    std::mutex mutex_;
    bool initialized_ = false;
};

} // namespace Tools
} // namespace HyperEditor
