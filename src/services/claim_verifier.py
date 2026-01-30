"""
Claim Verifier Service
Core verification logic that combines GLiNER entities with Neo4j knowledge graph
"""

from typing import List
from loguru import logger

from src.models.responses import (
    Entity,
    Evidence,
    ClaimVerification,
    VerificationStatus
)
from src.services.gliner_client import GLiNERClient, get_gliner_client
from src.services.knowledge_graph import KnowledgeGraphService, get_knowledge_graph_service


class ClaimVerifier:
    """
    Verifies medical claims by:
    1. Extracting entities from text using GLiNER (zero-shot NER)
    2. Checking relationships in Neo4j knowledge graph
    3. Returning structured verification results
    """

    def __init__(
        self,
        entity_extractor: GLiNERClient = None,
        kg_service: KnowledgeGraphService = None
    ):
        self.extractor = entity_extractor or get_gliner_client()
        self.kg = kg_service or get_knowledge_graph_service()
    
    async def verify_text(self, text: str) -> List[ClaimVerification]:
        """
        Verify medical claims in text

        Args:
            text: Medical text to verify

        Returns:
            List of ClaimVerification objects
        """
        # Step 1: Extract entities using GLiNER
        logger.info(f"Verifying text: {text[:100]}...")
        entities = await self.extractor.extract_entities(text)

        if not entities:
            logger.warning("No entities extracted from text")
            return [ClaimVerification(
                claim="No medical entities detected",
                status=VerificationStatus.UNKNOWN,
                confidence=0.0,
                entities=[],
                evidence=[]
            )]

        # Step 2: Group entities by type (GLiNER provides types directly - no inference needed)
        drugs = [e for e in entities if e.type == "Drug" and not e.negated]
        diseases = [e for e in entities if e.type == "Disease" and not e.negated]
        symptoms = [e for e in entities if e.type == "Symptom" and not e.negated]

        logger.info(f"Found: {len(drugs)} drugs, {len(diseases)} diseases, {len(symptoms)} symptoms")

        # Step 4: Verify relationships
        verifications = []

        # Check drug-disease relationships
        for drug in drugs:
            for disease in diseases:
                verification = await self._verify_drug_disease(drug, disease)
                if verification:
                    verifications.append(verification)

        # Check drug-symptom relationships (side effects)
        for drug in drugs:
            for symptom in symptoms:
                verification = await self._verify_drug_side_effect(drug, symptom)
                if verification:
                    verifications.append(verification)

        # Check disease-symptom relationships
        for disease in diseases:
            for symptom in symptoms:
                verification = await self._verify_disease_symptom(disease, symptom)
                if verification:
                    verifications.append(verification)

        # Check drug-drug interactions
        if len(drugs) >= 2:
            for i, drug1 in enumerate(drugs):
                for drug2 in drugs[i+1:]:
                    verification = await self._verify_drug_interaction(drug1, drug2)
                    if verification:
                        verifications.append(verification)
        
        # If no specific claims verified, return entity summary
        if not verifications and entities:
            verifications.append(ClaimVerification(
                claim="Medical entities detected but no specific relationships verified",
                status=VerificationStatus.PARTIAL,
                confidence=0.5,
                entities=entities,
                evidence=[]
            ))
        
        return verifications
    
    async def _verify_drug_disease(self, drug: Entity, disease: Entity) -> ClaimVerification:
        """Verify drug-disease relationship (TREATS or CONTRAINDICATED)"""

        # Use original text for better Neo4j matching
        drug_name = self._get_search_term(drug)
        disease_name = self._get_search_term(disease)

        # First check if drug treats disease
        treats_result = await self.kg.check_drug_treats_disease(drug_name, disease_name)
        
        if treats_result["found"]:
            evidence = [
                Evidence(
                    source="PrimeKG",
                    relationship="TREATS",
                    subject=e.get("drug", drug.name),
                    object=e.get("disease", disease.name)
                )
                for e in treats_result["evidence"][:3]
            ]
            
            return ClaimVerification(
                claim=f"{drug.name} treats {disease.name}",
                status=VerificationStatus.SUPPORTED,
                confidence=self._calculate_confidence(drug, disease, treats_result),
                entities=[drug, disease],
                evidence=evidence
            )
        
        # Check if contraindicated
        contra_result = await self.kg.check_contraindication(drug_name, disease_name)
        
        if contra_result["found"]:
            evidence = [
                Evidence(
                    source="PrimeKG",
                    relationship="CONTRAINDICATED_FOR",
                    subject=e.get("drug", drug.name),
                    object=e.get("condition", disease.name)
                )
                for e in contra_result["evidence"][:3]
            ]
            
            return ClaimVerification(
                claim=f"{drug.name} for {disease.name}",
                status=VerificationStatus.CONTRADICTED,
                confidence=self._calculate_confidence(drug, disease, contra_result),
                entities=[drug, disease],
                evidence=evidence
            )
        
        # No relationship found
        return ClaimVerification(
            claim=f"{drug.name} - {disease.name} relationship",
            status=VerificationStatus.NOT_FOUND,
            confidence=0.3,
            entities=[drug, disease],
            evidence=[]
        )
    
    async def _verify_drug_side_effect(self, drug: Entity, symptom: Entity) -> ClaimVerification:
        """Verify if drug causes a side effect"""

        drug_name = self._get_search_term(drug)
        symptom_name = self._get_search_term(symptom)
        result = await self.kg.check_side_effect(drug_name, symptom_name)
        
        if result["found"]:
            evidence = [
                Evidence(
                    source="PrimeKG",
                    relationship="CAUSES_SIDE_EFFECT",
                    subject=e.get("drug", drug.name),
                    object=e.get("effect", symptom.name)
                )
                for e in result["evidence"][:3]
            ]
            
            return ClaimVerification(
                claim=f"{drug.name} may cause {symptom.name}",
                status=VerificationStatus.SUPPORTED,
                confidence=self._calculate_confidence(drug, symptom, result),
                entities=[drug, symptom],
                evidence=evidence
            )
        
        return None  # Don't report NOT_FOUND for side effects
    
    async def _verify_disease_symptom(self, disease: Entity, symptom: Entity) -> ClaimVerification:
        """Verify if disease has a symptom"""

        disease_name = self._get_search_term(disease)
        symptom_name = self._get_search_term(symptom)
        result = await self.kg.check_disease_symptom(disease_name, symptom_name)
        
        if result["found"]:
            evidence = [
                Evidence(
                    source="PrimeKG",
                    relationship="HAS_SYMPTOM",
                    subject=e.get("disease", disease.name),
                    object=e.get("symptom", symptom.name)
                )
                for e in result["evidence"][:3]
            ]
            
            return ClaimVerification(
                claim=f"{disease.name} presents with {symptom.name}",
                status=VerificationStatus.SUPPORTED,
                confidence=self._calculate_confidence(disease, symptom, result),
                entities=[disease, symptom],
                evidence=evidence
            )
        
        return None  # Don't report NOT_FOUND for symptoms
    
    async def _verify_drug_interaction(self, drug1: Entity, drug2: Entity) -> ClaimVerification:
        """Verify if two drugs interact"""

        drug1_name = self._get_search_term(drug1)
        drug2_name = self._get_search_term(drug2)
        result = await self.kg.check_drug_interaction(drug1_name, drug2_name)
        
        if result["found"]:
            evidence = [
                Evidence(
                    source="PrimeKG",
                    relationship="INTERACTS_WITH",
                    subject=e.get("drug1", drug1.name),
                    object=e.get("drug2", drug2.name)
                )
                for e in result["evidence"][:3]
            ]
            
            return ClaimVerification(
                claim=f"{drug1.name} interacts with {drug2.name}",
                status=VerificationStatus.SUPPORTED,
                confidence=self._calculate_confidence(drug1, drug2, result),
                entities=[drug1, drug2],
                evidence=evidence
            )
        
        return None  # Don't report NOT_FOUND for interactions
    
    def _get_search_term(self, entity: Entity) -> str:
        """
        Get the best search term for Neo4j lookup.

        Prefers entity.text (original input words) over entity.name (canonical SNOMED name)
        because original text matches Neo4j's normalized names much better.

        Example:
        - entity.text = "Hypertension" (matches Neo4j)
        - entity.name = "Hypertensive disorder, systemic arterial" (doesn't match)
        """
        # Prefer original text, fall back to canonical name
        search_term = entity.text if entity.text else entity.name
        return self._normalize_name(search_term)

    def _normalize_name(self, name: str) -> str:
        """
        Normalize entity name for better Neo4j matching.

        Handles cases like:
        - "Diabetes mellitus type 2" -> "type 2 diabetes"
        - "Metformin hydrochloride" -> "metformin"
        """
        name_lower = name.lower().strip()

        # Remove common suffixes that don't affect matching
        for suffix in [" hydrochloride", " sodium", " (disease)", " mellitus"]:
            name_lower = name_lower.replace(suffix, "")

        # For "X type N" patterns, try to reorder to "type N X"
        import re
        # Match patterns like "diabetes type 2" -> "type 2 diabetes"
        type_match = re.match(r"(.+?)\s+type\s+(\d+)$", name_lower)
        if type_match:
            base_name, type_num = type_match.groups()
            return f"type {type_num} {base_name}".strip()

        return name_lower.strip()

    def _calculate_confidence(
        self,
        entity1: Entity,
        entity2: Entity,
        kg_result: dict
    ) -> float:
        """
        Calculate overall confidence score
        
        Combines:
        - Entity extraction confidence
        - Number of evidence items found
        """
        # Average entity confidence
        entity_conf = (entity1.confidence + entity2.confidence) / 2
        
        # Evidence factor (more evidence = higher confidence)
        evidence_count = len(kg_result.get("evidence", []))
        evidence_factor = min(evidence_count / 3, 1.0)  # Cap at 3 pieces of evidence
        
        # Weighted combination
        confidence = (entity_conf * 0.6) + (evidence_factor * 0.4)
        
        return round(min(confidence, 1.0), 2)


# Factory function
def get_claim_verifier() -> ClaimVerifier:
    """Get claim verifier instance"""
    return ClaimVerifier()
