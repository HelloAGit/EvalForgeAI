import json
import re
from typing import Dict, Any

class LLMMetricsEngine:
    @staticmethod
    def calculate_exact_match(expected: str, actual: str) -> float:
        if not expected or not actual:
            return 0.0
        return 1.0 if expected.strip().lower() == actual.strip().lower() else 0.0

    @staticmethod
    def calculate_numerical_accuracy(expected: str, actual: str, tolerance: float = 0.01) -> float:
        def extract_numbers(text: str):
            return [float(n) for n in re.findall(r"[-+]?\d*\.\d+|\d+", text)]

        exp_nums = extract_numbers(expected)
        act_nums = extract_numbers(actual)

        if not exp_nums or not act_nums:
            return 0.0

        target = exp_nums[0]
        match = any(abs(n - target) <= tolerance * max(abs(target), 1.0) for n in act_nums)
        return 1.0 if match else 0.0

    @staticmethod
    def validate_json(actual: str) -> float:
        try:
            json.loads(actual)
            return 1.0
        except Exception:
            return 0.0

    def evaluate_sample(self, expected: str, actual: str) -> Dict[str, float]:
        return {
            "exact_match": self.calculate_exact_match(expected, actual),
            "numerical_accuracy": self.calculate_numerical_accuracy(expected, actual),
            "json_validity": self.validate_json(actual)
        }
