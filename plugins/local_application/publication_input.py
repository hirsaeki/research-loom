"""Diagnostic Publication reads reuse Writer pins without repairing source bytes."""
from __future__ import annotations

from .facade import LocalApplicationError
from .research_package_format import MAX_OUTPUT_BYTES, safe_component, verify_export_root
from .writer_composition_history_service import WriterCompositionHistoryService
from .writer_round_trip_service import WriterRoundTripService


class _PublicationCompositionReader(WriterCompositionHistoryService):
    def __init__(self, facade):
        super().__init__(facade)
        self.packages = {}
        self.diagnostics = []

    def _package(self, package_id, **_kwargs):
        if package_id not in self.packages:
            service = self._package_service()
            report = verify_export_root(service.root / safe_component(package_id, "package_id"),
                                        _visual_diagnostics=self.diagnostics)
            package = service._load_metadata(package_id, MAX_OUTPUT_BYTES)
            if package["package_digest"] != report["package_digest"]:
                raise LocalApplicationError("APPLICATION-PUBLICATION-INTEGRITY-001", "Package changed during Publication inspection")
            self.packages[package_id] = package
        return self.packages[package_id]


class _PublicationInputReader(WriterRoundTripService):
    def __init__(self, facade):
        super().__init__(facade)
        self.composer = _PublicationCompositionReader(facade)

    def _composition_service(self):
        return self.composer


def inspect_inputs(facade, composition_id, revision_id):
    try:
        inspection = facade.inspect_writer_round_trip(composition_id, revision_id)
        package_id = inspection["writer_input"]["source"]["research_package_id"]
        package = facade._writer_composition_service()._package(package_id)
        diagnostics = []
    except LocalApplicationError as exc:
        if exc.code != "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001":
            raise
        # Only missing/corrupt declared visual payloads may degrade. All original
        # Writer/Composition/Package identity, lineage and embedded-input validators
        # still execute; source text, schema, digest and reference errors still fail.
        reader = _PublicationInputReader(facade)
        inspection = reader.inspect(composition_id, revision_id)
        package = reader.composer._package(inspection["writer_input"]["source"]["research_package_id"])
        diagnostics = reader.composer.diagnostics
        if not diagnostics:
            raise exc
    return {**inspection, "source_package_document": package, "visual_diagnostics": diagnostics}
