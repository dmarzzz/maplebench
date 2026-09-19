"""Small public replay timeline, projected only from rechecked private receipts.

Input spans describe relay request through acknowledgment, not measured native
keydown duration. The recording's burned-in key HUD is the visual input record.
"""
import math

CONTROLS = frozenset(('LEFT', 'RIGHT', 'UP', 'DOWN', 'JUMP', 'ATTACK',
    'PRIMARY_SKILL', 'SECONDARY_SKILL', 'BUFF_1', 'BUFF_2', 'HP_POTION',
    'MP_POTION', 'SKILL_5', 'SKILL_6', 'SKILL_7', 'SKILL_8', 'SKILL_9', 'SKILL_10',
    'SKILL_11', 'SKILL_12', 'SKILL_13', 'SKILL_14', 'SKILL_15', 'SKILL_16', 'SKILL_17'))


def finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate_timeline(value):
    """Fail closed on extensions, excessive data, unknown controls, and bad clocks."""
    if not isinstance(value, dict) or set(value) != {
            'schema_version', 'clock', 'input_basis', 'duration_ms',
            'timing_uncertainty_ms', 'api_intervals', 'input_intervals'}:
        raise ValueError('replay_timeline_schema')
    if (type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['clock'] != 'recording_media_ms'
            or value['input_basis'] != 'relay_request_ack_v1'
            or not finite(value['duration_ms'], 1, 335000)
            or not finite(value['timing_uncertainty_ms'], 0, 100)):
        raise ValueError('replay_timeline_clock')
    duration = value['duration_ms']
    for field, maximum, width in (('api_intervals', 64, 3), ('input_intervals', 2400, 5)):
        rows = value[field]
        if rows is None and field == 'input_intervals':
            continue
        if not isinstance(rows, list) or len(rows) > maximum:
            raise ValueError('replay_timeline_rows')
        previous_end = -1
        previous_cycle = -1
        for row in rows:
            if (not isinstance(row, list) or len(row) != width
                    or type(row[0]) is not int or type(row[1]) is not int
                    or not 0 <= row[0] <= row[1] <= duration
                    or row[0] < previous_end
                    or type(row[2]) is not int or not 0 <= row[2] < 64
                    or row[2] < previous_cycle):
                raise ValueError('replay_timeline_interval')
            if field == 'input_intervals':
                keys = row[3]
                if (not isinstance(keys, list) or not 1 <= len(keys) <= 8
                        or any(type(k) is not str or k not in CONTROLS for k in keys)
                        or len(set(keys)) != len(keys)
                        or type(row[4]) is not int or not 1 <= row[4] <= 10000):
                    raise ValueError('replay_timeline_input')
            previous_end, previous_cycle = row[1], row[2]
    return value


def project_timeline(result, recording, checked):
    """Map the adaptive monotonic clock to the encoded recording's media clock."""
    start, end, duration = (recording.get(k) for k in ('start_ms', 'end_ms', 'duration_ms'))
    uncertainty = recording.get('timing_uncertainty_ms')
    adaptive_start = result.get('timeline', {}).get('adaptive_started_ms')
    if (recording.get('timing_method') != 'browser_monotonic_duration_with_measured_clock_offset'
            or not finite(start, -335000, 335000) or not finite(end, 0, 670000)
            or not finite(duration, 1, 335000) or abs(end - start - duration) > 100
            or not finite(uncertainty, 0, 100) or not finite(adaptive_start, 0, 335000)):
        return None
    origin = 0
    if recording.get('capture_duration_policy', {}).get('id') == 'post-render-encoded-frame-v1':
        origin = recording.get('first_frame_offset_ms')
        if not finite(origin, 0, duration):
            return None
    shift = adaptive_start - start - origin
    api = []
    for cycle in result['adaptive']['cycles']:
        timing = cycle.get('timing', {})
        if cycle.get('api_outcome') == 'confirmed':
            begin, finish = timing.get('api_started_ms'), timing.get('api_ended_ms')
            if not finite(begin, 0, 305000) or not finite(finish, begin, 305000):
                return None
            api.append([round(begin + shift), round(finish + shift), cycle['index']])
    inputs = checked.get('input_intervals')
    public_inputs = None if inputs is None else [
        [round(item['requested_ms'] + shift), round(item['acknowledged_ms'] + shift),
         item['cycle_index'], list(item['keys']), item['duration_ms']] for item in inputs]
    value = {'schema_version': 1, 'clock': 'recording_media_ms',
        'input_basis': 'relay_request_ack_v1', 'duration_ms': round(duration - origin),
        'timing_uncertainty_ms': uncertainty, 'api_intervals': api, 'input_intervals': public_inputs}
    try:
        return validate_timeline(value)
    except (ValueError, TypeError):
        return None
