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
    if (s == "wipeleft" || s == "wipe_left") return TransitionType::WipeLeft;
    if (s == "wiperight" || s == "wipe_right") return TransitionType::WipeRight;
    if (s == "slideleft" || s == "slide_left") return TransitionType::SlideLeft;
    if (s == "slideright" || s == "slide_right") return TransitionType::SlideRight;
    if (s == "circlecrop" || s == "circle_crop") return TransitionType::CircleCrop;
    if (s == "dissolve") return TransitionType::Dissolve;
    if (s == "zoom" || s == "zoomin" || s == "zoom_in") return TransitionType::ZoomIn;
    if (s == "none") return TransitionType::None;
    return TransitionType::Crossfade; // Default smooth crossfade
}

std::string SceneBuilder::transitionToString(TransitionType t) {
    switch (t) {
        case TransitionType::Crossfade: return "fade";
        case TransitionType::Fade: return "fade";
        case TransitionType::WipeLeft: return "wipeleft";
        case TransitionType::WipeRight: return "wiperight";
        case TransitionType::SlideLeft: return "slideleft";
        case TransitionType::SlideRight: return "slideright";
        case TransitionType::CircleCrop: return "circlecrop";
        case TransitionType::Dissolve: return "dissolve";
        case TransitionType::ZoomIn: return "zoomin";
        case TransitionType::None: return "none";
    }
    return "fade";
}

CameraMotion SceneBuilder::parseMotion(const std::string& str) {
    std::string s = str;
    std::transform(s.begin(), s.end(), s.begin(), ::tolower);
    if (s == "zoomin" || s == "zoom_in" || s == "zoom-in") return CameraMotion::ZoomIn;
    if (s == "zoomout" || s == "zoom_out" || s == "zoom-out") return CameraMotion::ZoomOut;
    if (s == "panleft" || s == "pan_left" || s == "pan-left") return CameraMotion::PanLeft;
    if (s == "panright" || s == "pan_right" || s == "pan-right") return CameraMotion::PanRight;
    if (s == "panup" || s == "pan_up" || s == "pan-up") return CameraMotion::PanUp;
    if (s == "pandown" || s == "pan_down" || s == "pan-down") return CameraMotion::PanDown;
    if (s == "none") return CameraMotion::None;
    return CameraMotion::None;
}

std::string SceneBuilder::motionToString(CameraMotion m) {
    switch (m) {
        case CameraMotion::ZoomIn: return "zoomin";
        case CameraMotion::ZoomOut: return "zoomout";
        case CameraMotion::PanLeft: return "panleft";
        case CameraMotion::PanRight: return "panright";
        case CameraMotion::PanUp: return "panup";
        case CameraMotion::PanDown: return "pandown";
        case CameraMotion::None: return "none";
    }
    return "none";
}

} // namespace hyper
