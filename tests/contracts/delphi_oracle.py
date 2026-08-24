from __future__ import annotations


def design_error(design):
    planned = design.get("planned_rounds", {})
    minimum = planned.get("minimum_rounds")
    maximum = planned.get("maximum_approved_rounds")
    if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
        return "DLP-DESIGN-ROUNDS-001"
    return None
