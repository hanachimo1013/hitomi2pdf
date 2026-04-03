import unittest
from hitomi2pdf import Hitomi2PDF

class TestHitomi2PDF(unittest.TestCase):
    def setUp(self):
        # We can pass an empty output_dir or something benign
        # to avoid actually creating 'outputs' if we don't want to.
        # But Hitomi2PDF makes it by default.
        self.hitomi = Hitomi2PDF(output_dir="test_outputs")

    def test_sanitize_normal_string(self):
        self.assertEqual(self.hitomi._sanitize("Normal Title"), "Normal_Title")

    def test_sanitize_invalid_characters(self):
        # Testing \ / * ? : " < > |
        self.assertEqual(self.hitomi._sanitize('Title \\ / * ? : " < > | Name'), "Title__________Name")
        self.assertEqual(self.hitomi._sanitize("invalid<chars>here"), "invalidcharshere")
        self.assertEqual(self.hitomi._sanitize("question?"), "question")
        self.assertEqual(self.hitomi._sanitize("star*"), "star")

    def test_sanitize_spaces(self):
        self.assertEqual(self.hitomi._sanitize("  Leading and trailing spaces  "), "Leading_and_trailing_spaces")
        self.assertEqual(self.hitomi._sanitize("Multiple   spaces"), "Multiple___spaces")

    def test_sanitize_empty_string(self):
        self.assertEqual(self.hitomi._sanitize(""), "")
        self.assertEqual(self.hitomi._sanitize("   "), "")

    def test_sanitize_only_invalid_chars(self):
        self.assertEqual(self.hitomi._sanitize("\\/*?:\"<>|"), "")

if __name__ == '__main__':
    unittest.main()
