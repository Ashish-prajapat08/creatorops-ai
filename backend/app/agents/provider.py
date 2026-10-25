"""Bounded structured generation; business/evidence validation stays with callers."""

import json

from openai import OpenAI
from pydantic import ValidationError

from app.core.config import settings
from app.core.errors import AppError


def nvidia_schema(schema):
    """Translate Decimal wire constraints to NVIDIA's regular-expression subset.

    The original Pydantic schema still validates every returned value locally.
    """

    def convert(node):
        if isinstance(node, list):
            return [convert(value) for value in node]
        if not isinstance(node, dict):
            return node
        result = {key: convert(value) for key, value in node.items()}
        if result.get("type") == "string" and "decimal_places" in result:
            places = result.pop("decimal_places")
            result.pop("max_digits", None)
            result.pop("gt", None)
            result["pattern"] = rf"^[0-9]+(\.[0-9]{{1,{places}}})?$"
        return result

    return convert(schema.model_json_schema(mode="serialization"))


def generate_structured(prompt, context, schema, *, validator=None):
    cfg = settings()
    key = cfg.nvidia_api_key if cfg.ai_provider == "nvidia" else cfg.openai_api_key
    if not key:
        raise AppError("AI_NOT_CONFIGURED", "Configure the selected AI provider", 503)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(context)},
    ]
    if cfg.ai_provider == "openai":
        response = OpenAI(api_key=key, timeout=45, max_retries=0).responses.parse(
            model=cfg.ai_model, input=messages, text_format=schema, store=False
        )
        if response.output_parsed is None:
            raise AppError("AI_REFUSED", "No valid structured output was returned", 422)
        result = response.output_parsed.model_dump(mode="json")
        if validator:
            validator(result, context)
        return result
    json_schema = nvidia_schema(schema)
    # Some compatible endpoints accept response_format without enforcing nested shapes.
    # Describe the exact contract in the system message too; never relax local validation.
    messages[0]["content"] += (
        "\nReturn exactly one JSON object conforming to this JSON Schema. "
        "Include every required field; nested objects must remain objects, not summaries. "
        "No markdown, commentary, extra keys, or reasoning in the final content.\n"
        + json.dumps(json_schema)
    )
    client = OpenAI(
        api_key=key,
        base_url="https://integrate.api.nvidia.com/v1",
        timeout=90,
        max_retries=0,
    )
    for attempt in range(2):
        response = client.chat.completions.create(
            model=cfg.ai_model,
            messages=messages,
            temperature=0,
            max_tokens=4096,
            stream=False,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": json_schema,
                },
            },
        )
        if not response.choices:
            raise AppError("AI_REFUSED", "No structured output was returned", 422)
        choice = response.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            raise AppError("AI_REFUSED", "Incomplete or refused structured output", 422)
        try:
            result = schema.model_validate_json(choice.message.content).model_dump(mode="json")
            if validator:
                validator(result, context)
            return result
        except AppError as exc:
            if exc.code != "INVALID_AI_EVIDENCE" or attempt:
                raise
            # Fixed application-authored validation messages only, never raw model output.
            messages = [
                {
                    "role": "system",
                    "content": messages[0]["content"]
                    + "\nThe previous attempt failed evidence validation: "
                    + exc.message
                    + " Generate a fresh complete object. Copy quotes exactly from subject/body. "
                    "Include a separate labelled evidence item for every extracted field. "
                    "Use null for unsupported fields; never invent or repair source facts.",
                },
                messages[1],
            ]
        except ValidationError as exc:
            if attempt:
                raise AppError(
                    "INVALID_AI_OUTPUT", "Model output did not match the required schema", 422
                ) from None
            # Only trusted schema paths/types go back to the model, never raw model output
            # (which can contain mailbox content or prompt-injection instructions).
            errors = [
                {"field": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_input=False, include_url=False)
                if error["type"] != "extra_forbidden"
            ][:10]
            messages = [
                {
                    "role": "system",
                    "content": messages[0]["content"]
                    + "\nThe previous attempt failed validation. Generate a fresh complete object. "
                    "Validation issues: " + json.dumps(errors),
                },
                messages[1],
            ]
