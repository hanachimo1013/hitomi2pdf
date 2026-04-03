import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from hitomi2pdf import Hitomi2PDF, retry_on_failure

class TestFetchImage(unittest.TestCase):
    def setUp(self):
        self.app = Hitomi2PDF(output_dir="test_outputs")
        # Ensure we don't delay during tests
        patcher = patch('hitomi2pdf.asyncio.sleep', new_callable=AsyncMock)
        self.mock_sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_url(self):
        # Test that an empty URL immediately returns False
        result = asyncio.run(self.app._fetch_image(None, "", {}, "dummy.jpg"))
        self.assertFalse(result)

    def test_non_200_status(self):
        # Mock session to return a 404
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 404

        # Async context manager mock
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_session.get.return_value = mock_context_manager

        result = asyncio.run(self.app._fetch_image(mock_session, "http://example.com/img.jpg", {}, "dummy.jpg"))
        self.assertFalse(result)

        # Test 500 status to trigger the print branch
        mock_response.status = 500
        result = asyncio.run(self.app._fetch_image(mock_session, "http://example.com/img.jpg", {}, "dummy.jpg"))
        self.assertFalse(result)

    def test_small_file_junk(self):
        # Mock session to return 200 but very small content
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = b"small" # < 500 bytes

        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_session.get.return_value = mock_context_manager

        result = asyncio.run(self.app._fetch_image(mock_session, "http://example.com/img.jpg", {}, "dummy.jpg"))
        self.assertFalse(result)

    @patch('hitomi2pdf.aiofiles.open')
    def test_happy_path(self, mock_aiofiles_open):
        # Mock session to return 200 and sufficient content
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read.return_value = b"x" * 600 # >= 500 bytes

        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_session.get.return_value = mock_context_manager

        # Mock aiofiles.open context manager
        mock_file_context = AsyncMock()
        mock_file = AsyncMock()
        mock_file_context.__aenter__.return_value = mock_file
        mock_aiofiles_open.return_value = mock_file_context

        result = asyncio.run(self.app._fetch_image(mock_session, "http://example.com/img.jpg", {}, "dummy.jpg"))

        self.assertTrue(result)
        mock_aiofiles_open.assert_called_once_with("dummy.jpg", "wb")
        mock_file.write.assert_called_once_with(b"x" * 600)

    def test_client_error_retry_exhaustion(self):
        # Mock session to raise ClientError
        mock_session = MagicMock()

        # When get() is called, raise an exception during __aenter__
        mock_context_manager = MagicMock()
        mock_context_manager.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Mock error"))
        mock_session.get.return_value = mock_context_manager

        # The retry decorator will retry 3 times and then return None
        result = asyncio.run(self.app._fetch_image(mock_session, "http://example.com/img.jpg", {}, "dummy.jpg"))
        self.assertIsNone(result)
        self.assertEqual(mock_session.get.call_count, 3)
        self.assertEqual(self.mock_sleep.call_count, 2) # Sleeps after attempt 1 and 2

if __name__ == '__main__':
    unittest.main()
