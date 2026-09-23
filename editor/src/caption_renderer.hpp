#pragma once

#include <string>
#include <vector>
#include <cstdint>

namespace hyper {

struct WordTiming {
    std::string word;
    double start_time; // in seconds
    double end_time;   // in seconds
};

struct CaptionSegment {
    double start_time;
    double end_time;
    std::string full_text;
    std::vector<WordTiming> words;
};

enum class CaptionSize {
    Small,
    Medium,
    Large
};

enum class CaptionStyle {
    Dynamic,  // Vibrant yellow/gold karaoke word tracking
    Bold,     // High-contrast clean white with thick black stroke
    Minimal   // Subtle modern center caption
};

class CaptionRenderer {
public:
    CaptionRenderer(int width, int height, CaptionSize size = CaptionSize::Medium, CaptionStyle style = CaptionStyle::Dynamic);

    void setResolution(int width, int height);
    void setSize(CaptionSize size);
    void setStyle(CaptionStyle style);
    void addSegment(const CaptionSegment& segment);
    void setSegments(const std::vector<CaptionSegment>& segments);

    // Calculates font size in pixels relative to 1080p reference
    int calculateFontSize() const;

    // Generates complete ASS subtitle content with karaoke word highlight tags
    std::string generateAssContent() const;

    // Exports ASS subtitle file to disk
    bool exportAssFile(const std::string& filePath) const;

    // Generates the FFmpeg filter graph string for burning subtitles
    std::string getFfmpegFilterString(const std::string& assFilePath) const;

    static CaptionSize parseSize(const std::string& str);
    static CaptionStyle parseStyle(const std::string& str);

private:
    int m_width;
    int m_height;
    CaptionSize m_size;
    CaptionStyle m_style;
    std::vector<CaptionSegment> m_segments;

    std::string formatTimeAss(double seconds) const;
};

} // namespace hyper
