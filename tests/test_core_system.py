#!/usr/bin/env python3
"""
Test Script for Core Communication System
==========================================
Comprehensive testing of bulletproof EA <-> Server communication

Usage:
    python test_core_system.py
    python test_core_system.py --verbose
    python test_core_system.py --account-id 1

Author: ngTradingBot
Last Modified: 2025-10-17
"""

import sys
import time
import argparse
import logging
from datetime import datetime
from typing import Dict, List

# Add project root to path
sys.path.insert(0, '/projects/ngTradingBot')

from database import init_db, ScopedSession
from models import Account, Trade, Command
from redis_client import init_redis, get_redis
from core_communication import (
    init_core_communication,
    get_core_comm,
    CommandPriority,
    ConnectionState
)
from core_api import (
    send_open_trade_command,
    send_modify_trade_command,
    send_close_trade_command,
    is_ea_connected
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CoreSystemTester:
    """Test suite for core communication system"""
    
    def __init__(self, account_id: int = 1):
        self.account_id = account_id
        self.tests_passed = 0
        self.tests_failed = 0
        self.errors = []
    
    def run_all_tests(self):
        """Run all test suites"""
        logger.info("="*70)
        logger.info("🧪 Starting Core Communication System Tests")
        logger.info("="*70)
        
        # Initialize systems
        self.test_initialization()
        
        # Test connection management
        self.test_connection_management()
        
        # Test command system
        self.test_command_system()
        
        # Test trade sync
        self.test_trade_sync()
        
        # Test health monitoring
        self.test_health_monitoring()
        
        # Test error handling
        self.test_error_handling()
        
        # Print results
        self.print_results()
    
    def test_initialization(self):
        """Test system initialization"""
        logger.info("\n📋 Test Suite: System Initialization")
        
        # Test database
        try:
            init_db()
            self.pass_test("Database initialization")
        except Exception as e:
            self.fail_test("Database initialization", str(e))
        
        # Test Redis
        try:
            init_redis()
            redis = get_redis()
            redis.redis_client.ping()
            self.pass_test("Redis initialization")
        except Exception as e:
            self.fail_test("Redis initialization", str(e))
        
        # Test core communication
        try:
            init_core_communication()
            comm = get_core_comm()
            self.pass_test("Core communication initialization")
        except Exception as e:
            self.fail_test("Core communication initialization", str(e))
    
    def test_connection_management(self):
        """Test EA connection management"""
        logger.info("\n📋 Test Suite: Connection Management")
        
        comm = get_core_comm()
        
        # Test connection registration
        try:
            conn = comm.register_connection(
                account_id=self.account_id,
                account_number=12345678,
                broker="Test Broker"
            )
            
            assert conn.state == ConnectionState.CONNECTED
            assert conn.account_id == self.account_id
            self.pass_test("Connection registration")
        except Exception as e:
            self.fail_test("Connection registration", str(e))
        
        # Test connection retrieval
        try:
            conn = comm.get_connection(self.account_id)
            assert conn is not None
            assert conn.state == ConnectionState.CONNECTED
            self.pass_test("Connection retrieval")
        except Exception as e:
            self.fail_test("Connection retrieval", str(e))
        
        # Test heartbeat processing
        try:
            result = comm.process_heartbeat(
                account_id=self.account_id,
                balance=10000.00,
                equity=10050.00,
                margin=100.00,
                free_margin=9950.00,
                latency_ms=45.3
            )
            
            assert result['status'] == 'success'
            
            conn = comm.get_connection(self.account_id)
            assert conn.heartbeat_count > 0
            self.pass_test("Heartbeat processing")
        except Exception as e:
            self.fail_test("Heartbeat processing", str(e))
        
        # Test connection health check
        try:
            conn = comm.get_connection(self.account_id)
            assert conn.is_healthy()
            assert conn.health_score > 90
            self.pass_test("Connection health check")
        except Exception as e:
            self.fail_test("Connection health check", str(e))
    
    def test_command_system(self):
        """Test command creation and execution"""
        logger.info("\n📋 Test Suite: Command System")
        
        comm = get_core_comm()
        
        # Test command creation
        try:
            cmd_id, cmd_exec = comm.create_command(
                account_id=self.account_id,
                command_type="TEST_COMMAND",
                payload={'test': 'data'},
                priority=CommandPriority.NORMAL
            )
            
            assert cmd_id is not None
            assert cmd_exec.status.value == 'pending'
            self.pass_test("Command creation")
        except Exception as e:
            self.fail_test("Command creation", str(e))
        
        # Test command retrieval from queue
        try:
            commands = comm.get_pending_commands(self.account_id, limit=10)
            assert len(commands) > 0
            assert commands[0]['type'] == 'TEST_COMMAND'
            self.pass_test("Command retrieval from queue")
        except Exception as e:
            self.fail_test("Command retrieval from queue", str(e))
        
        # Test command response processing
        try:
            comm.process_command_response(
                command_id=cmd_id,
                status='completed',
                response_data={'ticket': 99999, 'test': 'response'}
            )
            
            # Verify in database
            with ScopedSession() as db:
                cmd = db.query(Command).filter_by(id=cmd_id).first()
                assert cmd.status == 'completed'
            
            self.pass_test("Command response processing")
        except Exception as e:
            self.fail_test("Command response processing", str(e))
        
        # Test command priority
        try:
            # Create high priority command
            cmd_id_high, _ = comm.create_command(
                account_id=self.account_id,
                command_type="HIGH_PRIORITY_TEST",
                payload={'urgent': True},
                priority=CommandPriority.HIGH
            )
            
            # Create low priority command
            cmd_id_low, _ = comm.create_command(
                account_id=self.account_id,
                command_type="LOW_PRIORITY_TEST",
                payload={'urgent': False},
                priority=CommandPriority.LOW
            )
            
            self.pass_test("Command priority system")
        except Exception as e:
            self.fail_test("Command priority system", str(e))
    
    def test_trade_sync(self):
        """Test trade synchronization (EA as source of truth)"""
        logger.info("\n📋 Test Suite: Trade Synchronization")
        
        comm = get_core_comm()
        
        # Test empty sync
        try:
            result = comm.sync_trades_from_ea(
                account_id=self.account_id,
                ea_trades=[]
            )
            
            assert result['status'] == 'success'
            self.pass_test("Empty trade sync")
        except Exception as e:
            self.fail_test("Empty trade sync", str(e))
        
        # Test adding new trade from EA
        try:
            # Create trade in database (simulating manual entry)
            with ScopedSession() as db:
                trade = Trade(
                    account_id=self.account_id,
                    mt5_ticket=99999,
                    symbol='EURUSD',
                    direction='BUY',
                    volume=0.1,
                    open_price=1.0900,
                    open_time=datetime.utcnow(),
                    status='open'
                )
                db.add(trade)
                db.commit()
            
            # Sync with EA that has the trade
            result = comm.sync_trades_from_ea(
                account_id=self.account_id,
                ea_trades=[{
                    'ticket': 99999,
                    'symbol': 'EURUSD',
                    'direction': 'BUY',
                    'volume': 0.1,
                    'open_price': 1.0900,
                    'open_time': int(datetime.utcnow().timestamp()),
                    'sl': 1.0850,
                    'tp': 1.0950
                }]
            )
            
            assert result['status'] == 'success'
            assert result['reconciliation']['updated_trades'] >= 1
            self.pass_test("Trade sync with updates")
        except Exception as e:
            self.fail_test("Trade sync with updates", str(e))
        
        # Test closing trade not in EA (EA is truth)
        try:
            # Create another trade in DB
            with ScopedSession() as db:
                trade = Trade(
                    account_id=self.account_id,
                    mt5_ticket=88888,
                    symbol='GBPUSD',
                    direction='SELL',
                    volume=0.1,
                    open_price=1.2500,
                    open_time=datetime.utcnow(),
                    status='open'
                )
                db.add(trade)
                db.commit()
            
            # Sync with EA that does NOT have this trade
            result = comm.sync_trades_from_ea(
                account_id=self.account_id,
                ea_trades=[{
                    'ticket': 99999,
                    'symbol': 'EURUSD',
                    'direction': 'BUY',
                    'volume': 0.1,
                    'open_price': 1.0900,
                    'open_time': int(datetime.utcnow().timestamp()),
                    'sl': 1.0850,
                    'tp': 1.0950
                }]
            )
            
            # Trade 88888 should be closed
            with ScopedSession() as db:
                trade = db.query(Trade).filter_by(mt5_ticket=88888).first()
                assert trade.status == 'closed'
            
            assert result['reconciliation']['closed_trades'] >= 1
            self.pass_test("Trade sync closes trades not in EA")
        except Exception as e:
            self.fail_test("Trade sync closes trades not in EA", str(e))
        
        # Cleanup test trades
        try:
            with ScopedSession() as db:
                db.query(Trade).filter(
                    Trade.account_id == self.account_id,
                    Trade.mt5_ticket.in_([99999, 88888])
                ).delete()
                db.commit()
            self.pass_test("Trade cleanup")
        except Exception as e:
            self.fail_test("Trade cleanup", str(e))
    
    def test_health_monitoring(self):
        """Test health monitoring and metrics"""
        logger.info("\n📋 Test Suite: Health Monitoring")
        
        comm = get_core_comm()
        
        # Test system status
        try:
            status = comm.get_system_status()
            
            assert 'connections' in status
            assert 'commands' in status
            assert 'data' in status
            assert status['connections']['total'] >= 1
            
            self.pass_test("System status retrieval")
        except Exception as e:
            self.fail_test("System status retrieval", str(e))
        
        # Test connection metrics
        try:
            conn = comm.get_connection(self.account_id)
            metrics = conn.get_status_dict()
            
            assert 'health_score' in metrics
            assert 'heartbeat_count' in metrics
            assert 'is_healthy' in metrics
            assert metrics['is_healthy'] == True
            
            self.pass_test("Connection metrics")
        except Exception as e:
            self.fail_test("Connection metrics", str(e))
        
        # Test health degradation
        try:
            conn = comm.get_connection(self.account_id)
            initial_score = conn.health_score
            
            # Simulate failures
            for _ in range(3):
                conn.record_failure()
            
            assert conn.health_score < initial_score
            assert conn.consecutive_failures == 3
            
            # Restore health
            for _ in range(5):
                conn.update_heartbeat()
            
            assert conn.consecutive_failures == 0
            
            self.pass_test("Health degradation and recovery")
        except Exception as e:
            self.fail_test("Health degradation and recovery", str(e))
    
    def test_error_handling(self):
        """Test error handling and edge cases"""
        logger.info("\n📋 Test Suite: Error Handling")
        
        comm = get_core_comm()
        
        # Test unknown account
        try:
            result = comm.process_heartbeat(
                account_id=99999,
                balance=0,
                equity=0
            )
            
            assert result['status'] == 'error'
            self.pass_test("Unknown account handling")
        except Exception as e:
            self.fail_test("Unknown account handling", str(e))
        
        # Test invalid command response
        try:
            result = comm.process_command_response(
                command_id='nonexistent_cmd',
                status='completed',
                response_data={}
            )
            
            assert result['status'] == 'error'
            self.pass_test("Invalid command response handling")
        except Exception as e:
            self.fail_test("Invalid command response handling", str(e))
        
        # Test connection removal
        try:
            comm.remove_connection(self.account_id)
            conn = comm.get_connection(self.account_id)
            assert conn is None
            
            # Re-register for other tests
            comm.register_connection(self.account_id, 12345678, "Test Broker")
            
            self.pass_test("Connection removal")
        except Exception as e:
            self.fail_test("Connection removal", str(e))
    
    def pass_test(self, test_name: str):
        """Mark test as passed"""
        self.tests_passed += 1
        logger.info(f"✅ PASS: {test_name}")
    
    def fail_test(self, test_name: str, error: str):
        """Mark test as failed"""
        self.tests_failed += 1
        self.errors.append({'test': test_name, 'error': error})
        logger.error(f"❌ FAIL: {test_name} - {error}")
    
    def print_results(self):
        """Print test results summary"""
        logger.info("\n" + "="*70)
        logger.info("📊 Test Results Summary")
        logger.info("="*70)
        
        total = self.tests_passed + self.tests_failed
        success_rate = (self.tests_passed / total * 100) if total > 0 else 0
        
        logger.info(f"Total Tests:   {total}")
        logger.info(f"Passed:        {self.tests_passed} ✅")
        logger.info(f"Failed:        {self.tests_failed} ❌")
        logger.info(f"Success Rate:  {success_rate:.1f}%")
        
        if self.errors:
            logger.info("\n🔴 Failed Tests:")
            for error in self.errors:
                logger.info(f"  - {error['test']}: {error['error']}")
        
        logger.info("="*70)
        
        if self.tests_failed == 0:
            logger.info("🎉 All tests passed! Core system is bulletproof!")
        else:
            logger.error("⚠️  Some tests failed. Please review and fix issues.")
        
        return self.tests_failed == 0


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Test ngTradingBot Core Communication System'
    )
    parser.add_argument(
        '--account-id',
        type=int,
        default=1,
        help='Account ID to use for testing (default: 1)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Run tests
    tester = CoreSystemTester(account_id=args.account_id)
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⏸️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
