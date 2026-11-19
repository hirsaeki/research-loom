# Writer communication priorities

Issue #626, under Epic #624, corrects a projection gap in the existing public
Research Package → Composition → Writer input → response round trip.

The Research Package already retains `communication_brief.must_include`, but
the section-input projection previously delivered only `core_message` and
`must_not_claim`. A detached Writer could therefore receive prohibitions without
the positive communication priorities saved in the same package. This explains
an input difference; it does not establish a causal effect on prose.

## Projection and meaning

Nonempty `communication_brief.must_include` is copied, in its saved order, to
each selected section input's `communication.must_include`. The section digest
and compact round-trip identity cover it through their existing canonical
content hashing. Standalone section export and compact/expanded round-trip
inputs use the same builder. No new delivery channel or Profile version is
introduced. Empty or absent lists retain the previous projection bytes.

This is a document-level communication priority, not a requirement to repeat
every item in every section. Placement remains the Writer's task, using the
selected Section Contracts, reader questions, messages, opening/closing intents
and outline context. Existing research scope and support still govern what can
be said. A requested topic does not adopt a Finding or Recommendation, prove an
effect, authorize a new decision or override `must_not_claim`. Missing support
belongs in the existing Writing Feedback flow.

The existing union of brief and project prohibitions, source/Profile pins,
counter-evidence closure, qualifiers, materials and authority flags is unchanged.
Existing Workspaces and their Profile selections are not advanced automatically.

## Retained input compatibility

Immutable input receipts created before this correction can lack the positive
field even when the pinned package contains a nonempty list. When validating
such a receipt, reconstruct the historical section projection by removing only
`communication.must_include` and recomputing its section digest. Compare the
entire embedded payload and its summary against that projection, then retain
all existing receipt schema, identity, digest, source and origin checks.

An explicitly present field must exactly match the pinned package; altered
positive priorities are rejected. Historical absence is accepted, not silently
filled in or rewritten. As with the previous receipt format, absence alone has
no authenticated creation-time marker; it identifies the compatible historical
projection, not a claim about when a receipt was created. Other content changes
are never excused by this compatibility path.

Re-export after upgrading to deliver the positive priorities to a new Writer
pass. The changed content gets a new input identity while old responses remain
importable against their exact retained input. No research adoption or Human
Decision is inferred from either export or import.

## Verification boundary

The regression suite exercises public export/import/inspection, standalone
verification, compact expansion, priority/prohibition digest sensitivity,
unchanged section contracts and Research objects, empty/absent compatibility,
and import of retained old receipts. Altered priorities, prohibitions and
contracts remain failures even with recalculated section hashes.

These checks establish transport and compatibility. They do not establish
reader comprehension, better writing, semantic Profile PASS, publication
readiness, or ChatGPT Work integration acceptance (#628). The bounded prose
comparison belongs to #627; actual Work acceptance remains separate.
