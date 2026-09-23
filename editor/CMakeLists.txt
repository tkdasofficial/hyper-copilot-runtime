cmake_minimum_required(VERSION 3.16)
project(HyperEditor LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# High performance optimization flags
if(CMAKE_BUILD_TYPE STREQUAL "Release" OR NOT CMAKE_BUILD_TYPE)
    add_compile_options(-O3 -pipe -Wall -Wextra)
endif()

find_package(PkgConfig QUIET)
find_package(Threads REQUIRED)

# Core engine library sources
set(CORE_SOURCES
    src/scene_builder.cpp
    src/ffmpeg_graph.cpp
    src/caption_renderer.cpp
)

set(CORE_HEADERS
    src/scene_builder.hpp
    src/ffmpeg_graph.hpp
    src/caption_renderer.hpp
    src/utils.hpp
)

# 1. Hyper Editor (CLI Filter Graph & Subtitle Engine)
add_executable(hyper_editor src/main.cpp ${CORE_SOURCES} ${CORE_HEADERS})
target_include_directories(hyper_editor PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(hyper_editor PRIVATE Threads::Threads)

# 2. Hyper Pipeline (Strict C++ Full Video Creation Pipeline)
add_executable(hyper_pipeline src/pipeline.cpp ${CORE_SOURCES} ${CORE_HEADERS})
target_include_directories(hyper_pipeline PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(hyper_pipeline PRIVATE Threads::Threads)

# 3. Hyper Long-Form Engine (Strict C++ Episodic Documentary Pipeline)
add_executable(hyper_long_form src/long_form_pipeline.cpp ${CORE_SOURCES} ${CORE_HEADERS})
target_include_directories(hyper_long_form PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(hyper_long_form PRIVATE Threads::Threads)

# 4. Hyper Drive Exporter (Strict C++ Google Drive Exporter)
add_executable(hyper_drive_export src/export_to_drive.cpp ${CORE_HEADERS})
target_include_directories(hyper_drive_export PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(hyper_drive_export PRIVATE Threads::Threads)
