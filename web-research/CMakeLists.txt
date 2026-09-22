cmake_minimum_required(VERSION 3.16)
project(hyper_vision_agent 
    VERSION 1.0.0
    DESCRIPTION "High-performance stateless C++ Chromium headless browser engine operating via CDP"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler optimization and warning flags
if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -Wpedantic -O3 -fPIC)
endif()

# Threading support
find_package(Threads REQUIRED)

# Include Directories
include_directories(
    ${PROJECT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/extensions
)

# Core Library Sources
set(HVA_SOURCES
    src/process_launcher.cpp
    src/websocket_client.cpp
    src/cdp_connection.cpp
    src/target_session_manager.cpp
    src/command_dispatcher.cpp
    src/page.cpp
    src/browser_session.cpp
    src/engine.cpp
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

# Build Core Static Library
add_library(hyper_vision_agent_core STATIC
    ${HVA_SOURCES}
    ${HVA_HEADERS}
)

target_link_libraries(hyper_vision_agent_core PUBLIC
    Threads::Threads
)

# Modular Extensions
add_subdirectory(extensions)

# Build Engine CLI Binary
add_executable(hyper_vision_agent_engine
    src/main.cpp
)

target_link_libraries(hyper_vision_agent_engine PRIVATE
    hyper_vision_agent_core
    hyper_vision_agent_ext_screen_recorder
    hyper_vision_agent_ext_screenshot
    hyper_vision_agent_ext_anti_bot_stealth
    hyper_vision_agent_ext_duckduckgo_search
    Threads::Threads
)

# Install rules
install(TARGETS 
    hyper_vision_agent_core 
    hyper_vision_agent_engine
    hyper_vision_agent_ext_screen_recorder
    hyper_vision_agent_ext_screenshot
    hyper_vision_agent_ext_anti_bot_stealth
    hyper_vision_agent_ext_duckduckgo_search
    RUNTIME DESTINATION bin
    ARCHIVE DESTINATION lib
)

install(DIRECTORY include/hyper_vision_agent DESTINATION include)
