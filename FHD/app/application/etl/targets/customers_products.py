"""Compatibility exports for customer and product ETL adapters."""

from app.application.etl.targets.customer_products import CustomerProductsAdapter
from app.application.etl.targets.customers import CustomerAdapter
from app.application.etl.targets.products import ProductAdapter

__all__ = ["CustomerAdapter", "CustomerProductsAdapter", "ProductAdapter"]
