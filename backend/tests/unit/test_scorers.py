from agenteval_core.scorers.deterministic import (
    ExactMatchScorer,
    ContainsScorer,
    RegexMatchScorer,
    JsonSchemaValidScorer,
    LevenshteinSimilarityScorer,
)


def test_exact_match_pass():
    s = ExactMatchScorer()
    r = s.score("q", "hello", "hello", {})
    assert r.boolean_value is True
    assert r.error is None


def test_exact_match_fail():
    s = ExactMatchScorer()
    r = s.score("q", "hello", "world", {})
    assert r.boolean_value is False


def test_exact_match_case_insensitive():
    s = ExactMatchScorer(case_sensitive=False)
    assert s.score("q", "Hello", "hello", {}).boolean_value is True


def test_contains_pass():
    s = ContainsScorer()
    assert s.score("q", "the quick brown fox", "quick", {}).boolean_value is True


def test_contains_fail_empty_needle():
    s = ContainsScorer()
    assert s.score("q", "anything", "", {}).boolean_value is False


def test_regex_match_no_pattern_returns_error_not_raise():
    s = RegexMatchScorer(pattern=None)
    r = s.score("q", "abc", None, {})
    assert r.error is not None
    assert r.boolean_value is None


def test_regex_match_pattern():
    s = RegexMatchScorer(pattern=r"^\d{3}-\d{4}$")
    assert s.score("q", "555-1234", None, {}).boolean_value is True
    assert s.score("q", "not a number", None, {}).boolean_value is False


def test_json_schema_valid():
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    s = JsonSchemaValidScorer(schema=schema)
    assert s.score("q", {"name": "x"}, None, {}).boolean_value is True
    assert s.score("q", {"age": 1}, None, {}).boolean_value is False


def test_json_schema_malformed_output_never_raises():
    schema = {"type": "object"}
    s = JsonSchemaValidScorer(schema=schema)
    r = s.score("q", "{not valid json", None, {})
    assert r.error is not None  # caught by BaseScorer, not propagated


def test_levenshtein_identical():
    s = LevenshteinSimilarityScorer()
    r = s.score("q", "hello", "hello", {})
    assert r.numeric_value == 1.0


def test_levenshtein_partial():
    s = LevenshteinSimilarityScorer()
    r = s.score("q", "hello", "hallo", {})
    assert 0.0 < r.numeric_value < 1.0


def test_levenshtein_garbage_input_never_raises():
    s = LevenshteinSimilarityScorer()
    r = s.score("q", None, {"nested": ["object"]}, {})
    assert r.error is None  # non-string inputs are stringified, not fatal
    assert r.numeric_value is not None
