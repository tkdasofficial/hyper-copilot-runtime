#include "parsers/json_parser.hpp"
#include "utils/logger.hpp"
#include <fstream>
#include <sstream>

namespace HyperEditor {
namespace Parsers {

bool JsonParser::parseFile(const std::string& filePath, Core::Timeline& outTimeline) {
    std::ifstream file(filePath);
    if (!file.is_open()) {
        LOG_ERROR("JsonParser", "Cannot open timeline JSON file: ", filePath);
        return false;
    }
    std::stringstream buffer;
    buffer << file.rdbuf();
    return parseString(buffer.str(), outTimeline);
}

bool JsonParser::parseString(const std::string& jsonContent, Core::Timeline& outTimeline) {
    try {
        auto j = nlohmann::json::parse(jsonContent);

        parseTimelineSettings(j, outTimeline);
        if (j.contains("tracks") || j.contains("clips") || j.contains("scenes")) {
            parseClips(j, outTimeline);
        }
        if (j.contains("audio_tracks") || j.contains("audio")) {
            parseAudioTracks(j, outTimeline);
        }
        if (j.contains("captions")) {
            parseCaptions(j, outTimeline);
        }

        LOG_INFO("JsonParser", "Successfully loaded timeline: ", outTimeline.width, "x", outTimeline.height, 
                 " @ ", outTimeline.fps, "fps, clips: ", outTimeline.videoClips.size(),
                 ", audio tracks: ", outTimeline.audioTracks.size(),
                 ", captions: ", outTimeline.captions.size());
        return true;
    } catch (const std::exception& e) {
        LOG_ERROR("JsonParser", "JSON parsing error: ", e.what());
        return false;
    }
}

void JsonParser::parseTimelineSettings(const nlohmann::json& j, Core::Timeline& outTimeline) {
    if (j.contains("output")) {
        const auto& out = j["output"];
        outTimeline.width = out.value("width", 1920);
        outTimeline.height = out.value("height", 1080);
        outTimeline.fps = out.value("fps", 30.0);
        outTimeline.duration = out.value("duration", 10.0);
        outTimeline.outputPath = out.value("path", "output_master.mp4");
        outTimeline.sampleRate = out.value("sample_rate", 48000);
        outTimeline.channels = out.value("channels", 2);
    } else {
        if (j.contains("resolution")) {
            outTimeline.width = j["resolution"].value("width", 1920);
            outTimeline.height = j["resolution"].value("height", 1080);
        } else {
            outTimeline.width = j.value("width", 1920);
            outTimeline.height = j.value("height", 1080);
        }
        outTimeline.fps = j.value("fps", 30.0);
        outTimeline.duration = j.value("duration", 10.0);
        outTimeline.outputPath = j.value("outputPath", j.value("path", "output_master.mp4"));
        outTimeline.sampleRate = j.value("sample_rate", 48000);
        outTimeline.channels = j.value("channels", 2);
    }
}

Core::Keyframe JsonParser::parseKeyframe(const nlohmann::json& j) {
    Core::Keyframe kf;
    kf.time = j.value("time", 0.0);
    kf.posX = j.value("x", 0.0);
    kf.posY = j.value("y", 0.0);
    kf.scaleX = j.value("scale_x", j.value("scale", 1.0));
    kf.scaleY = j.value("scale_y", j.value("scale", 1.0));
    kf.rotation = j.value("rotation", 0.0);
    kf.opacity = j.value("opacity", 1.0);

    std::string ease = j.value("easing", "linear");
    if (ease == "ease_in") kf.easing = Core::EasingType::EaseIn;
    else if (ease == "ease_out") kf.easing = Core::EasingType::EaseOut;
    else if (ease == "ease_in_out") kf.easing = Core::EasingType::EaseInOut;
    else if (ease == "bezier") {
        kf.easing = Core::EasingType::Bezier;
        if (j.contains("bezier")) {
            kf.cp1X = j["bezier"].value("x1", 0.25);
            kf.cp1Y = j["bezier"].value("y1", 0.1);
            kf.cp2X = j["bezier"].value("x2", 0.25);
            kf.cp2Y = j["bezier"].value("y2", 1.0);
        }
    }
    return kf;
}

Core::MaskConfig JsonParser::parseMask(const nlohmann::json& j) {
    Core::MaskConfig m;
    std::string type = j.value("type", "none");
    if (type == "rectangular") m.type = Core::MaskType::Rectangular;
    else if (type == "elliptical") m.type = Core::MaskType::Elliptical;
    else if (type == "linear") m.type = Core::MaskType::Linear;
    else m.type = Core::MaskType::None;

    m.x = j.value("x", 0.0);
    m.y = j.value("y", 0.0);
    m.width = j.value("width", 1.0);
    m.height = j.value("height", 1.0);
    m.feather = j.value("feather", 0.0);
    m.invert = j.value("invert", false);
    m.angle = j.value("angle", 0.0);
    return m;
}

Core::OverlayConfig JsonParser::parseOverlay(const nlohmann::json& j) {
    Core::OverlayConfig ov;
    std::string mode = j.value("blend_mode", "normal");
    if (mode == "multiply") ov.mode = Core::BlendMode::Multiply;
    else if (mode == "screen") ov.mode = Core::BlendMode::Screen;
    else if (mode == "overlay") ov.mode = Core::BlendMode::Overlay;
    else if (mode == "additive") ov.mode = Core::BlendMode::Additive;
    else ov.mode = Core::BlendMode::Normal;

    ov.opacity = j.value("opacity", 1.0);
    ov.posX = j.value("x", 0);
    ov.posY = j.value("y", 0);
    ov.width = j.value("width", 0);
    ov.height = j.value("height", 0);
    return ov;
}

Core::TransitionConfig JsonParser::parseTransition(const nlohmann::json& j) {
    Core::TransitionConfig t;
    std::string type = j.value("type", "none");
    if (type == "crossfade") t.type = Core::TransitionType::Crossfade;
    else if (type == "zoom_in") t.type = Core::TransitionType::ZoomIn;
    else if (type == "zoom_out") t.type = Core::TransitionType::ZoomOut;
    else if (type == "wipe_left") t.type = Core::TransitionType::WipeLeft;
    else if (type == "wipe_right") t.type = Core::TransitionType::WipeRight;
    else if (type == "wipe_up") t.type = Core::TransitionType::WipeUp;
    else if (type == "wipe_down") t.type = Core::TransitionType::WipeDown;
    else if (type == "gaussian_blur") t.type = Core::TransitionType::GaussianBlur;
    else t.type = Core::TransitionType::None;

    t.duration = j.value("duration", 1.0);
    return t;
}

Core::ColorGradingConfig JsonParser::parseColorGrading(const nlohmann::json& j) {
    Core::ColorGradingConfig cg;
    cg.brightness = j.value("brightness", 0.0);
    cg.contrast = j.value("contrast", 1.0);
    cg.saturation = j.value("saturation", 1.0);
    cg.exposure = j.value("exposure", 0.0);
    cg.lutPath = j.value("lut_path", "");
    return cg;
}

Core::MotionZoomConfig JsonParser::parseMotionZoom(const nlohmann::json& j) {
    Core::MotionZoomConfig mz;
    mz.enabled = j.value("enabled", true);
    mz.startPanX = j.value("start_pan_x", 0.5);
    mz.startPanY = j.value("start_pan_y", 0.5);
    mz.startZoom = j.value("start_zoom", 1.0);
    mz.endPanX = j.value("end_pan_x", 0.5);
    mz.endPanY = j.value("end_pan_y", 0.5);
    mz.endZoom = j.value("end_zoom", 1.25);
    return mz;
}

Core::SpeedRampingConfig JsonParser::parseSpeedRamping(const nlohmann::json& j) {
    Core::SpeedRampingConfig sr;
    sr.enabled = j.value("enabled", true);
    if (j.contains("points") && j["points"].is_array()) {
        for (const auto& pj : j["points"]) {
            Core::SpeedPoint pt;
            pt.time = pj.value("time", 0.0);
            pt.speedMultiplier = pj.value("speed", 1.0);
            sr.points.push_back(pt);
        }
    }
    return sr;
}

Core::ChromaKeyConfig JsonParser::parseChromaKey(const nlohmann::json& j) {
    Core::ChromaKeyConfig ck;
    ck.enabled = j.value("enabled", true);
    ck.keyR = j.value("r", 0);
    ck.keyG = j.value("g", 255);
    ck.keyB = j.value("b", 0);
    ck.tolerance = j.value("tolerance", 0.25);
    ck.colorDistance = j.value("color_distance", 0.3);
    ck.edgeSoftness = j.value("edge_softness", 0.05);
    return ck;
}

Core::FrameScalerConfig JsonParser::parseFrameScaler(const nlohmann::json& j) {
    Core::FrameScalerConfig fs;
    fs.targetWidth = j.value("width", 1920);
    fs.targetHeight = j.value("height", 1080);
    std::string mode = j.value("mode", "letterbox");
    if (mode == "smart_crop") fs.mode = Core::ScaleMode::SmartCrop;
    else if (mode == "stretch") fs.mode = Core::ScaleMode::Stretch;
    else fs.mode = Core::ScaleMode::Letterbox;
    return fs;
}

Core::AudioEffectsConfig JsonParser::parseAudioEffects(const nlohmann::json& j) {
    Core::AudioEffectsConfig ae;
    ae.highPassHz = j.value("high_pass_hz", 0.0);
    ae.lowPassHz = j.value("low_pass_hz", 20000.0);
    ae.noiseGateThresholdDb = j.value("noise_gate_db", -80.0);
    ae.eqLowDb = j.value("eq_low_db", 0.0);
    ae.eqMidDb = j.value("eq_mid_db", 0.0);
    ae.eqHighDb = j.value("eq_high_db", 0.0);
    ae.pitchShiftSemitones = j.value("pitch_shift", 0.0);
    ae.tempoFactor = j.value("tempo", 1.0);
    return ae;
}

void JsonParser::parseClips(const nlohmann::json& j, Core::Timeline& outTimeline) {
    nlohmann::json clipsArray = nlohmann::json::array();
    if (j.contains("scenes") && j["scenes"].is_array()) {
        clipsArray = j["scenes"];
    } else if (j.contains("clips") && j["clips"].is_array()) {
        clipsArray = j["clips"];
    } else if (j.contains("tracks") && j["tracks"].is_array()) {
        for (const auto& t : j["tracks"]) {
            if (t.is_object() && t.value("type", "video") == "video" && t.contains("clips") && t["clips"].is_array()) {
                for (const auto& c : t["clips"]) {
                    clipsArray.push_back(c);
                }
            }
        }
    }
    if (!clipsArray.is_array()) return;

    for (const auto& cj : clipsArray) {
        Core::Clip clip;
        clip.id = cj.value("id", "clip_" + std::to_string(outTimeline.videoClips.size()));
        clip.filePath = cj.value("file", cj.value("path", ""));
        clip.trackIndex = cj.value("track", 0);
        clip.startTime = cj.value("start_time", cj.value("start", cj.value("startTime", 0.0)));
        clip.duration = cj.value("duration", 5.0);
        clip.sourceOffset = cj.value("source_offset", 0.0);
        clip.volume = cj.value("volume", 1.0);

        if (cj.contains("keyframes") && cj["keyframes"].is_array()) {
            for (const auto& kj : cj["keyframes"]) {
                clip.keyframes.push_back(parseKeyframe(kj));
            }
        }
        if (cj.contains("mask")) clip.mask = parseMask(cj["mask"]);
        if (cj.contains("overlay")) clip.overlay = parseOverlay(cj["overlay"]);
        if (cj.contains("transition_in")) clip.transitionIn = parseTransition(cj["transition_in"]);
        if (cj.contains("transition_out")) clip.transitionOut = parseTransition(cj["transition_out"]);
        if (cj.contains("color_grading")) clip.colorGrading = parseColorGrading(cj["color_grading"]);
        if (cj.contains("motion_zoom")) clip.motionZoom = parseMotionZoom(cj["motion_zoom"]);
        if (cj.contains("speed_ramping")) clip.speedRamping = parseSpeedRamping(cj["speed_ramping"]);
        if (cj.contains("chroma_key")) clip.chromaKey = parseChromaKey(cj["chroma_key"]);
        if (cj.contains("frame_scaler")) clip.frameScaler = parseFrameScaler(cj["frame_scaler"]);
        if (cj.contains("audio_effects")) clip.audioEffects = parseAudioEffects(cj["audio_effects"]);

        outTimeline.videoClips.push_back(clip);
    }
}

void JsonParser::parseAudioTracks(const nlohmann::json& j, Core::Timeline& outTimeline) {
    nlohmann::json audioArray = nlohmann::json::array();
    if (j.contains("audio_tracks") && j["audio_tracks"].is_array()) {
        audioArray = j["audio_tracks"];
    } else if (j.contains("audio") && j["audio"].is_array()) {
        audioArray = j["audio"];
    } else if (j.contains("tracks") && j["tracks"].is_array()) {
        for (const auto& t : j["tracks"]) {
            if (t.is_object() && t.value("type", "") == "audio" && t.contains("clips") && t["clips"].is_array()) {
                for (const auto& a : t["clips"]) {
                    audioArray.push_back(a);
                }
            }
        }
    }
    if (!audioArray.is_array()) return;

    for (const auto& aj : audioArray) {
        Core::AudioTrack track;
        track.id = aj.value("id", "audio_" + std::to_string(outTimeline.audioTracks.size()));
        track.filePath = aj.value("file", aj.value("path", ""));
        track.startTime = aj.value("start_time", aj.value("start", aj.value("startTime", 0.0)));
        track.duration = aj.value("duration", 0.0);
        track.volume = aj.value("volume", 1.0);
        track.isVoiceover = aj.value("is_voiceover", true);
        track.duckOnVoiceover = aj.value("duck_on_voiceover", false);
        track.duckingAttenuation = aj.value("ducking_attenuation", 0.2);
        track.duckingAttackSec = aj.value("ducking_attack", 0.2);
        track.duckingReleaseSec = aj.value("ducking_release", 0.4);

        if (aj.contains("effects")) {
            track.effects = parseAudioEffects(aj["effects"]);
        }

        outTimeline.audioTracks.push_back(track);
    }
}

void JsonParser::parseCaptions(const nlohmann::json& j, Core::Timeline& outTimeline) {
    if (!j.contains("captions") || !j["captions"].is_array()) return;

    for (const auto& cj : j["captions"]) {
        Core::CaptionItem cap;
        cap.text = cj.value("text", "");
        cap.startTime = cj.value("start_time", cj.value("start", 0.0));
        cap.endTime = cj.value("end_time", cj.value("end", cap.startTime + 3.0));
        cap.fontSize = cj.value("font_size", 48);
        cap.fontPath = cj.value("font_path", "");
        cap.textColor = cj.value("text_color", 0xFFFFFFFF);
        cap.glowColor = cj.value("glow_color", 0x00FFFF88);
        cap.glowRadius = cj.value("glow_radius", 8);
        cap.popAnimation = cj.value("pop_animation", true);
        cap.posX = cj.value("pos_x", 0.5);
        cap.posY = cj.value("pos_y", 0.85);

        if (cj.contains("words") && cj["words"].is_array()) {
            for (const auto& wj : cj["words"]) {
                Core::CaptionWord w;
                w.text = wj.value("text", "");
                w.start = wj.value("start", 0.0);
                w.end = wj.value("end", 0.0);
                w.activeColor = wj.value("active_color", 0xFFFFDD00);
                cap.words.push_back(w);
            }
        }

        outTimeline.captions.push_back(cap);
    }
}

} // namespace Parsers
} // namespace HyperEditor
