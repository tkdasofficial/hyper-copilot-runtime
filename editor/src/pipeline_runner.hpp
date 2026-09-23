#pragma once

#include <string>
#include <vector>

namespace hyper {

struct PipelineConfig {
    std::string video_id;
    std::string user_id = "user";
    std::string prompt;
    std::string negative_prompt;
    std::string category = "Documentary";
    std::string visual_style = "Cinematic";
    std::string mode = "long"; // "long" or "short"
    std::string aspect_ratio = "16:9";
    std::string resolution = "1080p";
    int fps = 60;
    int duration_seconds = 60;
    std::string voice_gender = "male";
    bool bgm = true;
    bool captions = true;
    std::string caption_style = "Dynamic";
    std::string caption_size = "Medium";
    std::string output_path = "out.mp4";

    // API Keys & endpoints
    std::string supabase_url;
    std::string supabase_service_role_key;
    std::string pexels_api_key;
    std::string pixabay_api_key;
};

class PipelineRunner {
public:
    static PipelineConfig parseEnvAndArgs(int argc, char* argv[]);
    static int run(const PipelineConfig& config);
    static void updateSupabase(
        const PipelineConfig& config,
        int progress,
        const std::string& step,
        const std::string& status = "processing"
    );
};

} // namespace hyper
