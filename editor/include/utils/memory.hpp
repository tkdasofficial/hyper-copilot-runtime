#pragma once

#include <memory>
#include <vector>
#include <mutex>
#include <queue>
#include <cstdint>

extern "C" {
#include <libavutil/frame.h>
#include <libavcodec/packet.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
#include <libswresample/swresample.h>
#include <libavutil/imgutils.h>
#include <libavutil/mem.h>
}

namespace HyperEditor {
namespace Utils {

// Custom deleters for FFmpeg C-API primitives
struct AVFrameDeleter {
    void operator()(AVFrame* frame) const noexcept {
        if (frame) {
            av_frame_free(&frame);
        }
    }
};

struct AVPacketDeleter {
    void operator()(AVPacket* pkt) const noexcept {
        if (pkt) {
            av_packet_free(&pkt);
        }
    }
};

struct AVFormatContextInputDeleter {
    void operator()(AVFormatContext* ctx) const noexcept {
        if (ctx) {
            avformat_close_input(&ctx);
        }
    }
};

struct AVFormatContextOutputDeleter {
    void operator()(AVFormatContext* ctx) const noexcept {
        if (ctx) {
            if (!(ctx->oformat->flags & AVFMT_NOFILE) && ctx->pb) {
                avio_closep(&ctx->pb);
            }
            avformat_free_context(ctx);
        }
    }
};

struct AVCodecContextDeleter {
    void operator()(AVCodecContext* ctx) const noexcept {
        if (ctx) {
            avcodec_free_context(&ctx);
        }
    }
};

struct SwsContextDeleter {
    void operator()(SwsContext* ctx) const noexcept {
        if (ctx) {
            sws_freeContext(ctx);
        }
    }
};

struct SwrContextDeleter {
    void operator()(SwrContext* ctx) const noexcept {
        if (ctx) {
            swr_free(&ctx);
        }
    }
};

// Aliases for RAII managed FFmpeg resources
using AVFramePtr = std::unique_ptr<AVFrame, AVFrameDeleter>;
using AVPacketPtr = std::unique_ptr<AVPacket, AVPacketDeleter>;
using AVFormatInputPtr = std::unique_ptr<AVFormatContext, AVFormatContextInputDeleter>;
using AVFormatOutputPtr = std::unique_ptr<AVFormatContext, AVFormatContextOutputDeleter>;
using AVCodecContextPtr = std::unique_ptr<AVCodecContext, AVCodecContextDeleter>;
using SwsContextPtr = std::unique_ptr<SwsContext, SwsContextDeleter>;
using SwrContextPtr = std::unique_ptr<SwrContext, SwrContextDeleter>;

// Factory functions
AVFramePtr makeAVFrame();
AVFramePtr makeVideoFrame(int width, int height, AVPixelFormat pixFmt);
AVPacketPtr makeAVPacket();

// Aligned Memory Buffer for audio/video DSP pipelines
class AlignedBuffer {
public:
    explicit AlignedBuffer(size_t size, size_t alignment = 32);
    ~AlignedBuffer();

    AlignedBuffer(const AlignedBuffer&) = delete;
    AlignedBuffer& operator=(const AlignedBuffer&) = delete;

    AlignedBuffer(AlignedBuffer&& other) noexcept;
    AlignedBuffer& operator=(AlignedBuffer&& other) noexcept;

    uint8_t* data() noexcept { return data_; }
    const uint8_t* data() const noexcept { return data_; }
    size_t size() const noexcept { return size_; }

private:
    uint8_t* data_ = nullptr;
    size_t size_ = 0;
};

// Thread-safe Frame Memory Pool for high-throughput headless video editing
class FramePool {
public:
    explicit FramePool(int width, int height, AVPixelFormat pixFmt, size_t initialCapacity = 16);
    ~FramePool();

    AVFramePtr acquire();
    void release(AVFramePtr frame);
    size_t availableCount();

private:
    int width_;
    int height_;
    AVPixelFormat pixFmt_;
    std::mutex mutex_;
    std::queue<AVFramePtr> pool_;
};

} // namespace Utils
} // namespace HyperEditor
