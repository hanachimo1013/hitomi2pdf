import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

from hitomi2pdf import Hitomi2PDF

def test_download_page_avif_success():
    downloader = Hitomi2PDF("test_output")
    downloader._fetch_image = AsyncMock(return_value=True)

    session = MagicMock()
    gallery_id = "12345"
    index = 1
    img_data = {
        'avif_url': 'https://example.com/1.avif',
        'webp_url': 'https://example.com/1.webp'
    }
    temp_path = "temp"

    result = asyncio.run(downloader.download_page(session, gallery_id, index, img_data, temp_path))

    assert result is True
    downloader._fetch_image.assert_called_once()
    assert downloader._fetch_image.call_args[0][1] == 'https://example.com/1.avif'

def test_download_page_fallback_success():
    downloader = Hitomi2PDF("test_output")
    downloader._fetch_image = AsyncMock(side_effect=[False, True])

    session = MagicMock()
    gallery_id = "12345"
    index = 1
    img_data = {
        'avif_url': 'https://example.com/1.avif',
        'webp_url': 'https://example.com/1.webp'
    }
    temp_path = "temp"

    result = asyncio.run(downloader.download_page(session, gallery_id, index, img_data, temp_path))

    assert result is True
    assert downloader._fetch_image.call_count == 2
    assert downloader._fetch_image.call_args_list[0][0][1] == 'https://example.com/1.avif'
    assert downloader._fetch_image.call_args_list[1][0][1] == 'https://example.com/1.webp'

def test_download_page_both_fail():
    downloader = Hitomi2PDF("test_output")
    downloader._fetch_image = AsyncMock(side_effect=[False, False])

    session = MagicMock()
    gallery_id = "12345"
    index = 1
    img_data = {
        'avif_url': 'https://example.com/1.avif',
        'webp_url': 'https://example.com/1.webp'
    }
    temp_path = "temp"

    result = asyncio.run(downloader.download_page(session, gallery_id, index, img_data, temp_path))

    assert result is False
    assert downloader._fetch_image.call_count == 2
    assert downloader._fetch_image.call_args_list[0][0][1] == 'https://example.com/1.avif'
    assert downloader._fetch_image.call_args_list[1][0][1] == 'https://example.com/1.webp'

def test_download_page_only_webp():
    downloader = Hitomi2PDF("test_output")
    downloader._fetch_image = AsyncMock(return_value=True)

    session = MagicMock()
    gallery_id = "12345"
    index = 1
    img_data = {
        'webp_url': 'https://example.com/1.webp'
    }
    temp_path = "temp"

    result = asyncio.run(downloader.download_page(session, gallery_id, index, img_data, temp_path))

    assert result is True
    downloader._fetch_image.assert_called_once()
    assert downloader._fetch_image.call_args[0][1] == 'https://example.com/1.webp'
