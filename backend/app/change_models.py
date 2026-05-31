from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip(" -\t") for line in value.splitlines() if line.strip(" -\t")]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


class ConfigurationItem(BaseModel):
    name: str = "TBD"
    item_type: str = Field(default="", validation_alias=AliasChoices("item_type", "type"))
    site_location: str = Field(default="", validation_alias=AliasChoices("site_location", "site_or_environment"))
    purpose: str = Field(default="", validation_alias=AliasChoices("purpose", "role_in_change"))
    version: str = ""


class RollbackBranch(BaseModel):
    scenario: str = "Rollback"
    steps: list[str] = Field(default_factory=list)

    @field_validator("steps", mode="before")
    @classmethod
    def normalise_steps(cls, value: Any) -> list[str]:
        return _strings(value)


class VerificationPlan(BaseModel):
    pre_change: list[str] = Field(default_factory=list)
    in_change: list[str] = Field(default_factory=list)
    post_change: list[str] = Field(default_factory=list)

    @field_validator("pre_change", "in_change", "post_change", mode="before")
    @classmethod
    def normalise_checks(cls, value: Any) -> list[str]:
        return _strings(value)


class ChangeDocument(BaseModel):
    title: str = "TBD"
    planned_change_date: str = "TBD"
    customer: str = "TBD"
    environment: str = "TBD"
    configuration_items: list[ConfigurationItem] = Field(default_factory=list)
    background: str = "TBD"
    change_description: str = "TBD"
    implementation_steps: list[str] = Field(default_factory=list)
    rollback_branches: list[RollbackBranch] = Field(default_factory=list)
    verification: VerificationPlan = Field(default_factory=VerificationPlan)
    risk_and_impact: str = "TBD"
    expected_outcome: str = "TBD"
    success_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    freshdesk_fields: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("implementation_steps", "success_criteria", "dependencies", "assumptions", mode="before")
    @classmethod
    def normalise_lists(cls, value: Any) -> list[str]:
        return _strings(value)

    @field_validator(
        "title",
        "planned_change_date",
        "customer",
        "environment",
        "background",
        "change_description",
        "risk_and_impact",
        "expected_outcome",
        mode="before",
    )
    @classmethod
    def normalise_text(cls, value: Any) -> str:
        if value is None or not str(value).strip():
            return "TBD"
        return str(value).strip()

    @field_validator("configuration_items", mode="before")
    @classmethod
    def normalise_configuration_items(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        return [{"name": item} if isinstance(item, str) else item for item in value]

    @field_validator("rollback_branches", mode="before")
    @classmethod
    def normalise_rollback_branches(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        return [
            {"scenario": "Rollback", "steps": [item]} if isinstance(item, str) else item
            for item in value
        ]

    @field_validator("verification", mode="before")
    @classmethod
    def normalise_verification(cls, value: Any) -> Any:
        if isinstance(value, list):
            return {"post_change": value}
        return value or {}


class ChangeSuggestionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100000)


class ChangeRenderRequest(BaseModel):
    change_document: ChangeDocument
