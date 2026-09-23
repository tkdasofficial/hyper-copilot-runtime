#include "scene_builder.hpp"
#include <algorithm>

namespace hyper {

SceneBuilder::SceneBuilder(int targetWidth, int targetHeight, int fps)
    : m_width(targetWidth), m_height(targetHeight), m_fps(fps) {
}

void SceneBuilder::setResolution(int width, int height) {
    m_width = width;
    m_height = height;
}

void SceneBuilder::setFps(int fps) {
    m_fps = fps;
}

void SceneBuilder::addScene(const SceneSegment& scene) {
    m_scenes.push_back(scene);
}

void SceneBuilder::clear() {
    m_scenes.clear();
}

std::vector<TimelineClip> SceneBuilder::getFlattenedClips() const {
    std::vector<TimelineClip> allClips;
    for (const auto& scene : m_scenes) {
        for (const auto& clip : scene.clips) {
            allClips.push_back(clip);
        }
    }
    return allClips;
}

double SceneBuilder::getTotalDuration() const {
    double total = 0.0;
    for (const auto& scene : m_scenes) {
        if (scene.end_time > total) {
            total = scene.end_time;
        }
    }
    return total;
}

TransitionType SceneBuilder::parseTransition(const std::string& str) {
    std::string s = str;
    std::transform(s.begin(), s.end(), s.begin(), ::tolower);
    if (s == "fade" || s == "crossfade") return TransitionType::Crossfade;
    if (s == "wipeleft") return TransitionType::WipeLeft;
    if (s == "wiperight") return TransitionType::WipeRight;
    if (s == "circlecrop") return TransitionType::CircleCrop;
    if (s == "zoomin") return TransitionType::ZoomIn;
    return TransitionType::Crossfade; // Default smooth crossfade
}

std::string SceneBuilder::transitionToString(TransitionType t) {
    switch (t) {
        case TransitionType::Crossfade: return "fade";
        case TransitionType::Fade: return "fade";
        case TransitionType::WipeLeft: return "wipeleft";
        case TransitionType::WipeRight: return "wiperight";
        case TransitionType::CircleCrop: return "circlecrop";
        case TransitionType::ZoomIn: return "zoomin";
        case TransitionType::None: return "none";
    }
    return "fade";
}

} // namespace hyper
