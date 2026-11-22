"""Bounded browser plans; Playwright owns browser behavior, not a second Agent loop."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BrowserLocator(BrowserInput):
    role: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=500)
    label: str | None = Field(default=None, min_length=1, max_length=500)
    text: str | None = Field(default=None, min_length=1, max_length=500)
    selector: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_strategy(self):
        if (
            sum(value is not None for value in (self.role, self.label, self.text, self.selector))
            != 1
        ):
            raise ValueError("exactly one locator strategy is required")
        if self.name is not None and self.role is None:
            raise ValueError("name requires role")
        return self


class BrowserUpload(BrowserInput):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")


class BrowserStep(BrowserInput):
    action: Literal["click", "fill", "select", "check", "press", "upload", "download"]
    locator: BrowserLocator
    frame: str | None = Field(default=None, min_length=1, max_length=1000)
    value: str | list[str] | bool | None = None
    files: list[BrowserUpload] = Field(default_factory=list, max_length=5)
    verify: list[BrowserCheck] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def action_arguments(self):
        if self.action in {"fill", "press"} and not isinstance(self.value, str):
            raise ValueError("fill/press require a string value")
        if self.action == "select" and not isinstance(self.value, (str, list)):
            raise ValueError("select requires a string or list of strings")
        if self.action == "check" and type(self.value) is not bool:
            raise ValueError("check requires a boolean value")
        if (self.action == "upload") != bool(self.files):
            raise ValueError("only upload accepts nonempty files")
        if self.action in {"click", "upload", "download"} and self.value is not None:
            raise ValueError("this action does not accept value")
        if isinstance(self.value, str) and len(self.value) > 10000:
            raise ValueError("input value is too large")
        if isinstance(self.value, list) and (
            len(self.value) > 100 or any(len(value) > 1000 for value in self.value)
        ):
            raise ValueError("selection is too large")
        return self


class BrowserCheck(BrowserInput):
    kind: Literal["text", "value", "visible", "url"]
    locator: BrowserLocator | None = None
    frame: str | None = Field(default=None, min_length=1, max_length=1000)
    expected: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def meaningful_check(self):
        if self.kind != "url" and self.locator is None:
            raise ValueError("element checks require a locator")
        if self.kind != "visible" and not self.expected:
            raise ValueError("this check requires a nonempty expected value")
        if self.kind == "visible":
            if "expected" not in self.model_fields_set:
                self.expected = "true"
            if self.expected not in {"true", "false"}:
                raise ValueError("visibility expectation must be true or false")
        if self.kind == "url" and (self.locator is not None or self.frame is not None):
            raise ValueError("url checks cannot select an element or frame")
        return self


class BrowserObserve(BrowserInput):
    url: str = Field(min_length=1, max_length=4096)
    screenshot: bool = False


class BrowserExecute(BrowserObserve):
    steps: list[BrowserStep] = Field(min_length=1, max_length=30)
    verify: list[BrowserCheck] = Field(min_length=1, max_length=20)


BrowserStep.model_rebuild()
BROWSER_INPUT_SCHEMAS = {
    ("browser", "observe"): BrowserObserve.model_json_schema(),
    ("browser", "execute"): BrowserExecute.model_json_schema(),
}
