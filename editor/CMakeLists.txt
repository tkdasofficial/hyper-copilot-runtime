cmake_minimum_required(VERSION 3.16)
project(HyperCopilotRuntime LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler optimization flags
if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -O3 -march=native -pthread -fPIC)
endif()

# Threading support
find_package(Threads REQUIRED)

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
    pkg_check_modules(NLOHMANN_JSON nlohmann_json)
endif()

# Include directories
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/extensions
    ${FREETYPE_INCLUDE_DIRS}
    ${HARFBUZZ_INCLUDE_DIRS}
)

# ==============================================================================
# 1. Hyper Editor: High-Performance C++ Video Processing & Rendering Engine
# ==============================================================================
set(EDITOR_SOURCES
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

add_executable(hyper_editor ${EDITOR_SOURCES})
target_link_libraries(hyper_editor PRIVATE
    PkgConfig::LIBAVCODEC
    PkgConfig::LIBAVFORMAT
    PkgConfig::LIBAVFILTER
    PkgConfig::LIBSWSCALE
    PkgConfig::LIBSWRESAMPLE
    PkgConfig::LIBAVUTIL
    PkgConfig::FREETYPE
    PkgConfig::HARFBUZZ
    Threads::Threads
    m
)

if (TARGET nlohmann_json::nlohmann_json)
    target_link_libraries(hyper_editor PRIVATE nlohmann_json::nlohmann_json)
endif()

if (OpenMP_CXX_FOUND)
    target_link_libraries(hyper_editor PRIVATE OpenMP::OpenMP_CXX)
endif()

# ==============================================================================
# 2. Hyper Vision Agent: Native Heavy C++ CDP Headless Browser & Vision Engine
# ==============================================================================
set(HVA_SOURCES
    src/vision/process_launcher.cpp
    src/vision/websocket_client.cpp
    src/vision/cdp_connection.cpp
    src/vision/target_session_manager.cpp
    src/vision/command_dispatcher.cpp
    src/vision/page.cpp
    src/vision/browser_session.cpp
    src/vision/engine.cpp
)

set(HVA_HEADERS
    include/hyper_vision_agent/types.hpp
    include/hyper_vision_agent/process_launcher.hpp
    include/hyper_vision_agent/websocket_client.hpp
    include/hyper_vision_agent/cdp_connection.hpp
    include/hyper_vision_agent/target_session_manager.hpp
    include/hyper_vision_agent/command_dispatcher.hpp
    include/hyper_vision_agent/page.hpp
    include/hyper_vision_agent/browser_session.hpp
    include/hyper_vision_agent/engine.hpp
)

add_library(hyper_vision_agent_core STATIC
    ${HVA_SOURCES}
    ${HVA_HEADERS}
)

target_include_directories(hyper_vision_agent_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/extensions
)

target_link_libraries(hyper_vision_agent_core PUBLIC
    Threads::Threads
)

# Modular Extensions
if (EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/extensions/CMakeLists.txt")
    add_subdirectory(extensions)
endif()

# Vision Engine Executable
if (EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/vision/vision_main.cpp")
    add_executable(hyper_vision_agent_engine
        src/vision/vision_main.cpp
    )
    target_link_libraries(hyper_vision_agent_engine PRIVATE
        hyper_vision_agent_core
        hyper_vision_agent_ext_screen_recorder
        hyper_vision_agent_ext_screenshot
        hyper_vision_agent_ext_anti_bot_stealth
        hyper_vision_agent_ext_duckduckgo_search
        Threads::Threads
    )
endif()

# Install rules
install(TARGETS hyper_editor hyper_vision_agent_core hyper_vision_agent_engine DESTINATION bin OPTIONAL)
