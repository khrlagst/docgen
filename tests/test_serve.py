import threading
import urllib.request
from pathlib import Path

from docgen.cli import _build_preview_server


def test_preview_server_serves_and_shuts_down_cleanly(tmp_path):
    """The freeze bug: a single-threaded server blocked the main thread on a
    keep-alive request so Ctrl+C was ignored, and observer.join() could hang.
    The threaded server must serve a page and stop promptly on shutdown().
    """
    (tmp_path / "index.md").write_text("# Hi\n\nWelcome.\n", encoding="utf-8")

    server = _build_preview_server(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode()
        assert "Welcome." in body
        assert "<!DOCTYPE html>" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert not thread.is_alive()
