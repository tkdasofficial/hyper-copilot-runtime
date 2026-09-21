#pragma once

#include "utils/memory.hpp"
#include "tools/audio_mixer.hpp"
#include <string>
#include <vector>
#include <memory>
#include <mutex>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavfilter/avfilter.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
#include <libavutil/opt.h>
#include <libavutil/mathematics.h>
}

namespace HyperEditor {
namespace Core {

class VideoDecoder {
public:
    VideoDecoder() = default;
    ~VideoDecoder();

    bool open(const std::string& filePath, int targetWidth, int targetHeight);
    void close();

    // Decodes next frame or seeks to timestamp (in seconds) and retrieves RGBA frame
    bool getFrameAt(double timestampSec, AVFrame* outRgbaFrame);

    double getDuration() const { return durationSec_; }
    int getWidth() const { return width_; }
    int getHeight() const { return height_; }
    double getFps() const { return fps_; }

private:
    std::string filePath_;
    AVFormatContext* fmtCtx_ = nullptr;
    AVCodecContext* codecCtx_ = nullptr;
    SwsContext* swsCtx_ = nullptr;
    int videoStreamIdx_ = -1;
    double durationSec_ = 0.0;
    int width_ = 0;
    int height_ = 0;
    double fps_ = 30.0;
    int targetW_ = 0;
    int targetH_ = 0;

    Utils::AVFramePtr rawFrame_;
    Utils::AVPacketPtr packet_;
    std::mutex mutex_;
};

class AudioDecoder {
public:
    AudioDecoder() = default;
    ~AudioDecoder();

    bool open(const std::string& filePath, int targetSampleRate = 48000, int targetChannels = 2);
    void close();

    // Decodes all audio into memory buffer
    bool decodeAll(Tools::AudioBuffer& outBuffer);

private:
    std::string filePath_;
    AVFormatContext* fmtCtx_ = nullptr;
    AVCodecContext* codecCtx_ = nullptr;
    SwrContext* swrCtx_ = nullptr;
    int audioStreamIdx_ = -1;
    int targetSampleRate_ = 48000;
    int targetChannels_ = 2;
    double durationSec_ = 0.0;
};

class MediaEncoder {
public:
    MediaEncoder() = default;
    ~MediaEncoder();

    bool initialize(const std::string& outputPath, int width, int height, double fps, 
                    int sampleRate = 48000, int channels = 2, const std::string& videoCodec = "libx264");
    
    // Encodes one video RGBA canvas frame
    bool encodeVideoFrame(AVFrame* rgbaFrame, int64_t frameIndex);

    // Encodes interleaved audio buffer
    bool encodeAudioBuffer(const Tools::AudioBuffer& audioBuffer);

    // Flushes encoders and finalizes MP4 container
    bool finalize();

private:
    std::string outputPath_;
    int width_ = 0;
    int height_ = 0;
    double fps_ = 30.0;
    int sampleRate_ = 48000;
    int channels_ = 2;

    AVFormatContext* outFmtCtx_ = nullptr;
    AVStream* videoStream_ = nullptr;
    AVStream* audioStream_ = nullptr;
    AVCodecContext* videoCodecCtx_ = nullptr;
    AVCodecContext* audioCodecCtx_ = nullptr;
    SwsContext* swsRgbaToYuv_ = nullptr;
    SwrContext* swrAudioCtx_ = nullptr;

    Utils::AVFramePtr yuvFrame_;
    Utils::AVFramePtr audioFrame_;
    Utils::AVPacketPtr packet_;

    int64_t nextAudioPts_ = 0;
    bool finalized_ = false;
    std::mutex mutex_;

    bool flushVideo();
    bool flushAudio();
};

// Synthetic generator for testing and headless fallback
class SyntheticMediaGenerator {
public:
    static void generateVideoFrame(AVFrame* rgbaFrame, double timestamp, int patternType = 0);
    static void generateAudioTrack(Tools::AudioBuffer& buffer, double durationSec, double freqHz = 440.0);
};

} // namespace Core
} // namespace HyperEditor
