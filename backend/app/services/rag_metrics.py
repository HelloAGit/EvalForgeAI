from typing import List, Dict, Any

class RAGMetricsEngine:
    @staticmethod
    def precision_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int) -> float:
        top_k = retrieved_ids[:k]
        if not top_k:
            return 0.0
        relevant_retrieved = [doc for doc in top_k if doc in relevant_ids]
        return len(relevant_retrieved) / min(k, len(top_k))

    @staticmethod
    def recall_at_k(retrieved_ids: List[str], relevant_ids: List[str], k: int) -> float:
        if not relevant_ids:
            return 1.0
        top_k = retrieved_ids[:k]
        relevant_retrieved = [doc for doc in top_k if doc in relevant_ids]
        return len(relevant_retrieved) / len(relevant_ids)

    @staticmethod
    def mean_reciprocal_rank(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
        for index, doc_id in enumerate(retrieved_ids):
            if doc_id in relevant_ids:
                return 1.0 / (index + 1)
        return 0.0

    def evaluate_retrieval(self, retrieved: List[str], relevant: List[str], k: int = 3) -> Dict[str, float]:
        return {
            f"precision_at_{k}": self.precision_at_k(retrieved, relevant, k),
            f"recall_at_{k}": self.recall_at_k(retrieved, relevant, k),
            "mrr": self.mean_reciprocal_rank(retrieved, relevant)
        }
