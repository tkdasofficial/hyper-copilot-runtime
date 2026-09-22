#ifndef HYPER_VISION_AGENT_EXT_DDG_SEARCH_HPP
#define HYPER_VISION_AGENT_EXT_DDG_SEARCH_HPP

#include "hyper_vision_agent/types.hpp"
#include "hyper_vision_agent/page.hpp"
#include <string>
#include <vector>
#include <chrono>

namespace hyper_vision_agent {
namespace extensions {

struct SearchResultItem {
    std::string title = "";
    std::string url = "";
    std::string snippet = "";
    int position = 0;
};

struct SearchResponse {
    std::string query = "";
    std::vector<SearchResultItem> items;
    bool success = false;
    std::string error_message = "";
    std::chrono::milliseconds elapsed_time{0};
    int total_results = 0;
};

struct SearchOptions {
    int max_results = 10;
    bool html_backend = true; // Use https://html.duckduckgo.com/html/?q= for clean, robust markup
    std::string region = "wt-wt"; // Worldwide
    bool safe_search = false;
    std::chrono::milliseconds timeout{15000};
};

class DuckDuckGoSearch {
public:
    DuckDuckGoSearch() = default;
    ~DuckDuckGoSearch() = default;

    // Executes search and extracts structured results
    static SearchResponse Search(
        Page& page, 
        const std::string& query, 
        const SearchOptions& options = SearchOptions{}
    );

    // Generates formatted DuckDuckGo URL
    static std::string BuildQueryUrl(const std::string& query, const SearchOptions& options = SearchOptions{});

    // Extracts result items from current page DOM
    static std::vector<SearchResultItem> ExtractResultsFromDom(Page& page, int max_results = 10);

    // Resolves redirect URLs (/l/?uddg=https%3A%2F%2F... into destination URL)
    static std::string UnpackDdgRedirect(const std::string& raw_url);

    // URL Encoding / Decoding helpers
    static std::string UrlEncode(const std::string& value);
    static std::string UrlDecode(const std::string& value);
};

} // namespace extensions
} // namespace hyper_vision_agent

#endif // HYPER_VISION_AGENT_EXT_DDG_SEARCH_HPP
