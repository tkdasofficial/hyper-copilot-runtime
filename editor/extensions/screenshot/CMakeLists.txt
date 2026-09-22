add_library(hyper_vision_agent_ext_screenshot STATIC
    screenshot.cpp
    screenshot.hpp
)

target_include_directories(hyper_vision_agent_ext_screenshot PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${PROJECT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/extensions
)

target_link_libraries(hyper_vision_agent_ext_screenshot PUBLIC
    hyper_vision_agent_core
    Threads::Threads
)
