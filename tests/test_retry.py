from openai import RateLimitError

import pytest

from docgen.llm.retry import _wait_with_retry_after, with_retry


class _FakeResp:
    request = None
    status_code = None

    def __init__(self, headers=None):
        self.headers = headers or {}


def _make_rate_limit(retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    return RateLimitError("rate limited", response=_FakeResp(headers), body=None)


def test_retries_then_succeeds():
    calls = {"n": 0}

    @with_retry(max_attempts=3)
    def call():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _make_rate_limit()
        return "ok"

    assert call() == "ok"
    assert calls["n"] == 3


def test_retries_exhausted_raises():
    calls = {"n": 0}

    @with_retry(max_attempts=3)
    def call():
        calls["n"] += 1
        raise _make_rate_limit()

    with pytest.raises(RateLimitError):
        call()
    assert calls["n"] == 3


def test_non_retryable_reraises_immediately():
    calls = {"n": 0}

    @with_retry(max_attempts=3)
    def call():
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        call()
    assert calls["n"] == 1


def test_retry_after_header_honored():
    err = _make_rate_limit(retry_after=5)

    class _Outcome:
        def exception(self):
            return err

    class _State:
        outcome = _Outcome()

    assert _wait_with_retry_after(_State()) == 5.0


def test_retry_after_absent_falls_back_to_jitter():
    err = _make_rate_limit()

    class _Outcome:
        def exception(self):
            return err

    class _State:
        outcome = _Outcome()
        attempt_number = 1

    wait = _wait_with_retry_after(_State())
    assert isinstance(wait, (int, float))
    assert wait >= 0
