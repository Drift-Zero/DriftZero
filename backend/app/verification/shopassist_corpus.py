"""The built-in ShopAssist verification corpus.

This is the "trusted source the owner already has" made concrete: the store's
own policies and catalogue. It exists so a new user can demonstrate the whole
loop without first uploading anything.

The retired returns policy is included on purpose. It stays readable as history
-- an operator can ask what the old rule said -- while being excluded from
current verification, which is exactly the distinction the stale-policy
scenario is built to show.
"""

from __future__ import annotations

from typing import Any

CORPUS_NAME = "ShopAssist knowledge base"
RETIRED_CORPUS_NAME = "ShopAssist knowledge base (retired returns policy)"

# Each chunk carries prose for a human and structured facts for the comparator.
# ``terms`` scope a fact to the claims it may settle, so a shipping figure can
# never be compared against a returns claim.
CURRENT_CHUNKS: list[dict[str, Any]] = [
    {
        "text": (
            "Returns Policy v2.1 (current). Electronics -- including headphones, "
            "smartwatches and speakers -- can be returned within 14 days with a receipt. "
            "All other unused items can be returned within 30 days. Clearance items are "
            "final sale unless damaged or defective."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "electronics_return_window_days",
                    "label": "Electronics return window",
                    "value": 14,
                    "unit": "days",
                    "terms": ["return", "electronics"],
                },
                {
                    "key": "general_return_window_days",
                    "label": "General return window",
                    "value": 30,
                    "unit": "days",
                    "terms": ["return", "unused"],
                },
                {
                    "key": "headphones_return_window_days",
                    "label": "Headphones return window",
                    "value": 14,
                    "unit": "days",
                    "terms": ["return", "headphone"],
                },
                {
                    "key": "smartwatch_return_window_days",
                    "label": "Smartwatch return window",
                    "value": 14,
                    "unit": "days",
                    "terms": ["return", "smartwatch"],
                },
                {
                    "key": "speaker_return_window_days",
                    "label": "Speaker return window",
                    "value": 14,
                    "unit": "days",
                    "terms": ["return", "speaker"],
                },
            ]
        },
        "metadata": {"section": "returns", "policy_version": "v2.1"},
    },
    {
        "text": (
            "Refunds Policy v2.1. Approved refunds are issued to the original payment "
            "method within 5 business days of the returned item being received."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "refund_days",
                    "label": "Refund processing time",
                    "value": 5,
                    "unit": "days",
                    "terms": ["refund"],
                }
            ]
        },
        "metadata": {"section": "refunds"},
    },
    {
        "text": (
            "Electronics Warranty v3.0. Electronics carry a 12 month manufacturer "
            "warranty covering defects. Accidental damage is not covered."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "warranty_months",
                    "label": "Electronics warranty length",
                    "value": 12,
                    "unit": "months",
                    "terms": ["warranty", "electronics"],
                }
            ]
        },
        "metadata": {"section": "warranty"},
    },
    {
        "text": (
            "Shipping Guide v2.3. Standard delivery arrives in 5 business days. "
            "Express delivery arrives in 2 business days."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "standard_shipping_days",
                    "label": "Standard delivery time",
                    "value": 5,
                    "unit": "days",
                    "terms": ["shipping", "standard"],
                },
                {
                    "key": "express_shipping_days",
                    "label": "Express delivery time",
                    "value": 2,
                    "unit": "days",
                    "terms": ["shipping", "express"],
                },
            ]
        },
        "metadata": {"section": "shipping"},
    },
    {
        "text": (
            "Product catalogue snapshot. Nova ANC Headphones cost $149 with 18 in stock. "
            "Pulse Smartwatch costs $229 with 7 in stock. Arc Mini Speaker costs $79 and "
            "is sold out. Loom Everyday Hoodie costs $64 with 31 in stock. Stride Runner "
            "costs $118 with 12 in stock."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "nova_headphones_price",
                    "label": "Nova ANC Headphones price",
                    "value": 149,
                    "unit": "currency",
                    "terms": ["nova", "headphone", "price"],
                },
                {
                    "key": "pulse_smartwatch_price",
                    "label": "Pulse Smartwatch price",
                    "value": 229,
                    "unit": "currency",
                    "terms": ["pulse", "smartwatch", "price"],
                },
                {
                    "key": "arc_mini_speaker_available",
                    "label": "Arc Mini Speaker availability",
                    "value": False,
                    "terms": ["arc", "speaker"],
                },
            ]
        },
        "metadata": {"section": "catalogue"},
    },
    {
        "text": (
            "Promotions ledger v5.2. The SAVE20 campaign ended and is no longer valid. "
            "The current promotion is WELCOME10, giving 10 percent off a first order."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "welcome_discount_percent",
                    "label": "Current promotion discount",
                    "value": 10,
                    "unit": "percent",
                    "terms": ["promotion", "discount"],
                }
            ]
        },
        "metadata": {"section": "promotions"},
    },
    {
        "text": (
            "Demo orders. Order DZ-1042 shipped on 1 September. Order DZ-2088 is in "
            "transit. Order DZ-3190 was delivered on 4 September."
        ),
        "structured_facts": {"facts": []},
        "metadata": {"section": "orders"},
    },
]

# The superseded rule, kept as history. Its 30-day electronics window is the
# answer a drifted model gives.
RETIRED_CHUNKS: list[dict[str, Any]] = [
    {
        "text": (
            "Returns Policy v1.4 (retired). Electronics can be returned within 30 days "
            "with a receipt."
        ),
        "structured_facts": {
            "facts": [
                {
                    "key": "electronics_return_window_days",
                    "label": "Electronics return window (retired policy)",
                    "value": 30,
                    "unit": "days",
                    "terms": ["return", "electronics"],
                }
            ]
        },
        "metadata": {"section": "returns", "policy_version": "v1.4", "retired": True},
    }
]
