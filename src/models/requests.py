"""
Request models for MedVerify API
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class VerifyOptions(BaseModel):
    """Options for verification"""
    check_contraindications: bool = True
    check_side_effects: bool = True
    include_evidence: bool = True
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class VerifyRequest(BaseModel):
    """Request model for claim verification"""
    text: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="Medical text to verify"
    )
    options: Optional[VerifyOptions] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "Metformin is commonly prescribed to treat Type 2 Diabetes.",
                "options": {
                    "check_contraindications": True,
                    "check_side_effects": True
                }
            }
        }
    )


class ExtractRequest(BaseModel):
    """Request model for entity extraction"""
    text: str = Field(
        ...,
        min_length=1,
        max_length=50000,
        description="Text to extract medical entities from"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "Patient diagnosed with diabetes and hypertension."
            }
        }
    )
