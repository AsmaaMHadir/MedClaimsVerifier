"""
Knowledge Graph Service
Handles Neo4j queries for medical relationship verification
Uses async driver for better performance
"""

from typing import Optional, List, Dict, Any
from neo4j import AsyncGraphDatabase
from loguru import logger

from src.config.settings import get_settings
from src.services.cache import cached_drug_lookup, cached_disease_lookup, cached_relationship


class KnowledgeGraphService:
    """Service for querying Neo4j medical knowledge graph (async)"""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None
    ):
        settings = get_settings()
        self.uri = uri or settings.neo4j_uri
        self.user = user or settings.neo4j_user
        self.password = password or settings.neo4j_password
        self._driver = None

    async def _get_driver(self):
        """Get or create async Neo4j driver"""
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
        return self._driver

    async def close(self):
        """Close the Neo4j driver (async)"""
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def health_check(self) -> dict:
        """Check Neo4j connection health"""
        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run("RETURN 1 as test")
                await result.single()
            return {"status": "healthy"}
        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    # ==================== Drug-Disease Queries ====================

    async def check_drug_treats_disease(self, drug_name: str, disease_name: str) -> Dict[str, Any]:
        """
        Check if a drug treats a disease

        Args:
            drug_name: Name of the drug
            disease_name: Name of the disease

        Returns:
            Dict with 'found' boolean and 'evidence' list
        """
        query = """
        MATCH (d:Drug)-[r:TREATS]->(dis:Disease)
        WHERE toLower(d.name) CONTAINS toLower($drug)
          AND toLower(dis.name) CONTAINS toLower($disease)
        RETURN d.name as drug, dis.name as disease, type(r) as relationship
        LIMIT 5
        """
        return await self._execute_relationship_query(query, drug=drug_name, disease=disease_name)

    async def check_contraindication(self, drug_name: str, condition_name: str) -> Dict[str, Any]:
        """
        Check if a drug is contraindicated for a condition

        Args:
            drug_name: Name of the drug
            condition_name: Name of the condition

        Returns:
            Dict with 'found' boolean and 'evidence' list
        """
        query = """
        MATCH (d:Drug)-[r:CONTRAINDICATED_FOR]->(dis:Disease)
        WHERE toLower(d.name) CONTAINS toLower($drug)
          AND toLower(dis.name) CONTAINS toLower($condition)
        RETURN d.name as drug, dis.name as condition, type(r) as relationship
        LIMIT 5
        """
        return await self._execute_relationship_query(query, drug=drug_name, condition=condition_name)

    async def check_side_effect(self, drug_name: str, effect_name: str) -> Dict[str, Any]:
        """
        Check if a drug causes a side effect

        Args:
            drug_name: Name of the drug
            effect_name: Name of the side effect

        Returns:
            Dict with 'found' boolean and 'evidence' list
        """
        query = """
        MATCH (d:Drug)-[r:CAUSES_SIDE_EFFECT]->(e:Effect)
        WHERE toLower(d.name) CONTAINS toLower($drug)
          AND toLower(e.name) CONTAINS toLower($effect)
        RETURN d.name as drug, e.name as effect, type(r) as relationship
        LIMIT 5
        """
        return await self._execute_relationship_query(query, drug=drug_name, effect=effect_name)

    async def check_disease_symptom(self, disease_name: str, symptom_name: str) -> Dict[str, Any]:
        """
        Check if a disease has a symptom

        Args:
            disease_name: Name of the disease
            symptom_name: Name of the symptom

        Returns:
            Dict with 'found' boolean and 'evidence' list
        """
        query = """
        MATCH (dis:Disease)-[r:HAS_SYMPTOM]->(p:Phenotype)
        WHERE toLower(dis.name) CONTAINS toLower($disease)
          AND toLower(p.name) CONTAINS toLower($symptom)
        RETURN dis.name as disease, p.name as symptom, type(r) as relationship
        LIMIT 5
        """
        return await self._execute_relationship_query(query, disease=disease_name, symptom=symptom_name)

    async def check_drug_interaction(self, drug1_name: str, drug2_name: str) -> Dict[str, Any]:
        """
        Check if two drugs interact

        Args:
            drug1_name: Name of first drug
            drug2_name: Name of second drug

        Returns:
            Dict with 'found' boolean and 'evidence' list
        """
        query = """
        MATCH (d1:Drug)-[r:INTERACTS_WITH]-(d2:Drug)
        WHERE toLower(d1.name) CONTAINS toLower($drug1)
          AND toLower(d2.name) CONTAINS toLower($drug2)
        RETURN d1.name as drug1, d2.name as drug2, type(r) as relationship
        LIMIT 5
        """
        return await self._execute_relationship_query(query, drug1=drug1_name, drug2=drug2_name)

    # ==================== Entity Info Queries ====================

    async def get_drug_info(self, drug_name: str) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive information about a drug

        Args:
            drug_name: Name of the drug

        Returns:
            Dict with drug info or None if not found
        """
        query = """
        MATCH (d:Drug)
        WHERE toLower(d.name) CONTAINS toLower($drug)
        WITH d LIMIT 1
        OPTIONAL MATCH (d)-[:TREATS]->(dis:Disease)
        WITH d, collect(DISTINCT dis.name)[0..10] as indications
        OPTIONAL MATCH (d)-[:CONTRAINDICATED_FOR]->(contra:Disease)
        WITH d, indications, collect(DISTINCT contra.name)[0..10] as contraindications
        OPTIONAL MATCH (d)-[:CAUSES_SIDE_EFFECT]->(eff:Effect)
        WITH d, indications, contraindications, collect(DISTINCT eff.name)[0..10] as side_effects
        OPTIONAL MATCH (d)-[:INTERACTS_WITH]-(other:Drug)
        RETURN d.name as drug,
               indications,
               contraindications,
               side_effects,
               collect(DISTINCT other.name)[0..10] as interactions
        """
        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(query, drug=drug_name)
                record = await result.single()
                if record:
                    return dict(record)
                return None
        except Exception as e:
            logger.error(f"Failed to get drug info: {e}")
            return None

    async def get_disease_info(self, disease_name: str) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive information about a disease

        Args:
            disease_name: Name of the disease

        Returns:
            Dict with disease info or None if not found
        """
        query = """
        MATCH (dis:Disease)
        WHERE toLower(dis.name) CONTAINS toLower($disease)
        WITH dis LIMIT 1
        OPTIONAL MATCH (d:Drug)-[:TREATS]->(dis)
        WITH dis, collect(DISTINCT d.name)[0..10] as treatments
        OPTIONAL MATCH (dis)-[:HAS_SYMPTOM]->(p:Phenotype)
        WITH dis, treatments, collect(DISTINCT p.name)[0..10] as symptoms
        OPTIONAL MATCH (dis)-[:RELATED_DISEASE]-(related:Disease)
        RETURN dis.name as disease,
               treatments,
               symptoms,
               collect(DISTINCT related.name)[0..10] as related_conditions
        """
        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(query, disease=disease_name)
                record = await result.single()
                if record:
                    return dict(record)
                return None
        except Exception as e:
            logger.error(f"Failed to get disease info: {e}")
            return None

    # ==================== Subgraph Queries ====================

    def get_verification_subgraph(self, entities: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get subgraph data for visualization based on verified entities and evidence.

        Args:
            entities: List of entity dicts with 'name' and 'type'
            evidence: List of evidence dicts with 'subject', 'object', 'relationship'

        Returns:
            Dict with 'nodes' and 'edges' for graph visualization
        """
        nodes = []
        edges = []
        node_ids = set()

        # Add nodes from entities
        for i, entity in enumerate(entities):
            if entity.get("name") not in node_ids:
                nodes.append({
                    "id": entity.get("name", f"unknown_{i}"),
                    "name": entity.get("name", "Unknown"),
                    "type": entity.get("type", "Medical"),
                    "text": entity.get("text", "")
                })
                node_ids.add(entity.get("name"))

        # Add edges from evidence
        for ev in evidence:
            source = ev.get("subject", "")
            target = ev.get("object", "")
            relationship = ev.get("relationship", "RELATED")

            # Ensure source and target nodes exist
            if source and source not in node_ids:
                nodes.append({
                    "id": source,
                    "name": source,
                    "type": "Drug",
                    "text": source
                })
                node_ids.add(source)

            if target and target not in node_ids:
                nodes.append({
                    "id": target,
                    "name": target,
                    "type": "Disease",
                    "text": target
                })
                node_ids.add(target)

            if source and target:
                edges.append({
                    "source": source,
                    "target": target,
                    "relationship": relationship
                })

        return {
            "nodes": nodes,
            "edges": edges
        }

    async def get_entity_neighborhood(self, entity_name: str, entity_type: str, limit: int = 5) -> Dict[str, Any]:
        """
        Get the neighborhood of an entity for expanded visualization.

        Args:
            entity_name: Name of the entity
            entity_type: Type of entity (Drug, Disease, etc.)
            limit: Max neighbors to return

        Returns:
            Dict with 'nodes' and 'edges'
        """
        nodes = []
        edges = []

        if entity_type == "Drug":
            query = """
            MATCH (d:Drug)-[r]->(n)
            WHERE toLower(d.name) CONTAINS toLower($name)
            RETURN d.name as source, n.name as target, type(r) as relationship, labels(n)[0] as target_type
            LIMIT $limit
            """
        elif entity_type == "Disease":
            query = """
            MATCH (n)-[r]->(dis:Disease)
            WHERE toLower(dis.name) CONTAINS toLower($name)
            RETURN n.name as source, dis.name as target, type(r) as relationship, labels(n)[0] as source_type
            LIMIT $limit
            """
        else:
            return {"nodes": [], "edges": []}

        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(query, name=entity_name, limit=limit)
                records = [dict(r) async for r in result]

                node_ids = set()
                for r in records:
                    source = r.get("source", "")
                    target = r.get("target", "")

                    if source and source not in node_ids:
                        nodes.append({
                            "id": source,
                            "name": source,
                            "type": r.get("source_type", "Drug")
                        })
                        node_ids.add(source)

                    if target and target not in node_ids:
                        nodes.append({
                            "id": target,
                            "name": target,
                            "type": r.get("target_type", "Disease")
                        })
                        node_ids.add(target)

                    if source and target:
                        edges.append({
                            "source": source,
                            "target": target,
                            "relationship": r.get("relationship", "RELATED")
                        })

                return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logger.error(f"Failed to get entity neighborhood: {e}")
            return {"nodes": [], "edges": []}

    # ==================== Helper Methods ====================

    async def _execute_relationship_query(self, query: str, **params) -> Dict[str, Any]:
        """Execute a relationship query and return standardized result"""
        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(query, **params)
                records = [dict(r) async for r in result]
                return {
                    "found": len(records) > 0,
                    "evidence": records
                }
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {"found": False, "evidence": [], "error": str(e)}

    async def search_entity(self, name: str, label: str = None) -> List[Dict[str, Any]]:
        """
        Search for an entity by name

        Args:
            name: Name to search for
            label: Optional node label (Drug, Disease, etc.)

        Returns:
            List of matching entities
        """
        if label:
            query = f"""
            MATCH (n:{label})
            WHERE toLower(n.name) CONTAINS toLower($name)
            RETURN n.name as name, n.node_id as id, labels(n) as labels
            LIMIT 10
            """
        else:
            query = """
            MATCH (n)
            WHERE toLower(n.name) CONTAINS toLower($name)
            RETURN n.name as name, n.node_id as id, labels(n) as labels
            LIMIT 10
            """

        try:
            driver = await self._get_driver()
            async with driver.session() as session:
                result = await session.run(query, name=name)
                return [dict(r) async for r in result]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []


# Singleton instance
_kg_service: Optional[KnowledgeGraphService] = None


def get_knowledge_graph_service() -> KnowledgeGraphService:
    """Get singleton knowledge graph service instance"""
    global _kg_service
    if _kg_service is None:
        _kg_service = KnowledgeGraphService()
    return _kg_service
