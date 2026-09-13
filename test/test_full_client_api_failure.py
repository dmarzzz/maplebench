"""Safe HTTP failure evidence; all HTTP/provider I/O is stubbed, never sent."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).resolve().parent)]
import maple_agent as agent
import full_client_bridge as bridge_module
from full_client_adaptive import DEFAULT_PROTOCOL
import test_full_client_bridge as bridge_fixture

PRIVATE = 'SYNTHETIC_PRIVATE_ERROR_AND_BODY'


def worker_envelope(cause, input_value=None):
    """Execute the actual trusted helper text with urlopen replaced before I/O."""
    request = input_value or {'url':'https://synthetic.invalid/responses', 'key':PRIVATE,
                              'payload':{'private':PRIVATE}, 'timeout':1}
    output = io.StringIO()
    with mock.patch('urllib.request.urlopen', side_effect=cause) as http, \
            mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(request))), contextlib.redirect_stdout(output):
        exec(compile(agent.HTTP_WORKER, '<trusted-http-worker-test>', 'exec'), {})
    http.assert_called_once()
    return output.getvalue().encode()


class ApiFailureTests(unittest.TestCase):
    def endpoint_error(self, cause):
        raw = worker_envelope(cause)
        with mock.patch.object(agent.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout=raw)):
            with self.assertRaises(agent.AgentError) as caught:
                agent.bounded_request('https://synthetic.invalid/responses', key=PRIVATE)
        self.assertNotIn(PRIVATE, raw.decode())
        self.assertNotIn(PRIVATE, str(caught.exception))
        return caught.exception

    def test_http_statuses_survive_actual_worker_boundary_without_body_or_headers(self):
        for status in (401, 429):
            body = mock.Mock()
            error = urllib.error.HTTPError('https://synthetic.invalid/'+PRIVATE, status,
                                          PRIVATE, {'Authorization':PRIVATE}, body)
            caught = self.endpoint_error(error)
            body.read.assert_not_called()
            self.assertEqual(str(caught), 'HTTP '+str(status))
            self.assertEqual(agent.safe_request_failure(caught),
                {'schema_version':1,'category':'http_error','http_status':status})

    def test_transport_timeout_and_unknown_errors_have_only_fixed_categories(self):
        for error, category in ((urllib.error.URLError(PRIVATE),'transport_error'),
                                (TimeoutError(PRIVATE),'timeout'), (RuntimeError(PRIVATE),'request_failed')):
            with self.subTest(category=category):
                caught = self.endpoint_error(error)
                self.assertEqual(agent.safe_request_failure(caught),
                    {'schema_version':1,'category':category,'http_status':None})

    def test_arbitrary_exception_strings_and_malformed_diagnostics_are_not_parsed(self):
        for error in (RuntimeError('HTTP 401 '+PRIVATE), agent.AgentError('HTTP 429 '+PRIVATE),
                      agent.AgentError(PRIVATE, request_failure={'category':PRIVATE,'http_status':401}),
                      agent.AgentError(PRIVATE, request_failure=['http_error',429])):
            self.assertEqual(agent.safe_request_failure(error),
                {'schema_version':1,'category':'request_failed','http_status':None})
        for status in ('401', True, 599, -1, 200):
            error = agent.AgentError(PRIVATE,request_failure={'category':'http_error','http_status':status,'body':PRIVATE})
            self.assertEqual(agent.safe_request_failure(error),
                {'schema_version':1,'category':'http_error','http_status':None})
        error = agent.AgentError(PRIVATE,request_failure={'category':'http_error','http_status':401,'body':PRIVATE})
        self.assertEqual(agent.safe_request_failure(error),
            {'schema_version':1,'category':'http_error','http_status':401})

    def test_untrusted_worker_error_text_is_not_promoted_to_exception_or_diagnostic(self):
        replies = [b'not-json '+PRIVATE.encode(), json.dumps({'ok':False,'error':PRIVATE}).encode(),
                   json.dumps({'ok':False,'failure':{'category':PRIVATE,'http_status':PRIVATE}}).encode()]
        for raw in replies:
            with mock.patch.object(agent.subprocess, 'run',return_value=SimpleNamespace(returncode=0,stdout=raw)):
                with self.assertRaises(agent.AgentError) as caught: agent.bounded_request('https://synthetic.invalid')
            self.assertNotIn(PRIVATE,str(caught.exception))
            self.assertNotIn(PRIVATE,json.dumps(agent.safe_request_failure(caught.exception)))

    def run_bridge_failure(self, cause, *, adaptive=False):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); key = root/'unused-test-key'; key.write_text(PRIVATE); key.chmod(0o600)
        bridge = bridge_module.FullClientBridge(root/'runs',key)
        fixture = bridge_fixture.FullClientTests()
        bridge.frame(fixture.frame())
        options = {'adaptive_protocol':DEFAULT_PROTOCOL,'total_token_limit':DEFAULT_PROTOCOL['max_total_tokens']} if adaptive else {}
        with mock.patch.object(bridge_module.threading,'Thread'):
            run = bridge.start('api','gpt-5.6-luna',300 if adaptive else 60,**options)
        def http_child(argv, *, input, **kwargs):
            return SimpleNamespace(returncode=0,stdout=worker_envelope(cause,json.loads(input)))
        with mock.patch.object(bridge,'request',return_value=fixture.observation()), \
                mock.patch.object(bridge,'_wait_for_capture'), \
                mock.patch.object(agent.subprocess,'run',side_effect=http_child) as transport, \
                mock.patch.object(bridge_module,'execute_program') as execute:
            bridge._run(run)
        transport.assert_called_once(); execute.assert_not_called()
        folder = bridge.output/run['id']
        controller = json.loads((folder/'controller.json').read_bytes())
        output = json.loads((folder/('result.json' if adaptive else 'failure.json')).read_bytes())
        self.assertEqual(controller['status'],'failed'); self.assertEqual(controller['actions'],0)
        self.assertEqual(controller['reason'],'AgentError')
        self.assertEqual(controller['apiOutcome'],'uncertain')
        self.assertFalse((folder/'api-response.json').exists()); self.assertFalse((folder/'program.js').exists())
        for path in folder.rglob('*.json'): self.assertNotIn(PRIVATE,path.read_text())
        self.assertEqual(output['apiFailure'],controller['apiFailure'])
        if adaptive:
            self.assertEqual(output['adaptive']['counters']['api_requests_started'],1)
            self.assertEqual(output['adaptive']['counters']['api_responses_confirmed'],0)
        else:
            self.assertEqual(output['error'],'AgentError'); self.assertEqual(output['phase'],'api_request')
        return output['apiFailure']

    def test_short_full_client_failures_save_safe_status_and_do_not_retry_or_execute(self):
        for status in (401,429):
            with self.subTest(status=status):
                error = urllib.error.HTTPError('https://synthetic.invalid',status,PRIVATE,{},None)
                self.assertEqual(self.run_bridge_failure(error),
                    {'schema_version':1,'category':'http_error','http_status':status})
        self.assertEqual(self.run_bridge_failure(urllib.error.URLError(PRIVATE)),
                         {'schema_version':1,'category':'transport_error','http_status':None})
        self.assertEqual(self.run_bridge_failure(RuntimeError(PRIVATE)),
                         {'schema_version':1,'category':'request_failed','http_status':None})

    def test_adaptive_failure_saves_same_diagnostic_outside_frozen_trace_without_retry(self):
        error = urllib.error.HTTPError('https://synthetic.invalid',429,PRIVATE,{},None)
        self.assertEqual(self.run_bridge_failure(error,adaptive=True),
                         {'schema_version':1,'category':'http_error','http_status':429})


if __name__ == '__main__': unittest.main()
