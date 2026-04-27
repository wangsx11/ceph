#pragma once
// Minimal header-only logger. Replace with spdlog later if needed.
#include <cstdio>
#include <cstdarg>
#include <ctime>
#include <mutex>

namespace nr {

enum class LogLevel { DEBUG = 0, INFO = 1, WARN = 2, ERROR = 3 };

class Logger {
public:
    static Logger& instance() { static Logger l; return l; }
    void set_level(LogLevel lv) { level_ = lv; }

    void log(LogLevel lv, const char* file, int line, const char* fmt, ...) {
        if (lv < level_) return;
        std::lock_guard<std::mutex> lk(mu_);
        char   ts[32];
        std::time_t t = std::time(nullptr);
        std::strftime(ts, sizeof(ts), "%F %T", std::localtime(&t));
        static const char* tag[] = {"DEBUG", "INFO ", "WARN ", "ERROR"};
        std::fprintf(stderr, "[%s] [%s] %s:%d ", ts, tag[(int)lv], file, line);
        va_list ap;
        va_start(ap, fmt);
        std::vfprintf(stderr, fmt, ap);
        va_end(ap);
        std::fputc('\n', stderr);
    }
private:
    LogLevel level_ = LogLevel::INFO;
    std::mutex mu_;
};

} // namespace nr

#define NR_LOG(lv, ...) ::nr::Logger::instance().log(lv, __FILE__, __LINE__, __VA_ARGS__)
#define NR_DEBUG(...)   NR_LOG(::nr::LogLevel::DEBUG, __VA_ARGS__)
#define NR_INFO(...)    NR_LOG(::nr::LogLevel::INFO,  __VA_ARGS__)
#define NR_WARN(...)    NR_LOG(::nr::LogLevel::WARN,  __VA_ARGS__)
#define NR_ERROR(...)   NR_LOG(::nr::LogLevel::ERROR, __VA_ARGS__)
