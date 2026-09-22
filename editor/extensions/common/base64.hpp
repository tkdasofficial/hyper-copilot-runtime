#ifndef HYPER_VISION_AGENT_BASE64_HPP
#define HYPER_VISION_AGENT_BASE64_HPP

#include <string>
#include <vector>
#include <cstdint>

namespace hyper_vision_agent {
namespace utils {

inline std::string Base64Encode(const uint8_t* data, size_t length) {
    static const char kEncodeTable[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string result;
    result.reserve(((length + 2) / 3) * 4);

    size_t i = 0;
    while (i < length) {
        uint32_t octet_a = i < length ? data[i++] : 0;
        uint32_t octet_b = i < length ? data[i++] : 0;
        uint32_t octet_c = i < length ? data[i++] : 0;

        uint32_t triple = (octet_a << 16) | (octet_b << 8) | octet_c;

        result.push_back(kEncodeTable[(triple >> 18) & 0x3F]);
        result.push_back(kEncodeTable[(triple >> 12) & 0x3F]);
        result.push_back(i > length + 1 ? '=' : kEncodeTable[(triple >> 6) & 0x3F]);
        result.push_back(i > length ? '=' : kEncodeTable[triple & 0x3F]);
    }
    return result;
}

inline std::string Base64Encode(const std::string& input) {
    return Base64Encode(reinterpret_cast<const uint8_t*>(input.data()), input.size());
}

inline std::vector<uint8_t> Base64Decode(const std::string& input) {
    std::vector<uint8_t> result;
    if (input.empty()) return result;

    static const int kDecodeTable[256] = {
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,62,-1,-1,-1,63,
        52,53,54,55,56,57,58,59,60,61,-1,-1,-1,-1,-1,-1,
        -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,10,11,12,13,14,
        15,16,17,18,19,20,21,22,23,24,25,-1,-1,-1,-1,-1,
        -1,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
        41,42,43,44,45,46,47,48,49,50,51,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
        -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1
    };

    result.reserve((input.size() * 3) / 4);
    uint32_t val = 0;
    int valb = -8;

    for (unsigned char c : input) {
        if (c == '=' || c == '\r' || c == '\n' || c == ' ') continue;
        int d = kDecodeTable[c];
        if (d == -1) continue;
        val = (val << 6) | d;
        valb += 6;
        if (valb >= 0) {
            result.push_back(static_cast<uint8_t>((val >> valb) & 0xFF));
            valb -= 8;
        }
    }
    return result;
}

} // namespace utils
} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_BASE64_HPP
