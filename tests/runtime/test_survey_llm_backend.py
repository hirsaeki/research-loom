from __future__ import annotations

import json
import os
import socket
import unittest
from unittest.mock import patch

from plugins.survey_virtual_runner.llm_backend import (
    OpenAIResponsesVirtualRespondentBackend,
    VirtualRespondentBackendError,
    _HttpResponse,
    prompt_template_pin,
)
from tests.runtime.test_survey_production import extended_questionnaire


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _provider(answer_text: str, *, request_id: str = "resp_test") -> _HttpResponse:
    body = {
        "id": request_id,
        "status": "completed",
        "model": "gpt-test",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "output": [{"type": "message", "id": "msg_test", "status": "completed", "content": [{"type": "output_text", "text": answer_text}]}],
    }
    return _HttpResponse(200, json.dumps(body).encode("utf-8"), {"x-request-id": request_id})


class SurveyLlmBackendTests(unittest.TestCase):
    def setUp(self):
        self.instrument = extended_questionnaire()
        self.profile = {
            "profile_id": "SYN-PROFILE-001",
            "attributes": {"role": "manager", "ai_usage_level": "moderate"},
            "knowledge_scope": ["own role and ordinary work experience"],
        }
        self.config = {
            "backend_id": "openai_responses",
            "model_id": "gpt-test",
            "credential_env": "SURVEY_TEST_KEY",
            "timeout_seconds": 3,
            "max_transport_retries": 1,
            "max_repair_attempts": 1,
            "temperature": 0.2,
            "top_p": 0.9,
            "max_output_tokens": 500,
        }

    def test_request_is_structured_minimal_and_secret_is_not_returned(self):
        transport = _Transport([_provider(json.dumps({"answers": [{"response_key": "role", "state": "answered", "value": "manager"}, {"response_key": "usefulness", "state": "answered", "value": 4}, {"response_key": "count", "state": "unknown", "value": None}, {"response_key": "notes", "state": "answered", "value": "short synthetic note"}]}))])
        backend = OpenAIResponsesVirtualRespondentBackend(transport=transport)
        with patch.dict(os.environ, {"SURVEY_TEST_KEY": "super-secret-test-key"}, clear=False):
            result = backend.generate_response(
                instrument=self.instrument,
                profile=self.profile,
                generation_config=self.config,
                prompt_template=prompt_template_pin(),
            )
        self.assertEqual(result["parsed_answer_payload"]["answers"][0]["value"], "manager")
        call = transport.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer super-secret-test-key")
        request_body = json.loads(call["body"])
        self.assertFalse(request_body["store"])
        self.assertEqual(request_body["text"]["format"]["type"], "json_schema")
        self.assertTrue(request_body["text"]["format"]["strict"])
        semantic = json.loads(request_body["input"])
        self.assertEqual(semantic["synthetic_respondent_profile"]["profile_id"], "SYN-PROFILE-001")
        self.assertEqual(semantic["survey"]["questions"][0]["prompt"], "Role?")
        self.assertNotIn("research_findings", semantic)
        persisted = json.dumps(result, sort_keys=True)
        self.assertNotIn("super-secret-test-key", persisted)
        self.assertIn("provider_response_digest", result)
        self.assertIn("parsed_answer_payload_digest", result)

    def test_invalid_json_gets_one_serialization_only_repair(self):
        transport = _Transport([
            _provider("not-json", request_id="resp_bad"),
            _provider(json.dumps({"answers": [{"response_key": "role", "state": "answered", "value": "manager"}, {"response_key": "usefulness", "state": "answered", "value": 5}]}), request_id="resp_fixed"),
        ])
        backend = OpenAIResponsesVirtualRespondentBackend(transport=transport)
        with patch.dict(os.environ, {"SURVEY_TEST_KEY": "test-key"}, clear=False):
            result = backend.generate_response(
                instrument=self.instrument,
                profile=self.profile,
                generation_config=self.config,
                prompt_template=prompt_template_pin(),
            )
        self.assertEqual(len(transport.calls), 2)
        repaired = json.loads(json.loads(transport.calls[1]["body"])["input"])
        self.assertTrue(repaired["serialization_repair_only"])
        self.assertEqual(repaired["invalid_output"], "not-json")
        self.assertEqual(result["parsed_answer_payload"]["answers"][1]["value"], 5)
        self.assertEqual([x["kind"] for x in result["attempts"]], ["generation", "serialization_repair"])

    def test_missing_credential_and_timeout_are_distinct_runtime_failures(self):
        backend = OpenAIResponsesVirtualRespondentBackend(transport=_Transport([]))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(VirtualRespondentBackendError) as missing:
                backend.generate_response(
                    instrument=self.instrument,
                    profile=self.profile,
                    generation_config=self.config,
                    prompt_template=prompt_template_pin(),
                )
        self.assertEqual(missing.exception.code, "AUTH_CONFIGURATION_MISSING")

        transport = _Transport([socket.timeout("slow"), socket.timeout("still slow")])
        backend = OpenAIResponsesVirtualRespondentBackend(transport=transport)
        with patch.dict(os.environ, {"SURVEY_TEST_KEY": "test-key"}, clear=False):
            with self.assertRaises(VirtualRespondentBackendError) as timeout:
                backend.generate_response(
                    instrument=self.instrument,
                    profile=self.profile,
                    generation_config=self.config,
                    prompt_template=prompt_template_pin(),
                )
        self.assertEqual(timeout.exception.code, "REQUEST_TIMEOUT")
        self.assertEqual(len(timeout.exception.attempts), 2)

    def test_provider_error_and_malformed_provider_payload_fail_closed(self):
        backend = OpenAIResponsesVirtualRespondentBackend(
            transport=_Transport([_HttpResponse(400, b'{"error":{"message":"bad"}}', {})])
        )
        with patch.dict(os.environ, {"SURVEY_TEST_KEY": "test-key"}, clear=False):
            with self.assertRaises(VirtualRespondentBackendError) as provider:
                backend.generate_response(
                    instrument=self.instrument,
                    profile=self.profile,
                    generation_config=self.config,
                    prompt_template=prompt_template_pin(),
                )
        self.assertEqual(provider.exception.code, "PROVIDER_ERROR")

        backend = OpenAIResponsesVirtualRespondentBackend(transport=_Transport([_HttpResponse(200, b'not-http-json', {})]))
        with patch.dict(os.environ, {"SURVEY_TEST_KEY": "test-key"}, clear=False):
            with self.assertRaises(VirtualRespondentBackendError) as malformed:
                backend.generate_response(
                    instrument=self.instrument,
                    profile=self.profile,
                    generation_config=self.config,
                    prompt_template=prompt_template_pin(),
                )
        self.assertEqual(malformed.exception.code, "MALFORMED_MODEL_OUTPUT")


if __name__ == "__main__":
    unittest.main()
