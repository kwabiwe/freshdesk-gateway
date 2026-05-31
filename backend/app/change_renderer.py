from __future__ import annotations

from html import escape

from .change_models import ChangeDocument


def _text(value: str) -> str:
    return escape(value or "TBD").replace("\n", "<br>")


def _list(items: list[str]) -> str:
    values = items or ["TBD"]
    return "<ol>" + "".join(f"<li>{_text(item)}</li>" for item in values) + "</ol>"


def _section(title: str, body: str) -> str:
    return f"<h2>{escape(title)}</h2>{body}"


def _useful(value: str) -> bool:
    return bool(value and value.strip().lower() not in {"tbd", "not provided", "unknown"})


def render_change_html(document: ChangeDocument) -> str:
    parts = [
        f"<h1>{_text(document.title)}</h1>",
        _section("Change classification", f"<p><strong>Type:</strong> {_text(document.change_type)}</p>"),
    ]
    if _useful(document.planned_start) or _useful(document.planned_end):
        parts.append(
            _section(
                "Planned window",
                f"<p><strong>Start:</strong> {_text(document.planned_start)}<br>"
                f"<strong>End:</strong> {_text(document.planned_end)}</p>",
            )
        )
    else:
        parts.append(_section("Planned change date", f"<p>{_text(document.planned_change_date)}</p>"))
    parts.extend(
        [
        _section("Customer / environment", f"<p><strong>Customer:</strong> {_text(document.customer)}<br><strong>Environment:</strong> {_text(document.environment)}</p>"),
        ]
    )
    if document.configuration_items:
        rows = "".join(
            f"<tr><td>{_text(item.name)}</td><td>{_text(item.item_type)}</td><td>{_text(item.site_location)}</td>"
            f"<td>{_text(item.purpose)}</td><td>{_text(item.version)}</td></tr>"
            for item in document.configuration_items
        )
        parts.append(
            _section(
                "Configuration items",
                "<table><thead><tr><th>Configuration item</th><th>Type</th><th>Site / environment</th>"
                "<th>Role in change</th><th>Version</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>",
            )
        )
    parts.extend(
        [
            _section("Background", f"<p>{_text(document.background)}</p>"),
            _section("Change description", f"<p>{_text(document.change_description)}</p>"),
            _section("Implementation steps", _list(document.implementation_steps)),
        ]
    )
    rollback = "".join(
        f"<h3>{_text(branch.scenario)}</h3>{_list(branch.steps)}" for branch in document.rollback_branches
    ) or _list([])
    parts.append(_section("Rollback plan", rollback))
    verification = (
        f"<h3>Pre-change verification</h3>{_list(document.verification.pre_change)}"
        f"<h3>In-change verification</h3>{_list(document.verification.in_change)}"
        f"<h3>Post-change verification</h3>{_list(document.verification.post_change)}"
    )
    parts.extend(
        [
            _section("Verification plan", verification),
            _section(
                "Risk and impact",
                f"<p><strong>Risk:</strong> {_text(document.risk)}<br><strong>Impact:</strong> {_text(document.impact)}"
                f"<br><strong>Summary:</strong> {_text(document.risk_and_impact)}</p>",
            ),
            _section("Expected outcome", f"<p>{_text(document.expected_outcome)}</p>"),
            _section("Success criteria", _list(document.success_criteria)),
        ]
    )
    if document.risks_and_mitigations:
        rows = "".join(
            f"<tr><td>{_text(item.risk)}</td><td>{_text(item.mitigation)}</td></tr>"
            for item in document.risks_and_mitigations
        )
        parts.append(_section("Risks and mitigations", f"<table><thead><tr><th>Risk</th><th>Mitigation</th></tr></thead><tbody>{rows}</tbody></table>"))
    if document.communication_plan:
        parts.append(_section("Communication plan", _list(document.communication_plan)))
    if document.dependencies:
        parts.append(_section("Dependencies", _list(document.dependencies)))
    return "".join(parts)
