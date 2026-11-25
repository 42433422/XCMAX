"""
客户 Schema

客户相关的 Pydantic 模型定义。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CustomerCreate(BaseModel):
    customer_code: str | None = Field(None, description="客户编码")
    name: str = Field(..., min_length=1, max_length=200, description="客户名称")
    contact_person: str | None = Field(None, max_length=100, description="联系人")
    phone: str | None = Field(None, max_length=50, description="电话")
    email: str | None = Field(None, max_length=100, description="邮箱")
    address: str | None = Field(None, max_length=500, description="地址")
    customer_type: str = Field("普通客户", max_length=50, description="客户类型")
    credit_level: str | None = Field(None, max_length=50, description="信用等级")
    payment_terms: str | None = Field(None, max_length=200, description="付款条款")
    description: str | None = Field(None, max_length=1000, description="描述信息")
    is_active: int = Field(1, ge=0, le=1)

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("客户名称不能为空")
        return v.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            if "@" not in v:
                raise ValueError("邮箱格式不正确")
        return v


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    contact_person: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=100)
    address: str | None = Field(None, max_length=500)
    customer_type: str | None = Field(None, max_length=50)
    credit_level: str | None = Field(None, max_length=50)
    payment_terms: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=1000)
    is_active: int | None = Field(None, ge=0, le=1)


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    name: str
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    customer_type: str
    credit_level: str | None = None
    payment_terms: str | None = None
    description: str | None = None
    is_active: int
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    success: bool = True
    data: list[CustomerResponse]
    total: int
    page: int
    per_page: int
    count: int


class CustomerCompatMutation(BaseModel):
    """Validated legacy /customers write contract; never trust client tenant fields."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    customer_name: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    unit_name: str | None = Field(default=None, max_length=200)
    contact_person: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=50)
    contact_address: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=0)

    @field_validator("expected_version", mode="before")
    @classmethod
    def strict_expected_version(cls, value: object) -> int | None:
        if value is None:
            return None
        if type(value) is int:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        raise ValueError("expected_version must be a nonnegative integer")

    @model_validator(mode="after")
    def reject_conflicting_aliases(self):
        for values in (
            (self.customer_name, self.name, self.unit_name),
            (self.contact_address, self.address),
        ):
            if len({value for value in values if value}) > 1:
                raise ValueError("Conflicting customer field aliases")
        return self
