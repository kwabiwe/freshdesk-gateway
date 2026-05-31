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


def render_change_html(document: ChangeDocument) -> str:
    parts = [
        f"<h1>{_text(document.title)}</h1>",
        _section("Planned change date", f"<p>{_text(document.planned_change_date)}</p>"),
        _section("Customer / environment", f"<p><strong>Customer:</strong> {_text(document.customer)}<br><strong>Environment:</strong> {_text(document.environment)}</p>"),
    ]
    if document.configuration_items:
        rows = "".join(
            f"<tr><td>{_text(item.name)}</td><td>{_text(item.site_location)}</td><td>{_text(item.purpose)}</td></tr>"
            for item in document.configuration_items
        )
        parts.append(
            _section(
                "Configuration items",
                "<table><thead><tr><th>Configuration item</th><th>Site / location</th><th>Purpose</th></tr></thead>"
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
            _section("Risk and impact", f"<p>{_text(document.risk_and_impact)}</p>"),
            _section("Expected outcome", f"<p>{_text(document.expected_outcome)}</p>"),
            _section("Success criteria", _list(document.success_criteria)),
        ]
    )
    if document.dependencies:
        parts.append(_section("Dependencies", _list(document.dependencies)))
    return "".join(parts)
