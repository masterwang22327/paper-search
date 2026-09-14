#!/usr/bin/env python3
"""Check page insight evidence, cache identity, validation and request isolation."""

from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from runtime_store import RuntimeStore


ANSWER = {
    "main_point": "本页说明 Transformer 的编码器与解码器结构。",
    "context": ["前文定义序列转换任务。"],
    "sections": [{"kind": "mechanism", "title": "掩码如何避免未来信息泄漏", "source_location": "3.1 节 Decoder 段", "source_quote": "The decoder is also composed of a stack of", "original_meaning": "解码器自注意力不能读取后续位置。", "paragraphs": ["右移输入配合掩码，使位置只能访问已知输出。", "仅右移并不足以阻断其他位置的信息，因此仍需要注意力掩码。"], "boundary": "", "evidence": ["p.3 图 1"]}],
    "takeaways": ["输入右移与注意力掩码共同保证自回归条件。"],
    "caveats": [],
}
ANSWER["sections"][0]["source_regions"] = []


class PageInsightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pdf = self.root / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-test-original")
        self.state = server.ReaderState.__new__(server.ReaderState)
        self.state.user_dir = self.root
        self.state.runtime_store = RuntimeStore(self.root / "state.sqlite3")
        self.state.lock = threading.RLock()
        self.state.page_insight_locks = {}
        self.state.source_pdf = mock.Mock(return_value=self.pdf)
        self.state.source_metadata = mock.Mock(return_value={"page_count": 4, "title": "Test paper"})
        self.state.pdf_page_count = mock.Mock(return_value=4)
        self.state.pdf_page_text = mock.Mock(side_effect=lambda source, page: f"Original text on page {page}")
        self.state.call_responses_api = mock.Mock(return_value=(json.dumps(ANSWER), "response-id"))
        self.payload = {"source_id": "test-paper", "page": 3, "model": "gpt-5.6-terra", "reasoning_effort": "medium"}

    def test_manual_only_and_persistent_cache(self):
        self.assertEqual(self.state.page_insight_state(self.payload), {"insight": None, "cached": False})
        self.state.call_responses_api.assert_not_called()
        first = self.state.generate_page_insight(self.payload)
        self.assertFalse(first["cached"])
        second = self.state.generate_page_insight(self.payload)
        self.assertTrue(second["cached"])
        self.assertEqual(first["insight"], second["insight"])
        self.state.runtime_store = RuntimeStore(self.root / "state.sqlite3")
        self.assertEqual(self.state.page_insight_state(self.payload)["insight"], first["insight"])
        self.assertEqual(self.state.call_responses_api.call_count, 1)
        self.assertFalse((self.root / "page-insights").exists())

    def test_raw_page_image_and_bounded_auxiliary_context(self):
        self.state.generate_page_insight(self.payload)
        args, kwargs = self.state.call_responses_api.call_args
        evidence = json.loads(args[0])
        self.assertEqual(kwargs["image_contexts"][0], {"source_id": "test-paper", "page": 3})
        self.assertEqual(evidence["image_pages_in_order"], [3, 1, 2, 4])
        self.assertEqual([item["physical_page"] for item in evidence["surrounding_pages"]], [1, 2, 4])
        self.assertEqual(evidence["current_page_text"], "Original text on page 3")
        self.assertEqual(evidence["previous_page_tail"], "Original text on page 2")
        self.assertEqual(evidence["next_page_head"], "Original text on page 4")
        self.assertEqual(evidence["paper_opening_text"], "Original text on page 1")
        self.assertIn("纯参考文献", kwargs["system_prompt"])
        self.assertIn("从观察到观点的桥梁", kwargs["system_prompt"])
        self.assertEqual(evidence["preceding_pages"][0]["physical_page"], 1)
        self.assertEqual(kwargs["model"], self.payload["model"])
        self.assertEqual(kwargs["reasoning_effort"], "medium")

    def test_cache_separates_model_effort_page_file_and_prompt(self):
        self.state.generate_page_insight(self.payload)
        for changes in ({"model": "gpt-6-astra"}, {"reasoning_effort": "high"}, {"page": 2}):
            self.assertIsNone(self.state.page_insight_state({**self.payload, **changes})["insight"])
        original_read = Path.read_text

        def changed_prompt(path, *args, **kwargs):
            value = original_read(path, *args, **kwargs)
            return value + "\nPrompt revision" if path.name == "page-insight.md" else value

        with mock.patch.object(Path, "read_text", changed_prompt):
            self.assertIsNone(self.state.page_insight_state(self.payload)["insight"])
        self.pdf.write_bytes(b"%PDF-new-version")
        self.assertIsNone(self.state.page_insight_state(self.payload)["insight"])

    def test_failure_keeps_previous_result_and_releases_lock(self):
        first = self.state.generate_page_insight(self.payload)
        self.state.call_responses_api.return_value = ('{"main_point":"truncated"}', "id")
        with self.assertRaises(server.ApiError):
            self.state.generate_page_insight({**self.payload, "force": True})
        self.assertEqual(self.state.page_insight_state(self.payload)["insight"], first["insight"])
        self.state.call_responses_api.return_value = (json.dumps(ANSWER), "id")
        self.assertFalse(self.state.generate_page_insight({**self.payload, "force": True})["cached"])

    def test_invalid_requests_never_call_model(self):
        for changes in (
            {"page": 0}, {"page": 5}, {"page": 1.5}, {"page": True}, {"page": "oops"},
            {"model": []}, {"model": "unknown"}, {"reasoning_effort": []},
            {"reasoning_effort": "low"}, {"model": "gpt-6-astra", "reasoning_effort": "ultra"},
            {"source_id": "../bad"},
        ):
            with self.subTest(changes=changes), self.assertRaises(server.ApiError) as raised:
                self.state.generate_page_insight({**self.payload, **changes})
            self.assertEqual(raised.exception.status, 400)
        self.state.call_responses_api.assert_not_called()

    def test_duplicate_request_does_not_start_second_generation(self):
        def respond(*args, **kwargs):
            with self.assertRaises(server.ApiError) as raised:
                self.state.generate_page_insight(self.payload)
            self.assertEqual(raised.exception.status, 409)
            self.assertIsNone(self.state.page_insight_state(self.payload)["insight"])
            return json.dumps(ANSWER), "id"

        self.state.call_responses_api.side_effect = respond
        self.state.generate_page_insight(self.payload)
        self.assertEqual(self.state.call_responses_api.call_count, 1)

    def test_references_and_image_only_pages(self):
        references = {**ANSWER, "context": [], "sections": [], "takeaways": []}
        self.state.pdf_page_text.return_value = ""
        self.state.pdf_page_text.side_effect = None
        self.state.call_responses_api.return_value = (json.dumps(references), "id")
        result = self.state.generate_page_insight({**self.payload, "page": 4})
        self.assertEqual(result["insight"]["content"]["sections"], [])
        args, kwargs = self.state.call_responses_api.call_args
        self.assertEqual(json.loads(args[0])["next_page_head"], "")
        self.assertEqual(kwargs["image_contexts"][0]["page"], 4)
        for invalid in ({**ANSWER, "priority": "highest"}, {**ANSWER, "sections": ANSWER["sections"] * 13}, {**ANSWER, "main_point": " "}):
            with self.assertRaises(server.ApiError):
                self.state.validate_page_insight(invalid)

    def test_preceding_context_is_bounded_and_page_labelled(self):
        self.state.source_metadata.return_value["page_count"] = 30
        self.state.pdf_page_count.return_value = 30
        self.state.pdf_page_text.side_effect = lambda source, page: str(page) + "x" * 9999
        self.state.generate_page_insight({**self.payload, "page": 20})
        evidence = json.loads(self.state.call_responses_api.call_args.args[0])
        previous = evidence["preceding_pages"]
        self.assertLessEqual(sum(len(item["text"]) for item in previous), 32000)
        self.assertEqual([item["physical_page"] for item in previous], [15, 16, 17, 18])
        self.assertTrue(previous[0]["truncated"])
        self.assertNotIn(20, [item["physical_page"] for item in previous])
        self.assertEqual(evidence["image_pages_in_order"], [20, 18, 19, 21, 22])

    def test_region_validation(self):
        for box in ([0, 0, 1001, 100], [0, 200, 100, 100], [True, 0, 100, 100], [0, 0, float("nan"), 100]):
            invalid = {**ANSWER, "sections": [{**ANSWER["sections"][0], "source_regions": [box]}]}
            with self.assertRaises(server.ApiError):
                self.state.validate_page_insight(invalid)

    def test_pdf_change_during_generation_is_not_cached(self):
        def respond(*args, **kwargs):
            self.pdf.write_bytes(b"%PDF-replaced-during-request")
            return json.dumps(ANSWER), "id"

        self.state.call_responses_api.side_effect = respond
        with self.assertRaises(server.ApiError) as raised:
            self.state.generate_page_insight(self.payload)
        self.assertEqual(raised.exception.status, 409)
        self.assertIsNone(self.state.page_insight_state(self.payload)["insight"])

    def test_transport_sends_png_and_selected_parameters(self):
        del self.state.call_responses_api
        png = b"\x89PNG\r\n\x1a\nraw-page-image"
        self.state.render_pdf_page = mock.Mock(side_effect=lambda context, path: path.write_bytes(png))
        self.state.load_translation_api_url = mock.Mock(return_value="https://provider.test/v1/responses")
        self.state.load_translation_api_key = mock.Mock(return_value="test-key")
        self.state.translation_ssl_context = None
        stream = io.BytesIO(("data: " + json.dumps({"type": "response.output_text.delta", "delta": json.dumps(ANSWER)}) + "\n\n").encode())
        with mock.patch.object(server, "urlopen", return_value=stream) as open_request:
            self.state.generate_page_insight({**self.payload, "model": "gpt-6-astra", "reasoning_effort": "low"})
        request = json.loads(open_request.call_args.args[0].data)
        self.assertEqual(request["model"], "gpt-6-astra")
        self.assertEqual(request["reasoning"]["effort"], "low")
        self.assertFalse(request["store"])
        self.assertNotIn("tools", request)
        image = request["input"][1]["content"][1]
        self.assertEqual(base64.b64decode(image["image_url"].split(",")[1]), png)
        self.assertEqual(image["detail"], "high")
        self.assertEqual(request["text"]["format"]["name"], "paper_page_insight")


if __name__ == "__main__":
    unittest.main()
