#include "logger.h"
// Currently the logger is fully header-inlined; this TU exists so that
// the library has at least one object file and can be linked as STATIC.
namespace nr {
void logger_dummy() {}
}
