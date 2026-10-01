TRIAGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "urgency": {
            "type": "string",
            "enum": ["Critical", "High", "Medium", "Low"],
        },
        "category": {
            "type": "string",
            "enum": [
                "Billing",
                "Technical",
                "Account",
                "Feedback",
                "Other",
            ],
        },
        "sentiment": {
            "type": "string",
            "enum": [
                "Angry",
                "Frustrated",
                "Neutral",
                "Happy",
            ],
        },
        "suggested_reply": {
            "type": "string",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "rationale": {
            "type": "string",
            "maxLength": 240,
        },
        "needs_human_review": {
            "type": "boolean",
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "urgency",
        "category",
        "sentiment",
        "suggested_reply",
        "confidence",
        "rationale",
        "needs_human_review",
        "tags",
    ],
}