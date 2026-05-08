"""
Quality Evaluation Test Suite for MedVerify API
Runs comprehensive tests against /extract and /verify endpoints
Outputs results to CSV for analysis
"""

import json
import csv
import time
import httpx
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


# Configuration
API_BASE_URL = "http://localhost:8000"
TIMEOUT = 120  # seconds (GLiNER cold-start may take a while on first request)
RESULTS_DIR = Path(__file__).parent / "results"


def load_test_data() -> Dict[str, List[Dict]]:
    """Load test cases from JSON file"""
    test_file = Path(__file__).parent / "test_data.json"
    with open(test_file) as f:
        return json.load(f)


def calculate_entity_metrics(expected: List[Dict], actual: List[Dict]) -> Dict[str, float]:
    """
    Calculate precision, recall, and F1 for entity extraction

    Matching is done by entity name (case-insensitive, partial match)
    """
    if not expected and not actual:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    if not expected:
        return {"precision": 0.0, "recall": 1.0, "f1": 0.0}

    if not actual:
        return {"precision": 1.0, "recall": 0.0, "f1": 0.0}

    # Extract names for matching
    expected_names = {e["name"].lower() for e in expected}
    actual_names = {e.get("name", e.get("text", "")).lower() for e in actual}

    # Calculate matches (partial matching)
    true_positives = 0
    for exp_name in expected_names:
        for act_name in actual_names:
            if exp_name in act_name or act_name in exp_name:
                true_positives += 1
                break

    precision = true_positives / len(actual_names) if actual_names else 0
    recall = true_positives / len(expected_names) if expected_names else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def run_extract_test(client: httpx.Client, test_case: Dict) -> Dict[str, Any]:
    """Run a single extraction test and return results"""
    start_time = time.time()

    try:
        response = client.post(
            f"{API_BASE_URL}/extract",
            json={"text": test_case["input"]},
            timeout=TIMEOUT
        )
        processing_ms = (time.time() - start_time) * 1000

        if response.status_code != 200:
            return {
                "test_id": test_case["id"],
                "category": test_case["category"],
                "input_text": test_case["input"],
                "expected_entities": json.dumps(test_case["expected_entities"]),
                "actual_entities": f"ERROR: {response.status_code}",
                "entities_found": 0,
                "entities_expected": len(test_case["expected_entities"]),
                "precision": 0,
                "recall": 0,
                "f1": 0,
                "processing_ms": round(processing_ms, 2),
                "error": response.text
            }

        data = response.json()
        actual_entities = data.get("entities", [])

        # Calculate metrics
        metrics = calculate_entity_metrics(test_case["expected_entities"], actual_entities)

        # Format actual entities for CSV
        actual_formatted = [
            {"name": e.get("name", e.get("text", "")), "type": e.get("type", ""), "negated": e.get("negated", False)}
            for e in actual_entities
        ]

        return {
            "test_id": test_case["id"],
            "category": test_case["category"],
            "input_text": test_case["input"],
            "expected_entities": json.dumps(test_case["expected_entities"]),
            "actual_entities": json.dumps(actual_formatted),
            "entities_found": len(actual_entities),
            "entities_expected": len(test_case["expected_entities"]),
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
            "processing_ms": round(processing_ms, 2),
            "error": ""
        }

    except Exception as e:
        return {
            "test_id": test_case["id"],
            "category": test_case["category"],
            "input_text": test_case["input"],
            "expected_entities": json.dumps(test_case["expected_entities"]),
            "actual_entities": "ERROR",
            "entities_found": 0,
            "entities_expected": len(test_case["expected_entities"]),
            "precision": 0,
            "recall": 0,
            "f1": 0,
            "processing_ms": 0,
            "error": str(e)
        }


def run_verify_test(client: httpx.Client, test_case: Dict) -> Dict[str, Any]:
    """Run a single verification test and return results"""
    start_time = time.time()

    try:
        response = client.post(
            f"{API_BASE_URL}/verify",
            json={"text": test_case["input"]},
            timeout=TIMEOUT
        )
        processing_ms = (time.time() - start_time) * 1000

        if response.status_code != 200:
            return {
                "test_id": test_case["id"],
                "category": test_case["category"],
                "input_text": test_case["input"],
                "expected_status": test_case["expected_status"],
                "actual_status": f"ERROR: {response.status_code}",
                "status_match": False,
                "expected_relationship": test_case.get("expected_relationship", ""),
                "actual_relationship": "",
                "evidence_found": False,
                "confidence": 0,
                "processing_ms": round(processing_ms, 2),
                "error": response.text
            }

        data = response.json()
        claims = data.get("claims", [])

        # Get primary claim result
        if claims:
            primary_claim = claims[0]
            actual_status = primary_claim.get("status", "UNKNOWN")
            confidence = primary_claim.get("confidence", 0)
            evidence = primary_claim.get("evidence", [])
            actual_relationship = evidence[0].get("relationship", "") if evidence else ""
        else:
            actual_status = "UNKNOWN"
            confidence = 0
            evidence = []
            actual_relationship = ""

        # Check status match
        status_match = actual_status == test_case["expected_status"]

        return {
            "test_id": test_case["id"],
            "category": test_case["category"],
            "input_text": test_case["input"],
            "expected_status": test_case["expected_status"],
            "actual_status": actual_status,
            "status_match": status_match,
            "expected_relationship": test_case.get("expected_relationship", ""),
            "actual_relationship": actual_relationship,
            "evidence_found": len(evidence) > 0,
            "confidence": round(confidence, 3),
            "processing_ms": round(processing_ms, 2),
            "error": ""
        }

    except Exception as e:
        return {
            "test_id": test_case["id"],
            "category": test_case["category"],
            "input_text": test_case["input"],
            "expected_status": test_case["expected_status"],
            "actual_status": "ERROR",
            "status_match": False,
            "expected_relationship": test_case.get("expected_relationship", ""),
            "actual_relationship": "",
            "evidence_found": False,
            "confidence": 0,
            "processing_ms": 0,
            "error": str(e)
        }


def write_extract_csv(results: List[Dict], filepath: Path):
    """Write extraction results to CSV"""
    fieldnames = [
        "test_id", "category", "input_text", "expected_entities", "actual_entities",
        "entities_found", "entities_expected", "precision", "recall", "f1",
        "processing_ms", "error"
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def write_verify_csv(results: List[Dict], filepath: Path):
    """Write verification results to CSV"""
    fieldnames = [
        "test_id", "category", "input_text", "expected_status", "actual_status",
        "status_match", "expected_relationship", "actual_relationship",
        "evidence_found", "confidence", "processing_ms", "error"
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def print_summary(extract_results: List[Dict], verify_results: List[Dict]):
    """Print summary statistics"""
    print("\n" + "="*60)
    print("QUALITY EVALUATION SUMMARY")
    print("="*60)

    # Extract summary
    print("\n--- ENTITY EXTRACTION (/extract) ---")
    if extract_results:
        avg_precision = sum(r["precision"] for r in extract_results) / len(extract_results)
        avg_recall = sum(r["recall"] for r in extract_results) / len(extract_results)
        avg_f1 = sum(r["f1"] for r in extract_results) / len(extract_results)
        avg_time = sum(r["processing_ms"] for r in extract_results) / len(extract_results)
        errors = sum(1 for r in extract_results if r["error"])

        print(f"Total tests:      {len(extract_results)}")
        print(f"Avg Precision:    {avg_precision:.3f}")
        print(f"Avg Recall:       {avg_recall:.3f}")
        print(f"Avg F1 Score:     {avg_f1:.3f}")
        print(f"Avg Response:     {avg_time:.0f}ms")
        print(f"Errors:           {errors}")

    # Verify summary
    print("\n--- CLAIM VERIFICATION (/verify) ---")
    if verify_results:
        correct = sum(1 for r in verify_results if r["status_match"])
        accuracy = correct / len(verify_results) if verify_results else 0
        avg_confidence = sum(r["confidence"] for r in verify_results) / len(verify_results)
        avg_time = sum(r["processing_ms"] for r in verify_results) / len(verify_results)
        errors = sum(1 for r in verify_results if r["error"])
        evidence_rate = sum(1 for r in verify_results if r["evidence_found"]) / len(verify_results)

        print(f"Total tests:      {len(verify_results)}")
        print(f"Status Accuracy:  {accuracy:.1%} ({correct}/{len(verify_results)})")
        print(f"Avg Confidence:   {avg_confidence:.3f}")
        print(f"Evidence Rate:    {evidence_rate:.1%}")
        print(f"Avg Response:     {avg_time:.0f}ms")
        print(f"Errors:           {errors}")

    print("\n" + "="*60)


def main():
    """Main entry point"""
    print("MedVerify Quality Evaluation")
    print("="*60)

    # Ensure results directory exists
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load test data
    print("Loading test data...")
    test_data = load_test_data()

    extract_tests = test_data.get("extract_tests", [])
    verify_tests = test_data.get("verify_tests", [])

    print(f"Found {len(extract_tests)} extract tests, {len(verify_tests)} verify tests")

    # Check API health
    print(f"\nChecking API at {API_BASE_URL}...")
    try:
        with httpx.Client() as client:
            health = client.get(f"{API_BASE_URL}/health", timeout=TIMEOUT)
            if health.status_code == 200:
                health_data = health.json()
                print(f"API Status: {health_data.get('status', 'unknown')}")
                services = health_data.get("services", {})
                for name, info in services.items():
                    print(f"  - {name}: {info.get('status', 'unknown')}")
            else:
                print(f"WARNING: Health check returned {health.status_code}")
    except Exception as e:
        print(f"ERROR: Cannot connect to API - {e}")
        print("Make sure the API is running: uvicorn src.main:app --reload")
        return

    # Run tests
    extract_results = []
    verify_results = []

    with httpx.Client() as client:
        # Run extract tests
        print(f"\nRunning {len(extract_tests)} extraction tests...")
        for i, test in enumerate(extract_tests, 1):
            print(f"  [{i}/{len(extract_tests)}] {test['id']}: {test['input'][:40]}...")
            result = run_extract_test(client, test)
            extract_results.append(result)
            if result["error"]:
                print(f"    ERROR: {result['error'][:50]}")
            else:
                print(f"    Found {result['entities_found']} entities, F1={result['f1']}")

        # Run verify tests
        print(f"\nRunning {len(verify_tests)} verification tests...")
        for i, test in enumerate(verify_tests, 1):
            print(f"  [{i}/{len(verify_tests)}] {test['id']}: {test['input'][:40]}...")
            result = run_verify_test(client, test)
            verify_results.append(result)
            if result["error"]:
                print(f"    ERROR: {result['error'][:50]}")
            else:
                match_str = "MATCH" if result["status_match"] else "MISMATCH"
                print(f"    {result['actual_status']} (expected: {result['expected_status']}) - {match_str}")

    # Write results to CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    extract_csv = RESULTS_DIR / f"extract_results_{timestamp}.csv"
    verify_csv = RESULTS_DIR / f"verify_results_{timestamp}.csv"

    print(f"\nWriting results...")
    write_extract_csv(extract_results, extract_csv)
    write_verify_csv(verify_results, verify_csv)

    print(f"  Extract results: {extract_csv}")
    print(f"  Verify results:  {verify_csv}")

    # Also write latest versions without timestamp
    write_extract_csv(extract_results, RESULTS_DIR / "extract_results.csv")
    write_verify_csv(verify_results, RESULTS_DIR / "verify_results.csv")

    # Print summary
    print_summary(extract_results, verify_results)


if __name__ == "__main__":
    main()
