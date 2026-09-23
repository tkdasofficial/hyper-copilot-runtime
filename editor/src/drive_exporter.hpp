#pragma once

#include <string>

namespace hyper {

struct DriveExportResult {
    bool success = false;
    std::string file_id;
    std::string direct_download_url;
    std::string drive_url;
    std::string error_message;
};

class DriveExporter {
public:
    static DriveExportResult exportFile(
        const std::string& filePath,
        const std::string& videoId,
        const std::string& title,
        const std::string& targetFolderId = ""
    );

    static bool updateSupabaseDriveMeta(
        const std::string& supabaseUrl,
        const std::string& serviceRoleKey,
        const std::string& videoId,
        const DriveExportResult& result,
        const std::string& title
    );
};

} // namespace hyper
