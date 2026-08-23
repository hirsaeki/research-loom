# Plugins

Canonical home for imperative extensions and integrations: custom importers/exporters, source adapters, calculations, anonymization, external-system integration, and concrete Research Capability adapters/runtimes such as future Desktop Research, Survey, Case, Delphi, or Virtual Runner implementations.

Common Capability Descriptor / Context Pack / Invocation / Handoff contracts live in `core/packages/`. Plugins implement those contracts without redefining authority/adoption semantics. Profiles may constrain Capabilities and Project Config may configure or hint at them, but neither owns imperative implementations.
