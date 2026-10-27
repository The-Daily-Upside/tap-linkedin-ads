import importlib.util
import os
import unittest
from unittest import mock

SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "exchange_auth_code.py"
)
SPEC = importlib.util.spec_from_file_location("exchange_auth_code", SCRIPT)
exchange = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exchange)

BASE = [
    "--client-id", "id",
    "--client-secret", "secret",
    "--redirect-uri", "http://localhost:8080/callback",
    "--out", "/tmp/linkedin-ads-tokens.json",
]


class TestOAuthStateCheck(unittest.TestCase):

    def test_mismatch_does_not_exchange(self):
        argv = BASE + [
            "--state", "expected-state-value",
            "--code", "one-time-code",
            "--returned-state", "other-state-value!",
        ]
        with mock.patch.object(exchange.urllib.request, "urlopen") as urlopen:
            self.assertEqual(exchange.main(argv), 1)
        urlopen.assert_not_called()

    def test_code_without_returned_state_does_not_exchange(self):
        argv = BASE + ["--state", "expected-state-value", "--code", "one-time-code"]
        with mock.patch.object(exchange.urllib.request, "urlopen") as urlopen:
            self.assertEqual(exchange.main(argv), 1)
        urlopen.assert_not_called()

    def test_redirect_url_state_must_match_before_exchange(self):
        argv = BASE + [
            "--state", "expected-state-value",
            "--redirect-url",
            "http://localhost:8080/callback?code=one-time-code&state=expected-state-value",
        ]
        response = mock.Mock()
        response.read.return_value = b'{"access_token":"a","refresh_token":"r","refresh_token_expires_in":10}'
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(exchange.urllib.request, "urlopen", return_value=response) as urlopen:
            with mock.patch.object(exchange, "_exchange", return_value=0) as exchange_call:
                self.assertEqual(exchange.main(argv), 0)
        urlopen.assert_not_called()
        exchange_call.assert_called_once()
        self.assertEqual(exchange_call.call_args.args[0].code, "one-time-code")

    def test_redirect_url_code_without_state_does_not_exchange(self):
        argv = BASE + [
            "--state", "expected-state-value",
            "--returned-state", "expected-state-value",
            "--redirect-url", "http://localhost:8080/callback?code=one-time-code",
        ]
        with mock.patch.object(exchange, "_exchange") as exchange_call:
            self.assertEqual(exchange.main(argv), 1)
        exchange_call.assert_not_called()

    def test_redirect_url_blank_state_does_not_exchange(self):
        argv = BASE + [
            "--state", "expected-state-value",
            "--returned-state", "expected-state-value",
            "--redirect-url", "http://localhost:8080/callback?code=one-time-code&state=",
        ]
        with mock.patch.object(exchange, "_exchange") as exchange_call:
            self.assertEqual(exchange.main(argv), 1)
        exchange_call.assert_not_called()

    def test_authorization_error_redirect_does_not_exchange(self):
        argv = BASE + [
            "--state", "expected-state-value",
            "--redirect-url",
            "http://localhost:8080/callback?error=access_denied&state=expected-state-value",
        ]
        with mock.patch.object(exchange, "_exchange") as exchange_call:
            self.assertEqual(exchange.main(argv), 1)
        exchange_call.assert_not_called()
