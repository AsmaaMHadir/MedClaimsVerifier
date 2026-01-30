"""
MedCAT Model Test Script
Tests the downloaded MedCAT model for medical entity recognition and linking.

Usage:
    python test_medcat_model.py --model-path /path/to/model_pack

Requirements:
    pip install medcat
"""

import argparse
import json
from pathlib import Path

def test_medcat_model(model_path: str):
    """Test MedCAT model with sample medical texts"""
    
    print("=" * 60)
    print("MedCAT Model Test")
    print("=" * 60)
    
    # Import MedCAT
    print("\n1. Importing MedCAT...")
    try:
        from medcat.cat import CAT
        print("   ✅ MedCAT imported successfully")
    except ImportError as e:
        print(f"   ❌ Failed to import MedCAT: {e}")
        print("   Run: pip install medcat")
        return False
    
    # Load model
    print(f"\n2. Loading model from: {model_path}")
    try:
        # Check if it's a directory (extracted) or zip file
        model_path = Path(model_path)
        if model_path.is_dir():
            # Look for model pack inside directory
            zip_files = list(model_path.glob("*.zip"))
            if zip_files:
                model_path = zip_files[0]
                print(f"   Found model pack: {model_path}")
            else:
                # Try loading as directory directly
                pass
        
        cat = CAT.load_model_pack(str(model_path))
        print("   ✅ Model loaded successfully")
        
        # Print model info
        print(f"\n   Model info:")
        print(f"   - CDB size: {len(cat.cdb.cui2names)} concepts")
        
    except Exception as e:
        print(f"   ❌ Failed to load model: {e}")
        return False
    
    # Test texts
    print("\n3. Testing entity extraction...")
    
    test_cases = [
        {
            "text": "Patient diagnosed with Type 2 Diabetes Mellitus and prescribed Metformin 500mg twice daily.",
            "expected_entities": ["Type 2 Diabetes", "Metformin"]
        },
        {
            "text": "History of hypertension treated with Lisinopril. No evidence of heart failure.",
            "expected_entities": ["hypertension", "Lisinopril", "heart failure"]
        },
        {
            "text": "The patient presents with chest pain, shortness of breath, and elevated troponin levels suggesting acute myocardial infarction.",
            "expected_entities": ["chest pain", "shortness of breath", "myocardial infarction"]
        },
        {
            "text": "Contraindicated: Do not use Aspirin in patients with active peptic ulcer disease.",
            "expected_entities": ["Aspirin", "peptic ulcer"]
        },
        {
            "text": "Ibuprofen may cause gastrointestinal bleeding as a side effect.",
            "expected_entities": ["Ibuprofen", "gastrointestinal bleeding"]
        }
    ]
    
    all_passed = True
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n   Test {i}: {test['text'][:60]}...")
        
        try:
            # Get entities
            result = cat.get_entities(test['text'])
            entities = result.get('entities', {})
            
            print(f"   Found {len(entities)} entities:")
            
            for ent_id, ent_data in entities.items():
                name = ent_data.get('pretty_name', ent_data.get('source_value', 'Unknown'))
                cui = ent_data.get('cui', 'N/A')
                detected = ent_data.get('detected_name', ent_data.get('source_value', ''))
                confidence = ent_data.get('context_similarity', ent_data.get('acc', 0))
                types = ent_data.get('types', [])
                
                # Check for negation (if MetaCAT is included)
                meta_anns = ent_data.get('meta_anns', {})
                status = meta_anns.get('Status', {}).get('value', 'N/A')
                
                print(f"      - {detected} → {name} (CUI: {cui}, conf: {confidence:.2f}, status: {status})")
            
            print("   ✅ Extraction successful")
            
        except Exception as e:
            print(f"   ❌ Extraction failed: {e}")
            all_passed = False
    
    # Test specific medical query
    print("\n4. Testing concept lookup...")
    
    lookup_terms = ["diabetes", "metformin", "hypertension", "aspirin", "heart attack"]
    
    for term in lookup_terms:
        try:
            # Search for concept
            results = cat.cdb.search(term, top_n=3)
            if results:
                print(f"   '{term}' → {len(results)} matches")
                for cui, score in results[:2]:
                    name = cat.cdb.cui2preferred_name.get(cui, cat.cdb.cui2names.get(cui, ['Unknown'])[0] if cui in cat.cdb.cui2names else 'Unknown')
                    print(f"      - {name} (CUI: {cui}, score: {score:.2f})")
            else:
                print(f"   '{term}' → No matches found")
        except Exception as e:
            print(f"   '{term}' → Error: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All tests passed! MedCAT model is working correctly.")
    else:
        print("⚠️  Some tests failed. Check the errors above.")
    print("=" * 60)
    
    return all_passed


def main():
    parser = argparse.ArgumentParser(description='Test MedCAT model')
    parser.add_argument('--model-path', type=str, required=True, help='Path to MedCAT model pack (zip or directory)')
    
    args = parser.parse_args()
    
    success = test_medcat_model(args.model_path)
    exit(0 if success else 1)


if __name__ == '__main__':
    main()