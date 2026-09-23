#pragma once

#include <string>
#include <vector>

namespace hyper {

enum class CameraMotion {
    None,
    ZoomIn,
    ZoomOut,
    PanLeft,
    PanRight,
    PanUp,
    PanDown
};

enum class TransitionType {
    None,
    Fade,
    Crossfade,
    WipeLeft,
    WipeRight,
    SlideLeft,
    SlideRight,
    CircleCrop,
    Dissolve,
    ZoomIn
};

struct TimelineClip {
    std::string id;
    std::string file_path;
    double start_time = 0.0;       // Timeline start in seconds
    double duration = 4.0;         // Duration in seconds in output
    double source_trim_start = 0.0;// Source file offset in seconds
    double speed_factor = 1.0;     // Clip playback speed (0.8x, 1.0x, 1.25x - 1.5x)
    CameraMotion motion = CameraMotion::None; // Ken Burns motion
    TransitionType transition = TransitionType::Crossfade;
    double transition_duration = 0.4; // Typically 0.3 - 0.5 seconds
    bool is_image = false;
};

struct SceneSegment {
    int index = 0;
    double start_time = 0.0;
    double end_time = 0.0;
    double duration = 4.0;
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

    static CameraMotion parseMotion(const std::string& str);
    static std::string motionToString(CameraMotion m);

private:
    int m_width;
    int m_height;
    int m_fps;
    std::vector<SceneSegment> m_scenes;
};

} // namespace hyper
