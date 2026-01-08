// webloc2md.cpp (macOS only)
// Recursively scans a directory for .webloc files, parses their URL via CoreFoundation,
// and writes a Markdown tree to LINKS.md in the current working directory.
//
// Build (clang++):
//   clang++ -std=c++17 -Wall -Wextra -O2 webloc2md.cpp -o webloc2md \
//     -framework CoreFoundation
//
// Usage:
//   ./webloc2md [options] /path/to/directory
//
// Options:
//   -o, --output FILE     Write Markdown to FILE (default: LINKS.md)
//   -s, --skip PATTERN    Append an extra glob pattern to skip (can repeat)
//   -i, --include PATTERN Only emit .webloc entries for directories matching globs
//   -d, --max-depth N     Recurse at most N levels deep (0 = root only)
//       --include-empty   Emit empty directories (default: skip them)
//       --no-files        Suppress listing non-.webloc files in a section
//       --no-restrict-names
//                         Allow full Unicode (default restricts to safe ASCII)
//   -h, --help            Show usage information
//
// Output:
//   ./LINKS.md

#include <CoreFoundation/CoreFoundation.h>

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <filesystem>
#include <fnmatch.h>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

static const std::vector<std::string> DEFAULT_SKIP_GLOBS = {
    ".git", "*/.git",
    ".hg", "*/.hg",
    ".svn", "*/.svn",
    ".bzr", "*/.bzr",
    ".idea", "*/.idea",
    ".DS_Store", "*/.DS_Store",
    "__pycache__", "*/__pycache__",
    "node_modules", "*/node_modules"
};

static const std::set<char> RESTRICTED_CHARACTERS = []{
    const char* allowed =
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        "!#$%&()*+,-./:;<=>?@[]^_`{|}~ ";
    std::set<char> s;
    for (const char* p = allowed; *p; ++p) s.insert(*p);
    return s;
}();

static std::string escape_markdown_text(const std::string& s) {
    // Minimal escaping for link text / headers.
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        switch (c) {
            case '\\': out += "\\\\"; break;
            case '[':  out += "\\[";  break;
            case ']':  out += "\\]";  break;
            case '*':  out += "\\*";  break;
            case '_':  out += "\\_";  break;
            case '`':  out += "\\`";  break;
            default:   out += c;      break;
        }
    }
    return out;
}

static std::string filename_stem_no_ext(const fs::path& p) {
    // For "foo.webloc" -> "foo"
    return p.stem().string();
}

static bool has_webloc_ext(const fs::path& p) {
    auto ext = p.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c){ return (char)std::tolower(c); });
    return ext == ".webloc";
}

static std::optional<std::string> cfstring_to_utf8(CFStringRef s) {
    if (!s) return std::nullopt;

    // Fast path if internal rep is UTF-8.
    const char* cstr = CFStringGetCStringPtr(s, kCFStringEncodingUTF8);
    if (cstr) return std::string(cstr);

    // Fallback: allocate buffer.
    CFIndex len = CFStringGetLength(s);
    CFIndex maxSize =
        CFStringGetMaximumSizeForEncoding(len, kCFStringEncodingUTF8) + 1;
    std::string buf((size_t)maxSize, '\0');
    if (CFStringGetCString(s, buf.data(), maxSize, kCFStringEncodingUTF8)) {
        buf.resize(std::char_traits<char>::length(buf.c_str()));
        return buf;
    }
    return std::nullopt;
}

static std::optional<std::string> parse_webloc_url(const fs::path& file) {
    // Read file into memory
    std::error_code ec;
    auto fsize = fs::file_size(file, ec);
    if (ec) return std::nullopt;
    if (fsize == 0) return std::nullopt;
    if (fsize > (uintmax_t)std::numeric_limits<CFIndex>::max()) return std::nullopt;

    std::vector<uint8_t> bytes((size_t)fsize);
    std::ifstream in(file, std::ios::binary);
    if (!in) return std::nullopt;
    in.read(reinterpret_cast<char*>(bytes.data()), (std::streamsize)bytes.size());
    if (!in) return std::nullopt;

    CFDataRef data = CFDataCreate(kCFAllocatorDefault, bytes.data(), (CFIndex)bytes.size());
    if (!data) return std::nullopt;

    CFErrorRef error = nullptr;
    CFPropertyListRef plist =
        CFPropertyListCreateWithData(kCFAllocatorDefault, data,
                                     kCFPropertyListImmutable, nullptr, &error);

    CFRelease(data);

    if (!plist) {
        if (error) CFRelease(error);
        return std::nullopt;
    }

    std::optional<std::string> url;

    if (CFGetTypeID(plist) == CFDictionaryGetTypeID()) {
        auto dict = (CFDictionaryRef)plist;
        CFStringRef key = CFSTR("URL");
        CFTypeRef val = CFDictionaryGetValue(dict, key);
        if (val && CFGetTypeID(val) == CFStringGetTypeID()) {
            url = cfstring_to_utf8((CFStringRef)val);
        }
    }

    CFRelease(plist);
    if (error) CFRelease(error);
    return url;
}

struct LinkItem {
    std::string name;
    std::string url;
};

struct Options {
    fs::path root;
    fs::path output = "LINKS.md";
    std::vector<std::string> skip_patterns;
    std::vector<std::string> include_patterns;
    std::optional<int> max_depth;
    bool include_empty = false;
    bool include_files = true;
    bool restrict_names = true;
};

static void print_usage(const char* prog) {
    std::cerr << "Usage: " << (prog ? prog : "webloc2md")
              << " [options] /path/to/directory\n\n"
              << "Options:\n"
              << "  -o, --output FILE     Write Markdown to FILE (default: LINKS.md)\n"
              << "  -s, --skip PATTERN    Append a glob to skip directories/files (repeatable)\n"
              << "      --skip=PATTERN\n"
              << "  -i, --include PATTERN Only emit entries for directories matching globs\n"
              << "      --include=PATTERN\n"
              << "  -d, --max-depth N     Recurse at most N levels deep (0=root only)\n"
              << "      --max-depth=N\n"
              << "      --include-empty   Emit empty directories (default skips them)\n"
              << "      --no-files        Do not list regular files alongside .webloc links\n"
              << "      --files           Re-enable file listings if disabled earlier\n"
              << "      --no-restrict-names Allow all Unicode characters in names\n"
              << "      --restrict-names  Re-enable ASCII restriction if disabled earlier\n"
              << "  -h, --help            Show this help text\n\n"
              << "Globs are matched against each relative path (e.g. 'docs/private') and"
              << " filename (e.g. '.git').\n"
              << "Default skip globs: .git, .hg, .svn, .bzr, .idea, node_modules\n";
}

static bool matches_glob(const std::string& target, const std::string& pattern) {
    if (pattern.empty()) return false;
    return fnmatch(pattern.c_str(), target.c_str(), 0) == 0;
}

static std::string sanitize_display_text(const std::string& input, bool restrict) {
    if (!restrict) return input;
    std::string out;
    out.reserve(input.size());
    for (char c : input) {
        if (RESTRICTED_CHARACTERS.count(c)) {
            out.push_back(c);
        }
    }
    if (out.empty()) out = "_";
    return out;
}

static std::vector<std::string> make_match_targets(const fs::path& root,
                                                   const fs::path& candidate) {
    std::vector<std::string> targets;
    std::error_code ec;
    fs::path rel = fs::relative(candidate, root, ec);
    if (!ec && rel != ".") {
        targets.push_back(rel.generic_string());
    }
    targets.push_back(candidate.filename().generic_string());
    targets.emplace_back(candidate.generic_string());
    return targets;
}

static bool path_matches_patterns(const std::vector<std::string>& patterns,
                                  const std::vector<std::string>& targets) {
    if (patterns.empty()) return false;
    for (const auto& pat : patterns) {
        for (const auto& t : targets) {
            if (matches_glob(t, pat)) {
                return true;
            }
        }
    }
    return false;
}

static bool should_skip_path(const fs::path& root,
                             const fs::path& candidate,
                             const std::vector<std::string>& patterns) {
    if (patterns.empty()) return false;
    return path_matches_patterns(patterns, make_match_targets(root, candidate));
}

static std::string markdown_header_prefix(int level) {
    if (level < 1) level = 1;
    // cap at 6 to keep it sane
    if (level > 6) level = 6;
    return std::string((size_t)level, '#');
}

static bool write_directory_markdown(std::ostream& out,
                                     const fs::path& root,
                                     const fs::path& dir,
                                     const Options& options,
                                     int depth_from_root = 0) {
    if (dir != root && should_skip_path(root, dir, options.skip_patterns)) {
        return false;
    }

    int headerLevel = 1 + depth_from_root;

    std::string title = (dir == root) ? root.filename().string() : dir.filename().string();
    if (title.empty()) title = dir.string();
    std::string title_text = sanitize_display_text(title, options.restrict_names);

    auto match_targets = make_match_targets(root, dir);
    bool include_here = options.include_patterns.empty() ||
                        path_matches_patterns(options.include_patterns, match_targets);
    bool eligible_for_empty = (dir == root) || include_here || options.include_patterns.empty();

    std::ostringstream buffer;
    bool wrote_header = false;
    auto ensure_header = [&]() {
        if (!wrote_header) {
            buffer << markdown_header_prefix(headerLevel) << " " << escape_markdown_text(title_text) << "\n\n";
            wrote_header = true;
        }
    };

    // Gather .webloc files in this directory
    std::error_code ec;
    std::vector<LinkItem> links;
    std::vector<fs::path> other_files;
    if (include_here) {
        for (const auto& entry : fs::directory_iterator(dir, fs::directory_options::skip_permission_denied, ec)) {
            if (ec) break;
            if (!entry.is_regular_file(ec)) continue;
            if (should_skip_path(root, entry.path(), options.skip_patterns)) continue;
            const auto& p = entry.path();
            if (has_webloc_ext(p)) {
                auto url = parse_webloc_url(p);
                if (!url || url->empty()) continue;

                LinkItem item;
                item.name = sanitize_display_text(filename_stem_no_ext(p), options.restrict_names);
                item.url = *url;
                links.push_back(std::move(item));
            } else if (options.include_files) {
                other_files.push_back(p);
            }
        }
    }

    std::sort(links.begin(), links.end(), [](const LinkItem& a, const LinkItem& b) {
        return a.name < b.name;
    });

    for (const auto& l : links) {
        ensure_header();
        buffer << "- [" << escape_markdown_text(l.name) << "](" << l.url << ")\n";
    }
    if (!links.empty()) buffer << "\n";

    if (!other_files.empty()) {
        std::sort(other_files.begin(), other_files.end(), [](const fs::path& a, const fs::path& b) {
            return a.filename().string() < b.filename().string();
        });
        ensure_header();
        buffer << "**files:**\n";
        for (const auto& file : other_files) {
            std::error_code rel_ec;
            auto rel = fs::relative(file, root, rel_ec);
            std::string target = rel_ec ? file.generic_string() : rel.generic_string();
            std::string fname = sanitize_display_text(file.filename().string(), options.restrict_names);
            buffer << "- [" << escape_markdown_text(fname) << "](<" << target << ">)\n";
        }
        buffer << "\n";
    }

    // Recurse into subdirectories (sorted by name for stable output)
    std::vector<fs::path> subdirs;
    bool can_recurse = !options.max_depth || depth_from_root < *options.max_depth;
    if (can_recurse) {
        ec.clear();
        for (const auto& entry : fs::directory_iterator(dir, fs::directory_options::skip_permission_denied, ec)) {
            if (ec) break;
            if (!entry.is_directory(ec)) continue;
            if (should_skip_path(root, entry.path(), options.skip_patterns)) continue;
            subdirs.push_back(entry.path());
        }
    }

    std::sort(subdirs.begin(), subdirs.end(), [](const fs::path& a, const fs::path& b) {
        return a.filename().string() < b.filename().string();
    });

    for (const auto& sd : subdirs) {
        std::ostringstream child_buffer;
        if (write_directory_markdown(child_buffer, root, sd, options, depth_from_root + 1)) {
            ensure_header();
            buffer << child_buffer.str();
        }
    }

    if (!wrote_header && options.include_empty && eligible_for_empty) {
        ensure_header();
    }

    if (!wrote_header) {
        return false;
    }

    out << buffer.str();
    return true;
}

static bool parse_arguments(int argc, char** argv, Options& options) {
    options.skip_patterns = DEFAULT_SKIP_GLOBS;

    std::vector<std::string> positional;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-h" || arg == "--help") {
            print_usage(argv[0]);
            return false;
        } else if (arg == "-o" || arg == "--output") {
            if (i + 1 >= argc) {
                std::cerr << "Error: missing value for " << arg << "\n";
                return false;
            }
            options.output = argv[++i];
        } else if (arg == "-s" || arg == "--skip") {
            if (i + 1 >= argc) {
                std::cerr << "Error: missing glob for " << arg << "\n";
                return false;
            }
            options.skip_patterns.push_back(argv[++i]);
        } else if (arg.rfind("--skip=", 0) == 0) {
            options.skip_patterns.push_back(arg.substr(std::string("--skip=").size()));
        } else if (arg == "-i" || arg == "--include") {
            if (i + 1 >= argc) {
                std::cerr << "Error: missing glob for " << arg << "\n";
                return false;
            }
            options.include_patterns.push_back(argv[++i]);
        } else if (arg.rfind("--include=", 0) == 0) {
            options.include_patterns.push_back(arg.substr(std::string("--include=").size()));
        } else if (arg == "-d" || arg == "--max-depth") {
            if (i + 1 >= argc) {
                std::cerr << "Error: missing value for " << arg << "\n";
                return false;
            }
            std::string val = argv[++i];
            try {
                long parsed = std::stol(val);
                if (parsed < 0) throw std::out_of_range("negative");
                options.max_depth = static_cast<int>(parsed);
            } catch (const std::exception&) {
                std::cerr << "Error: invalid max depth '" << val << "'\n";
                return false;
            }
        } else if (arg.rfind("--max-depth=", 0) == 0) {
            std::string val = arg.substr(std::string("--max-depth=").size());
            try {
                long parsed = std::stol(val);
                if (parsed < 0) throw std::out_of_range("negative");
                options.max_depth = static_cast<int>(parsed);
            } catch (const std::exception&) {
                std::cerr << "Error: invalid max depth '" << val << "'\n";
                return false;
            }
        } else if (arg == "--include-empty") {
            options.include_empty = true;
        } else if (arg == "--no-files") {
            options.include_files = false;
        } else if (arg == "--files") {
            options.include_files = true;
        } else if (arg == "--restrict-names") {
            options.restrict_names = true;
        } else if (arg == "--no-restrict-names") {
            options.restrict_names = false;
        } else if (!arg.empty() && arg[0] == '-') {
            std::cerr << "Error: unknown option " << arg << "\n";
            return false;
        } else {
            positional.push_back(arg);
        }
    }

    if (positional.size() != 1) {
        print_usage(argv[0]);
        return false;
    }

    options.root = positional.front();
    return true;
}

int main(int argc, char** argv) {
    Options options;
    if (!parse_arguments(argc, argv, options)) {
        return 2;
    }

    std::error_code ec;
    if (!fs::exists(options.root, ec) || ec) {
        std::cerr << "Error: path does not exist: " << options.root << "\n";
        return 1;
    }
    if (!fs::is_directory(options.root, ec) || ec) {
        std::cerr << "Error: path is not a directory: " << options.root << "\n";
        return 1;
    }

    std::ofstream out(options.output, std::ios::binary);
    if (!out) {
        std::cerr << "Error: could not open " << options.output << " for writing.\n";
        return 1;
    }

    write_directory_markdown(out, options.root, options.root, options);

    if (!out) {
        std::cerr << "Error: failed while writing " << options.output << "\n";
        return 1;
    }

    return 0;
}
