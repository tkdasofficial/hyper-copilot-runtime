cmake_minimum_required(VERSION 3.16)
project(HyperEditor LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler optimization flags
if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -O3 -march=native -pthread)
endif()

# Find OpenMP for parallel frame processing
find_package(OpenMP)
if (OpenMP_CXX_FOUND)
    message(STATUS "OpenMP found: enabling multi-core frame DSP acceleration")
endif()

# Find PkgConfig
find_package(PkgConfig REQUIRED)

# Direct FFmpeg C-APIs
pkg_check_modules(LIBAVCODEC REQUIRED IMPORTED_TARGET libavcodec)
pkg_check_modules(LIBAVFORMAT REQUIRED IMPORTED_TARGET libavformat)
pkg_check_modules(LIBAVFILTER REQUIRED IMPORTED_TARGET libavfilter)
pkg_check_modules(LIBSWSCALE REQUIRED IMPORTED_TARGET libswscale)
pkg_check_modules(LIBSWRESAMPLE REQUIRED IMPORTED_TARGET libswresample)
pkg_check_modules(LIBAVUTIL REQUIRED IMPORTED_TARGET libavutil)

# FreeType2 & HarfBuzz for dynamic typography and captions
pkg_check_modules(FREETYPE REQUIRED IMPORTED_TARGET freetype2)
pkg_check_modules(HARFBUZZ REQUIRED IMPORTED_TARGET harfbuzz)

# nlohmann/json
find_package(nlohmann_json 3.2.0 QUIET)
if (NOT nlohmann_json_FOUND)
    # Check pkg-config or standard header path
    pkg_check_modules(NLOHMANN_JSON nlohmann_json)
endif()

# Include directories
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${FREETYPE_INCLUDE_DIRS}
    ${HARFBUZZ_INCLUDE_DIRS}
)

# Source files
set(SOURCES
    src/main.cpp
    src/core/editor.cpp
    src/core/ffmpeg_bridge.cpp
    src/core/timeline.cpp
    src/tools/keyframing.cpp
    src/tools/masking.cpp
    src/tools/overlays.cpp
    src/tools/captions.cpp
    src/tools/transitions.cpp
    src/tools/audio_mixer.cpp
    src/tools/color_grading.cpp
    src/tools/motion_zoom.cpp
    src/tools/speed_ramping.cpp
    src/tools/chroma_key.cpp
    src/tools/audio_effects.cpp
    src/tools/frame_scaler.cpp
    src/parsers/json_parser.cpp
    src/utils/memory.cpp
    src/utils/logger.cpp
)

add_executable(hyper_editor ${SOURCES})

target_link_libraries(hyper_editor PRIVATE
    PkgConfig::LIBAVCODEC
    PkgConfig::LIBAVFORMAT
    PkgConfig::LIBAVFILTER
    PkgConfig::LIBSWSCALE
    PkgConfig::LIBSWRESAMPLE
    PkgConfig::LIBAVUTIL
    PkgConfig::FREETYPE
    PkgConfig::HARFBUZZ
    pthread
    m
)

if (TARGET nlohmann_json::nlohmann_json)
    target_link_libraries(hyper_editor PRIVATE nlohmann_json::nlohmann_json)
endif()

if (OpenMP_CXX_FOUND)
    target_link_libraries(hyper_editor PRIVATE OpenMP::OpenMP_CXX)
endif()

install(TARGETS hyper_editor DESTINATION bin)
