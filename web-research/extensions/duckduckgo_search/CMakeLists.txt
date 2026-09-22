add_library(hyper_vision_agent_ext_duckduckgo_search STATIC
    ddg_search.cpp
    ddg_search.hpp
)

target_include_directories(hyper_vision_agent_ext_duckduckgo_search PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${PROJECT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/extensions
)

target_link_libraries(hyper_vision_agent_ext_duckduckgo_search PUBLIC
    hyper_vision_agent_core
    Threads::Threads
)
