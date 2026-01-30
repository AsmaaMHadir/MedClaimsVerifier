"""
PrimeKG to Neo4j Import Script (Memory-Efficient)
Processes the CSV in chunks to avoid memory issues.

Usage:
    python import_primekg_chunked.py --kg-path ./kg.csv --neo4j-uri bolt://localhost:7687
"""

import argparse
import csv
from neo4j import GraphDatabase
from collections import defaultdict
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Priority relationships for medical claim verification
PRIORITY_RELATIONS = {
    'indication',
    'contraindication', 
    'drug_effect',
    'off-label use',
    'disease_phenotype_positive',
    'disease_phenotype_negative',
    'drug_drug',
    'disease_protein',
    'drug_protein',
    'disease_disease',
}

def get_node_label(node_type: str) -> str:
    """Map PrimeKG node types to Neo4j labels"""
    mapping = {
        'gene/protein': 'Gene',
        'drug': 'Drug',
        'disease': 'Disease',
        'phenotype': 'Phenotype',
        'effect/phenotype': 'Effect',
        'anatomy': 'Anatomy',
        'biological_process': 'BiologicalProcess',
        'molecular_function': 'MolecularFunction',
        'cellular_component': 'CellularComponent',
        'pathway': 'Pathway',
        'exposure': 'Exposure',
    }
    return mapping.get(node_type, 'Entity')

def get_relationship_type(relation: str) -> str:
    """Map PrimeKG relations to Neo4j relationship types"""
    mapping = {
        'indication': 'TREATS',
        'contraindication': 'CONTRAINDICATED_FOR',
        'drug_effect': 'CAUSES_SIDE_EFFECT',
        'off-label use': 'OFF_LABEL_FOR',
        'drug_drug': 'INTERACTS_WITH',
        'drug_protein': 'TARGETS',
        'disease_phenotype_positive': 'HAS_SYMPTOM',
        'disease_phenotype_negative': 'EXCLUDES_SYMPTOM',
        'disease_protein': 'ASSOCIATED_WITH_GENE',
        'disease_disease': 'RELATED_DISEASE',
        'protein_protein': 'PPI',
    }
    return mapping.get(relation, relation.upper().replace('-', '_').replace(' ', '_'))


class ChunkedImporter:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Connected to Neo4j at {uri}")
        
    def close(self):
        self.driver.close()
    
    def clear_database(self):
        """Clear all nodes and relationships"""
        with self.driver.session() as session:
            # Delete in batches to avoid timeout
            logger.info("Clearing database...")
            while True:
                result = session.run("""
                    MATCH (n) 
                    WITH n LIMIT 10000 
                    DETACH DELETE n 
                    RETURN count(*) as deleted
                """)
                deleted = result.single()["deleted"]
                if deleted == 0:
                    break
                logger.info(f"  Deleted {deleted} nodes...")
            logger.info("Database cleared")
    
    def create_constraints_and_indexes(self):
        """Create constraints and indexes"""
        with self.driver.session() as session:
            # Create unique constraints (which also create indexes)
            labels = ['Drug', 'Disease', 'Gene', 'Phenotype', 'Effect', 
                     'Anatomy', 'BiologicalProcess', 'MolecularFunction', 
                     'CellularComponent', 'Pathway', 'Exposure', 'Entity']
            
            for label in labels:
                try:
                    session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.node_index)")
                    session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.name)")
                except Exception as e:
                    logger.debug(f"Index note for {label}: {e}")
            
            logger.info("Indexes created")
    
    def process_csv_chunked(self, kg_path: str, priority_only: bool = True, chunk_size: int = 5000):
        """Process CSV file in chunks"""
        
        nodes_seen = set()
        nodes_batch = []
        rels_batch = defaultdict(list)
        
        total_rows = 0
        filtered_rows = 0
        
        logger.info(f"Processing {kg_path} in chunks of {chunk_size}...")
        
        with open(kg_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                total_rows += 1
                
                # Filter by relation type if needed
                relation = row['relation']
                if priority_only and relation not in PRIORITY_RELATIONS:
                    continue
                
                filtered_rows += 1
                
                # Collect unique nodes
                x_key = row['x_index']
                y_key = row['y_index']
                
                if x_key not in nodes_seen:
                    nodes_seen.add(x_key)
                    nodes_batch.append({
                        'node_index': int(row['x_index']),
                        'node_id': row['x_id'],
                        'name': row['x_name'],
                        'source': row['x_source'],
                        'label': get_node_label(row['x_type'])
                    })
                
                if y_key not in nodes_seen:
                    nodes_seen.add(y_key)
                    nodes_batch.append({
                        'node_index': int(row['y_index']),
                        'node_id': row['y_id'],
                        'name': row['y_name'],
                        'source': row['y_source'],
                        'label': get_node_label(row['y_type'])
                    })
                
                # Collect relationship
                rel_key = (get_node_label(row['x_type']), get_node_label(row['y_type']), get_relationship_type(relation))
                rels_batch[rel_key].append({
                    'x_index': int(row['x_index']),
                    'y_index': int(row['y_index']),
                    'display': row.get('display_relation', relation)
                })
                
                # Flush nodes periodically
                if len(nodes_batch) >= chunk_size:
                    self._insert_nodes_batch(nodes_batch)
                    nodes_batch = []
                
                # Flush relationships periodically
                for key in list(rels_batch.keys()):
                    if len(rels_batch[key]) >= chunk_size:
                        self._insert_rels_batch(key, rels_batch[key])
                        rels_batch[key] = []
                
                # Progress update
                if total_rows % 500000 == 0:
                    logger.info(f"  Processed {total_rows:,} rows, kept {filtered_rows:,}...")
        
        # Flush remaining batches
        if nodes_batch:
            self._insert_nodes_batch(nodes_batch)
        
        for key, batch in rels_batch.items():
            if batch:
                self._insert_rels_batch(key, batch)
        
        logger.info(f"Processed {total_rows:,} total rows, imported {filtered_rows:,} relationships")
        logger.info(f"Created {len(nodes_seen):,} unique nodes")
    
    def _insert_nodes_batch(self, nodes: list):
        """Insert a batch of nodes grouped by label"""
        # Group by label
        by_label = defaultdict(list)
        for node in nodes:
            by_label[node['label']].append(node)
        
        with self.driver.session() as session:
            for label, batch in by_label.items():
                query = f"""
                UNWIND $nodes AS node
                MERGE (n:{label} {{node_index: node.node_index}})
                SET n.node_id = node.node_id,
                    n.name = node.name,
                    n.source = node.source
                """
                session.run(query, nodes=batch)
    
    def _insert_rels_batch(self, key: tuple, rels: list):
        """Insert a batch of relationships"""
        x_label, y_label, rel_type = key
        
        query = f"""
        UNWIND $rels AS rel
        MATCH (x:{x_label} {{node_index: rel.x_index}})
        MATCH (y:{y_label} {{node_index: rel.y_index}})
        MERGE (x)-[r:{rel_type}]->(y)
        """
        
        with self.driver.session() as session:
            session.run(query, rels=rels)
    
    def get_stats(self):
        """Get database statistics"""
        with self.driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
            
            logger.info(f"Database stats: {nodes:,} nodes, {rels:,} relationships")
            
            # Sample some data
            sample = session.run("""
                MATCH (d:Drug)-[r:TREATS]->(dis:Disease) 
                RETURN d.name as drug, dis.name as disease 
                LIMIT 5
            """)
            
            logger.info("Sample TREATS relationships:")
            for record in sample:
                logger.info(f"  {record['drug']} TREATS {record['disease']}")


def main():
    parser = argparse.ArgumentParser(description='Import PrimeKG to Neo4j (Memory-Efficient)')
    parser.add_argument('--kg-path', type=str, default='./kg.csv')
    parser.add_argument('--neo4j-uri', type=str, default='bolt://localhost:7687')
    parser.add_argument('--neo4j-user', type=str, default='neo4j')
    parser.add_argument('--neo4j-password', type=str, required=True)
    parser.add_argument('--priority-only', action='store_true', help='Import only medical relations')
    parser.add_argument('--clear-db', action='store_true', help='Clear database first')
    parser.add_argument('--chunk-size', type=int, default=5000)
    
    args = parser.parse_args()
    
    start = time.time()
    
    importer = ChunkedImporter(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    
    try:
        if args.clear_db:
            importer.clear_database()
        
        importer.create_constraints_and_indexes()
        importer.process_csv_chunked(args.kg_path, args.priority_only, args.chunk_size)
        importer.get_stats()
        
        logger.info(f"Total time: {time.time() - start:.1f}s")
        
    finally:
        importer.close()


if __name__ == '__main__':
    main()