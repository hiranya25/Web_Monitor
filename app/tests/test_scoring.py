import unittest
from app.detailed_analysis import calculate_overall_score

class TestScoring(unittest.TestCase):
    def test_overall_score_weighted_average(self):
        categories = [
            {"name": "Performance", "score": 40},      # Weight 2
            {"name": "Metadata", "score": 60},         # Weight 2
            {"name": "Accessibility", "score": 80},    # Weight 2
            {"name": "URL Structure", "score": 100},   # Weight 1
            {"name": "SEO", "score": 100},             # Weight 1
        ]
        # Total weight = 2 + 2 + 2 + 1 + 1 = 8
        # Total score = (40*2) + (60*2) + (80*2) + (100*1) + (100*1) = 80 + 120 + 160 + 100 + 100 = 560
        # Expected = 560 / 8 = 70
        score, grade = calculate_overall_score(categories)
        self.assertEqual(score, 70)
        self.assertEqual(grade, "C")

    def test_overall_score_bounds(self):
        categories = [
            {"name": "Performance", "score": 10},
            {"name": "SEO", "score": 20},
        ]
        score, grade = calculate_overall_score(categories)
        self.assertGreaterEqual(score, 10)
        self.assertLessEqual(score, 20)
        
        # Test extreme case where min and max are the same
        categories = [{"name": "SEO", "score": 50}, {"name": "Performance", "score": 50}]
        score, grade = calculate_overall_score(categories)
        self.assertEqual(score, 50)

if __name__ == "__main__":
    unittest.main()
