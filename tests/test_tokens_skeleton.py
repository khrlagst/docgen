from docgen.context.source import SourceParser, extract_skeleton
from docgen.generator.token_budget import maybe_skeleton, SKELETON_TOKEN_THRESHOLD


SAMPLE = '''
"""Module docstring."""

def foo(a, b):
    """Do foo."""
    return a + b

class Bar:
    """A bar class."""

    def method(self):
        """method doc."""
        x = 1
        return x
'''


def test_skeleton_keeps_signatures_and_docstrings():
    sk = SourceParser(SAMPLE).skeleton()
    assert "def foo(a, b):" in sk
    assert '"""Do foo."""' in sk
    assert "class Bar:" in sk
    assert "def method(self):" in sk
    assert '"""method doc."""' in sk


def test_skeleton_strips_function_bodies():
    sk = SourceParser(SAMPLE).skeleton()
    assert "return a + b" not in sk
    assert "x = 1" not in sk


def test_extract_skeleton_falls_back_on_syntax_error():
    bad = "def (:\n    x = 1\n"
    assert extract_skeleton(bad) == bad


def test_small_python_file_not_skeletoned():
    small = "def f():\n    return 1\n"
    content, is_skeleton = maybe_skeleton("small.py", small)
    assert is_skeleton is False
    assert content == small


def test_large_python_file_is_skeletoned():
    big = "def huge():\n" + "    x = 1\n" * 6000
    content, is_skeleton = maybe_skeleton("mod.py", big)
    assert is_skeleton is True
    assert "x = 1" not in content  # body stripped
    assert "def huge():" in content


def test_non_python_never_skeletoned():
    big = "function huge() {\n" + "  var x = 1;\n" * 6000
    content, is_skeleton = maybe_skeleton("mod.js", big)
    assert is_skeleton is False
    assert content == big


def test_skeleton_threshold_is_meaningful():
    assert SKELETON_TOKEN_THRESHOLD > 0
