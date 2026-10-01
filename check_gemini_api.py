"""Manual Gemini connectivity check.

Run explicitly:

    python check_gemini_api.py

This module performs no network call on import, so pytest (or any other
tool that merely imports it) never triggers an API request.
"""

import os
import json

import httpx
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

url = "https://generativelanguage.googleapis.com/v1beta/interactions"

schema = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["billing", "technical", "account", "other"],
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "sentiment": {
            "type": "string",
            "enum": ["positive", "neutral", "negative"],
        },
        "summary": {
            "type": "string",
        },
    },
    "required": [
        "category",
        "priority",
        "sentiment",
        "summary",
    ],
}

payload = {
    "model": "gemini-3.5-flash-lite",
    "input": """
    Classify this customer support ticket:

    "I was charged twice for my subscription this month.
    Please refund the duplicate payment."
    """,
    "response_format": {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    },
}


def main() -> None:
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    response = httpx.post(
        url,
        headers=headers,
        json=payload,
        timeout=60,
    )

    print("Status:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return

    data = response.json()

    output_text = None

    for step in data.get("steps", []):
        if step.get("type") == "model_output":
            for content in step.get("content", []):
                if content.get("type") == "text":
                    output_text = content.get("text")

    print("Raw structured output:")
    print(output_text)

    if output_text:
        result = json.loads(output_text)

        print("\nParsed JSON:")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()