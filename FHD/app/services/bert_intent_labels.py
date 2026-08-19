"""Canonical label ordering for the BERT intent classifier."""

INTENT_LABELS = [
    "shipment_generate", "customers", "products", "shipments", "wechat_send",
    "print_label", "upload_file", "materials", "shipment_template", "template_extract",
    "business_docking", "template_preview", "shipment_records", "wechat", "printer_list",
    "settings", "tools_table", "other_tools", "ai_ecosystem", "excel_decompose",
    "show_images", "show_videos", "greet", "goodbye", "help", "negation",
    "customer_export", "customer_edit", "customer_supplement", "unk",
]

LABEL_TO_ID = {label: index for index, label in enumerate(INTENT_LABELS)}
ID_TO_LABEL = {index: label for index, label in enumerate(INTENT_LABELS)}

__all__ = ["ID_TO_LABEL", "INTENT_LABELS", "LABEL_TO_ID"]
