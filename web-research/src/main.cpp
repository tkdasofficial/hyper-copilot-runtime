#include "hyper_vision_agent/engine.hpp"
#include "screen_recorder/screen_recorder.hpp"
#include "screenshot/screenshot.hpp"
#include "anti_bot_stealth/stealth.hpp"
#include "anti_bot_stealth/captcha_solver.hpp"
#include "duckduckgo_search/ddg_search.hpp"
#include <iostream>
#include <fstream>
#include <sstream>
#include <csignal>
#include <chrono>
#include <iomanip>
#include <filesystem>

namespace fs = std::filesystem;
using namespace hyper_vision_agent;

static std::shared_ptr<BrowserSession> g_active_session = nullptr;

void SignalHandler(int signum) {
    std::cout << "\n[Hyper Vision Native C++ Engine] Caught signal " << signum << ", shutting down gracefully...\n";
    if (g_active_session) {
        g_active_session->Close();
    }
    Engine::Instance().Shutdown();
    std::exit(0);
}

void PrintBanner() {
    std::cout << "==================================================================\n";
    std::cout << "  " << Engine::GetEngineBrand() << " (C++17 Heavy Engine v" << Engine::GetVersion() << ")\n";
    std::cout << "  Native C++ Stateless Chromium CDP Heavy Web Research Engine\n";
    std::cout << "==================================================================\n";
}

// Escape string for JSON
std::string EscapeJson(const std::string& s) {
    std::ostringstream o;
    for (char c : s) {
        switch (c) {
            case '"': o << "\\\""; break;
            case '\\': o << "\\\\"; break;
            case '\b': o << "\\b"; break;
            case '\f': o << "\\f"; break;
            case '\n': o << "\\n"; break;
            case '\r': o << "\\r"; break;
            case '\t': o << "\\t"; break;
            default:
                if ('\x00' <= c && c <= '\x1f') {
                    o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << (int)c;
                } else {
                    o << c;
                }
        }
    }
    return o.str();
}

int RunHeavyFetch(const std::string& target_url, const std::string& output_dir = "research_output") {
    std::cout << "[NATIVE C++ ENGINE] Initiating Heavy Data Fetch for: " << target_url << "\n";
    fs::create_directories(output_dir);

    auto& engine = Engine::Instance();
    engine.Initialize();

    LaunchConfig config;
    config.headless = true;
    config.no_sandbox = true;
    config.disable_gpu = true;

    auto session = engine.Launch(config);
    g_active_session = session;

    auto page = session->NewPage("about:blank");

    // Apply Native C++ Stealth
    extensions::StealthConfig stealth_cfg;
    stealth_cfg.hide_webdriver = true;
    stealth_cfg.mock_chrome_runtime = true;
    stealth_cfg.languages = {"en-US", "en"};
    extensions::Stealth::Apply(*page, stealth_cfg);

    std::cout << "[NATIVE C++ ENGINE] Navigating to target URL via CDP...\n";
    auto t0 = std::chrono::steady_clock::now();
    auto nav_res = page->Navigate(target_url);
    auto t1 = std::chrono::steady_clock::now();
    double nav_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

    std::string title = page->GetTitle();
    std::cout << "  -> Loaded in " << nav_ms << " ms. Page Title: " << title << "\n";

    // Extract rich DOM metadata using native JS evaluation
    std::string meta_js = R"JS(
        JSON.stringify({
            metaDescription: document.querySelector('meta[name="description"]')?.content || '',
            ogTitle: document.querySelector('meta[property="og:title"]')?.content || '',
            ogDescription: document.querySelector('meta[property="og:description"]')?.content || '',
            keywords: document.querySelector('meta[name="keywords"]')?.content || '',
            canonicalUrl: document.querySelector('link[rel="canonical"]')?.href || location.href,
            h1List: Array.from(document.querySelectorAll('h1')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 10),
            h2List: Array.from(document.querySelectorAll('h2')).map(e => e.innerText.trim()).filter(Boolean).slice(0, 15),
            textSnippet: (document.body ? document.body.innerText.replace(/\s+/g, ' ').trim().slice(0, 8000) : ''),
            linkCount: document.querySelectorAll('a[href]').length
        })
    )JS";

    auto eval_meta = page->EvaluateScript(meta_js);

    // Capture Full Page or Viewport Screenshot
    std::string shot_path = output_dir + "/heavy_fetch_screenshot.png";
    extensions::ScreenshotOptions shot_opt;
    shot_opt.format = extensions::ImageFormat::PNG;
    shot_opt.output_path = shot_path;
    auto shot_res = extensions::Screenshot::CaptureViewport(*page, shot_opt);
    if (shot_res.success) {
        extensions::Screenshot::SaveToFile(shot_res, shot_path);
        std::cout << "  -> High-resolution screenshot captured: " << shot_path 
                  << " (" << shot_res.binary_data.size() << " bytes)\n";
    }

    // Save structured report
    std::string report_json_path = output_dir + "/research_report.json";
    std::ofstream json_out(report_json_path);
    json_out << "{\n"
             << "  \"target_url\": \"" << EscapeJson(target_url) << "\",\n"
             << "  \"title\": \"" << EscapeJson(title) << "\",\n"
             << "  \"elapsed_ms\": " << nav_ms << ",\n"
             << "  \"screenshot_path\": \"" << EscapeJson(shot_path) << "\",\n"
             << "  \"metadata\": " << (eval_meta.value_string.empty() ? "{}" : eval_meta.value_string) << "\n"
             << "}\n";
    json_out.close();

    std::string report_md_path = output_dir + "/research_report.md";
    std::ofstream md_out(report_md_path);
    md_out << "# Heavy Web Research Dossier\n\n"
           << "- **Target URL**: " << target_url << "\n"
           << "- **Page Title**: " << title << "\n"
           << "- **Fetch Latency**: " << nav_ms << " ms\n"
           << "- **Engine**: Native C++17 Headless Browser Engine\n\n"
           << "## Page Metadata & Snapshot\n"
           << "Screenshot captured at `" << shot_path << "`\n\n"
           << "## Raw Content Extraction\n"
           << "```json\n" << (eval_meta.value_string.empty() ? "{}" : eval_meta.value_string) << "\n```\n";
    md_out.close();

    std::cout << "[NATIVE C++ ENGINE] Heavy Fetch Complete!\n"
              << "  -> Report: " << report_md_path << "\n"
              << "  -> Data:   " << report_json_path << "\n";

    session->Close();
    g_active_session = nullptr;
    return 0;
}

int RunHeavyResearch(const std::string& query, const std::string& output_dir = "research_output") {
    std::cout << "[NATIVE C++ ENGINE] Initiating Heavy Web Research for Query: '" << query << "'\n";
    fs::create_directories(output_dir);

    auto& engine = Engine::Instance();
    engine.Initialize();

    LaunchConfig config;
    config.headless = true;
    config.no_sandbox = true;
    config.disable_gpu = true;

    auto session = engine.Launch(config);
    g_active_session = session;

    auto page = session->NewPage("about:blank");

    // Apply Stealth
    extensions::StealthConfig stealth_cfg;
    stealth_cfg.hide_webdriver = true;
    stealth_cfg.mock_chrome_runtime = true;
    extensions::Stealth::Apply(*page, stealth_cfg);

    // Search via DuckDuckGo
    extensions::SearchOptions s_opts;
    s_opts.max_results = 10;
    auto search_res = extensions::DuckDuckGoSearch::Search(*page, query, s_opts);

    std::cout << "[NATIVE C++ ENGINE] Search query returned " << search_res.items.size() 
              << " results in " << search_res.elapsed_time.count() << " ms\n";

    // Capture Search Page Screenshot
    std::string shot_path = output_dir + "/search_serp_screenshot.png";
    extensions::ScreenshotOptions shot_opt;
    shot_opt.format = extensions::ImageFormat::PNG;
    shot_opt.output_path = shot_path;
    auto serp_shot = extensions::Screenshot::CaptureViewport(*page, shot_opt);
    if (serp_shot.success) {
        extensions::Screenshot::SaveToFile(serp_shot, shot_path);
    }

    // Write JSON and Markdown
    std::string report_json_path = output_dir + "/research_report.json";
    std::ofstream json_out(report_json_path);
    json_out << "{\n"
             << "  \"query\": \"" << EscapeJson(query) << "\",\n"
             << "  \"total_results\": " << search_res.items.size() << ",\n"
             << "  \"elapsed_ms\": " << search_res.elapsed_time.count() << ",\n"
             << "  \"items\": [\n";
    for (size_t i = 0; i < search_res.items.size(); ++i) {
        const auto& it = search_res.items[i];
        json_out << "    {\n"
                 << "      \"position\": " << it.position << ",\n"
                 << "      \"title\": \"" << EscapeJson(it.title) << "\",\n"
                 << "      \"url\": \"" << EscapeJson(it.url) << "\",\n"
                 << "      \"snippet\": \"" << EscapeJson(it.snippet) << "\"\n"
                 << "    }" << (i + 1 < search_res.items.size() ? "," : "") << "\n";
    }
    json_out << "  ]\n}\n";
    json_out.close();

    std::string report_md_path = output_dir + "/research_report.md";
    std::ofstream md_out(report_md_path);
    md_out << "# Heavy Web Research Dossier\n\n"
           << "- **Query**: " << query << "\n"
           << "- **Total Items Discovered**: " << search_res.items.size() << "\n"
           << "- **Elapsed Time**: " << search_res.elapsed_time.count() << " ms\n"
           << "- **Engine**: Native C++17 Headless Browser Runtime\n\n"
           << "## Top Findings\n\n";

    for (const auto& it : search_res.items) {
        md_out << "### " << it.position << ". " << it.title << "\n"
               << "- **URL**: " << it.url << "\n"
               << "- **Snippet**: " << it.snippet << "\n\n";
    }
    md_out.close();

    std::cout << "[NATIVE C++ ENGINE] Heavy Research Completed Successfully!\n"
              << "  -> Report: " << report_md_path << "\n"
              << "  -> Data:   " << report_json_path << "\n";

    session->Close();
    g_active_session = nullptr;
    return 0;
}

int RunSelfTests() {
    std::cout << "[TEST] Initializing Hyper Vision Agent Engine...\n";
    auto& engine = Engine::Instance();
    engine.Initialize();

    std::cout << "[TEST] 1. Launching isolated headless Chromium process...\n";
    auto start_time = std::chrono::steady_clock::now();
        
    LaunchConfig config;
    config.headless = true;
    config.no_sandbox = true;
    config.disable_gpu = true;
        
    std::shared_ptr<BrowserSession> session;
    try {
        session = engine.Launch(config);
        g_active_session = session;
    } catch (const std::exception& e) {
        std::cerr << "[ERROR] Failed to launch session: " << e.what() << "\n";
        return 1;
    }

    auto launch_dur = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start_time);
    std::cout << "  -> Launched in " << launch_dur.count() << " ms (PID: " 
              << session->GetProcessId() << ", Port: " << session->GetPort() << ")\n";

    std::cout << "[TEST] 2. Querying Browser Version via CDP...\n";
    std::string version = session->GetBrowserVersion();
    std::cout << "  -> Target Browser: " << version << "\n";

    std::cout << "[TEST] 3. Creating Isolated Page Target...\n";
    auto page = session->NewPage("about:blank");
    std::cout << "  -> Page Target ID: " << page->GetTargetId() << "\n";
    std::cout << "  -> Session ID: " << page->GetSessionId() << "\n";

    std::cout << "[TEST] 4. Script Evaluation (Runtime.evaluate)...\n";
    auto eval_res = page->EvaluateScript("2 + 2");
    std::cout << "  -> '2 + 2' => Result: " << eval_res.value_number 
              << " (" << (eval_res.value_number == 4 ? "PASS" : "FAIL") << ")\n";

    session->Close();
    g_active_session = nullptr;
    return 0;
}

int main(int argc, char* argv[]) {
    std::signal(SIGINT, SignalHandler);
    std::signal(SIGTERM, SignalHandler);

    PrintBanner();

    std::string mode = "--test";
    if (argc > 1) {
        mode = argv[1];
    }

    if (mode == "--fetch" || mode == "--heavy-fetch" || mode == "--url") {
        if (argc < 3) {
            std::cerr << "Usage: hyper_vision_agent_engine --fetch <url> [output_dir]\n";
            return 1;
        }
        std::string out_dir = (argc > 3 ? argv[3] : "research_output");
        return RunHeavyFetch(argv[2], out_dir);
    } else if (mode == "--research" || mode == "--query" || mode == "--search") {
        if (argc < 3) {
            std::cerr << "Usage: hyper_vision_agent_engine --research <query> [output_dir]\n";
            return 1;
        }
        std::string out_dir = (argc > 3 ? argv[3] : "research_output");
        return RunHeavyResearch(argv[2], out_dir);
    } else if (mode == "--benchmark") {
        return RunSelfTests();
    } else if (mode == "--navigate" && argc > 2) {
        auto session = Engine::Instance().Launch();
        auto page = session->NewPage(argv[2]);
        std::cout << "Title: " << page->GetTitle() << "\n";
        session->Close();
        return 0;
    }

    return RunSelfTests();
}
