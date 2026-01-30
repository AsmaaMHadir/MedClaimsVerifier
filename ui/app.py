"""
MedVerify - Interactive Medical Claim Verification UI
Run with: streamlit run ui/app.py
"""

import streamlit as st
import requests
import json
from pyvis.network import Network
import tempfile
import os

# Configuration
API_URL = os.getenv("MEDVERIFY_API_URL", "http://localhost:8000")

# Page config
st.set_page_config(
    page_title="MedVerify",
    page_icon="🏥",
    layout="wide"
)

# Custom CSS for styling
st.markdown("""
<style>
    .verdict-supported {
        background-color: #d4edda;
        border: 2px solid #28a745;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .verdict-contradicted {
        background-color: #f8d7da;
        border: 2px solid #dc3545;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .verdict-not-found {
        background-color: #fff3cd;
        border: 2px solid #ffc107;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .verdict-partial {
        background-color: #cce5ff;
        border: 2px solid #007bff;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .verdict-unknown {
        background-color: #e2e3e5;
        border: 2px solid #6c757d;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .entity-drug {
        background-color: #28a745;
        color: white;
        padding: 5px 10px;
        border-radius: 15px;
        margin: 2px;
        display: inline-block;
    }
    .entity-disease {
        background-color: #dc3545;
        color: white;
        padding: 5px 10px;
        border-radius: 15px;
        margin: 2px;
        display: inline-block;
    }
    .entity-symptom {
        background-color: #fd7e14;
        color: white;
        padding: 5px 10px;
        border-radius: 15px;
        margin: 2px;
        display: inline-block;
    }
    .entity-medical {
        background-color: #6c757d;
        color: white;
        padding: 5px 10px;
        border-radius: 15px;
        margin: 2px;
        display: inline-block;
    }
    .confidence-meter {
        height: 20px;
        background-color: #e9ecef;
        border-radius: 10px;
        overflow: hidden;
    }
    .confidence-fill {
        height: 100%;
        background: linear-gradient(90deg, #28a745, #20c997);
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)


def get_verdict_style(status: str) -> tuple:
    """Get styling for verdict based on status"""
    styles = {
        "SUPPORTED": ("verdict-supported", "✅", "#28a745"),
        "CONTRADICTED": ("verdict-contradicted", "❌", "#dc3545"),
        "NOT_FOUND": ("verdict-not-found", "⚠️", "#ffc107"),
        "PARTIAL": ("verdict-partial", "ℹ️", "#007bff"),
        "UNKNOWN": ("verdict-unknown", "❓", "#6c757d"),
    }
    return styles.get(status, styles["UNKNOWN"])


def create_knowledge_graph(nodes: list, edges: list) -> str:
    """Create an interactive knowledge graph visualization"""
    net = Network(
        height="400px",
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        font_color="#333333"
    )

    # Node colors by type
    colors = {
        "Drug": "#28a745",      # Green
        "Disease": "#dc3545",   # Red
        "Symptom": "#fd7e14",   # Orange
        "Effect": "#fd7e14",    # Orange
        "Medical": "#6c757d",   # Gray
    }

    # Add nodes
    for node in nodes:
        node_id = node.get("id", node.get("name", "unknown"))
        node_name = node.get("name", "Unknown")
        node_type = node.get("type", "Medical")
        color = colors.get(node_type, "#6c757d")

        net.add_node(
            node_id,
            label=node_name,
            title=f"{node_type}: {node_name}",
            color=color,
            size=30,
            font={"size": 14, "color": "#333333"}
        )

    # Add edges
    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        relationship = edge.get("relationship", "RELATED")

        if source and target:
            net.add_edge(
                source,
                target,
                title=relationship,
                label=relationship,
                arrows="to",
                color="#666666",
                font={"size": 10, "color": "#666666"}
            )

    # Configure physics
    net.set_options("""
    {
        "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -50,
                "centralGravity": 0.01,
                "springLength": 150,
                "springConstant": 0.08
            },
            "stabilization": {
                "iterations": 100
            }
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100
        }
    }
    """)

    # Generate HTML
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        net.save_graph(f.name)
        with open(f.name, "r") as html_file:
            html_content = html_file.read()
        os.unlink(f.name)
        return html_content


def verify_claim(text: str) -> dict:
    """Call the verification API"""
    try:
        response = requests.post(
            f"{API_URL}/verify",
            json={"text": text},
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e), "success": False}


def build_subgraph(claims: list) -> tuple:
    """Build nodes and edges from verification claims"""
    nodes = []
    edges = []
    node_ids = set()

    for claim in claims:
        # Add entity nodes
        for entity in claim.get("entities", []):
            entity_name = entity.get("name", "Unknown")
            if entity_name not in node_ids:
                nodes.append({
                    "id": entity_name,
                    "name": entity.get("text", entity_name),
                    "type": entity.get("type", "Medical")
                })
                node_ids.add(entity_name)

        # Add evidence edges
        for ev in claim.get("evidence", []):
            source = ev.get("subject", "")
            target = ev.get("object", "")
            relationship = ev.get("relationship", "RELATED")

            # Add source node if not exists
            if source and source not in node_ids:
                nodes.append({
                    "id": source,
                    "name": source,
                    "type": "Drug"
                })
                node_ids.add(source)

            # Add target node if not exists
            if target and target not in node_ids:
                nodes.append({
                    "id": target,
                    "name": target,
                    "type": "Disease"
                })
                node_ids.add(target)

            # Add edge
            if source and target:
                edges.append({
                    "source": source,
                    "target": target,
                    "relationship": relationship
                })

    return nodes, edges


# Main UI
st.title("🏥 MedVerify")
st.markdown("**Medical Claim Verification powered by Knowledge Graphs**")
st.markdown("---")

# Input section
col1, col2 = st.columns([3, 1])

with col1:
    claim_text = st.text_area(
        "Enter a medical claim to verify:",
        placeholder="e.g., Metformin treats Type 2 Diabetes",
        height=100
    )

with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    verify_button = st.button("🔍 Verify Claim", type="primary", use_container_width=True)

# Example claims
with st.expander("📝 Example claims to try"):
    examples = [
        "Metformin treats Type 2 Diabetes",
        "Lisinopril is used for hypertension",
        "Warfarin treats thrombotic disease",
        "Insulin treats diabetes mellitus",
        "Acetaminophen treats diabetes",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex}"):
            st.session_state["claim_text"] = ex
            st.rerun()

# Handle example selection
if "claim_text" in st.session_state:
    claim_text = st.session_state["claim_text"]
    del st.session_state["claim_text"]

# Verification
if verify_button and claim_text:
    with st.spinner("Verifying claim..."):
        result = verify_claim(claim_text)

    if result.get("error"):
        st.error(f"Error: {result['error']}")
    elif result.get("success"):
        claims = result.get("claims", [])

        if claims:
            # Display each claim result
            for i, claim in enumerate(claims):
                status = claim.get("status", "UNKNOWN")
                confidence = claim.get("confidence", 0)
                claim_text_result = claim.get("claim", "")
                entities = claim.get("entities", [])
                evidence = claim.get("evidence", [])

                style_class, icon, color = get_verdict_style(status)

                st.markdown("---")

                # Verdict card
                col_verdict, col_confidence = st.columns([2, 1])

                with col_verdict:
                    st.markdown(f"""
                    <div class="{style_class}">
                        <h2>{icon} {status}</h2>
                        <p><strong>{claim_text_result}</strong></p>
                    </div>
                    """, unsafe_allow_html=True)

                with col_confidence:
                    st.metric("Confidence", f"{confidence*100:.0f}%")
                    st.progress(confidence)

                # Entities section
                st.markdown("### 🏷️ Entities Found")
                entity_html = ""
                for entity in entities:
                    entity_type = entity.get("type", "Medical").lower()
                    entity_text = entity.get("text", entity.get("name", "Unknown"))
                    entity_html += f'<span class="entity-{entity_type}">{entity_type.upper()}: {entity_text}</span> '

                if entity_html:
                    st.markdown(entity_html, unsafe_allow_html=True)
                else:
                    st.info("No entities extracted")

                # Evidence section
                if evidence:
                    st.markdown("### 📚 Evidence from Knowledge Graph")
                    for ev in evidence:
                        st.markdown(f"- **{ev.get('subject', '?')}** → *{ev.get('relationship', 'RELATED')}* → **{ev.get('object', '?')}** (Source: {ev.get('source', 'PrimeKG')})")

                # Graph visualization
                st.markdown("### 🕸️ Knowledge Graph Visualization")

                nodes, edges = build_subgraph([claim])

                if nodes and edges:
                    graph_html = create_knowledge_graph(nodes, edges)
                    st.components.v1.html(graph_html, height=450, scrolling=False)
                elif nodes:
                    st.info("Entities found but no relationships to visualize. The graph shows detected entities without connecting relationships.")
                    # Show just the nodes
                    graph_html = create_knowledge_graph(nodes, [])
                    st.components.v1.html(graph_html, height=300, scrolling=False)
                else:
                    st.info("No graph data available for visualization")

            # Processing time
            st.markdown("---")
            st.caption(f"⏱️ Processing time: {result.get('processing_time_ms', 0):.0f}ms")
        else:
            st.warning("No claims were verified. Try a different input.")
    else:
        st.error("Verification failed. Please check that the API is running.")

# Sidebar
with st.sidebar:
    st.markdown("## About MedVerify")
    st.markdown("""
    MedVerify verifies medical claims against the **PrimeKG** knowledge graph containing:
    - 44,316 medical entities
    - 2.4M relationships

    ### Supported Verifications
    - Drug → treats → Disease
    - Drug → causes → Side Effect
    - Drug ↔ interacts with ↔ Drug
    - Disease → has symptom → Symptom

    ### Legend
    """)

    st.markdown("""
    <span class="entity-drug">Drug</span>
    <span class="entity-disease">Disease</span>
    <span class="entity-symptom">Symptom</span>
    <span class="entity-medical">Medical</span>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### API Status")

    # Health check
    try:
        health_response = requests.get(f"{API_URL}/health", timeout=5)
        if health_response.status_code == 200:
            health = health_response.json()
            st.success("✅ API Online")
            st.caption(f"MedCAT: {health.get('medcat', {}).get('status', 'unknown')}")
            st.caption(f"Neo4j: {health.get('neo4j', {}).get('status', 'unknown')}")
        else:
            st.error("❌ API Error")
    except:
        st.error("❌ API Offline")
        st.caption("Start with: `uvicorn src.main:app --reload`")
