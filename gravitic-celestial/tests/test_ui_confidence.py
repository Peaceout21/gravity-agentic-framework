import unittest

from ui.confidence import confidence_label, confidence_level, low_confidence_warning, normalize_confidence


class UiConfidenceTests(unittest.TestCase):
    def test_normalize_confidence_bounds(self):
        self.assertEqual(normalize_confidence(-1), 0.0)
        self.assertEqual(normalize_confidence(2), 1.0)
        self.assertEqual(normalize_confidence("0.556"), 0.556)

    def test_confidence_levels(self):
        self.assertEqual(confidence_level(0.9), "high")
        self.assertEqual(confidence_level(0.6), "medium")
        self.assertEqual(confidence_level(0.2), "low")

    def test_confidence_label_contains_percent(self):
        self.assertIn("High confidence", confidence_label(0.8))
        self.assertIn("80%", confidence_label(0.8))

    def test_low_confidence_warning(self):
        self.assertTrue(low_confidence_warning(0.2))
        self.assertEqual(low_confidence_warning(0.8), "")


if __name__ == "__main__":
    unittest.main()
