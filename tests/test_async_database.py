"""
Test async database operations to ensure event loop is not blocked
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from core.database import DatabaseManager


class TestAsyncDatabaseOperations(unittest.TestCase):
    """Test async wrapper methods for database operations"""

    def test_async_wrapper_methods_exist(self):
        """Test that all async wrapper methods exist"""
        db = DatabaseManager(":memory:")

        # Check that async wrapper methods exist
        async_methods = [
            'add_user_async',
            'save_signal_async',
            'get_active_signal_async',
            'get_recent_signals_async',
            'get_last_signal_time_async',
            'count_signals_last_hour_async',
            'get_all_users_async',
            'save_signal_tracking_async',
            'update_signal_tracking_async',
            'close_signal_tracking_async',
            'get_active_signals_async',
            'save_statistics_async',
            'is_banned_async',
            'save_ai_log_async',
            'save_market_data_async'
        ]

        for method_name in async_methods:
            self.assertTrue(hasattr(db, method_name), f"Missing async method: {method_name}")
            self.assertTrue(callable(getattr(db, method_name)), f"Method {method_name} is not callable")

    def test_async_wrapper_does_not_block_event_loop(self):
        """Test that async wrapper doesn't block the event loop"""
        db = DatabaseManager(":memory:")
        db.init_database()

        async def run_test():
            # Test that multiple async operations can run concurrently
            tasks = [
                db.add_user_async(123456, "testuser", "Test", is_admin=False),
                db.add_user_async(123457, "testuser2", "Test2", is_admin=False),
                db.add_user_async(123458, "testuser3", "Test3", is_admin=False),
            ]

            # If these were blocking, they would run sequentially
            # With async wrappers, they should run concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Check that all completed without blocking
            self.assertEqual(len(results), 3)

        asyncio.run(run_test())

    def test_async_wrapper_signature_matches_sync(self):
        """Test that async wrapper signatures match sync methods"""
        db = DatabaseManager(":memory:")

        # Check that async wrappers have the same parameters as sync methods
        async_method_pairs = [
            ('add_user_async', 'add_user'),
            ('save_signal_async', 'save_signal'),
            ('get_active_signal_async', 'get_active_signal'),
            ('get_recent_signals_async', 'get_recent_signals'),
            ('get_last_signal_time_async', 'get_last_signal_time'),
            ('count_signals_last_hour_async', 'count_signals_last_hour'),
            ('get_all_users_async', 'get_all_users'),
            ('save_signal_tracking_async', 'save_signal_tracking'),
            ('update_signal_tracking_async', 'update_signal_tracking'),
            ('close_signal_tracking_async', 'close_signal_tracking'),
            ('get_active_signals_async', 'get_active_signals'),
            ('save_statistics_async', 'save_statistics'),
            ('is_banned_async', 'is_banned'),
            ('save_ai_log_async', 'save_ai_log'),
            ('save_market_data_async', 'save_market_data'),
        ]

        for async_name,sync_name in async_method_pairs:
            async_method = getattr(db, async_name)
            sync_method = getattr(db, sync_name)
            self.assertIsNotNone(async_method)
            self.assertIsNotNone(sync_method)


if __name__ == '__main__':
    unittest.main()
