import json


def extract_model_output(data: dict) -> dict:
    steps = data.get("steps", [])

    for step in steps:
        if step.get("type") != "model_output":
            continue

        for content in step.get("content", []):
            if content.get("type") != "text":
                continue

            text = content.get("text", "").strip()

            if not text:
                continue

            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Gemini returned invalid JSON"
                ) from exc

    raise ValueError("No model output found in Gemini response")