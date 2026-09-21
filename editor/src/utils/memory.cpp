#include "utils/memory.hpp"
#include <stdexcept>
#include <cstdlib>

namespace HyperEditor {
namespace Utils {

AVFramePtr makeAVFrame() {
    AVFrame* f = av_frame_alloc();
    if (!f) {
        throw std::runtime_error("Failed to allocate AVFrame");
    }
    return AVFramePtr(f);
}

AVFramePtr makeVideoFrame(int width, int height, AVPixelFormat pixFmt) {
    AVFramePtr frame = makeAVFrame();
    frame->format = pixFmt;
    frame->width = width;
    frame->height = height;

    int ret = av_frame_get_buffer(frame.get(), 32);
    if (ret < 0) {
        throw std::runtime_error("Failed to allocate AVFrame buffer");
    }
    return frame;
}

AVPacketPtr makeAVPacket() {
    AVPacket* pkt = av_packet_alloc();
    if (!pkt) {
        throw std::runtime_error("Failed to allocate AVPacket");
    }
    return AVPacketPtr(pkt);
}

AlignedBuffer::AlignedBuffer(size_t size, size_t alignment) : size_(size) {
    (void)alignment;
    if (size_ > 0) {
        data_ = static_cast<uint8_t*>(av_mallocz(size_));
        if (!data_) {
            throw std::bad_alloc();
        }
    }
}

AlignedBuffer::~AlignedBuffer() {
    if (data_) {
        av_freep(&data_);
    }
}

AlignedBuffer::AlignedBuffer(AlignedBuffer&& other) noexcept 
    : data_(other.data_), size_(other.size_) {
    other.data_ = nullptr;
    other.size_ = 0;
}

AlignedBuffer& AlignedBuffer::operator=(AlignedBuffer&& other) noexcept {
    if (this != &other) {
        if (data_) av_freep(&data_);
        data_ = other.data_;
        size_ = other.size_;
        other.data_ = nullptr;
        other.size_ = 0;
    }
    return *this;
}

FramePool::FramePool(int width, int height, AVPixelFormat pixFmt, size_t initialCapacity)
    : width_(width), height_(height), pixFmt_(pixFmt) {
    for (size_t i = 0; i < initialCapacity; ++i) {
        pool_.push(makeVideoFrame(width_, height_, pixFmt_));
    }
}

FramePool::~FramePool() {
    std::lock_guard<std::mutex> lock(mutex_);
    while (!pool_.empty()) {
        pool_.pop();
    }
}

AVFramePtr FramePool::acquire() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!pool_.empty()) {
        AVFramePtr frame = std::move(pool_.front());
        pool_.pop();
        return frame;
    }
    return makeVideoFrame(width_, height_, pixFmt_);
}

void FramePool::release(AVFramePtr frame) {
    if (!frame) return;
    std::lock_guard<std::mutex> lock(mutex_);
    if (frame->width == width_ && frame->height == height_ && frame->format == pixFmt_) {
        pool_.push(std::move(frame));
    }
}

size_t FramePool::availableCount() {
    std::lock_guard<std::mutex> lock(mutex_);
    return pool_.size();
}

} // namespace Utils
} // namespace HyperEditor
