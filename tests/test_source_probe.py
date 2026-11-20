import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("probe", Path(__file__).resolve().parents[1] / "scripts" / "probe_sources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceContentTests(unittest.TestCase):
    def test_cn_api_requires_success_flag(self):
        self.assertEqual(module.inspect_content({"mode": "cn_json"}, b'{"show":0,"pageInfo":{"rows":[]}}')["status"], "invalid_content")

    def test_cn_empty_list_requires_review(self):
        self.assertEqual(module.inspect_content({"mode": "cn_json"}, b'{"show":1,"pageInfo":{"rows":[]}}')["status"], "needs_review")

    def test_cn_valid_page(self):
        data = b'{"show":1,"pageInfo":{"rows":[{"title":"Example","url":"/article/example.html"}],"total":1}}'
        self.assertEqual(module.inspect_content({"mode": "cn_json"}, data)["items"], 1)

    def test_cn_legacy_encoding(self):
        data = '{"show":1,"pageInfo":{"rows":[{"title":"出口管制公告","url":"/article/test.html"}]}}'.encode("gb18030")
        self.assertEqual(module.inspect_content({"mode": "cn_json"}, data)["items"], 1)

    def test_cn_wrong_top_level(self):
        self.assertEqual(module.inspect_content({"mode": "cn_json"}, b'[]')["status"], "invalid_content")
    def test_challenge_is_not_success(self):
        result = module.inspect_content({"mode": "html", "selector": "main"}, b"<title>Just a moment</title><main>Verify you are human</main>")
        self.assertEqual(result["status"], "challenge")

    def test_map_shell_requires_browser(self):
        result = module.inspect_content({"mode": "browser"}, b"<html><app-root></app-root><script>data</script></html>")
        self.assertEqual(result["status"], "needs_browser")

    def test_empty_json_is_review_not_success(self):
        self.assertEqual(module.inspect_content({"mode": "json"}, b'{"results": []}')["status"], "needs_review")

    def test_challenge_json_is_invalid(self):
        self.assertEqual(module.inspect_content({"mode": "json"}, b'{"challenge": true}')["status"], "invalid_content")

    def test_html_is_not_rss(self):
        self.assertEqual(module.inspect_content({"mode": "rss"}, b"<html><body>Access denied</body></html>")["status"], "invalid_content")

    def test_invalid_regulation_record(self):
        self.assertEqual(module.inspect_content({"mode": "json"}, b'{"results": [{"title":"test"}]}')["status"], "invalid_content")

    def test_valid_feed_has_items(self):
        self.assertEqual(module.inspect_content({"mode": "rss"}, b"<rss><channel><item><title>Test</title></item></channel></rss>")["items"], 1)


if __name__ == "__main__":
    unittest.main()
