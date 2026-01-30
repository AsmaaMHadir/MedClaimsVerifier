"""
Response models for MedVerify API
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class VerificationStatus(str, Enum):
    """Status of a claim verification"""
    SUPPORTED = "SUPPORTED"           # Claim found in knowledge graph
    CONTRADICTED = "CONTRADICTED"     # Claim conflicts with knowledge graph
    NOT_FOUND = "NOT_FOUND"          # Entities found but no relationship
    PARTIAL = "PARTIAL"              # Some claims verified, others not
    UNKNOWN = "UNKNOWN"              # Could not extract entities


class Entity(BaseModel):
    """A medical entity extracted from text"""
    text: str = Field(..., description="Original text span")
    cui: str = Field(..., description="Concept Unique Identifier")
    name: str = Field(..., description="Canonical name")
    type: str = Field(..., description="Entity type (Drug, Disease, Symptom)")
    confidence: float = Field(..., description="Extraction confidence (0-1)")
    start: Optional[int] = Field(None, description="Start character offset")
    end: Optional[int] = Field(None, description="End character offset")
    negated: bool = Field(False, description="Whether entity is negated")


class Evidence(BaseModel):
    """Evidence supporting a verification"""
    source: str = Field(..., description="Data source (e.g., PrimeKG)")
    relationship: str = Field(..., description="Relationship type")
    subject: str = Field(..., description="Subject of relationship")
    object: str = Field(..., description="Object of relationship")


class ClaimVerification(BaseModel):
    """Verification result for a single claim"""
    claim: str = Field(..., description="The claim being verified")
    status: VerificationStatus = Field(..., description="Verification status")
    confidence: float = Field(..., description="Overall confidence (0-1)")
    entities: List[Entity] = Field(default=[], description="Entities in claim")
    evidence: List[Evidence] = Field(default=[], description="Supporting evidence")


class VerifyResponse(BaseModel):
    """Response model for verification endpoint"""
    success: bool = Field(..., description="Whether request succeeded")
    claims: List[ClaimVerification] = Field(default=[], description="Verified claims")
    warnings: List[str] = Field(default=[], description="Any warnings")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "claims": [
                    {
                        "claim": "Metformin treats Type 2 Diabetes",
                        "status": "SUPPORTED",
                        "confidence": 0.95,
                        "entities": [
                            {"text": "Metformin", "cui": "C0025598", "name": "Metformin", "type": "Drug", "confidence": 0.98},
                            {"text": "Type 2 Diabetes", "cui": "C0011860", "name": "Diabetes Mellitus, Type 2", "type": "Disease", "confidence": 0.95}
                        ],
                        "evidence": [
                            {"source": "PrimeKG", "relationship": "TREATS", "subject": "Metformin", "object": "Diabetes Mellitus, Type 2"}
                        ]
                    }
                ],
                "warnings": [],
                "processing_time_ms": 245.5
            }
        }
    )


class ExtractResponse(BaseModel):
    """Response model for entity extraction endpoint"""
    success: bool = True
    entities: List[Entity] = Field(default=[], description="Extracted entities")
    count: int = Field(..., description="Number of entities found")


class DrugInfo(BaseModel):
    """Drug information from knowledge graph"""
    drug: str
    indications: List[str] = Field(default=[], description="Diseases this drug treats")
    contraindications: List[str] = Field(default=[], description="Conditions where drug is contraindicated")
    side_effects: List[str] = Field(default=[], description="Known side effects")
    interactions: List[str] = Field(default=[], description="Drug interactions")


class DiseaseInfo(BaseModel):
    """Disease information from knowledge graph"""
    disease: str
    treatments: List[str] = Field(default=[], description="Drugs that treat this disease")
    symptoms: List[str] = Field(default=[], description="Associated symptoms")
    related_conditions: List[str] = Field(default=[], description="Related diseases")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = Field(..., description="Overall status (healthy, degraded, unhealthy)")
    services: Dict[str, Dict[str, Any]] = Field(..., description="Individual service statuses")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    """Error response model"""
    success: bool = False
    error: Dict[str, str] = Field(..., description="Error details")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "MedCAT service is not responding"
                }
            }
        }
    )
