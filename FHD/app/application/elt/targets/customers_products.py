"""Compatibility exports for customer and product ETL adapters."""

from app.application.elt.targets.customer_products import CustomerProductsAdapter
from app.application.elt.targets.customers import CustomerAdapter
from app.application.elt.targets.products import ProductAdapter

__all__ = ["CustomerAdapter", "CustomerProductsAdapter", "ProductAdapter"]
