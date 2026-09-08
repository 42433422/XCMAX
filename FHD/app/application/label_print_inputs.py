"""Extract label model and count without treating units or specifications as models."""

import re


def extract_label_print_slots(text: str) -> dict:
    quantity = re.search(r"(?<![0-9A-Za-z.-])(\d+)\s*(?:张|份|个|次|条)", text)
    model_text = text
    if quantity:
        model_text = model_text[: quantity.start()] + " " + model_text[quantity.end() :]
    model_text = re.sub(r"规格\s*\d+(?:\.\d+)?", " ", model_text)
    model_text = re.sub(r"\d+(?:\.\d+)?\s*规格(?!\s*\d)", " ", model_text)
    models = re.findall(r"[0-9A-Za-z-]{2,}", model_text)
    # Multiple candidates need clarification; silently selecting the first could
    # print another product's labels.
    unique_models = list(dict.fromkeys(model.upper() for model in models))
    return {
        "model_number": unique_models[0] if len(unique_models) == 1 else "",
        "quantity": int(quantity.group(1)) if quantity else 1,
    }
