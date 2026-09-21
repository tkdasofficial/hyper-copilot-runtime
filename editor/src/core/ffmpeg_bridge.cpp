#include "core/ffmpeg_bridge.hpp"
#include "utils/logger.hpp"
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <cstring>

extern "C" {
#include <libavutil/channel_layout.h>
}

namespace HyperEditor {
namespace Core {

// ---------------------------------------------------------------------------
// VideoDecoder
// ---------------------------------------------------------------------------

VideoDecoder::~VideoDecoder() {
    close();
}

void VideoDecoder::close() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (swsCtx_) {
        sws_freeContext(swsCtx_);
        swsCtx_ = nullptr;
    }
    if (codecCtx_) {
        avcodec_free_context(&codecCtx_);
        codecCtx_ = nullptr;
    }
    if (fmtCtx_) {
        avformat_close_input(&fmtCtx_);
        fmtCtx_ = nullptr;
    }
    rawFrame_.reset();
    packet_.reset();
}

bool VideoDecoder::open(const std::string& filePath, int targetWidth, int targetHeight) {
    close();
    std::lock_guard<std::mutex> lock(mutex_);
    filePath_ = filePath;
    targetW_ = targetWidth;
    targetH_ = targetHeight;

    if (avformat_open_input(&fmtCtx_, filePath.c_str(), nullptr, nullptr) < 0) {
        LOG_WARN("VideoDecoder", "Could not open video file: ", filePath);
        return false;
    }

    if (avformat_find_stream_info(fmtCtx_, nullptr) < 0) {
        LOG_ERROR("VideoDecoder", "Could not find stream info for: ", filePath);
        close();
        return false;
    }

    const AVCodec* decoder = nullptr;
    videoStreamIdx_ = av_find_best_stream(fmtCtx_, AVMEDIA_TYPE_VIDEO, -1, -1, &decoder, 0);
    if (videoStreamIdx_ < 0) {
        LOG_ERROR("VideoDecoder", "No video stream in: ", filePath);
        close();
        return false;
    }

    AVStream* stream = fmtCtx_->streams[videoStreamIdx_];
    codecCtx_ = avcodec_alloc_context3(decoder);
    if (!codecCtx_) {
        close();
        return false;
    }

    if (avcodec_parameters_to_context(codecCtx_, stream->codecpar) < 0) {
        close();
        return false;
    }

    if (avcodec_open2(codecCtx_, decoder, nullptr) < 0) {
        LOG_ERROR("VideoDecoder", "Failed to open video codec for: ", filePath);
        close();
        return false;
    }

    width_ = codecCtx_->width;
    height_ = codecCtx_->height;
    if (stream->avg_frame_rate.num > 0 && stream->avg_frame_rate.den > 0) {
        fps_ = av_q2d(stream->avg_frame_rate);
    }
    if (stream->duration != AV_NOPTS_VALUE) {
        durationSec_ = stream->duration * av_q2d(stream->time_base);
    } else if (fmtCtx_->duration != AV_NOPTS_VALUE) {
        durationSec_ = static_cast<double>(fmtCtx_->duration) / AV_TIME_BASE;
    }

    swsCtx_ = sws_getContext(width_, height_, codecCtx_->pix_fmt,
                             targetW_, targetH_, AV_PIX_FMT_RGBA,
                             SWS_BILINEAR, nullptr, nullptr, nullptr);

    rawFrame_ = Utils::makeAVFrame();
    packet_ = Utils::makeAVPacket();

    LOG_INFO("VideoDecoder", "Opened video: ", filePath, " (", width_, "x", height_, " @ ", fps_, "fps)");
    return true;
}

bool VideoDecoder::getFrameAt(double timestampSec, AVFrame* outRgbaFrame) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!fmtCtx_ || !codecCtx_ || !swsCtx_ || !outRgbaFrame) return false;

    AVStream* stream = fmtCtx_->streams[videoStreamIdx_];
    int64_t seekTarget = static_cast<int64_t>(timestampSec / av_q2d(stream->time_base));
    av_seek_frame(fmtCtx_, videoStreamIdx_, seekTarget, AVSEEK_FLAG_BACKWARD);
    avcodec_flush_buffers(codecCtx_);

    bool frameFound = false;
    while (av_read_frame(fmtCtx_, packet_.get()) >= 0) {
        if (packet_->stream_index == videoStreamIdx_) {
            if (avcodec_send_packet(codecCtx_, packet_.get()) >= 0) {
                while (avcodec_receive_frame(codecCtx_, rawFrame_.get()) >= 0) {
                    double pts = rawFrame_->pts * av_q2d(stream->time_base);
                    if (pts >= timestampSec - 0.05) {
                        // Convert to RGBA
                        sws_scale(swsCtx_, rawFrame_->data, rawFrame_->linesize, 0, height_,
                                  outRgbaFrame->data, outRgbaFrame->linesize);
                        frameFound = true;
                        av_packet_unref(packet_.get());
                        return true;
                    }
                }
            }
        }
        av_packet_unref(packet_.get());
    }

    return frameFound;
}

// ---------------------------------------------------------------------------
// AudioDecoder
// ---------------------------------------------------------------------------

AudioDecoder::~AudioDecoder() {
    close();
}

void AudioDecoder::close() {
    if (swrCtx_) {
        swr_free(&swrCtx_);
        swrCtx_ = nullptr;
    }
    if (codecCtx_) {
        avcodec_free_context(&codecCtx_);
        codecCtx_ = nullptr;
    }
    if (fmtCtx_) {
        avformat_close_input(&fmtCtx_);
        fmtCtx_ = nullptr;
    }
}

bool AudioDecoder::open(const std::string& filePath, int targetSampleRate, int targetChannels) {
    close();
    filePath_ = filePath;
    targetSampleRate_ = targetSampleRate;
    targetChannels_ = targetChannels;

    if (avformat_open_input(&fmtCtx_, filePath.c_str(), nullptr, nullptr) < 0) {
        LOG_WARN("AudioDecoder", "Could not open audio file: ", filePath);
        return false;
    }

    if (avformat_find_stream_info(fmtCtx_, nullptr) < 0) {
        close();
        return false;
    }

    const AVCodec* decoder = nullptr;
    audioStreamIdx_ = av_find_best_stream(fmtCtx_, AVMEDIA_TYPE_AUDIO, -1, -1, &decoder, 0);
    if (audioStreamIdx_ < 0) {
        LOG_WARN("AudioDecoder", "No audio stream found in: ", filePath);
        close();
        return false;
    }

    AVStream* stream = fmtCtx_->streams[audioStreamIdx_];
    codecCtx_ = avcodec_alloc_context3(decoder);
    if (!codecCtx_ || avcodec_parameters_to_context(codecCtx_, stream->codecpar) < 0) {
        close();
        return false;
    }

    if (avcodec_open2(codecCtx_, decoder, nullptr) < 0) {
        close();
        return false;
    }

    // Configure resampler to output interleaved 32-bit float stereo
    swrCtx_ = swr_alloc();
    AVChannelLayout outLayout, inLayout;
    av_channel_layout_default(&outLayout, targetChannels_);
    
    // Check channel layout compatibility
    if (codecCtx_->ch_layout.nb_channels > 0) {
        av_channel_layout_copy(&inLayout, &codecCtx_->ch_layout);
    } else {
        av_channel_layout_default(&inLayout, 2);
    }

    swr_alloc_set_opts2(&swrCtx_, 
                        &outLayout, AV_SAMPLE_FMT_FLT, targetSampleRate_,
                        &inLayout, codecCtx_->sample_fmt, codecCtx_->sample_rate,
                        0, nullptr);
    swr_init(swrCtx_);

    av_channel_layout_uninit(&outLayout);
    av_channel_layout_uninit(&inLayout);

    LOG_INFO("AudioDecoder", "Opened audio: ", filePath, " (", codecCtx_->sample_rate, "Hz)");
    return true;
}

bool AudioDecoder::decodeAll(Tools::AudioBuffer& outBuffer) {
    if (!fmtCtx_ || !codecCtx_ || !swrCtx_) return false;

    outBuffer.sampleRate = targetSampleRate_;
    outBuffer.channels = targetChannels_;
    outBuffer.samples.clear();

    auto rawFrame = Utils::makeAVFrame();
    auto pkt = Utils::makeAVPacket();

    const int maxDstSamples = 4096;
    std::vector<float> resampleBuf(maxDstSamples * targetChannels_);

    while (av_read_frame(fmtCtx_, pkt.get()) >= 0) {
        if (pkt->stream_index == audioStreamIdx_) {
            if (avcodec_send_packet(codecCtx_, pkt.get()) >= 0) {
                while (avcodec_receive_frame(codecCtx_, rawFrame.get()) >= 0) {
                    uint8_t* outData[1] = { reinterpret_cast<uint8_t*>(resampleBuf.data()) };
                    int converted = swr_convert(swrCtx_, outData, maxDstSamples,
                                                (const uint8_t**)rawFrame->data, rawFrame->nb_samples);
                    if (converted > 0) {
                        outBuffer.samples.insert(outBuffer.samples.end(), 
                                                 resampleBuf.begin(), 
                                                 resampleBuf.begin() + converted * targetChannels_);
                    }
                }
            }
        }
        av_packet_unref(pkt.get());
    }

    return !outBuffer.samples.empty();
}

// ---------------------------------------------------------------------------
// MediaEncoder
// ---------------------------------------------------------------------------

MediaEncoder::~MediaEncoder() {
    finalize();
}

bool MediaEncoder::initialize(const std::string& outputPath, int width, int height, double fps,
                              int sampleRate, int channels, const std::string& videoCodec) {
    std::lock_guard<std::mutex> lock(mutex_);
    outputPath_ = outputPath;
    width_ = width;
    height_ = height;
    fps_ = fps;
    sampleRate_ = sampleRate;
    channels_ = channels;

    avformat_alloc_output_context2(&outFmtCtx_, nullptr, nullptr, outputPath.c_str());
    if (!outFmtCtx_) {
        LOG_ERROR("MediaEncoder", "Could not allocate output context for: ", outputPath);
        return false;
    }

    // 1. Video Stream Setup
    const AVCodec* vCodec = avcodec_find_encoder_by_name(videoCodec.c_str());
    if (!vCodec) {
        LOG_WARN("MediaEncoder", "Codec ", videoCodec, " not found, falling back to mpeg4");
        vCodec = avcodec_find_encoder(AV_CODEC_ID_MPEG4);
    }

    videoStream_ = avformat_new_stream(outFmtCtx_, nullptr);
    videoCodecCtx_ = avcodec_alloc_context3(vCodec);

    videoCodecCtx_->codec_id = vCodec->id;
    videoCodecCtx_->codec_type = AVMEDIA_TYPE_VIDEO;
    videoCodecCtx_->width = width_;
    videoCodecCtx_->height = height_;
    videoCodecCtx_->pix_fmt = AV_PIX_FMT_YUV420P;
    videoCodecCtx_->time_base = AVRational{1, static_cast<int>(fps_)};
    videoCodecCtx_->framerate = AVRational{static_cast<int>(fps_), 1};
    videoCodecCtx_->bit_rate = 8000000; // 8 Mbps
    videoCodecCtx_->gop_size = 12;

    if (outFmtCtx_->oformat->flags & AVFMT_GLOBALHEADER) {
        videoCodecCtx_->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
    }

    if (vCodec->id == AV_CODEC_ID_H264) {
        av_opt_set(videoCodecCtx_->priv_data, "preset", "veryfast", 0);
        av_opt_set(videoCodecCtx_->priv_data, "crf", "20", 0);
    }

    if (avcodec_open2(videoCodecCtx_, vCodec, nullptr) < 0) {
        LOG_ERROR("MediaEncoder", "Failed to open video encoder");
        return false;
    }
    avcodec_parameters_from_context(videoStream_->codecpar, videoCodecCtx_);
    videoStream_->time_base = videoCodecCtx_->time_base;

    // 2. Audio Stream Setup (AAC)
    const AVCodec* aCodec = avcodec_find_encoder(AV_CODEC_ID_AAC);
    if (aCodec) {
        audioStream_ = avformat_new_stream(outFmtCtx_, nullptr);
        audioCodecCtx_ = avcodec_alloc_context3(aCodec);
        audioCodecCtx_->codec_id = AV_CODEC_ID_AAC;
        audioCodecCtx_->codec_type = AVMEDIA_TYPE_AUDIO;
        audioCodecCtx_->sample_fmt = AV_SAMPLE_FMT_FLTP; // AAC planar float
        audioCodecCtx_->bit_rate = 192000;
        audioCodecCtx_->sample_rate = sampleRate_;
        av_channel_layout_default(&audioCodecCtx_->ch_layout, channels_);
        audioCodecCtx_->time_base = AVRational{1, sampleRate_};

        if (outFmtCtx_->oformat->flags & AVFMT_GLOBALHEADER) {
            audioCodecCtx_->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
        }

        if (avcodec_open2(audioCodecCtx_, aCodec, nullptr) < 0) {
            LOG_WARN("MediaEncoder", "Failed to open AAC audio encoder");
            avcodec_free_context(&audioCodecCtx_);
            audioCodecCtx_ = nullptr;
        } else {
            avcodec_parameters_from_context(audioStream_->codecpar, audioCodecCtx_);
            audioStream_->time_base = audioCodecCtx_->time_base;
        }
    }

    // 3. Open output file and write header
    if (!(outFmtCtx_->oformat->flags & AVFMT_NOFILE)) {
        if (avio_open(&outFmtCtx_->pb, outputPath.c_str(), AVIO_FLAG_WRITE) < 0) {
            LOG_ERROR("MediaEncoder", "Could not open output file: ", outputPath);
            return false;
        }
    }

    if (avformat_write_header(outFmtCtx_, nullptr) < 0) {
        LOG_ERROR("MediaEncoder", "Could not write MP4 header to: ", outputPath);
        return false;
    }

    // Allocate conversion buffers
    swsRgbaToYuv_ = sws_getContext(width_, height_, AV_PIX_FMT_RGBA,
                                   width_, height_, AV_PIX_FMT_YUV420P,
                                   SWS_BICUBIC, nullptr, nullptr, nullptr);

    yuvFrame_ = Utils::makeVideoFrame(width_, height_, AV_PIX_FMT_YUV420P);
    packet_ = Utils::makeAVPacket();

    LOG_INFO("MediaEncoder", "Initialized encoder for master file: ", outputPath, 
             " (", width_, "x", height_, " @ ", fps_, "fps)");
    return true;
}

bool MediaEncoder::encodeVideoFrame(AVFrame* rgbaFrame, int64_t frameIndex) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!outFmtCtx_ || !videoCodecCtx_ || !rgbaFrame) return false;

    // Convert RGBA -> YUV420P
    sws_scale(swsRgbaToYuv_, rgbaFrame->data, rgbaFrame->linesize, 0, height_,
              yuvFrame_->data, yuvFrame_->linesize);

    yuvFrame_->pts = frameIndex;

    int ret = avcodec_send_frame(videoCodecCtx_, yuvFrame_.get());
    if (ret < 0) {
        LOG_ERROR("MediaEncoder", "Error sending video frame to encoder: ", ret);
        return false;
    }

    while (ret >= 0) {
        ret = avcodec_receive_packet(videoCodecCtx_, packet_.get());
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) {
            break;
        } else if (ret < 0) {
            LOG_ERROR("MediaEncoder", "Error encoding video packet");
            return false;
        }

        av_packet_rescale_ts(packet_.get(), videoCodecCtx_->time_base, videoStream_->time_base);
        packet_->stream_index = videoStream_->index;
        av_interleaved_write_frame(outFmtCtx_, packet_.get());
        av_packet_unref(packet_.get());
    }

    return true;
}

bool MediaEncoder::encodeAudioBuffer(const Tools::AudioBuffer& audioBuffer) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!outFmtCtx_ || !audioCodecCtx_ || audioBuffer.samples.empty()) return false;

    // Setup resampler to convert interleaved float to planar float for AAC encoder
    SwrContext* swr = swr_alloc();
    AVChannelLayout chLayout;
    av_channel_layout_default(&chLayout, channels_);

    swr_alloc_set_opts2(&swr,
                        &chLayout, AV_SAMPLE_FMT_FLTP, sampleRate_,
                        &chLayout, AV_SAMPLE_FMT_FLT, sampleRate_,
                        0, nullptr);
    swr_init(swr);

    int frameSize = audioCodecCtx_->frame_size > 0 ? audioCodecCtx_->frame_size : 1024;
    auto aFrame = Utils::makeAVFrame();
    aFrame->nb_samples = frameSize;
    aFrame->format = AV_SAMPLE_FMT_FLTP;
    av_channel_layout_copy(&aFrame->ch_layout, &chLayout);
    av_frame_get_buffer(aFrame.get(), 0);

    size_t totalFrames = audioBuffer.samples.size() / channels_;
    size_t offset = 0;

    while (offset < totalFrames) {
        int samplesToProcess = static_cast<int>(std::min<size_t>(frameSize, totalFrames - offset));

        const uint8_t* inData[1] = { reinterpret_cast<const uint8_t*>(&audioBuffer.samples[offset * channels_]) };
        swr_convert(swr, aFrame->data, samplesToProcess, inData, samplesToProcess);

        aFrame->pts = nextAudioPts_;
        nextAudioPts_ += samplesToProcess;

        if (avcodec_send_frame(audioCodecCtx_, aFrame.get()) >= 0) {
            while (avcodec_receive_packet(audioCodecCtx_, packet_.get()) >= 0) {
                av_packet_rescale_ts(packet_.get(), audioCodecCtx_->time_base, audioStream_->time_base);
                packet_->stream_index = audioStream_->index;
                av_interleaved_write_frame(outFmtCtx_, packet_.get());
                av_packet_unref(packet_.get());
            }
        }

        offset += samplesToProcess;
    }

    av_channel_layout_uninit(&chLayout);
    swr_free(&swr);
    return true;
}

bool MediaEncoder::flushVideo() {
    if (!videoCodecCtx_ || !videoStream_) return true;
    avcodec_send_frame(videoCodecCtx_, nullptr);
    while (avcodec_receive_packet(videoCodecCtx_, packet_.get()) >= 0) {
        av_packet_rescale_ts(packet_.get(), videoCodecCtx_->time_base, videoStream_->time_base);
        packet_->stream_index = videoStream_->index;
        av_interleaved_write_frame(outFmtCtx_, packet_.get());
        av_packet_unref(packet_.get());
    }
    return true;
}

bool MediaEncoder::flushAudio() {
    if (!audioCodecCtx_ || !audioStream_) return true;
    avcodec_send_frame(audioCodecCtx_, nullptr);
    while (avcodec_receive_packet(audioCodecCtx_, packet_.get()) >= 0) {
        av_packet_rescale_ts(packet_.get(), audioCodecCtx_->time_base, audioStream_->time_base);
        packet_->stream_index = audioStream_->index;
        av_interleaved_write_frame(outFmtCtx_, packet_.get());
        av_packet_unref(packet_.get());
    }
    return true;
}

bool MediaEncoder::finalize() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (finalized_ || !outFmtCtx_) return true;
    finalized_ = true;

    flushVideo();
    flushAudio();

    av_write_trailer(outFmtCtx_);

    if (swsRgbaToYuv_) {
        sws_freeContext(swsRgbaToYuv_);
        swsRgbaToYuv_ = nullptr;
    }
    if (videoCodecCtx_) {
        avcodec_free_context(&videoCodecCtx_);
        videoCodecCtx_ = nullptr;
    }
    if (audioCodecCtx_) {
        avcodec_free_context(&audioCodecCtx_);
        audioCodecCtx_ = nullptr;
    }
    if (outFmtCtx_->pb && !(outFmtCtx_->oformat->flags & AVFMT_NOFILE)) {
        avio_closep(&outFmtCtx_->pb);
    }
    avformat_free_context(outFmtCtx_);
    outFmtCtx_ = nullptr;

    LOG_INFO("MediaEncoder", "Successfully finalized master container: ", outputPath_);
    return true;
}

// ---------------------------------------------------------------------------
// SyntheticMediaGenerator
// ---------------------------------------------------------------------------

void SyntheticMediaGenerator::generateVideoFrame(AVFrame* rgbaFrame, double timestamp, int patternType) {
    if (!rgbaFrame) return;

    int w = rgbaFrame->width;
    int h = rgbaFrame->height;
    int linesize = rgbaFrame->linesize[0];

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; ++y) {
        uint8_t* row = rgbaFrame->data[0] + y * linesize;
        for (int x = 0; x < w; ++x) {
            float u = static_cast<float>(x) / w;
            float v = static_cast<float>(y) / h;

            uint8_t r = 0, g = 0, b = 0;
            if (patternType == 0) {
                // Dynamic animated gradient pattern
                r = static_cast<uint8_t>((0.5f + 0.5f * std::sin(u * 6.28f + timestamp * 2.0f)) * 255.0f);
                g = static_cast<uint8_t>((0.5f + 0.5f * std::cos(v * 6.28f + timestamp * 1.5f)) * 255.0f);
                b = static_cast<uint8_t>((0.5f + 0.5f * std::sin((u + v) * 3.14f + timestamp)) * 255.0f);
            } else if (patternType == 1) {
                // Green screen backdrop pattern (pure green for chroma key testing)
                r = 20;
                g = 220;
                b = 30;
                // Animate foreground circle
                float cx = 0.5f + 0.25f * std::cos(timestamp * 2.0f);
                float cy = 0.5f + 0.2f * std::sin(timestamp * 3.0f);
                float dist = std::hypot(u - cx, v - cy);
                if (dist < 0.15f) {
                    r = 240; g = 180; b = 40; // Gold orb
                }
            } else {
                // High contrast SMPTE-style test stripes
                int stripe = (x * 7) / w;
                const uint8_t colors[7][3] = {
                    {200, 200, 200}, {200, 200, 0}, {0, 200, 200}, {0, 200, 0},
                    {200, 0, 200}, {200, 0, 0}, {0, 0, 200}
                };
                r = colors[stripe][0];
                g = colors[stripe][1];
                b = colors[stripe][2];
            }

            row[x * 4 + 0] = r;
            row[x * 4 + 1] = g;
            row[x * 4 + 2] = b;
            row[x * 4 + 3] = 255; // Fully opaque
        }
    }
}

void SyntheticMediaGenerator::generateAudioTrack(Tools::AudioBuffer& buffer, double durationSec, double freqHz) {
    buffer.sampleRate = 48000;
    buffer.channels = 2;
    size_t numSamples = static_cast<size_t>(durationSec * buffer.sampleRate);
    buffer.samples.resize(numSamples * buffer.channels);

    for (size_t i = 0; i < numSamples; ++i) {
        double t = static_cast<double>(i) / buffer.sampleRate;
        float sample = static_cast<float>(0.3 * std::sin(2.0 * M_PI * freqHz * t));
        buffer.samples[i * 2 + 0] = sample;
        buffer.samples[i * 2 + 1] = sample;
    }
}

} // namespace Core
} // namespace HyperEditor
