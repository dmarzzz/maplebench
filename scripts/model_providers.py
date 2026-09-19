"""Frozen native API contracts for model-authored MapleBench programs.

This module performs no I/O, discovers no credentials, and never retries or
repairs an answer. Raw native requests/responses remain the evidence source;
normalized usage exists only to apply the same aggregate token limits.

Native contract references (checked 2026-09-19):
https://platform.claude.com/docs/en/api/messages/create
https://platform.claude.com/docs/en/build-with-claude/structured-outputs
https://platform.claude.com/docs/en/build-with-claude/prompt-caching
"""
import hashlib
import json
import re


OPENAI_MODELS = ('gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna')
ANTHROPIC_MODELS = ('claude-opus-5', 'claude-sonnet-5')
MODELS = OPENAI_MODELS + ANTHROPIC_MODELS
ENDPOINTS = {'openai': 'https://api.openai.com/v1/responses',
             'anthropic': 'https://api.anthropic.com/v1/messages'}
ANTHROPIC_VERSION = '2023-06-01'
SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'note': {'type': 'string'}, 'code': {'type': 'string'}},
    'required': ['note', 'code'],
}


def provider_for_model(model):
    if model in OPENAI_MODELS:
        return 'openai'
    if model in ANTHROPIC_MODELS:
        return 'anthropic'
    raise ValueError('unsupported_model')


def endpoint_for_model(model):
    return ENDPOINTS[provider_for_model(model)]


def request_headers(url, key=None):
    """Transport-only headers; callers never persist this value as evidence."""
    headers = {'Content-Type': 'application/json'}
    if url == ENDPOINTS['anthropic']:
        headers['anthropic-version'] = ANTHROPIC_VERSION
        if key:
            headers['x-api-key'] = key
    elif key:
        # Keep the generic localhost HTTP helper's existing Bearer contract.
        headers['Authorization'] = 'Bearer ' + key
    return headers


def program_request(model, instructions, input_value, output_tokens):
    provider = provider_for_model(model)
    if type(instructions) is not str or not instructions or type(output_tokens) is not int or output_tokens <= 0:
        raise ValueError('invalid_program_request')
    value = json.dumps(input_value, allow_nan=False)
    # Copy so a caller cannot mutate the process-wide frozen schema.
    schema = json.loads(json.dumps(SCHEMA))
    if provider == 'openai':
        # Preserve the original Responses API contract byte-for-byte in JSON.
        body = {'model': model, 'store': False, 'reasoning': {'effort': 'low'},
                'instructions': instructions, 'input': value, 'max_output_tokens': output_tokens,
                'text': {'format': {'type': 'json_schema', 'name': 'maple_program',
                                    'strict': True, 'schema': schema}}}
    else:
        # Native Messages API, without SDK retries, tool use, or prompt caching.
        body = {'model': model, 'system': instructions,
                'messages': [{'role': 'user', 'content': value}], 'max_tokens': output_tokens,
                'thinking': {'type': 'adaptive'},
                'output_config': {'effort': 'low', 'format': {'type': 'json_schema', 'schema': schema}}}
    return ENDPOINTS[provider], body


def request_input(model, body):
    """Return the exact model-visible input string for independent verification."""
    if provider_for_model(model) == 'openai':
        return body['input']
    messages = body.get('messages')
    if (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict)
            or set(messages[0]) != {'role', 'content'} or messages[0]['role'] != 'user'
            or type(messages[0]['content']) is not str):
        raise ValueError('invalid_provider_input')
    return messages[0]['content']


def request_token_upper_bound(model, body):
    """Conservative UTF-8/schema reservation, not a tokenizer guarantee."""
    if provider_for_model(model) == 'openai':
        instructions, schema, maximum = body['instructions'], body['text']['format']['schema'], body['max_output_tokens']
    else:
        instructions, schema, maximum = body['system'], body['output_config']['format']['schema'], body['max_tokens']
    return len(instructions.encode()) + len(request_input(model, body).encode()) + len(json.dumps(schema).encode()) + 1024 + maximum


def _identity(run_id, cycle_index):
    if (type(run_id) is not str or not re.fullmatch('[a-f0-9]{32}', run_id)
            or cycle_index is not None and (type(cycle_index) is not int or not 0 <= cycle_index < 16)):
        raise ValueError('invalid_provider_identity')
    value = {'maplebench_run_id': run_id}
    if cycle_index is not None:
        value['maplebench_cycle_index'] = str(cycle_index)
    return value


def bind_request_identity(model, body, run_id, cycle_index=None):
    identity = _identity(run_id, cycle_index)
    if body.get('model') != model or 'metadata' in body:
        raise ValueError('invalid_provider_request_identity')
    if provider_for_model(model) == 'anthropic':
        # Anthropic only accepts user_id. It does not echo this in the response.
        identity = {'user_id': 'maplebench:' + run_id + (':' + str(cycle_index) if cycle_index is not None else '')}
    return body | {'metadata': identity}


def response_identity_matches(model, response, run_id, cycle_index=None):
    identity = _identity(run_id, cycle_index)
    if not isinstance(response, dict):
        return False
    if provider_for_model(model) == 'openai':
        return response.get('metadata') == identity
    return (response.get('type') == 'message' and response.get('role') == 'assistant'
            and response.get('model') == model and type(response.get('id')) is str
            and re.fullmatch(r'msg_[A-Za-z0-9_-]{1,196}', response['id']) is not None)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def exchange_receipt(model, request, response, run_id, cycle_index=None):
    """Local collector binding, explicitly not an Anthropic metadata echo.

    Canonical digests supplement the exact artifact-byte hashes held by each
    cycle. Recomputing this receipt verifies consistency, not host authenticity.
    """
    _identity(run_id, cycle_index)
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise ValueError('invalid_provider_exchange')
    return {'schema_version': 1, 'source': 'trusted-provider-exchange',
            'identity_binding': 'local-request-response', 'provider': provider_for_model(model),
            'endpoint': endpoint_for_model(model), 'requested_model': model,
            'returned_model': response.get('model'), 'response_id': response.get('id'),
            'run_id': run_id, 'cycle_index': cycle_index,
            'request_sha256': _digest(request), 'response_sha256': _digest(response)}


def _strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_program_key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('nonfinite_program_value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _program(text):
    try:
        choice = _strict_json(text)
        if (type(choice) is not dict or set(choice) != {'note', 'code'}
                or type(choice['note']) is not str or type(choice['code']) is not str
                or not 0 < len(choice['code']) <= 12000 or len(choice['note']) > 2000):
            return None
        # Reject unpaired surrogates before program persistence/execution.
        choice['note'].encode(); choice['code'].encode()
        return choice
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None


def _anthropic_usage(usage):
    if not isinstance(usage, dict):
        return None
    counts = [usage.get('input_tokens'), usage.get('output_tokens'),
              usage.get('cache_creation_input_tokens', 0), usage.get('cache_read_input_tokens', 0)]
    if not all(type(n) is int and 0 <= n <= 2**53 - 1 for n in counts):
        return None
    # input_tokens alone excludes cache writes/reads in the Messages API.
    inputs = counts[0] + counts[2] + counts[3]
    return {'input_tokens': inputs, 'output_tokens': counts[1], 'total_tokens': inputs + counts[1]}


def parse_program_response(model, response):
    """Return strict program or None plus attributed, normalized API metadata."""
    provider = provider_for_model(model)
    if not isinstance(response, dict):
        response = {}
    if provider == 'openai':
        meta = {key: response.get(key) for key in ('id', 'model', 'usage', 'service_tier', 'status')}
        if response.get('status') != 'completed' or response.get('model') != model:
            return None, meta
        output = response.get('output', [])
        if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
            return None, meta
        parts = []
        for item in output:
            if item.get('type') != 'message':
                continue
            content = item.get('content', [])
            if not isinstance(content, list) or not all(isinstance(part, dict) for part in content):
                return None, meta
            for part in content:
                if part.get('type') == 'refusal':
                    return None, meta
                if part.get('type') == 'output_text':
                    if type(part.get('text')) is not str:
                        return None, meta
                    parts.append(part['text'])
        return _program(''.join(parts)), meta
    usage = response.get('usage')
    stop = response.get('stop_reason')
    refusal = stop == 'refusal' or isinstance(response.get('stop_details'), dict) and response['stop_details'].get('type') == 'refusal'
    status = 'refused' if refusal else 'completed' if stop == 'end_turn' else 'incomplete'
    meta = {'id': response.get('id'), 'model': response.get('model'), 'usage': _anthropic_usage(usage),
            'service_tier': usage.get('service_tier') if isinstance(usage, dict) else None,
            'status': status, 'provider': provider, 'stop_reason': stop, 'refusal': refusal,
            'native_usage': usage}
    if (status != 'completed' or response.get('model') != model or response.get('type') != 'message'
            or response.get('role') != 'assistant' or meta['usage'] is None
            or type(response.get('id')) is not str or not re.fullmatch(r'msg_[A-Za-z0-9_-]{1,196}', response['id'])
            or response.get('stop_sequence') is not None):
        return None, meta
    content = response.get('content')
    # Thinking is native on Claude 5. Retain it in raw evidence; only the single
    # final text block is a program. Never join tool/extra text blocks into code.
    if (not isinstance(content, list) or not content or not all(isinstance(block, dict) for block in content)
            or content[-1].get('type') != 'text' or type(content[-1].get('text')) is not str):
        return None, meta
    for block in content[:-1]:
        if block.get('type') == 'thinking':
            if type(block.get('thinking')) is not str or type(block.get('signature')) is not str:
                return None, meta
        elif block.get('type') == 'redacted_thinking':
            if type(block.get('data')) is not str:
                return None, meta
        else:
            return None, meta
    return _program(content[-1]['text']), meta
