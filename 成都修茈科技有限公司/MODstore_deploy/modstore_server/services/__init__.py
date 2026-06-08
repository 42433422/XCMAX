"""Cross-domain service ports.

These thin abstractions are the seam between the future Employee, Workflow
and LLM microservices. Anything that needs to reach across domains MUST go
through one of these client interfaces instead of importing the underlying
implementation module directly. See ``docs/SERVICE_BOUNDARIES.md`` and
``tests/test_service_boundaries.py``.
"""

from __future__ import annotations

from modstore_server.services.catalog import (
    CatalogClient,
    InProcessCatalogClient,
    get_default_catalog_client,
    set_default_catalog_client,
)
from modstore_server.services.employee import (
    EmployeeRuntimeClient,
    InProcessEmployeeRuntimeClient,
    get_default_employee_client,
    set_default_employee_client,
)
from modstore_server.services.knowledge import (
    InProcessKnowledgeClient,
    KnowledgeClient,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    get_default_knowledge_client,
    set_default_knowledge_client,
)
from modstore_server.services.llm import (
    InProcessLlmChatClient,
    LlmChatClient,
    LlmChatRequest,
    LlmChatResponse,
    get_default_llm_client,
    set_default_llm_client,
)
from modstore_server.services.notification import (
    InProcessNotificationClient,
    NotificationClient,
    get_default_notification_client,
    set_default_notification_client,
)
from modstore_server.services.openapi_connector import (
    ConnectorOperationCall,
    ConnectorOperationResult,
    InProcessOpenApiConnectorClient,
    OpenApiConnectorClient,
    get_default_connector_client,
    set_default_connector_client,
)
from modstore_server.services.workflow import (
    InProcessWorkflowEngineClient,
    WorkflowEngineClient,
    get_default_workflow_client,
    set_default_workflow_client,
)

__all__ = [
    "CatalogClient",
    "ConnectorOperationCall",
    "ConnectorOperationResult",
    "EmployeeRuntimeClient",
    "InProcessCatalogClient",
    "InProcessEmployeeRuntimeClient",
    "InProcessKnowledgeClient",
    "InProcessLlmChatClient",
    "InProcessNotificationClient",
    "InProcessOpenApiConnectorClient",
    "InProcessWorkflowEngineClient",
    "KnowledgeClient",
    "KnowledgeSearchHit",
    "KnowledgeSearchRequest",
    "LlmChatClient",
    "LlmChatRequest",
    "LlmChatResponse",
    "NotificationClient",
    "OpenApiConnectorClient",
    "WorkflowEngineClient",
    "get_default_catalog_client",
    "get_default_connector_client",
    "get_default_employee_client",
    "get_default_knowledge_client",
    "get_default_llm_client",
    "get_default_notification_client",
    "get_default_workflow_client",
    "set_default_catalog_client",
    "set_default_connector_client",
    "set_default_employee_client",
    "set_default_knowledge_client",
    "set_default_llm_client",
    "set_default_notification_client",
    "set_default_workflow_client",
]
