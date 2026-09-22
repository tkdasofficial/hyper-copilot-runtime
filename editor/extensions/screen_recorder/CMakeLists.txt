add_library(hyper_vision_agent_ext_screen_recorder STATIC
    screen_recorder.cpp
    screen_recorder.hpp
)

target_include_directories(hyper_vision_agent_ext_screen_recorder PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${PROJECT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/extensions
)

target_link_libraries(hyper_vision_agent_ext_screen_recorder PUBLIC
    hyper_vision_agent_core
    Threads::Threads
)
