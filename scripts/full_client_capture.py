"""Validate browser capture measurements without treating telemetry as review."""
import math
import re
import json


# Opt-in only, frozen in adaptive_protocol before dispatch. Recorder callbacks
# and decoded PTS have different endpoints; post-render offsets bound the gap.
CAPTURE_DURATION_POLICY = {'id':'post-render-frame-envelope-v1',
    'max_endpoint_gap_ms':250,'max_wall_drift_ms':5,'timestamp_slack_ms':2,
    'max_initial_frames':1}


def validate_duration_policy(value):
    if json.dumps(value,sort_keys=True,allow_nan=False)!=json.dumps(CAPTURE_DURATION_POLICY,sort_keys=True):
        raise ValueError('invalid_capture_duration_policy')
    return dict(CAPTURE_DURATION_POLICY)


def verify_video_duration(probe, recording, policy=None):
    """Compare saved presentation endpoints to independently measured frames."""
    if policy is None:
        if (not number(recording.get('duration_ms'),1,335000)
                or not number(probe.get('duration_ms'),1,335000)
                or abs(probe['duration_ms']-recording['duration_ms'])>100
                or 'capture_duration_policy' in recording):
            raise ValueError('recording_duration_mismatch')
        return
    policy=validate_duration_policy(policy)
    if validate_duration_policy(recording.get('capture_duration_policy'))!=policy:
        raise ValueError('capture_duration_policy_mismatch')
    duration=recording.get('duration_ms');first=recording.get('first_frame_offset_ms');last=recording.get('last_frame_offset_ms')
    span=probe.get('presentation_span_ms');extent=probe.get('presentation_extent_ms');tail=probe.get('last_packet_duration_ms')
    rendered=recording.get('rendered_frames');decoded=probe.get('frames');slack=policy['timestamp_slack_ms']
    if (not number(duration,1,335000) or not number(first,0,duration) or not number(last,first,duration)
            or first>policy['max_endpoint_gap_ms'] or duration-last>policy['max_endpoint_gap_ms']
            or not number(recording.get('wall_clock_drift_ms'),0,policy['max_wall_drift_ms'])
            or recording.get('interrupted') is not False or recording.get('post_render_capture') is not True
            or type(rendered) is not int or rendered<2 or type(decoded) is not int
            or not rendered<=decoded<=rendered+policy['max_initial_frames']
            or not number(span,1,335000) or not number(extent,span,335000)
            or not number(tail,0,policy['max_endpoint_gap_ms'])
            or not number(probe.get('duration_ms'),1,335000) or abs(probe['duration_ms']-extent)>100
            or abs(extent-span-tail)>0.000001
            or not last-first-slack<=span<=last+slack):
        raise ValueError('recording_frame_envelope_mismatch')


def number(value, minimum=0, maximum=2**53-1):
    return type(value) in (int,float) and math.isfinite(value) and minimum <= value <= maximum


def capture_receipt(value, owner, anchor, clock, terminal):
    policy=owner.get('adaptiveProtocol',{}).get('capture_duration_policy')
    if policy is not None:
        policy=validate_duration_policy(policy)
        if owner.get('protocol')!='full-client-adaptive-pilot-v1':raise ValueError('invalid_capture_duration_policy')
    required={'schema_version','run_id','client_id','start_wall_ms','end_wall_ms','duration_ms',
              'first_frame_wall_ms','last_frame_wall_ms','rendered_frames','max_frame_gap_ms',
              'hidden','errors','relay_lost','interrupted','clock','terminal_token'}
    if policy is not None:required|={'capture_duration_policy','first_frame_offset_ms','last_frame_offset_ms'}
    if not isinstance(value,dict) or set(value)!=required or type(value['schema_version']) is not int or value['schema_version']!=(2 if policy else 1):
        raise ValueError('invalid_capture_metadata')
    if value['run_id']!=owner['id'] or value['client_id']!=owner['client']:
        raise ValueError('capture_identity_mismatch')
    for key in ('start_wall_ms','end_wall_ms'):
        if not number(value[key]): raise ValueError('invalid_capture_timestamp')
    maximum=335000 if owner.get('protocol')=='full-client-adaptive-pilot-v1' else 125000
    if (not number(value['duration_ms'],1,maximum) or not number(value['max_frame_gap_ms'],0,maximum)
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
    if policy:
        if validate_duration_policy(value['capture_duration_policy'])!=policy:raise ValueError('capture_duration_policy_mismatch')
        first,last=value['first_frame_offset_ms'],value['last_frame_offset_ms']
        if value['rendered_frames']:
            if not number(first,0,value['duration_ms']) or not number(last,first,value['duration_ms']):
                raise ValueError('invalid_capture_frame_order')
            slack=policy['timestamp_slack_ms']
            if (abs(value['first_frame_wall_ms']-start-first)>wall_drift+slack
                    or abs(value['last_frame_wall_ms']-start-last)>wall_drift+slack
                    or max(first,value['duration_ms']-last)>value['max_frame_gap_ms']+slack):
                raise ValueError('capture_frame_clock_mismatch')
            interrupted|=max(first,value['duration_ms']-last)>policy['max_endpoint_gap_ms']
        elif first is not None or last is not None:raise ValueError('invalid_capture_frame_order')
        interrupted|=wall_drift>policy['max_wall_drift_ms']
        base|={'capture_duration_policy':policy,'first_frame_offset_ms':first,'last_frame_offset_ms':last}
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
