#include "caption_renderer.hpp"
#include "scene_builder.hpp"
#include <fstream>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cmath>
#include <iostream>

namespace hyper {

CaptionRenderer::CaptionRenderer(int width, int height, CaptionSize size, CaptionStyle style)
    : m_width(width), m_height(height), m_size(size), m_style(style) {
}

void CaptionRenderer::setResolution(int width, int height) {
    m_width = width;
    m_height = height;
}

void CaptionRenderer::setSize(CaptionSize size) {
    m_size = size;
}

void CaptionRenderer::setStyle(CaptionStyle style) {
    m_style = style;
}

void CaptionRenderer::addWord(const std::string& word, double start_time, double end_time) {
    if (word.empty()) return;
    WordTiming wt;
    wt.word = word;
    wt.start_time = start_time;
    wt.end_time = (end_time > start_time) ? end_time : (start_time + 0.25);
    m_rawWords.push_back(wt);
}

void CaptionRenderer::addSegment(const CaptionSegment& segment) {
    m_segments.push_back(segment);
}

void CaptionRenderer::setSegments(const std::vector<CaptionSegment>& segments) {
    m_segments = segments;
}

void CaptionRenderer::clear() {
    m_rawWords.clear();
    m_segments.clear();
}

int CaptionRenderer::calculateFontSize() const {
    // 1080p horizontal reference (1920x1080):
    // Small: 28px, Medium: 42px, Large: 56px
    // 1080p vertical reference (1080x1920):
    // Small: 48px, Medium: 72px, Large: 96px
    bool isVertical = (m_height > m_width);
    double base = 42.0;

    if (isVertical) {
        switch (m_size) {
            case CaptionSize::Small:  base = 48.0; break;
            case CaptionSize::Medium: base = 72.0; break;
            case CaptionSize::Large:  base = 96.0; break;
        }
        double scale = static_cast<double>(m_height) / 1920.0;
        int result = static_cast<int>(std::round(base * (scale > 0 ? scale : 1.0)));
        return std::max(result, 24);
    } else {
        switch (m_size) {
            case CaptionSize::Small:  base = 28.0; break;
            case CaptionSize::Medium: base = 42.0; break;
            case CaptionSize::Large:  base = 56.0; break;
        }
        double scale = static_cast<double>(m_height) / 1080.0;
        int result = static_cast<int>(std::round(base * (scale > 0 ? scale : 1.0)));
        return std::max(result, 18);
    }
}

std::string CaptionRenderer::formatTimeAss(double seconds) const {
    if (seconds < 0) seconds = 0;
    int total_cs = static_cast<int>(std::round(seconds * 100.0));
    int cs = total_cs % 100;
    int total_s = total_cs / 100;
    int s = total_s % 60;
    int total_m = total_s / 60;
    int m = total_m % 60;
    int h = total_m / 60;

    std::ostringstream oss;
    oss << h << ":"
        << std::setw(2) << std::setfill('0') << m << ":"
        << std::setw(2) << std::setfill('0') << s << "."
        << std::setw(2) << std::setfill('0') << cs;
    return oss.str();
}

bool CaptionRenderer::loadFromWordsJson(const std::string& jsonFilePath) {
    std::ifstream file(jsonFilePath);
    if (!file.is_open()) {
        std::cerr << "[CaptionRenderer] Could not open words JSON: " << jsonFilePath << std::endl;
        return false;
    }

    std::string content((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    m_rawWords.clear();

    // Parse array of word objects
    // Handles formats like:
    // [{"word": "the", "start_time": 0.12, "end_time": 0.35}, ...]
    // or {"text": "the", "start": 0.12, "end": 0.35}
    size_t pos = 0;
    while (pos < content.size()) {
        size_t wKey = content.find("\"word\"", pos);
        if (wKey == std::string::npos) {
            wKey = content.find("\"text\"", pos);
        }
        if (wKey == std::string::npos) break;

        size_t valStart = content.find(":", wKey);
        if (valStart == std::string::npos) break;
        size_t q1 = content.find("\"", valStart);
        if (q1 == std::string::npos) break;
        size_t q2 = content.find("\"", q1 + 1);
        if (q2 == std::string::npos) break;
        std::string wordText = content.substr(q1 + 1, q2 - q1 - 1);

        double st = 0.0;
        double et = 0.0;

        // Find start time
        size_t sKey = content.find("\"start", q2);
        if (sKey != std::string::npos && sKey < content.find("}", q2)) {
            size_t c1 = content.find(":", sKey);
            if (c1 != std::string::npos) {
                st = std::stod(content.substr(c1 + 1));
            }
        }

        // Find end time
        size_t eKey = content.find("\"end", q2);
        if (eKey != std::string::npos && eKey < content.find("}", q2)) {
            size_t c2 = content.find(":", eKey);
            if (c2 != std::string::npos) {
                et = std::stod(content.substr(c2 + 1));
            }
        }

        if (et <= st) {
            et = st + 0.25;
        }

        addWord(wordText, st, et);
        pos = q2 + 1;
    }

    std::cout << "[CaptionRenderer] Loaded " << m_rawWords.size() << " word timings from JSON." << std::endl;
    buildSegmentsFromRawWords();
    return !m_rawWords.empty();
}

bool CaptionRenderer::loadFromScenes(const std::vector<SceneSegment>& scenes) {
    m_rawWords.clear();
    m_segments.clear();

    double accumTime = 0.0;
    for (const auto& sc : scenes) {
        if (sc.narration_text.empty()) {
            accumTime += sc.duration;
            continue;
        }

        // Split narration into individual words
        std::vector<std::string> words;
        std::istringstream iss(sc.narration_text);
        std::string w;
        while (iss >> w) {
            words.push_back(w);
        }

        if (words.empty()) {
            accumTime += sc.duration;
            continue;
        }

        double sceneStart = (sc.start_time >= 0) ? sc.start_time : accumTime;
        double sceneDur = (sc.duration > 0) ? sc.duration : 4.0;
        double wordDur = sceneDur / static_cast<double>(words.size());
        if (wordDur < 0.15) wordDur = 0.15;

        for (size_t i = 0; i < words.size(); ++i) {
            double st = sceneStart + i * wordDur;
            double et = std::min(sceneStart + sceneDur, st + wordDur * 0.95);
            addWord(words[i], st, et);
        }

        accumTime = sceneStart + sceneDur;
    }

    std::cout << "[CaptionRenderer] Synthesized " << m_rawWords.size() << " word timings from scenes narration." << std::endl;
    buildSegmentsFromRawWords();
    return !m_rawWords.empty();
}

bool CaptionRenderer::loadFromScript(const std::string& script, double totalDuration) {
    m_rawWords.clear();
    m_segments.clear();

    std::vector<std::string> words;
    std::istringstream iss(script);
    std::string w;
    while (iss >> w) {
        words.push_back(w);
    }

    if (words.empty() || totalDuration <= 0) return false;

    double wordDur = totalDuration / static_cast<double>(words.size());
    for (size_t i = 0; i < words.size(); ++i) {
        double st = i * wordDur;
        double et = std::min(totalDuration, st + wordDur * 0.95);
        addWord(words[i], st, et);
    }

    buildSegmentsFromRawWords();
    return true;
}

void CaptionRenderer::buildSegmentsFromRawWords() {
    m_segments.clear();
    if (m_rawWords.empty()) return;

    // Rhythmic phrase chunking:
    // Vertical mobile 9:16 -> 3 to 4 words per subtitle screen for maximum punch and zero clipping
    // Horizontal 16:9 -> 4 to 5 words per subtitle screen
    bool isVertical = (m_height > m_width);
    size_t chunkSize = isVertical ? 3 : 5;

    for (size_t i = 0; i < m_rawWords.size(); i += chunkSize) {
        size_t endIdx = std::min(i + chunkSize, m_rawWords.size());
        CaptionSegment seg;
        seg.start_time = m_rawWords[i].start_time;
        seg.end_time = m_rawWords[endIdx - 1].end_time;

        std::string fullText;
        for (size_t j = i; j < endIdx; ++j) {
            seg.words.push_back(m_rawWords[j]);
            if (!fullText.empty()) fullText += " ";
            fullText += m_rawWords[j].word;
        }
        seg.full_text = fullText;
        m_segments.push_back(seg);
    }
}

std::string CaptionRenderer::generateAssContent() const {
    int fontSize = calculateFontSize();
    bool isVertical = (m_height > m_width);
    int outline = isVertical ? 5 : 4;
    int shadow = 2;
    int marginV = isVertical ? static_cast<int>(m_height * 0.16) : static_cast<int>(m_height * 0.08);

    // Color definitions (ASS uses &HAABBGGRR)
    // Primary: White (&H00FFFFFF)
    // Active Karaoke Highlight: Vivid Golden Yellow (&H0000E6FF) or Bright Cyan (&H0000FFFF)
    std::string highlightColor = "&H0000E6FF"; // Vibrant Gold/Yellow in BGR
    std::string dimColor = "&H00C0C0C0";       // Soft Silver for upcoming words in cue

    if (m_style == CaptionStyle::Bold) {
        highlightColor = "&H0000FFFF"; // Electric Cyan in BGR
        outline += 1;
    } else if (m_style == CaptionStyle::Minimal) {
        highlightColor = "&H00FFFFFF";
        shadow = 1;
    }

    std::ostringstream ss;
    ss << "[Script Info]\n"
       << "; Script generated by HyperEditor C++ Subtitle Engine\n"
       << "Title: Hyper Copilot Dynamic Synchronized Captions\n"
       << "ScriptType: v4.00+\n"
       << "WrapStyle: 0\n"
       << "ScaledBorderAndShadow: yes\n"
       << "PlayResX: " << m_width << "\n"
       << "PlayResY: " << m_height << "\n\n"
       << "[V4+ Styles]\n"
       << "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
       << "Style: Default,DejaVu Sans," << fontSize << ",&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
       << outline << "," << shadow << ",2,30,30," << marginV << ",1\n\n"
       << "[Events]\n"
       << "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n";

    for (const auto& seg : m_segments) {
        if (seg.words.empty()) {
            ss << "Dialogue: 0," << formatTimeAss(seg.start_time) << ","
               << formatTimeAss(seg.end_time) << ",Default,,0,0,0,,"
               << "{\\an2}" << seg.full_text << "\n";
            continue;
        }

        // Real-time word-level synchronization (Karaoke highlight)
        // For each active word in the phrase, emit a dialogue cue with the active word illuminated
        for (size_t i = 0; i < seg.words.size(); ++i) {
            double wordStart = seg.words[i].start_time;
            double wordEnd = seg.words[i].end_time;
            if (wordEnd <= wordStart) {
                wordEnd = wordStart + 0.22;
            }

            // Cap within segment bounds
            wordStart = std::max(wordStart, seg.start_time);
            wordEnd = std::min(wordEnd, seg.end_time);

            if (wordEnd <= wordStart) continue;

            std::ostringstream line;
            line << "Dialogue: 0," << formatTimeAss(wordStart) << ","
                 << formatTimeAss(wordEnd) << ",Default,,0,0,0,,{\\an2}";

            for (size_t j = 0; j < seg.words.size(); ++j) {
                const auto& w = seg.words[j];
                if (j == i) {
                    // Active word: illuminated in vivid highlight color with bold accent
                    line << "{\\c" << highlightColor << "}{\\b1}" << w.word << "{\\b0}{\\c&H00FFFFFF&}";
                } else if (j < i) {
                    // Already spoken in current phrase: clean white
                    line << "{\\c&H00FFFFFF&}" << w.word;
                } else {
                    // Upcoming in current phrase: dimmed silver
                    line << "{\\c" << dimColor << "}" << w.word << "{\\c&H00FFFFFF&}";
                }

                if (j + 1 < seg.words.size()) {
                    line << " ";
                }
            }
            ss << line.str() << "\n";
        }
    }

    return ss.str();
}

bool CaptionRenderer::exportAssFile(const std::string& filePath) const {
    std::ofstream out(filePath);
    if (!out.is_open()) return false;
    out << generateAssContent();
    std::cout << "[CaptionRenderer] Exported ASS captions to " << filePath << std::endl;
    return true;
}

std::string CaptionRenderer::getFfmpegFilterString(const std::string& assFilePath) const {
    std::string escaped;
    for (char c : assFilePath) {
        if (c == ':' || c == '\\' || c == '\'') {
            escaped += '\\';
        }
        escaped += c;
    }
    return "ass='" + escaped + "'";
}

CaptionSize CaptionRenderer::parseSize(const std::string& str) {
    std::string lower = str;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    if (lower.find("small") != std::string::npos || lower == "2") return CaptionSize::Small;
    if (lower.find("large") != std::string::npos || lower == "6") return CaptionSize::Large;
    return CaptionSize::Medium;
}

CaptionStyle CaptionRenderer::parseStyle(const std::string& str) {
    std::string lower = str;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    if (lower.find("bold") != std::string::npos) return CaptionStyle::Bold;
    if (lower.find("minimal") != std::string::npos) return CaptionStyle::Minimal;
    return CaptionStyle::Dynamic;
}

} // namespace hyper
