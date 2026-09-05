#pragma once
#include <cstdlib>
#include <string>
#ifdef MS_PLATFORM_WASM
#include <emscripten.h>
#endif

namespace jrc::demo_login
{
    inline bool take(const char* step)
    {
#ifdef MS_PLATFORM_WASM
        return EM_ASM_INT({
            const session = Module.MapleBenchSession;
            if (!session || !session.enabled) return 0;
            const key = "sent_" + UTF8ToString($0);
            if (session[key]) return 0;
            session[key] = true;
            return 1;
        }, step) != 0;
#else
        (void)step;
        return false;
#endif
    }

    inline std::string value(const char* key)
    {
#ifdef MS_PLATFORM_WASM
        auto* result = reinterpret_cast<char*>(EM_ASM_PTR({
            const value = Module.MapleBenchSession[UTF8ToString($0)] || "";
            const length = lengthBytesUTF8(value) + 1;
            const result = _malloc(length);
            stringToUTF8(value, result, length);
            return result;
        }, key));
        std::string text(result);
        std::free(result);
        return text;
#else
        (void)key;
        return {};
#endif
    }
}
