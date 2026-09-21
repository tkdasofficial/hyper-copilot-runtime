#pragma once

#include <string>
#include <vector>
#include <memory>
#include <cstdint>

namespace HyperEditor {
namespace Core {

// Easing types for keyframing
enum class EasingType {
    Linear = 0,
    EaseIn,
    EaseOut,
    EaseInOut,
    Bezier
};

struct Keyframe {
    double time = 0.0; // in seconds
    double posX = 0.0;
    double posY = 0.0;
    double scaleX = 1.0;
    double scaleY = 1.0;
    double rotation = 0.0; // degrees
    double opacity = 1.0;  // 0.0 to 1.0
    EasingType easing = EasingType::Linear;
    // Cubic Bezier control points (x1, y1, x2, y2)
    double cp1X = 0.25;
    double cp1Y = 0.1;
    double cp2X = 0.25;
    double cp2Y = 1.0;
};

// Mask types
enum class MaskType {
    None = 0,
    Rectangular,
    Elliptical,
    Linear
};

struct MaskConfig {
    MaskType type = MaskType::None;
    double x = 0.0; // Normalized 0..1 or absolute pixels
    double y = 0.0;
    double width = 1.0;
    double height = 1.0;
    double feather = 0.0; // softness 0..1
    bool invert = false;
    double angle = 0.0;   // for linear gradient mask
};

// Overlay blend modes
enum class BlendMode {
    Normal = 0,
    Multiply,
    Screen,
    Overlay,
    Additive
};

struct OverlayConfig {
    BlendMode mode = BlendMode::Normal;
    double opacity = 1.0;
    int posX = 0;
    int posY = 0;
    int width = 0;
    int height = 0;
};

// Dynamic captions
struct CaptionWord {
    std::string text;
    double start = 0.0;
    double end = 0.0;
    uint32_t activeColor = 0xFFFFDD00; // RGBA gold/yellow highlight
};

struct CaptionItem {
    std::string text;
    double startTime = 0.0;
    double endTime = 0.0;
    int fontSize = 48;
    std::string fontPath = "";
    uint32_t textColor = 0xFFFFFFFF; // White
    uint32_t glowColor = 0x00FFFF88; // Neon cyan glow
    int glowRadius = 8;
    bool popAnimation = true;
    double posX = 0.5; // Normalized relative to canvas center
    double posY = 0.85; // Lower third
    std::vector<CaptionWord> words;
};

// Transitions
enum class TransitionType {
    None = 0,
    Crossfade,
    ZoomIn,
    ZoomOut,
    WipeLeft,
    WipeRight,
    WipeUp,
    WipeDown,
    GaussianBlur
};

struct TransitionConfig {
    TransitionType type = TransitionType::None;
    double duration = 1.0; // seconds
};

// Color Grading & LUT
struct ColorGradingConfig {
    double brightness = 0.0; // -1.0 to 1.0
    double contrast = 1.0;   // 0.0 to 3.0
    double saturation = 1.0; // 0.0 to 3.0
    double exposure = 0.0;   // -2.0 to 2.0 stops
    std::string lutPath = "";
};

// Motion Zoom (Ken Burns)
struct MotionZoomConfig {
    bool enabled = false;
    double startPanX = 0.5;
    double startPanY = 0.5;
    double startZoom = 1.0;
    double endPanX = 0.5;
    double endPanY = 0.5;
    double endZoom = 1.25;
};

// Speed Ramping
struct SpeedPoint {
    double time = 0.0;
    double speedMultiplier = 1.0; // e.g. 0.5 = slow-mo, 2.0 = fast
};

struct SpeedRampingConfig {
    bool enabled = false;
    std::vector<SpeedPoint> points;
};

// Chroma Key
struct ChromaKeyConfig {
    bool enabled = false;
    uint8_t keyR = 0;
    uint8_t keyG = 255;
    uint8_t keyB = 0;
    double tolerance = 0.25;
    double colorDistance = 0.3;
    double edgeSoftness = 0.05;
};

// Frame Scaler
enum class ScaleMode {
    Letterbox = 0,
    SmartCrop,
    Stretch
};

struct FrameScalerConfig {
    int targetWidth = 1920;
    int targetHeight = 1080;
    ScaleMode mode = ScaleMode::Letterbox;
};

// Audio Effects
struct AudioEffectsConfig {
    double highPassHz = 0.0;
    double lowPassHz = 20000.0;
    double noiseGateThresholdDb = -60.0;
    double eqLowDb = 0.0;
    double eqMidDb = 0.0;
    double eqHighDb = 0.0;
    double pitchShiftSemitones = 0.0;
    double tempoFactor = 1.0;
};

// Clip structure
struct Clip {
    std::string id;
    std::string filePath;
    int trackIndex = 0;
    double startTime = 0.0;  // in timeline
    double duration = 5.0;   // timeline duration
    double sourceOffset = 0.0; // in source media
    double volume = 1.0;

    std::vector<Keyframe> keyframes;
    MaskConfig mask;
    OverlayConfig overlay;
    TransitionConfig transitionIn;
    TransitionConfig transitionOut;
    ColorGradingConfig colorGrading;
    MotionZoomConfig motionZoom;
    SpeedRampingConfig speedRamping;
    ChromaKeyConfig chromaKey;
    FrameScalerConfig frameScaler;
    AudioEffectsConfig audioEffects;
};

// Audio Track with Auto-Ducking
struct AudioTrack {
    std::string id;
    std::string filePath;
    double startTime = 0.0;
    double duration = 0.0; // 0 = full file
    double volume = 1.0;
    bool isVoiceover = false;
    bool duckOnVoiceover = false;
    double duckingAttenuation = 0.2; // reduce to 20%
    double duckingAttackSec = 0.2;
    double duckingReleaseSec = 0.4;
    AudioEffectsConfig effects;
};

// Master Timeline
struct Timeline {
    int width = 1920;
    int height = 1080;
    double fps = 30.0;
    double duration = 10.0; // Total duration in seconds
    int sampleRate = 48000;
    int channels = 2;
    std::string outputPath = "output_master.mp4";

    uint32_t backgroundColor = 0x000000FF; // RGBA Black

    std::vector<Clip> videoClips;
    std::vector<AudioTrack> audioTracks;
    std::vector<CaptionItem> captions;
};

} // namespace Core
} // namespace HyperEditor
