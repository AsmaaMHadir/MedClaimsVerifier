"""medverify-core: in-process medical claim verifier.

Public surface:

    from medverify_core import MedVerifier, MedVerifierConfig
    from medverify_core import VerificationStatus, Entity, Evidence
"""

from src.models.responses import (
    ClaimVerification,
    DiseaseInfo,
    DrugInfo,
    Entity,
    Evidence,
    VerificationStatus,
)

from .config import MedVerifierConfig
from .verifier import MedVerifier

__all__ = [
    "MedVerifier",
    "MedVerifierConfig",
    "VerificationStatus",
    "ClaimVerification",
    "Entity",
    "Evidence",
    "DrugInfo",
    "DiseaseInfo",
]

__version__ = "0.1.0"
