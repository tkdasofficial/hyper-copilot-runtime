add_library(hyper_vision_agent_ext_anti_bot_stealth STATIC
    stealth.cpp
    stealth.hpp
    captcha_solver.hpp
)

target_include_directories(hyper_vision_agent_ext_anti_bot_stealth PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${PROJECT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/extensions
)

target_link_libraries(hyper_vision_agent_ext_anti_bot_stealth PUBLIC
    hyper_vision_agent_core
    Threads::Threads
)
