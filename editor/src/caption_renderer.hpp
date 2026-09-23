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

// Forward declaration
struct SceneSegment;

enum class CaptionSize {
    Small,
    Medium,
    Large
};

enum class CaptionStyle {
    Dynamic,  // Vibrant golden yellow karaoke word tracking
    Bold,     // High-contrast clean cyan with thick black stroke
    Minimal   // Subtle modern center caption
};

class CaptionRenderer {
public:
    CaptionRenderer(int width = 1920, int height = 1080, CaptionSize size = CaptionSize::Medium, CaptionStyle style = CaptionStyle::Dynamic);

    void setResolution(int width, int height);
    void setSize(CaptionSize size);
    void setStyle(CaptionStyle style);

    void addWord(const std::string& word, double start_time, double end_time);
    void addSegment(const CaptionSegment& segment);
    void setSegments(const std::vector<CaptionSegment>& segments);
    void clear();

    // Data Loaders
    bool loadFromWordsJson(const std::string& jsonFilePath);
    bool loadFromScenes(const std::vector<SceneSegment>& scenes);
    bool loadFromScript(const std::string& script, double totalDuration);

    // Font size in pixels relative to video resolution (Small / Medium / Large)
    int calculateFontSize() const;

    // Generates complete ASS subtitle content with rhythmic phrase chunking & karaoke active word highlighting
    std::string generateAssContent() const;

    // Exports ASS subtitle file to disk
    bool exportAssFile(const std::string& filePath) const;

    // Generates the FFmpeg filter graph string for burning subtitles
    std::string getFfmpegFilterString(const std::string& assFilePath) const;

    static CaptionSize parseSize(const std::string& str);
    static CaptionStyle parseStyle(const std::string& str);

    const std::vector<WordTiming>& getWords() const { return m_rawWords; }
    size_t getWordCount() const { return m_rawWords.size(); }

private:
    int m_width;
    int m_height;
    CaptionSize m_size;
    CaptionStyle m_style;
    std::vector<WordTiming> m_rawWords;
    std::vector<CaptionSegment> m_segments;

    std::string formatTimeAss(double seconds) const;
    void buildSegmentsFromRawWords();
};

} // namespace hyper
