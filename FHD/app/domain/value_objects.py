"""Compatibility exports; shipment value objects have one canonical implementation."""

from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from typing import Any as Any
from typing import Dict as Dict
from typing import Optional as Optional

from app.domain.shipment.value_objects import (
    ContactInfo as ContactInfo,
)
from app.domain.shipment.value_objects import (
    ModelNumber as ModelNumber,
)
from app.domain.shipment.value_objects import (
    Money as Money,
)
from app.domain.shipment.value_objects import (
    OrderNumber as OrderNumber,
)
from app.domain.shipment.value_objects import (
    Price as Price,
)
from app.domain.shipment.value_objects import (
    Quantity as Quantity,
)
from app.domain.value_objects_industry import (
    get_current_industry_config as get_current_industry_config,
)
