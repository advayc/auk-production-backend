import itertools
import re
import unicodedata
import unittest
from auk_reliability.core import compare_transcript, normalized_tokens, EditorError


class UnicodeTranscriptQA(unittest.TestCase):
    def test_devanagari_vowel_marks_do_not_false_match(self):
        for expected, observed in [('दिन', 'दीन'), ('कुल', 'कूल')]:
            with self.subTest(expected=expected):
                result = compare_transcript(expected, observed)
                self.assertFalse(result['exact_normalized_match'])
                self.assertEqual(result['word_error_rate'], 1.0)
                self.assertEqual(result['status'], 'review_required')

    def test_devanagari_words_remain_whole(self):
        self.assertEqual(normalized_tokens('कुछ अणुओं में'), ['कुछ', 'अणुओं', 'में'])

    def test_arabic_combining_marks_not_erased(self):
        self.assertNotEqual(normalized_tokens('عَلَم'), normalized_tokens('عِلْم'))

    def test_canonical_equivalents_match(self):
        self.assertTrue(compare_transcript('café', 'cafe\u0301')['exact_normalized_match'])

    def test_english_punctuation_and_case_unchanged(self):
        self.assertTrue(compare_transcript("The sun's RAYS!", "the sun's rays")['exact_normalized_match'])

    def test_apostrophes_unchanged(self):
        self.assertEqual(normalized_tokens("I'd've John's don't ’quote’"), ["i'd", 've', "john's", "don't", 'quote'])

    def test_ascii_tokenization_exhaustively_matches_previous_rule(self):
        alphabet = "a3_'’- "
        for size in range(6):
            for chars in itertools.product(alphabet, repeat=size):
                text = ''.join(chars)
                old = re.findall(r"[^\W_]+(?:['’][^\W_]+)?", unicodedata.normalize('NFKC', text).casefold(), flags=re.UNICODE)
                self.assertEqual(normalized_tokens(text), old, repr(text))

    def test_standalone_marks_are_not_words(self):
        self.assertEqual(normalized_tokens('\u093f !!!'), [])
        with self.assertRaises(EditorError):
            compare_transcript('\u093f', 'word')

    def test_cjk_metric_unchanged(self):
        self.assertEqual(compare_transcript('你好世界', '你好')['metric'], 'character_error_rate')

    def test_whitespace_and_underscore_still_separate(self):
        self.assertEqual(normalized_tokens('one_two\nthree\tfour'), ['one', 'two', 'three', 'four'])


if __name__ == '__main__':
    unittest.main()
