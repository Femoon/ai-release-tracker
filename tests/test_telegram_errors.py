import unittest

from core.notify.telegram import _safe_request_error


class TelegramErrorTests(unittest.TestCase):
    def test_bot_token_is_redacted_from_request_error(self):
        token = "123456:secret-token"
        error = RuntimeError(f"request failed at /bot{token}/sendMessage")

        rendered = _safe_request_error(error, token)

        self.assertNotIn(token, rendered)
        self.assertIn("/bot<redacted>/sendMessage", rendered)


if __name__ == "__main__":
    unittest.main()
