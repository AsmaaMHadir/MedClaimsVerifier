"""
Configuration dataclass for the importable `MedVerifier` facade.

We deliberately use a stdlib dataclass (not pydantic-settings) so library
consumers don't inherit a hidden .env-parsing dependency. Anyone running the
FastAPI service still gets the full `pydantic-settings` flow via
`src/config/settings.py`; this is the slim parallel for in-process use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional


@dataclass
class MedVerifierConfig:
    """Explicit configuration for `MedVerifier`. Pass to the constructor directly,
    or call `MedVerifierConfig.from_env()` to read OS env vars (and optionally a .env file).

    Required:
        neo4j_uri, neo4j_password
    """

    # ----- Neo4j -----
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ----- Entity extraction (GLiNER) -----
    gliner_model: str = "Ihor/gliner-biomed-bi-large-v1.0"
    gliner_threshold: float = 0.5

    # ----- Lay-term canonicalisation (SapBERT) -----
    sapbert_index_dir: Path = field(default_factory=lambda: Path("data/sapbert"))
    sapbert_threshold: float = 0.77

    # ----- Drug normalization SQLite -----
    drug_norm_db: Path = field(default_factory=lambda: Path("data/drug_normalization.sqlite"))

    # ----- LLM predicate fallback -----
    enable_llm_fallback: bool = True
    anthropic_api_key: str = ""              # used if Bedrock not set
    aws_bearer_token_bedrock: str = ""        # takes precedence if set with bedrock_model
    aws_region: str = "us-east-1"
    bedrock_model: str = ""
    llm_model: str = "claude-haiku-4-5"
    llm_timeout_seconds: float = 8.0
    llm_min_confidence: float = 0.6

    # ----- Misc -----
    log_level: str = "INFO"

    # ============================================================

    def __post_init__(self) -> None:
        # Coerce path-like strings into Path objects so callers can pass either.
        if isinstance(self.sapbert_index_dir, str):
            self.sapbert_index_dir = Path(self.sapbert_index_dir)
        if isinstance(self.drug_norm_db, str):
            self.drug_norm_db = Path(self.drug_norm_db)
        if not self.neo4j_uri or not self.neo4j_password:
            raise ValueError(
                "MedVerifierConfig: neo4j_uri and neo4j_password are required. "
                "Pass them to the constructor or set NEO4J_URI / NEO4J_PASSWORD in the environment."
            )

    # ----- factory -----

    @classmethod
    def from_env(cls, dotenv_path: Optional[Path] = None) -> "MedVerifierConfig":
        """Read configuration from environment variables (and an optional .env file).

        Loads variables matching the dataclass field names in upper-case (e.g.
        `neo4j_uri` -> `NEO4J_URI`). Missing fields fall back to the dataclass default.
        """
        if dotenv_path is not None:
            _load_dotenv(dotenv_path)

        kwargs: dict = {}
        for f in fields(cls):
            env_key = f.name.upper()
            raw = os.environ.get(env_key)
            if raw is None or raw == "":
                continue
            kwargs[f.name] = _coerce(raw, f.type)
        return cls(**kwargs)


# ---------- helpers ----------

def _coerce(raw: str, hint: object) -> object:
    """Best-effort string -> typed value coercion for dataclass fields."""
    name = getattr(hint, "__name__", str(hint))
    if "bool" in name:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if "int" in name:
        return int(raw)
    if "float" in name:
        return float(raw)
    if "Path" in name:
        return Path(raw)
    return raw  # str fallback


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader. Lines like KEY=VALUE; comments and blanks ignored."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
