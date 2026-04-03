import asyncio
import aiohttp
import pytest
from unittest.mock import patch, AsyncMock

from hitomi2pdf import retry_on_failure

def test_success_on_first_try():
    call_count = 0

    @retry_on_failure(max_retries=3, base_delay=0)
    async def dummy_func():
        nonlocal call_count
        call_count += 1
        return "success"

    result = asyncio.run(dummy_func())
    assert result == "success"
    assert call_count == 1

def test_retry_on_client_error_then_success():
    call_count = 0

    @retry_on_failure(max_retries=3, base_delay=0)
    async def dummy_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise aiohttp.ClientError("dummy error")
        return "success"

    with patch('hitomi2pdf.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        result = asyncio.run(dummy_func())

    assert result == "success"
    assert call_count == 3
    assert mock_sleep.call_count == 2

def test_exhaust_retries_on_timeout_error():
    call_count = 0

    @retry_on_failure(max_retries=3, base_delay=0)
    async def dummy_func():
        nonlocal call_count
        call_count += 1
        raise asyncio.TimeoutError("timeout")

    with patch('hitomi2pdf.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        result = asyncio.run(dummy_func())

    assert result is None
    assert call_count == 3
    assert mock_sleep.call_count == 2

def test_other_exceptions_are_not_caught():
    call_count = 0

    @retry_on_failure(max_retries=3, base_delay=0)
    async def dummy_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("other error")

    with patch('hitomi2pdf.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(ValueError):
            asyncio.run(dummy_func())

    assert call_count == 1
    assert mock_sleep.call_count == 0
