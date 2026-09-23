#pragma once

#include <string>
#include <vector>

namespace hyper {

enum class TransitionType {
    None,
    Fade,
    Crossfade,
    WipeLeft,
    WipeRight,
    CircleCrop,
    ZoomIn
};

struct TimelineClip {
    std::string id;
    std::string file_path;
    double start_time;       // Timeline start in seconds
    double duration;         // Duration in seconds in output
    double source_trim_start;// Source file offset in seconds
    TransitionType transition;
    double transition_duration; // Typically 0.3 - 0.5 seconds
};

struct SceneSegment {
    int index;
    double start_time;
    double end_time;
    double duration;
    std::string primary_keyword;
    std::string secondary_keyword;
    std::string narration_text;
    std::vector<TimelineClip> clips; // 1 or more distinct clips, NO LOOPING
};

class SceneBuilder {
public:
    SceneBuilder(int targetWidth = 1920, int targetHeight = 1080, int fps = 60);

    void setResolution(int width, int height);
    void setFps(int fps);
    void addScene(const SceneSegment& scene);
    void addSegment(const SceneSegment& scene) { addScene(scene); }
    void clear();

    const std::vector<SceneSegment>& getScenes() const { return m_scenes; }
    std::vector<TimelineClip> getFlattenedClips() const;

    int getWidth() const { return m_width; }
    int getHeight() const { return m_height; }
    int getFps() const { return m_fps; }
    double getTotalDuration() const;

    static TransitionType parseTransition(const std::string& str);
    static std::string transitionToString(TransitionType t);

private:
    int m_width;
    int m_height;
    int m_fps;
    std::vector<SceneSegment> m_scenes;
};

} // namespace hyper
