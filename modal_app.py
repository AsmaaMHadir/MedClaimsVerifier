"""
MedCAT API on Modal
Deploy: modal deploy modal_app.py
Test locally: modal serve modal_app.py
"""

import modal

# Define the image with compatible dependencies
# MedCAT 2.x requires numpy>=2.0, which requires spacy 3.8+ (numpy 2.x compatible wheels)
image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("build-essential", "unzip")
    .pip_install(
        # spacy 3.8+ has numpy 2.x compatible wheels
        "spacy>=3.8.0",
        "https://github.com/explosion/spacy-models/releases/download/en_core_web_md-3.8.0/en_core_web_md-3.8.0-py3-none-any.whl",
    )
    .pip_install(
        # MedCAT 2.x with numpy 2.x
        "medcat>=2.0.0,<3.0.0",
        # FastAPI stack
        "fastapi>=0.109.0",
        "uvicorn>=0.27.0",
    )
)

# Create Modal app
app = modal.App("medcat-api", image=image)

# Volume with the model
volume = modal.Volume.from_name("medcat-model-vol", create_if_missing=True)
MODEL_DIR = "/model"


@app.cls(
    volumes={MODEL_DIR: volume},
    memory=8192,  # 8GB RAM
    scaledown_window=300,  # Keep warm for 5 min
)
@modal.concurrent(max_inputs=10)
class MedCATService:
    """MedCAT service that loads model once and handles requests"""
    
    @modal.enter()
    def load_model(self):
        """Called once when container starts - loads the model"""
        import os
        import subprocess
        from pathlib import Path

        zip_path = Path(MODEL_DIR) / "medcat_model.zip"
        model_path = Path(MODEL_DIR) / "medcat_model"

        print(f"📁 MODEL_DIR contents: {list(Path(MODEL_DIR).iterdir())}")

        # Unzip if needed
        if zip_path.exists() and (not model_path.exists() or not any(model_path.iterdir())):
            print(f"Extracting model from {zip_path}...")
            model_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(["unzip", "-o", str(zip_path), "-d", str(model_path)], check=True)
            volume.commit()  # Save the unzipped files to volume
            print("✅ Model extracted")

        # Find the actual model directory (might be deeply nested)
        # Look for model_card.json which exists in MedCAT model packs
        actual_model_path = model_path

        # Try finding model_card.json (newer format)
        model_card_files = list(model_path.rglob("model_card.json"))
        if model_card_files:
            actual_model_path = model_card_files[0].parent
            print(f"📍 Found model_card.json at: {actual_model_path}")
        else:
            # Try finding cdb directory (newer format uses cdb/ directory not cdb.dat)
            cdb_dirs = list(model_path.rglob("cdb"))
            for cdb_dir in cdb_dirs:
                if cdb_dir.is_dir():
                    actual_model_path = cdb_dir.parent
                    print(f"📍 Found cdb directory at: {actual_model_path}")
                    break
            else:
                # Fallback: look for cdb.dat (older format)
                for f in model_path.rglob("cdb.dat"):
                    actual_model_path = f.parent
                    print(f"📍 Found cdb.dat at: {actual_model_path}")
                    break

        print(f"📂 Model directory contents: {list(actual_model_path.iterdir()) if actual_model_path.exists() else 'NOT FOUND'}")
        print(f"🔄 Loading MedCAT from {actual_model_path}...")

        try:
            from medcat.cat import CAT
            self.cat = CAT.load_model_pack(str(actual_model_path))
            # MedCAT 2.x uses cui2preferred_name instead of cui2names
            concept_count = len(getattr(self.cat.cdb, 'cui2preferred_name', {}))
            print(f"✅ MedCAT loaded: {concept_count} concepts")
        except Exception as e:
            import traceback
            print(f"❌ Failed to load model: {e}")
            print(f"❌ Traceback: {traceback.format_exc()}")
            self.cat = None
    
    @modal.method()
    def extract(self, text: str) -> dict:
        """Extract medical entities from text"""
        if not self.cat:
            return {"error": "Model not loaded", "entities": [], "count": 0}
        
        result = self.cat.get_entities(text)
        
        entities = []
        for ent_id, data in result.get('entities', {}).items():
            meta = data.get('meta_anns', {})
            negated = meta.get('Negation', {}).get('value', 'Affirmed') == 'Negated'
            
            entities.append({
                "text": data.get('source_value', ''),
                "cui": data.get('cui', ''),
                "name": data.get('pretty_name', data.get('source_value', '')),
                "types": data.get('types', []),
                "confidence": data.get('context_similarity', 0),
                "start": data.get('start', 0),
                "end": data.get('end', 0),
                "negated": negated
            })
        
        return {"entities": entities, "count": len(entities)}
    
    @modal.method()
    def health(self) -> dict:
        """Health check"""
        return {
            "status": "healthy" if self.cat else "degraded",
            "model_loaded": self.cat is not None
        }


# FastAPI web endpoint
@app.function(
    image=image,
    volumes={MODEL_DIR: volume},
    memory=8192,
    scaledown_window=300,
)
@modal.asgi_app()
def fastapi_app():
    """FastAPI wrapper for REST API access"""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    
    web_app = FastAPI(title="MedCAT API", version="1.0.0")
    
    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    class ExtractRequest(BaseModel):
        text: str = Field(..., min_length=1, max_length=50000)
    
    # Get reference to the service
    service = MedCATService()
    
    @web_app.get("/")
    def root():
        return {"service": "MedCAT API", "docs": "/docs"}
    
    @web_app.get("/health")
    def health():
        return service.health.remote()
    
    @web_app.post("/extract")
    def extract(request: ExtractRequest):
        result = service.extract.remote(request.text)
        if "error" in result:
            raise HTTPException(503, result["error"])
        return result
    
    return web_app


# CLI for direct Python calls
@app.local_entrypoint()
def main(text: str = "Patient has diabetes and takes metformin daily."):
    """Test the service from command line"""
    service = MedCATService()
    result = service.extract.remote(text)
    print(f"Input: {text}")
    print(f"Found {result['count']} entities:")
    for ent in result['entities']:
        print(f"  - {ent['text']} → {ent['name']} (CUI: {ent['cui']})")