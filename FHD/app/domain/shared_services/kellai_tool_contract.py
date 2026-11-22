"""Kellai domain operation inputs; runtime identity and approval are not user data."""

KELLAI_MESSAGE_MAX_LENGTH = 8000

KELLAI_INPUT_SCHEMAS = {
    ("kellai", "channels"): {"type": "object", "properties": {}, "additionalProperties": False},
    ("kellai", "contacts"): {
        "type": "object",
        "additionalProperties": False,
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
    },
    ("kellai", "messages"): {
        "type": "object",
        "required": ["customer_id", "connection_id"],
        "additionalProperties": False,
        "properties": {
            "customer_id": {"type": "integer", "minimum": 1},
            "connection_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    },
    ("kellai", "send"): {
        "type": "object",
        "required": ["customer_id", "connection_id", "channel_type", "contact_id", "content"],
        "additionalProperties": False,
        "properties": {
            "customer_id": {"type": "integer", "minimum": 1},
            "connection_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "channel_type": {"type": "string", "pattern": "^[a-z0-9_-]{1,64}$"},
            "contact_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
                "pattern": r"[\s\S]*\S[\s\S]*",
            },
            "content": {
                "type": "string",
                "minLength": 1,
                "maxLength": KELLAI_MESSAGE_MAX_LENGTH,
                "pattern": r"[\s\S]*\S[\s\S]*",
            },
        },
    },
    ("kellai", "receipt"): {
        "type": "object",
        "required": ["client_request_id"],
        "additionalProperties": False,
        "properties": {
            "client_request_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{12,128}$"}
        },
    },
}
