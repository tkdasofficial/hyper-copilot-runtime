#include "ddg_search.hpp"
#include <iostream>
#include <sstream>
#include <iomanip>
#include <cctype>

namespace hyper_vision_agent {
namespace extensions {

std::string DuckDuckGoSearch::UrlEncode(const std::string& value) {
    std::ostringstream escaped;
    escaped.fill('0');
    escaped << std::hex;

    for (unsigned char c : value) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
            escaped << c;
        } else if (c == ' ') {
            escaped << '+';
        } else {
            escaped << std::uppercase;
            escaped << '%' << std::setw(2) << static_cast<int>(c);
            escaped << std::nouppercase;
        }
    }
    return escaped.str();
}

std::string DuckDuckGoSearch::UrlDecode(const std::string& value) {
    std::string result;
    result.reserve(value.size());

    for (size_t i = 0; i < value.size(); ++i) {
        if (value[i] == '%') {
            if (i + 2 < value.size()) {
                int hex_val = 0;
                std::istringstream hex_stream(value.substr(i + 1, 2));
                if (hex_stream >> std::hex >> hex_val) {
                    result += static_cast<char>(hex_val);
                    i += 2;
                } else {
                    result += '%';
                }
            } else {
                result += '%';
            }
        } else if (value[i] == '+') {
            result += ' ';
        } else {
            result += value[i];
        }
    }
    return result;
}

std::string DuckDuckGoSearch::UnpackDdgRedirect(const std::string& raw_url) {
    // Check for DDG redirect pattern: /l/?uddg=https%3A%2F%2F...
    size_t uddg_pos = raw_url.find("uddg=");
    if (uddg_pos == std::string::npos) {
        // Return raw url if already absolute
        if (raw_url.rfind("//", 0) == 0) {
            return "https:" + raw_url;
        }
        return raw_url;
    }

    size_t start = uddg_pos + 5;
    size_t end = raw_url.find('&', start);
    std::string encoded_target = (end == std::string::npos) 
        ? raw_url.substr(start) 
        : raw_url.substr(start, end - start);

    return UrlDecode(encoded_target);
}

std::string DuckDuckGoSearch::BuildQueryUrl(const std::string& query, const SearchOptions& options) {
    std::stringstream ss;
    if (options.html_backend) {
        ss << "https://html.duckduckgo.com/html/?q=" << UrlEncode(query);
        ss << "&kl=" << options.region;
        if (options.safe_search) {
            ss << "&kp=1";
        } else {
            ss << "&kp=-1";
        }
    } else {
        ss << "https://duckduckgo.com/?q=" << UrlEncode(query);
        ss << "&kl=" << options.region;
    }
    return ss.str();
}

std::vector<SearchResultItem> DuckDuckGoSearch::ExtractResultsFromDom(Page& page, int max_results) {
    std::vector<SearchResultItem> results;

    std::string extractor_script = 
        "(function() {"
        "  var items = [];"
        "  /* 1. Try HTML backend format (.result__body, .web-result) */\n"
        "  var htmlElements = document.querySelectorAll('.result__body, .web-result, .result');"
        "  if (htmlElements && htmlElements.length > 0) {"
        "    for (var i = 0; i < htmlElements.length; i++) {"
        "      var el = htmlElements[i];"
        "      var titleEl = el.querySelector('.result__title a, .result__a');"
        "      var snippetEl = el.querySelector('.result__snippet');"
        "      var title = titleEl ? (titleEl.textContent || titleEl.innerText || '').trim() : '';"
        "      var href = titleEl ? (titleEl.getAttribute('href') || '') : '';"
        "      var snippet = snippetEl ? (snippetEl.textContent || snippetEl.innerText || '').trim() : '';"
        "      if (title && href && href !== '#') {"
        "        items.push({ title: title, url: href, snippet: snippet });"
        "      }"
        "    }"
        "  }"
        "  /* 2. Fallback to standard modern DDG format */\n"
        "  if (items.length === 0) {"
        "    var stdElements = document.querySelectorAll('article, [data-testid=\"result\"]');"
        "    for (var j = 0; j < stdElements.length; j++) {"
        "      var card = stdElements[j];"
        "      var tEl = card.querySelector('h2 a, a[data-testid=\"result-title-a\"]');"
        "      var sEl = card.querySelector('[data-result=\"snippet\"], [style*=\"-webkit-line-clamp\"]');"
        "      var t = tEl ? (tEl.textContent || tEl.innerText || '').trim() : '';"
        "      var h = tEl ? (tEl.getAttribute('href') || '') : '';"
        "      var s = sEl ? (sEl.textContent || sEl.innerText || '').trim() : '';"
        "      if (t && h) {"
        "        items.push({ title: t, url: h, snippet: s });"
        "      }"
        "    }"
        "  }"
        "  return JSON.stringify(items);"
        "})()";

    auto eval_res = page.EvaluateScript(extractor_script);
    if (!eval_res.success || eval_res.value_string.empty()) {
        return results;
    }

    std::string json = eval_res.value_string;
    // Parse array of objects: [{"title": "...","url": "...","snippet": "..."}, ...]
    size_t pos = 0;
    int current_pos = 1;

    while ((pos = json.find('{', pos)) != std::string::npos && static_cast<int>(results.size()) < max_results) {
        size_t end_obj = json.find('}', pos);
        if (end_obj == std::string::npos) break;

        std::string obj_str = json.substr(pos, end_obj - pos + 1);

        auto extract_key = [&obj_str](const std::string& key) -> std::string {
            std::string pattern = "\"" + key + "\":\"";
            size_t kpos = obj_str.find(pattern);
            if (kpos == std::string::npos) return "";
            kpos += pattern.length();
            size_t end_quote = obj_str.find('"', kpos);
            while (end_quote != std::string::npos && obj_str[end_quote - 1] == '\\') {
                end_quote = obj_str.find('"', end_quote + 1);
            }
            if (end_quote == std::string::npos) return "";
            return obj_str.substr(kpos, end_quote - kpos);
        };

        std::string title = extract_key("title");
        std::string raw_url = extract_key("url");
        std::string snippet = extract_key("snippet");

        if (!title.empty() && !raw_url.empty()) {
            SearchResultItem item;
            item.title = title;
            item.url = UnpackDdgRedirect(raw_url);
            item.snippet = snippet;
            item.position = current_pos++;
            results.push_back(item);
        }

        pos = end_obj + 1;
    }

    return results;
}

SearchResponse DuckDuckGoSearch::Search(Page& page, const std::string& query, const SearchOptions& options) {
    auto start_time = std::chrono::steady_clock::now();
    SearchResponse response;
    response.query = query;

    std::string target_url = BuildQueryUrl(query, options);
    auto nav_result = page.Navigate(target_url, options.timeout);

    if (!nav_result.success) {
        response.success = false;
        response.error_message = "Navigation failed to DuckDuckGo search URL: " + target_url;
        response.elapsed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start_time);
        return response;
    }

    // Wait slightly for DOM to settle if needed
    page.Sleep(std::chrono::milliseconds(100));

    response.items = ExtractResultsFromDom(page, options.max_results);
    response.total_results = static_cast<int>(response.items.size());
    response.success = !response.items.empty();
    response.elapsed_time = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start_time);

    return response;
}

} // namespace extensions
} // namespace hyper_vision_agent
