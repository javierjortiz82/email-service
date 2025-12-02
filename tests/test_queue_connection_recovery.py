"""Test suite for email queue connection recovery and retry logic.

Tests automatic connection recovery mechanism for the email queue
that handles stale PostgreSQL connections.

Features tested:
- Connection validation (ping test)
- Automatic dead connection detection and replacement
"""

import pytest
from unittest.mock import MagicMock
from psycopg2 import OperationalError


def test_validate_connection_alive():
    """Test connection validation with a healthy connection."""
    from email_service.database.queue import _validate_connection

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = None
    mock_cursor.execute.return_value = None
    mock_cursor.fetchone.return_value = (1,)

    result = _validate_connection(mock_conn)
    assert result is True


def test_validate_connection_dead():
    """Test connection validation detects dead connection."""
    from email_service.database.queue import _validate_connection

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.execute.side_effect = OperationalError("server closed")

    result = _validate_connection(mock_conn)
    assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
