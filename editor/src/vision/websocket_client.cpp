#include "hyper_vision_agent/websocket_client.hpp"
#include <iostream>
#include <sstream>
#include <vector>
#include <cstring>
#include <random>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <poll.h>
#include <fcntl.h>

namespace hyper_vision_agent {

namespace {

// Pure C++ Base64 implementation
const std::string BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

std::string Base64Encode(const unsigned char* bytes_to_encode, size_t in_len) {
    std::string ret;
    int i = 0;
    int j = 0;
    unsigned char char_array_3[3];
    unsigned char char_array_4[4];

    while (in_len--) {
        char_array_3[i++] = *(bytes_to_encode++);
        if (i == 3) {
            char_array_4[0] = (char_array_3[0] & 0xfc) >> 2;
            char_array_4[1] = ((char_array_3[0] & 0x03) << 4) + ((char_array_3[1] & 0xf0) >> 4);
            char_array_4[2] = ((char_array_3[1] & 0x0f) << 2) + ((char_array_3[2] & 0xc0) >> 6);
            char_array_4[3] = char_array_3[2] & 0x3f;

            for (i = 0; i < 4; i++) ret += BASE64_CHARS[char_array_4[i]];
            i = 0;
        }
    }

    if (i) {
        for (j = i; j < 3; j++) char_array_3[j] = '\0';

        char_array_4[0] = (char_array_3[0] & 0xfc) >> 2;
        char_array_4[1] = ((char_array_3[0] & 0x03) << 4) + ((char_array_3[1] & 0xf0) >> 4);
        char_array_4[2] = ((char_array_3[1] & 0x0f) << 2) + ((char_array_3[2] & 0xc0) >> 6);

        for (j = 0; j < i + 1; j++) ret += BASE64_CHARS[char_array_4[j]];
        while ((i++ < 3)) ret += '=';
    }

    return ret;
}

// Pure C++ SHA-1 implementation (RFC 3174) for WebSocket Handshake validation
[[maybe_unused]] uint32_t LeftRotate(uint32_t value, size_t count) {
    return (value << count) ^ (value >> (32 - count));
}

[[maybe_unused]] std::vector<uint8_t> CalculateSha1(const std::string& input) {
    uint32_t h0 = 0x67452301;
    uint32_t h1 = 0xEFCDAB89;
    uint32_t h2 = 0x98BADCFE;
    uint32_t h3 = 0x10325476;
    uint32_t h4 = 0xC3D2E1F0;

    std::vector<uint8_t> msg(input.begin(), input.end());
    uint64_t original_len_bits = msg.size() * 8;

    msg.push_back(0x80);
    while ((msg.size() % 64) != 56) {
        msg.push_back(0x00);
    }

    for (int i = 7; i >= 0; --i) {
        msg.push_back(static_cast<uint8_t>((original_len_bits >> (i * 8)) & 0xFF));
    }

    for (size_t chunk = 0; chunk < msg.size(); chunk += 64) {
        uint32_t w[80];
        for (size_t i = 0; i < 16; ++i) {
            w[i] = (static_cast<uint32_t>(msg[chunk + i * 4]) << 24) |
                   (static_cast<uint32_t>(msg[chunk + i * 4 + 1]) << 16) |
                   (static_cast<uint32_t>(msg[chunk + i * 4 + 2]) << 8) |
                   (static_cast<uint32_t>(msg[chunk + i * 4 + 3]));
        }
        for (size_t i = 16; i < 80; ++i) {
            w[i] = LeftRotate(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        }

        uint32_t a = h0;
        uint32_t b = h1;
        uint32_t c = h2;
        uint32_t d = h3;
        uint32_t e = h4;

        for (size_t i = 0; i < 80; ++i) {
            uint32_t f = 0;
            uint32_t k = 0;

            if (i < 20) {
                f = (b & c) | ((~b) & d);
                k = 0x5A827999;
            } else if (i < 40) {
                f = b ^ c ^ d;
                k = 0x6ED9EBA1;
            } else if (i < 60) {
                f = (b & c) | (b & d) | (c & d);
                k = 0x8F1BBCDC;
            } else {
                f = b ^ c ^ d;
                k = 0xCA62C1D6;
            }

            uint32_t temp = LeftRotate(a, 5) + f + e + k + w[i];
            e = d;
            d = c;
            c = LeftRotate(b, 30);
            b = a;
            a = temp;
        }

        h0 += a;
        h1 += b;
        h2 += c;
        h3 += d;
        h4 += e;
    }

    std::vector<uint8_t> digest(20);
    for (size_t i = 0; i < 4; ++i) {
        digest[i]      = static_cast<uint8_t>((h0 >> (24 - i * 8)) & 0xFF);
        digest[i + 4]  = static_cast<uint8_t>((h1 >> (24 - i * 8)) & 0xFF);
        digest[i + 8]  = static_cast<uint8_t>((h2 >> (24 - i * 8)) & 0xFF);
        digest[i + 12] = static_cast<uint8_t>((h3 >> (24 - i * 8)) & 0xFF);
        digest[i + 16] = static_cast<uint8_t>((h4 >> (24 - i * 8)) & 0xFF);
    }
    return digest;
}

std::string GenerateWebSocketKey() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 255);
    unsigned char bytes[16];
    for (int i = 0; i < 16; ++i) {
        bytes[i] = static_cast<unsigned char>(dis(gen));
    }
    return Base64Encode(bytes, 16);
}

} // namespace

WebSocketClient::WebSocketClient() {}

WebSocketClient::~WebSocketClient() {
    Close(1001, "Destructor called");
}

bool WebSocketClient::Connect(const std::string& ws_url, [[maybe_unused]] std::chrono::milliseconds timeout) {
    std::lock_guard<std::mutex> lock(send_mutex_);
    url_ = ws_url;
    state_ = WebSocketState::CONNECTING;

    // Parse ws://host:port/path
    std::string prefix = "ws://";
    if (ws_url.rfind(prefix, 0) != 0) {
        if (error_handler_) error_handler_("Invalid WebSocket URL format, must start with ws://");
        state_ = WebSocketState::FAILED;
        return false;
    }

    std::string remainder = ws_url.substr(prefix.length());
    size_t slash_pos = remainder.find('/');
    std::string host_port = (slash_pos == std::string::npos) ? remainder : remainder.substr(0, slash_pos);
    std::string path = (slash_pos == std::string::npos) ? "/" : remainder.substr(slash_pos);

    std::string host;
    int port = 80;
    size_t colon_pos = host_port.find(':');
    if (colon_pos != std::string::npos) {
        host = host_port.substr(0, colon_pos);
        port = std::stoi(host_port.substr(colon_pos + 1));
    } else {
        host = host_port;
    }

    if (!PerformHandshake(host, port, path)) {
        state_ = WebSocketState::FAILED;
        if (socket_fd_ >= 0) {
            close(socket_fd_);
            socket_fd_ = -1;
        }
        return false;
    }

    state_ = WebSocketState::OPEN;
    if (state_handler_) state_handler_(WebSocketState::OPEN);

    // Start background network receiver thread
    stop_worker_ = false;
    worker_thread_ = std::thread(&WebSocketClient::NetworkWorkerLoop, this);
    return true;
}

bool WebSocketClient::PerformHandshake(const std::string& host, int port, const std::string& path) {
    socket_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (socket_fd_ < 0) return false;

    // Enable TCP_NODELAY for lowest latency
    int flag = 1;
    setsockopt(socket_fd_, IPPROTO_TCP, TCP_NODELAY, (char*)&flag, sizeof(int));

    struct sockaddr_in serv_addr;
    std::memset(&serv_addr, 0, sizeof(serv_addr));
    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port);

    if (inet_pton(AF_INET, host.c_str(), &serv_addr.sin_addr) <= 0) {
        struct hostent* he = gethostbyname(host.c_str());
        if (!he) {
            close(socket_fd_);
            socket_fd_ = -1;
            return false;
        }
        std::memcpy(&serv_addr.sin_addr, he->h_addr_list[0], he->h_length);
    }

    if (connect(socket_fd_, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) < 0) {
        close(socket_fd_);
        socket_fd_ = -1;
        return false;
    }

    std::string key = GenerateWebSocketKey();
    std::ostringstream req;
    req << "GET " << path << " HTTP/1.1\r\n"
        << "Host: " << host << ":" << port << "\r\n"
        << "Upgrade: websocket\r\n"
        << "Connection: Upgrade\r\n"
        << "Sec-WebSocket-Key: " << key << "\r\n"
        << "Sec-WebSocket-Version: 13\r\n"
        << "Origin: http://127.0.0.1:" << port << "\r\n\r\n";

    std::string req_str = req.str();
    if (send(socket_fd_, req_str.c_str(), req_str.length(), 0) < 0) {
        close(socket_fd_);
        socket_fd_ = -1;
        return false;
    }

    // Read Handshake response
    char buffer[4096];
    std::string response;
    while (response.find("\r\n\r\n") == std::string::npos) {
        ssize_t n = recv(socket_fd_, buffer, sizeof(buffer) - 1, 0);
        if (n <= 0) {
            close(socket_fd_);
            socket_fd_ = -1;
            return false;
        }
        buffer[n] = '\0';
        response += buffer;
    }

    if (response.find(" 101 ") == std::string::npos && response.find("101 Switching Protocols") == std::string::npos && response.find("101 WebSocket Protocol Handshake") == std::string::npos) {
        std::cerr << "[CDP WebSocket Handshake Error] Non-101 response: " << response << "\n";
        close(socket_fd_);
        socket_fd_ = -1;
        return false;
    }

    return true;
}

bool WebSocketClient::Send(const std::string& text) {
    if (state_ != WebSocketState::OPEN || socket_fd_ < 0) {
        return false;
    }
    return SendFrame(0x1, reinterpret_cast<const uint8_t*>(text.data()), text.size(), true);
}

bool WebSocketClient::SendFrame(uint8_t opcode, const uint8_t* payload, size_t length, bool mask) {
    std::lock_guard<std::mutex> lock(send_mutex_);
    if (socket_fd_ < 0) return false;

    std::vector<uint8_t> frame;
    // FIN = 1, RSV = 0, opcode
    frame.push_back(0x80 | (opcode & 0x0F));

    uint8_t mask_bit = mask ? 0x80 : 0x00;
    if (length < 126) {
        frame.push_back(mask_bit | static_cast<uint8_t>(length));
    } else if (length <= 65535) {
        frame.push_back(mask_bit | 126);
        frame.push_back(static_cast<uint8_t>((length >> 8) & 0xFF));
        frame.push_back(static_cast<uint8_t>(length & 0xFF));
    } else {
        frame.push_back(mask_bit | 127);
        for (int i = 7; i >= 0; --i) {
            frame.push_back(static_cast<uint8_t>((length >> (i * 8)) & 0xFF));
        }
    }

    if (mask) {
        uint8_t masking_key[4] = {
            static_cast<uint8_t>(rand() % 256),
            static_cast<uint8_t>(rand() % 256),
            static_cast<uint8_t>(rand() % 256),
            static_cast<uint8_t>(rand() % 256)
        };
        frame.insert(frame.end(), masking_key, masking_key + 4);

        size_t payload_offset = frame.size();
        frame.resize(payload_offset + length);
        for (size_t i = 0; i < length; ++i) {
            frame[payload_offset + i] = payload[i] ^ masking_key[i % 4];
        }
    } else {
        frame.insert(frame.end(), payload, payload + length);
    }

    size_t total_sent = 0;
    while (total_sent < frame.size()) {
        ssize_t sent = send(socket_fd_, frame.data() + total_sent, frame.size() - total_sent, 0);
        if (sent <= 0) {
            return false;
        }
        total_sent += sent;
    }

    return true;
}

void WebSocketClient::NetworkWorkerLoop() {
    std::vector<uint8_t> rx_buffer;
    rx_buffer.reserve(65536);
    uint8_t temp_buf[8192];

    while (!stop_worker_ && socket_fd_ >= 0) {
        struct pollfd pfd;
        pfd.fd = socket_fd_;
        pfd.events = POLLIN;
        pfd.revents = 0;

        int poll_res = poll(&pfd, 1, 100); // 100ms timeout
        if (poll_res < 0) {
            break;
        }
        if (poll_res == 0) {
            continue;
        }

        if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) {
            break;
        }

        if (pfd.revents & POLLIN) {
            ssize_t n = recv(socket_fd_, temp_buf, sizeof(temp_buf), 0);
            if (n <= 0) {
                break;
            }

            rx_buffer.insert(rx_buffer.end(), temp_buf, temp_buf + n);
            
            // Frame parsing loop
            while (rx_buffer.size() >= 2) {
                uint8_t b0 = rx_buffer[0];
                uint8_t b1 = rx_buffer[1];
                [[maybe_unused]] bool fin = (b0 & 0x80) != 0;
                uint8_t opcode = b0 & 0x0F;
                bool is_masked = (b1 & 0x80) != 0;
                uint64_t payload_len = b1 & 0x7F;

                size_t header_len = 2;
                if (payload_len == 126) {
                    if (rx_buffer.size() < 4) break;
                    payload_len = (static_cast<uint64_t>(rx_buffer[2]) << 8) | rx_buffer[3];
                    header_len = 4;
                } else if (payload_len == 127) {
                    if (rx_buffer.size() < 10) break;
                    payload_len = 0;
                    for (int i = 0; i < 8; ++i) {
                        payload_len = (payload_len << 8) | rx_buffer[2 + i];
                    }
                    header_len = 10;
                }

                size_t mask_len = is_masked ? 4 : 0;
                if (rx_buffer.size() < header_len + mask_len + payload_len) {
                    break; // Wait for full frame
                }

                uint8_t mask_key[4] = {0};
                if (is_masked) {
                    std::memcpy(mask_key, rx_buffer.data() + header_len, 4);
                }

                size_t payload_start = header_len + mask_len;
                std::vector<uint8_t> unmasked_payload(payload_len);
                for (size_t i = 0; i < payload_len; ++i) {
                    uint8_t b = rx_buffer[payload_start + i];
                    unmasked_payload[i] = is_masked ? (b ^ mask_key[i % 4]) : b;
                }

                // Handle Frame Opcode
                if (opcode == 0x1) { // Text frame
                    std::string text_msg(unmasked_payload.begin(), unmasked_payload.end());
                    std::lock_guard<std::mutex> hlock(handler_mutex_);
                    if (message_handler_) {
                        message_handler_(text_msg);
                    }
                } else if (opcode == 0x8) { // Close
                    state_ = WebSocketState::CLOSED;
                    break;
                } else if (opcode == 0x9) { // Ping -> send Pong
                    SendFrame(0xA, unmasked_payload.data(), unmasked_payload.size(), true);
                }

                // Advance rx_buffer
                size_t total_frame_len = header_len + mask_len + payload_len;
                rx_buffer.erase(rx_buffer.begin(), rx_buffer.begin() + total_frame_len);
            }
        }
    }

    state_ = WebSocketState::CLOSED;
    if (state_handler_) state_handler_(WebSocketState::CLOSED);
}

void WebSocketClient::Close(uint16_t code, [[maybe_unused]] const std::string& reason) {
    if (state_ == WebSocketState::CLOSED || state_ == WebSocketState::DISCONNECTED) {
        return;
    }
    state_ = WebSocketState::CLOSING;
    stop_worker_ = true;

    // Send close frame
    uint8_t payload[2];
    payload[0] = static_cast<uint8_t>((code >> 8) & 0xFF);
    payload[1] = static_cast<uint8_t>(code & 0xFF);
    SendFrame(0x8, payload, 2, true);

    if (worker_thread_.joinable()) {
        worker_thread_.join();
    }

    if (socket_fd_ >= 0) {
        close(socket_fd_);
        socket_fd_ = -1;
    }

    state_ = WebSocketState::CLOSED;
    if (state_handler_) state_handler_(WebSocketState::CLOSED);
}

bool WebSocketClient::IsConnected() const {
    return state_ == WebSocketState::OPEN;
}

WebSocketState WebSocketClient::GetState() const {
    return state_;
}

void WebSocketClient::SetMessageHandler(MessageHandler handler) {
    std::lock_guard<std::mutex> lock(handler_mutex_);
    message_handler_ = std::move(handler);
}

void WebSocketClient::SetStateHandler(StateHandler handler) {
    std::lock_guard<std::mutex> lock(handler_mutex_);
    state_handler_ = std::move(handler);
}

void WebSocketClient::SetErrorHandler(ErrorHandler handler) {
    std::lock_guard<std::mutex> lock(handler_mutex_);
    error_handler_ = std::move(handler);
}

} // namespace hyper_vision_agent
