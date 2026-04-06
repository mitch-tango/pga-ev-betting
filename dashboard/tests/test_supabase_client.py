from unittest.mock import MagicMock, patch

import pytest


class TestGetClient:
    def test_raises_on_missing_url(self):
        from lib.supabase_client import get_client

        mock_secrets = MagicMock()
        mock_secrets.__getitem__ = MagicMock(side_effect=KeyError("SUPABASE_URL"))

        with patch("lib.supabase_client.st") as mock_st:
            mock_st.secrets = mock_secrets
            with pytest.raises(RuntimeError, match="SUPABASE_URL"):
                get_client.__wrapped__()

    def test_raises_on_missing_key(self):
        from lib.supabase_client import get_client

        mock_secrets = MagicMock()
        def getitem(self, key):
            if key == "SUPABASE_URL":
                return "https://test.supabase.co"
            raise KeyError(key)
        mock_secrets.__getitem__ = getitem

        with patch("lib.supabase_client.st") as mock_st:
            mock_st.secrets = mock_secrets
            with pytest.raises(RuntimeError, match="SUPABASE_KEY"):
                get_client.__wrapped__()

    def test_returns_client_when_configured(self):
        from lib.supabase_client import get_client

        mock_secrets = MagicMock()
        mock_secrets.__getitem__ = lambda self, key: {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_KEY": "test-anon-key",
        }[key]

        with patch("lib.supabase_client.st") as mock_st, \
             patch("lib.supabase_client.create_client") as mock_create:
            mock_st.secrets = mock_secrets
            mock_create.return_value = MagicMock()
            client = get_client.__wrapped__()
            mock_create.assert_called_once_with("https://test.supabase.co", "test-anon-key")
            assert client is mock_create.return_value
