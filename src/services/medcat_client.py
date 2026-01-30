"""
MedCAT API Client
Handles communication with the MedCAT service on Modal
"""

import httpx
from typing import List, Optional
from loguru import logger

from src.config.settings import get_settings
from src.models.responses import Entity


class MedCATClient:
    """Client for MedCAT entity extraction service"""
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 60):
        settings = get_settings()
        self.base_url = base_url or settings.medcat_api_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def health_check(self) -> dict:
        """Check if MedCAT service is healthy"""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"MedCAT health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}
    
    async def extract_entities(self, text: str) -> List[Entity]:
        """
        Extract medical entities from text
        
        Args:
            text: Medical text to process
            
        Returns:
            List of extracted Entity objects
        """
        try:
            client = await self._get_client()
            
            logger.debug(f"Extracting entities from text: {text[:100]}...")
            
            response = await client.post(
                "/extract",
                json={"text": text}
            )
            response.raise_for_status()
            
            data = response.json()
            
            entities = []
            for ent in data.get("entities", []):
                # Map MedCAT types to simplified types
                entity_type = self._map_entity_type(ent.get("types", []))
                
                entities.append(Entity(
                    text=ent.get("text", ""),
                    cui=ent.get("cui", ""),
                    name=ent.get("name", ent.get("text", "")),
                    type=entity_type,
                    confidence=ent.get("confidence", 0.0),
                    start=ent.get("start"),
                    end=ent.get("end"),
                    negated=ent.get("negated", False)
                ))
            
            logger.info(f"Extracted {len(entities)} entities")
            return entities
            
        except httpx.TimeoutException:
            logger.error("MedCAT request timed out (cold start may take up to 60s)")
            raise
        except Exception as e:
            logger.error(f"MedCAT extraction failed: {e}")
            raise
    
    def _map_entity_type(self, types: List[str]) -> str:
        """
        Map SNOMED/UMLS semantic types to simplified categories
        
        Common types:
        - T047: Disease or Syndrome
        - T184: Sign or Symptom
        - T121: Pharmacologic Substance
        - T109: Organic Chemical
        - T023: Body Part
        - T028: Gene or Genome
        """
        type_str = " ".join(types).lower()
        
        # Check for drug indicators
        if any(t in type_str for t in ["t121", "t109", "drug", "pharma", "medication"]):
            return "Drug"
        
        # Check for disease indicators
        if any(t in type_str for t in ["t047", "disease", "disorder", "syndrome"]):
            return "Disease"
        
        # Check for symptom indicators
        if any(t in type_str for t in ["t184", "symptom", "sign", "finding"]):
            return "Symptom"
        
        # Check for anatomy
        if any(t in type_str for t in ["t023", "anatomy", "body"]):
            return "Anatomy"
        
        # Check for genes
        if any(t in type_str for t in ["t028", "gene", "protein"]):
            return "Gene"
        
        return "Medical"


# Singleton instance
_medcat_client: Optional[MedCATClient] = None


def get_medcat_client() -> MedCATClient:
    """Get singleton MedCAT client instance"""
    global _medcat_client
    if _medcat_client is None:
        _medcat_client = MedCATClient()
    return _medcat_client
