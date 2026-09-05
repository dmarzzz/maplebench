"""Combat metrics derived from server events and time-weighted observations."""
from collections import Counter, defaultdict


def summarize_combat(observations, events):
    if not observations:
        return {'combatMetricsAvailable': False}
    start, end = observations[0]['nowMs'], observations[-1]['nowMs']
    if not all(o.get('combatTrace') == 'combat-v1' for o in observations):
        return {'combatMetricsAvailable': False}
    cid = observations[0]['character']['id']
    combo_observed = all('combo' in o['character'] for o in observations)
    buffs_observed = all('skills' in o for o in observations)
    events = [e for e in events if start <= e['tMs'] <= end and e.get('characterId', cid) == cid]
    attacks = [e for e in events if e['kind'] == 'combat_attack']
    hits = [e for e in events if e['kind'] == 'monster_hit']
    incoming = [e for e in events if e['kind'] == 'player_hit']
    actions = [e for e in events if e['kind'] == 'action' and e.get('accepted')]
    targets = Counter(e['attackId'] for e in hits if e.get('attackId', -1) >= 0)
    skill_uses = Counter(str(e['skillId']) for e in events if e['kind'] in ('combat_attack', 'skill_cast'))
    potions = Counter(str(e['action']['itemId']) for e in actions if e['action']['type'] == 'use_item')
    active_ms = defaultdict(float)
    charged_ms = 0
    minimum_hp = 100.0
    max_combo = 0
    observed_ms = 0
    for i, obs in enumerate(observations):
        c = obs['character']
        if c['id'] != cid: continue
        minimum_hp = min(minimum_hp, 100 * c['hp'] / max(1, c['maxHp']))
        combo = c.get('combo', {})
        max_combo = max(max_combo, combo.get('orbs', 0))
        if i + 1 == len(observations): continue
        after = observations[i + 1]
        # Large recording gaps are unknown time, not evidence of continued buff uptime.
        dt = after['nowMs'] - obs['nowMs']
        if after['character']['id'] != cid or dt < 0 or dt > 2000: continue
        observed_ms += dt
        if combo.get('orbs', 0) > 0: charged_ms += dt
        for skill in obs.get('skills', []):
            if skill.get('selfBuff') and skill.get('active'):
                active_ms[str(skill['skillId'])] += min(dt, max(0, skill.get('remainingMs', 0)))
    return {
        'combatMetricsAvailable': True,
        'mechanicsVersion': observations[0].get('mechanicsVersion', 'combat-trace-v1'),
        'monstersKilled': len({(e['mapId'], e['objectId']) for e in hits if e.get('killed')}),
        'damageDealt': sum(max(0, e.get('hpLoss', 0)) for e in hits),
        'damageRolled': sum(sum(max(0, n) for n in e.get('damageLines', [])) for e in hits),
        'overkillDamage': sum(max(0, e.get('damage', 0) - e.get('hpBefore', 0)) for e in hits),
        'incomingDamage': sum(max(0, e.get('damage', 0)) for e in incoming),
        'incomingHits': sum(not e.get('miss', False) for e in incoming),
        'incomingMisses': sum(e.get('miss', False) for e in incoming),
        'knockbacks': sum(bool(e.get('knockback')) for e in incoming),
        'attackCount': len(attacks),
        'averageTargetsPerAttack': sum(targets.get(a['seq'], 0) for a in attacks) / max(1, len(attacks)),
        'minimumHpPercent': round(minimum_hp, 2),
        'maximumComboOrbs': max_combo if combo_observed else None,
        'chargedComboPercent': round(100 * charged_ms / max(1, observed_ms), 2) if combo_observed else None,
        'buffUptimePercent': {sid: round(100 * dt / max(1, observed_ms), 2) for sid, dt in sorted(active_ms.items())} if buffs_observed else None,
        'observationCoveragePercent': round(100 * observed_ms / max(1, end - start), 2),
        'skillUses': dict(sorted(skill_uses.items())),
        'potionsUsed': dict(sorted(potions.items())),
    }
