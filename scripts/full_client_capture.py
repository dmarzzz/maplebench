"""Validate browser capture measurements without treating telemetry as review."""
import math
import re


def number(value, minimum=0, maximum=2**53-1):
    return type(value) in (int,float) and math.isfinite(value) and minimum <= value <= maximum


def capture_receipt(value, owner, anchor, clock, terminal):
    required={'schema_version','run_id','client_id','start_wall_ms','end_wall_ms','duration_ms',
              'first_frame_wall_ms','last_frame_wall_ms','rendered_frames','max_frame_gap_ms',
              'hidden','errors','relay_lost','interrupted','clock','terminal_token'}
    if not isinstance(value,dict) or set(value)!=required or type(value['schema_version']) is not int or value['schema_version']!=1:
        raise ValueError('invalid_capture_metadata')
    if value['run_id']!=owner['id'] or value['client_id']!=owner['client']:
        raise ValueError('capture_identity_mismatch')
    for key in ('start_wall_ms','end_wall_ms'):
        if not number(value[key]): raise ValueError('invalid_capture_timestamp')
    if (not number(value['duration_ms'],1,125000) or not number(value['max_frame_gap_ms'],0,125000)
            or type(value['rendered_frames']) is not int or not 0 <= value['rendered_frames'] <= 100000
            or type(value['errors']) is not int or not 0 <= value['errors'] <= 100000
            or any(type(value[key]) is not bool for key in ('hidden','relay_lost','interrupted'))):
        raise ValueError('invalid_capture_measurement')
    start,end=value['start_wall_ms'],value['end_wall_ms']
    if end<start:
        raise ValueError('invalid_capture_frame_order')
    if value['rendered_frames'] and (not number(value['first_frame_wall_ms']) or not number(value['last_frame_wall_ms'])
            or not start <= value['first_frame_wall_ms'] <= value['last_frame_wall_ms'] <= end):
        raise ValueError('invalid_capture_frame_order')
    if not value['rendered_frames'] and (value['first_frame_wall_ms'] is not None or value['last_frame_wall_ms'] is not None):
        raise ValueError('invalid_capture_frame_order')
    if value['terminal_token'] is not None and (not isinstance(value['terminal_token'],str)
            or not re.fullmatch('[a-f0-9]{32}',value['terminal_token'])):
        raise ValueError('invalid_capture_terminal_identity')
    wall_drift=abs(end-start-value['duration_ms'])
    interrupted=(value['interrupted'] or value['hidden'] or value['relay_lost'] or value['errors']>0
                 or value['max_frame_gap_ms']>1000 or wall_drift>100 or value['rendered_frames']==0)
    base={'duration_ms':value['duration_ms'],'wall_clock_drift_ms':wall_drift,
          'post_render_capture':value['rendered_frames']>0,'rendered_frames':value['rendered_frames'],
          'max_frame_gap_ms':value['max_frame_gap_ms']}
    sync=value['clock']
    fields={'id','client_sent_ms','client_received_ms','server_received_ms','server_sent_ms'}
    if sync is None:
        # Save a failed capture without manufacturing synchronization or coverage.
        return base|{'start_ms':None,'end_ms':None,'interrupted':True,
                     'timing_method':'unavailable','timing_uncertainty_ms':None}
    if not isinstance(sync,dict) or set(sync)!=fields or not isinstance(clock,dict):
        raise ValueError('capture_clock_unavailable')
    if any(sync.get(key)!=clock.get(key) for key in fields-{'client_received_ms'}):
        raise ValueError('capture_clock_receipt_mismatch')
    if not number(sync['client_received_ms']) or not sync['client_sent_ms'] <= sync['client_received_ms'] <= end:
        raise ValueError('invalid_capture_clock')
    lower=sync['server_sent_ms']-sync['client_received_ms']
    upper=sync['server_received_ms']-sync['client_sent_ms']
    if upper < lower or upper-lower > 5000:
        raise ValueError('capture_clock_uncertainty_too_large')
    if not isinstance(anchor,dict) or anchor.get('runId')!=owner['id']:
        interrupted=True
    terminal_matches=(isinstance(terminal,dict) and terminal.get('id')==value['terminal_token'])
    if not terminal_matches: interrupted=True
    midpoint=(lower+upper)/2
    origin=owner['startedAtMs']
    # Point estimates remain explicitly accompanied by their measured interval.
    # Causal server receipts independently establish first-frame-before-input and
    # terminal-observed-before-stop; neither makes this a visual review.
    return base|{'start_ms':start+midpoint-origin,'end_ms':end+midpoint-origin,
            'duration_ms':value['duration_ms'],'interrupted':interrupted,
            'timing_method':'browser_monotonic_duration_with_measured_clock_offset',
            'clock_offset_ms':{'lower':lower,'upper':upper},
            'timing_uncertainty_ms':(upper-lower)/2,'wall_clock_drift_ms':wall_drift,
            'capture_ready_at_ms':anchor['serverReceivedAtMs'] if anchor else None,
            'terminal_observed_after_ms':terminal['serverIssuedAtMs'] if terminal_matches else None,
            'post_render_capture':True,'rendered_frames':value['rendered_frames'],
            'max_frame_gap_ms':value['max_frame_gap_ms']}
