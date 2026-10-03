import json


def extract_model_output(data: dict) -> dict:
    for choice in data.get("choices", []):
        message = choice.get("message", {})

        text = (message.get("content") or "").strip()

        if not text:
            continue

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Groq returned invalid JSON"
            ) from exc

    raise ValueError("No model output found in Groq response")