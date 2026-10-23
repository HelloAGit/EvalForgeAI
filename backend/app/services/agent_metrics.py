from typing import List, Dict, Any

class AgentMetricsEngine:
    @staticmethod
    def calculate_task_completion(verified_outcome: str, expected_outcome: str) -> float:
        if not verified_outcome or not expected_outcome:
            return 0.0
        return 1.0 if verified_outcome.strip().lower() == expected_outcome.strip().lower() else 0.0

    @staticmethod
    def calculate_tool_accuracy(trace_steps: List[Dict[str, Any]]) -> float:
        if not trace_steps:
            return 0.0
        correct = sum(1 for step in trace_steps if step.get("status") == "SUCCESS")
        return correct / len(trace_steps)

    def evaluate_agent_trace(self, trace: Dict[str, Any]) -> Dict[str, float]:
        steps = trace.get("steps", [])
        return {
            "task_completion": self.calculate_task_completion(
                trace.get("verified_outcome", ""),
                trace.get("expected_outcome", "")
            ),
            "tool_accuracy": self.calculate_tool_accuracy(steps),
            "avg_tool_calls": float(len(steps))
        }
