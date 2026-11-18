"""Explicit public failures from external knowledge-source adapters."""


class DocumentSourceError(ValueError):
    """A controlled validation message, independent of the diagnostic exception.

    Only pass product-authored messages and deliberate public input details here.
    Preserve unexpected upstream errors as the cause for server-side logging.
    """

    def __init__(self, public_detail: str) -> None:
        super().__init__(public_detail)
        self.public_detail = public_detail
