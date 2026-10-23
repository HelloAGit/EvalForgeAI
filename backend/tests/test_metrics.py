from app.services.llm_metrics import LLMMetricsEngine
from app.services.rag_metrics import RAGMetricsEngine

def test_exact_match():
    engine = LLMMetricsEngine()
    assert engine.calculate_exact_match("Hello World", "hello world ") == 1.0
    assert engine.calculate_exact_match("Hello", "World") == 0.0

def test_numerical_accuracy():
    engine = LLMMetricsEngine()
    assert engine.calculate_numerical_accuracy("Net margin is 20%", "The answer is 20.0%") == 1.0
    assert engine.calculate_numerical_accuracy("Target is 100", "Result was 50") == 0.0

def test_rag_precision_and_recall():
    engine = RAGMetricsEngine()
    retrieved = ["doc-1", "doc-2", "doc-3"]
    relevant = ["doc-1"]
    
    metrics = engine.evaluate_retrieval(retrieved, relevant, k=3)
    assert metrics["precision_at_3"] == 1.0 / 3.0
    assert metrics["recall_at_3"] == 1.0
    assert metrics["mrr"] == 1.0
