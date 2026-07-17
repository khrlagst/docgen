import ast

from docgen.context.source import extract_skeleton
from docgen.generator.token_budget import chunk_by_symbol, estimate_tokens

BIG_PY = "\n".join(
    f"def func_{i}(a, b):\n    \"\"\"Doc {i}.\"\"\"\n    return a + b + {i}\n"
    for i in range(40)
)


def test_chunk_by_symbol_splits_large_file_into_budget():
    chunks = chunk_by_symbol({"mod.py": BIG_PY}, max_tokens=400)
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        text = next(iter(chunk.values()))
        assert estimate_tokens(text) <= 400, "chunk exceeds budget"


def test_chunk_by_symbol_keeps_symbols_intact():
    chunks = chunk_by_symbol({"mod.py": BIG_PY}, max_tokens=400)
    joined = "\n\n".join(next(iter(c.values())) for c in chunks)
    # Every function definition from the source survives chunking.
    src_funcs = {
        n.name for n in ast.walk(ast.parse(BIG_PY)) if isinstance(n, ast.FunctionDef)
    }
    chunk_funcs = {
        n.name for n in ast.walk(ast.parse(joined)) if isinstance(n, ast.FunctionDef)
    }
    assert chunk_funcs == src_funcs


def test_chunk_by_symbol_truncates_giant_symbol():
    giant = "def huge():\n" + "\n".join(f"    x = {i}" for i in range(5000))
    chunks = chunk_by_symbol({"g.py": giant}, max_tokens=200)
    text = next(iter(chunks[0].values()))
    assert estimate_tokens(text) <= 200
    assert "truncated" in text


def test_extract_skeleton_body_preview_zero_is_signature_only():
    src = (
        "def f(a):\n"
        '    """Doc."""\n'
        "    x = 1\n"
        "    y = 2\n"
        "    return x + y\n"
    )
    skel = extract_skeleton(src, body_preview_lines=0)
    assert "def f(a):" in skel
    assert '"""Doc."""' in skel
    assert "x = 1" not in skel
    assert "return x + y" not in skel


def test_extract_skeleton_body_preview_includes_leading_body_lines():
    src = (
        "def f(a):\n"
        '    """Doc."""\n'
        "    x = 1\n"
        "    y = 2\n"
        "    return x + y\n"
    )
    skel = extract_skeleton(src, body_preview_lines=2)
    assert "def f(a):" in skel
    assert '"""Doc."""' in skel
    assert "x = 1" in skel
    assert "y = 2" in skel
    # Only the first two body lines are kept.
    assert "return x + y" not in skel
