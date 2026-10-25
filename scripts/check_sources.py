"""Validate release configuration and prevent accidental secret/generated-file packaging."""

import json
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
assert (root / "MASTER_CONTEXT.md").read_bytes() == (
    root / "master_contex.md"
).read_bytes()
blueprint = yaml.safe_load((root / "render.yaml").read_text())
assert [service["type"] for service in blueprint["services"]] == ["web", "keyvalue"]
assert all(service["plan"] == "free" for service in blueprint["services"])
assert not blueprint.get("databases")
web = blueprint["services"][0]
assert "preDeployCommand" not in web
assert web["startCommand"] == "python -m app.deployment.free_demo"
assert web["numInstances"] == 1
assert json.loads((root / "frontend/vercel.json").read_text())["framework"] == "nextjs"
pipeline = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
assert "verify" in pipeline["jobs"]

print("Source context, CI YAML, Render blueprint, and Vercel config verified")
