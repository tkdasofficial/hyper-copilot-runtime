#include "tools/captions.hpp"
#include "utils/logger.hpp"
#include <cmath>
#include <algorithm>
#include <filesystem>

namespace HyperEditor {
namespace Tools {

CaptionsTool::CaptionsTool() {
    init();
}

CaptionsTool::~CaptionsTool() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (ftLibrary_) {
        FT_Done_FreeType(ftLibrary_);
        ftLibrary_ = nullptr;
    }
}

bool CaptionsTool::init() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (initialized_) return true;

    FT_Error err = FT_Init_FreeType(&ftLibrary_);
    if (err) {
        LOG_ERROR("CaptionsTool", "Failed to initialize FreeType library: ", err);
        return false;
    }
    initialized_ = true;
    return true;
}

void CaptionsTool::render(AVFrame* frame, const std::vector<Core::CaptionItem>& captions, double currentTime) {
    if (!frame || captions.empty()) return;
    if (!initialized_ && !init()) return;

    for (const auto& item : captions) {
        if (currentTime >= item.startTime && currentTime <= item.endTime) {
            renderCaptionItem(frame, item, currentTime);
        }
    }
}

static std::string resolveFontPath(const std::string& requested) {
    if (!requested.empty() && std::filesystem::exists(requested)) {
        return requested;
    }
    const std::vector<std::string> defaults = {
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    };
    for (const auto& p : defaults) {
        if (std::filesystem::exists(p)) return p;
    }
    return "";
}

void CaptionsTool::renderCaptionItem(AVFrame* frame, const Core::CaptionItem& item, double currentTime) {
    std::string fontFile = resolveFontPath(item.fontPath);
    if (fontFile.empty()) {
        LOG_WARN("CaptionsTool", "No suitable TTF font found on system for caption rendering.");
        return;
    }

    FT_Face face = nullptr;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (FT_New_Face(ftLibrary_, fontFile.c_str(), 0, &face)) {
            LOG_ERROR("CaptionsTool", "Failed to load font face from: ", fontFile);
            return;
        }
    }

    FT_Set_Pixel_Sizes(face, 0, item.fontSize);

    // Pop-in animation calculation
    double progress = (currentTime - item.startTime);
    double scale = 1.0;
    if (item.popAnimation && progress < 0.25) {
        // Elastic / overshoot pop-up: scale from 0.7 to 1.15 to 1.0
        double t = progress / 0.25;
        scale = 0.7 + 0.3 * std::sin(t * M_PI * 0.5) + 0.15 * std::sin(t * M_PI);
    }

    int canvasW = frame->width;
    int canvasH = frame->height;
    int centerX = static_cast<int>(item.posX * canvasW);
    int centerY = static_cast<int>(item.posY * canvasH);

    // If word-by-word highlights are provided:
    if (!item.words.empty()) {
        // First, measure total width to center properly
        int totalWidth = 0;
        std::vector<int> wordWidths;
        for (const auto& w : item.words) {
            std::string wordWithSpace = w.text + " ";
            hb_buffer_t* hbBuf = hb_buffer_create();
            hb_buffer_add_utf8(hbBuf, wordWithSpace.c_str(), -1, 0, -1);
            hb_buffer_guess_segment_properties(hbBuf);
            hb_font_t* hbFont = hb_ft_font_create(face, nullptr);
            hb_shape(hbFont, hbBuf, nullptr, 0);

            unsigned int glyphCount;
            hb_glyph_position_t* glyphPos = hb_buffer_get_glyph_positions(hbBuf, &glyphCount);
            int wWidth = 0;
            for (unsigned int i = 0; i < glyphCount; ++i) {
                wWidth += (glyphPos[i].x_advance >> 6);
            }
            wordWidths.push_back(wWidth);
            totalWidth += wWidth;

            hb_font_destroy(hbFont);
            hb_buffer_destroy(hbBuf);
        }

        int curX = centerX - static_cast<int>((totalWidth * scale) / 2);
        for (size_t i = 0; i < item.words.size(); ++i) {
            const auto& w = item.words[i];
            bool isActive = (currentTime >= w.start && currentTime <= w.end);
            uint32_t color = isActive ? w.activeColor : item.textColor;
            uint32_t glow = isActive ? 0xFFFFAA00 : item.glowColor; // Rich glow for active word
            int radius = isActive ? item.glowRadius + 4 : item.glowRadius;

            renderTextWithGlow(frame, curX, centerY, w.text + " ", color, glow, radius, scale, face);
            curX += static_cast<int>(wordWidths[i] * scale);
        }
    } else {
        // Single text line with HarfBuzz shaping
        hb_buffer_t* hbBuf = hb_buffer_create();
        hb_buffer_add_utf8(hbBuf, item.text.c_str(), -1, 0, -1);
        hb_buffer_guess_segment_properties(hbBuf);
        hb_font_t* hbFont = hb_ft_font_create(face, nullptr);
        hb_shape(hbFont, hbBuf, nullptr, 0);

        unsigned int glyphCount;
        hb_glyph_position_t* glyphPos = hb_buffer_get_glyph_positions(hbBuf, &glyphCount);
        int totalWidth = 0;
        for (unsigned int i = 0; i < glyphCount; ++i) {
            totalWidth += (glyphPos[i].x_advance >> 6);
        }
        hb_font_destroy(hbFont);
        hb_buffer_destroy(hbBuf);

        int startX = centerX - static_cast<int>((totalWidth * scale) / 2);
        renderTextWithGlow(frame, startX, centerY, item.text, item.textColor, item.glowColor, item.glowRadius, scale, face);
    }

    FT_Done_Face(face);
}

void CaptionsTool::renderTextWithGlow(AVFrame* frame, int startX, int startY, const std::string& text, 
                                     uint32_t textColor, uint32_t glowColor, int glowRadius, double scale, FT_Face face) {
    hb_buffer_t* hbBuf = hb_buffer_create();
    hb_buffer_add_utf8(hbBuf, text.c_str(), -1, 0, -1);
    hb_buffer_guess_segment_properties(hbBuf);
    hb_font_t* hbFont = hb_ft_font_create(face, nullptr);
    hb_shape(hbFont, hbBuf, nullptr, 0);

    unsigned int glyphCount;
    hb_glyph_info_t* glyphInfo = hb_buffer_get_glyph_infos(hbBuf, &glyphCount);
    hb_glyph_position_t* glyphPos = hb_buffer_get_glyph_positions(hbBuf, &glyphCount);

    int curX = startX;
    int curY = startY;

    uint8_t tR = (textColor >> 24) & 0xFF;
    uint8_t tG = (textColor >> 16) & 0xFF;
    uint8_t tB = (textColor >> 8) & 0xFF;
    uint8_t tA = textColor & 0xFF;

    uint8_t gR = (glowColor >> 24) & 0xFF;
    uint8_t gG = (glowColor >> 16) & 0xFF;
    uint8_t gB = (glowColor >> 8) & 0xFF;

    for (unsigned int i = 0; i < glyphCount; ++i) {
        FT_UInt glyphIndex = glyphInfo[i].codepoint;
        if (FT_Load_Glyph(face, glyphIndex, FT_LOAD_DEFAULT)) continue;
        if (FT_Render_Glyph(face->glyph, FT_RENDER_MODE_NORMAL)) continue;

        FT_Bitmap& bmp = face->glyph->bitmap;
        int xOffset = static_cast<int>((glyphPos[i].x_offset >> 6) * scale);
        int yOffset = static_cast<int>((glyphPos[i].y_offset >> 6) * scale);
        int left = curX + xOffset + static_cast<int>(face->glyph->bitmap_left * scale);
        int top = curY + yOffset - static_cast<int>(face->glyph->bitmap_top * scale);

        // Neon glow blur pass (draw wider softer halo)
        if (glowRadius > 0) {
            for (int r = glowRadius; r >= 1; r -= 2) {
                float glowAlpha = 0.25f / (r * 0.7f);
                for (int gy = -r; gy <= r; gy += 2) {
                    for (int gx = -r; gx <= r; gx += 2) {
                        for (unsigned int by = 0; by < bmp.rows; ++by) {
                            int py = top + by + gy;
                            if (py < 0 || py >= frame->height) continue;
                            uint8_t* row = frame->data[0] + py * frame->linesize[0];
                            for (unsigned int bx = 0; bx < bmp.width; ++bx) {
                                int px = left + bx + gx;
                                if (px < 0 || px >= frame->width) continue;
                                uint8_t srcAlpha = bmp.buffer[by * bmp.pitch + bx];
                                if (srcAlpha == 0) continue;

                                float a = (srcAlpha / 255.0f) * glowAlpha;
                                row[px * 4 + 0] = static_cast<uint8_t>(std::min(255.0f, row[px * 4 + 0] + gR * a));
                                row[px * 4 + 1] = static_cast<uint8_t>(std::min(255.0f, row[px * 4 + 1] + gG * a));
                                row[px * 4 + 2] = static_cast<uint8_t>(std::min(255.0f, row[px * 4 + 2] + gB * a));
                                row[px * 4 + 3] = static_cast<uint8_t>(std::min(255.0f, row[px * 4 + 3] + 255.0f * a));
                            }
                        }
                    }
                }
            }
        }

        // Crisp glyph rasterization
        for (unsigned int by = 0; by < bmp.rows; ++by) {
            int py = top + by;
            if (py < 0 || py >= frame->height) continue;
            uint8_t* row = frame->data[0] + py * frame->linesize[0];
            for (unsigned int bx = 0; bx < bmp.width; ++bx) {
                int px = left + bx;
                if (px < 0 || px >= frame->width) continue;
                uint8_t srcAlpha = bmp.buffer[by * bmp.pitch + bx];
                if (srcAlpha == 0) continue;

                float a = (srcAlpha / 255.0f) * (tA / 255.0f);
                row[px * 4 + 0] = static_cast<uint8_t>(row[px * 4 + 0] * (1.0f - a) + tR * a);
                row[px * 4 + 1] = static_cast<uint8_t>(row[px * 4 + 1] * (1.0f - a) + tG * a);
                row[px * 4 + 2] = static_cast<uint8_t>(row[px * 4 + 2] * (1.0f - a) + tB * a);
                row[px * 4 + 3] = static_cast<uint8_t>(std::min(255.0f, row[px * 4 + 3] + srcAlpha * (tA / 255.0f)));
            }
        }

        curX += static_cast<int>((glyphPos[i].x_advance >> 6) * scale);
        curY += static_cast<int>((glyphPos[i].y_advance >> 6) * scale);
    }

    hb_font_destroy(hbFont);
    hb_buffer_destroy(hbBuf);
}

} // namespace Tools
} // namespace HyperEditor
