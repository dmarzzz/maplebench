#pragma once
#include <cstdint>
#include <limits>

namespace jrc {
// Soul Arrow substitutes ammunition only for bows and crossbows. It does not
// grant a skill, bypass MP/weapon/job checks, or apply to claws and guns.
inline uint16_t effective_ammunition(uint16_t inventory_count, bool bow_weapon,
                                      bool soul_arrow) {
    return bow_weapon && soul_arrow ? std::numeric_limits<uint16_t>::max()
                                    : inventory_count;
}
inline bool has_ranged_projectile(bool inventory_projectile, bool bow_weapon,
                                  bool soul_arrow) {
    return inventory_projectile || (bow_weapon && soul_arrow);
}
}
