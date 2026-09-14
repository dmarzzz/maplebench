// MapleBench spell range policy, version 1. AGPL-3.0-or-later.
// Spell power and mastery come from the pinned skill definition. Maximum
// base/amp rounding follows the pinned Cosmic parser; mastery is a WZ tier
// (10 = 60%), not a percent or a physical-weapon mastery value.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
namespace jrc {
struct SpellRange { double minimum, maximum; };
inline SpellRange spell_range(int32_t magic, int32_t intelligence,
                             int32_t power, int32_t mastery_tier,
                             int32_t amplification_percent) {
    const double m = std::max(0, magic);
    const double i = std::max(0, intelligence);
    const double mastery = std::min(1.0, std::max(0.1, 0.1 + mastery_tier * 0.05));
    const double maximum = std::ceil((m * m / 1000.0 + m) / 30.0 + i / 200.0);
    const double minimum = std::ceil((m * m / 1000.0 + m * mastery * 0.9) / 30.0 + i / 200.0);
    const double amp = std::max(100, amplification_percent);
    const double spell = std::max(0, power);
    return {std::floor(minimum * amp / 100.0) * spell,
            std::floor(maximum * amp / 100.0) * spell};
}
inline float spell_hit_chance(int32_t intelligence, int32_t luck,
                             int16_t level_delta, int32_t avoid) {
    if (avoid <= 0) return 1.0f;
    const double accuracy = 5.0 * (std::max(0, intelligence) / 10 + std::max(0, luck) / 10);
    if (accuracy <= 0) return 0.01f;
    const double rate = accuracy * 100.0 / (std::max<int16_t>(0, level_delta) * 10.0 + 255.0);
    return static_cast<float>(std::min(1.0, std::max(0.01, (1.2 - avoid / rate) / 0.7)));
}
}
