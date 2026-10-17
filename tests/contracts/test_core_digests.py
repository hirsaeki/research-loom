"""Pinned behavior of the shared RFC 8785 digest helpers (core/runtime/digests.py, #489)."""

from __future__ import annotations

import unittest

from core.runtime import canonical_digest
from core.runtime.digests import jcs_digest, jcs_digest_without

_VALUE = {"b": 1.0, "a": "é", "n": [1, 2]}
_JCS = "sha256:a63897096ff9792bb735a7c0f84893b68af447eba6758ec4aa3cc82d7e7fa80d"


class CoreDigestTests(unittest.TestCase):
    def test_jcs_digest_is_pinned(self):
        self.assertEqual(jcs_digest(_VALUE), _JCS)

    def test_jcs_and_sorted_json_digests_are_distinct_encodings(self):
        # 1.0 encodes as "1" under RFC 8785 but "1.0" under json.dumps.
        self.assertNotEqual(canonical_digest(_VALUE), jcs_digest(_VALUE))

    def test_digest_without_drops_only_named_top_level_fields(self):
        document = {**_VALUE, "registry_digest": "sha256:old", "nested": {"registry_digest": 1}}
        expected = jcs_digest({**_VALUE, "nested": {"registry_digest": 1}})
        self.assertEqual(jcs_digest_without(document, "registry_digest"), expected)
        self.assertEqual(document["registry_digest"], "sha256:old")
        self.assertEqual(jcs_digest_without(_VALUE, "absent"), _JCS)

    def test_uncanonicalizable_values_raise(self):
        with self.assertRaises((TypeError, ValueError)):
            jcs_digest({"x": object()})


if __name__ == "__main__":
    unittest.main()
