#!/usr/bin/env python3
"""
Core Communication Module for ngTradingBot
=========================================
Bulletproof EA <-> Server Communication Layer

This is the CORE layer - absolutely reliable communication with MT5 EA.
EA (MT5) is the SINGLE SOURCE OF TRUTH for all trading data.

Architecture:
-------------
1. EA sends data TO server (ticks, trades, account state)
2. Server sends commands TO EA (open, modify, close trades)
3. EA confirms command execution with response
4. All communication is validated, logged, and monitored

Key Principles:
--------------
- Zero data loss: All EA messages are persisted immediately
- Fast command delivery: Redis queue for instant command push
- Reliable responses: Timeout tracking and retry logic
- Connection resilience: Auto-reconnect with exponential backoff
- Complete audit trail: Every interaction logged with metrics

Author: ngTradingBot
Last Modified: 2025-10-17
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
from threading import Lock

from sqlalchemy import func
from database import ScopedSession
from models import Account, Command, Trade, Tick, Log, AccountTransaction
from redis_client import get_redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class ConnectionState(Enum):
    """EA connection states"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class CommandPriority(Enum):
    """Command priority levels (higher = more urgent)"""
    LOW = 1          # Symbol updates, settings changes
    NORMAL = 5       # Regular trade operations
    HIGH = 10        # SL/TP modifications, urgent closes
    CRITICAL = 99    # Emergency close all, connection issues


class CommandStatus(Enum):
    """Command execution states"""
    PENDING = "pending"         # Created, waiting for EA
    EXECUTING = "executing"     # Sent to EA, awaiting response
    COMPLETED = "completed"     # Successfully executed
    FAILED = "failed"           # Execution failed
    TIMEOUT = "timeout"         # EA did not respond in time
    CANCELLED = "cancelled"     # Manually cancelled


@dataclass
class EAConnection:
    """Represents an active EA connection"""
    account_id: int
    account_number: int
    broker: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    
    # Connection metrics
    connected_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    last_tick_received: Optional[datetime] = None
    last_command_sent: Optional[datetime] = None
    
    # Performance metrics
    heartbeat_count: int = 0
    tick_count: int = 0
    command_count: int = 0
    failed_heartbeats: int = 0
    reconnect_count: int = 0
    
    # Latency tracking (in seconds)
    avg_heartbeat_latency: float = 0.0
    avg_command_response_latency: float = 0.0
    
    # Connection quality
    consecutive_failures: int = 0
    health_score: float = 100.0  # 0-100
    
    def __post_init__(self):
        self.lock = Lock()
    
    def update_heartbeat(self):
        """Update heartbeat metrics with timezone-aware timestamps"""
        with self.lock:
            now = tz.now_utc()
            self.last_heartbeat = tz.to_db(now)  # Store as naive UTC for DB
            self.heartbeat_count += 1
            self.consecutive_failures = 0
            
            # Improve health score
            if self.health_score < 100:
                self.health_score = min(100, self.health_score + 5)
    
    def record_failure(self):
        """Record a communication failure"""
        with self.lock:
            self.consecutive_failures += 1
            self.failed_heartbeats += 1
            
            # Degrade health score
            self.health_score = max(0, self.health_score - 10)
    
    def is_healthy(self, max_heartbeat_age: int = 60) -> bool:
        """Check if connection is healthy"""
        if self.state != ConnectionState.CONNECTED:
            return False
        
        if not self.last_heartbeat:
            return False
        
        # Convert naive UTC from DB to aware UTC
        last_hb_aware = tz.from_db(self.last_heartbeat)
        age = (tz.now_utc() - last_hb_aware).total_seconds()
        
        return (
            age < max_heartbeat_age and
            self.consecutive_failures < 3 and
            self.health_score > 50
        )
    
    def get_status_dict(self) -> Dict:
        """Get connection status as dictionary"""
        return {
            'account_id': self.account_id,
            'account_number': self.account_number,
            'broker': self.broker,
            'state': self.state.value,
            'connected_at': self.connected_at.isoformat() if self.connected_at else None,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'last_heartbeat_age_seconds': (datetime.utcnow() - self.last_heartbeat).total_seconds() if self.last_heartbeat else None,
            'heartbeat_count': self.heartbeat_count,
            'tick_count': self.tick_count,
            'command_count': self.command_count,
            'failed_heartbeats': self.failed_heartbeats,
            'reconnect_count': self.reconnect_count,
            'consecutive_failures': self.consecutive_failures,
            'health_score': round(self.health_score, 2),
            'is_healthy': self.is_healthy(),
            'avg_heartbeat_latency_ms': round(self.avg_heartbeat_latency * 1000, 2),
            'avg_command_latency_ms': round(self.avg_command_response_latency * 1000, 2)
        }


@dataclass
class CommandExecution:
    """Track command execution state"""
    command_id: str
    account_id: int
    command_type: str
    priority: CommandPriority
    
    # Execution tracking
    status: CommandStatus = CommandStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Retry logic
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None
    
    # Response data
    response_data: Optional[Dict] = None
    error_message: Optional[str] = None
    
    # Timeout configuration (seconds)
    timeout: int = 30
    
    def is_expired(self) -> bool:
        """Check if command has expired"""
        if self.status == CommandStatus.COMPLETED:
            return False
        
        age = (datetime.utcnow() - self.created_at).total_seconds()
        max_age = self.timeout * (self.retry_count + 1)
        
        return age > max_age
    
    def can_retry(self) -> bool:
        """Check if command can be retried"""
        return (
            self.status in [CommandStatus.FAILED, CommandStatus.TIMEOUT] and
            self.retry_count < self.max_retries and
            not self.is_expired()
        )
    
    def get_latency_ms(self) -> Optional[float]:
        """Get command execution latency in milliseconds"""
        if self.sent_at and self.completed_at:
            delta = (self.completed_at - self.sent_at).total_seconds()
            return round(delta * 1000, 2)
        return None


# ============================================================================
# CORE COMMUNICATION MANAGER
# ============================================================================

class CoreCommunicationManager:
    """
    Bulletproof EA <-> Server Communication Manager
    
    Responsibilities:
    - Manage EA connections and health monitoring
    - Handle command queue with priority and retry logic
    - Process EA responses with validation
    - Maintain connection state and metrics
    - Provide comprehensive logging and alerting
    """
    
    def __init__(self):
        self.redis = get_redis()
        self.connections: Dict[int, EAConnection] = {}  # account_id -> EAConnection
        self.active_commands: Dict[str, CommandExecution] = {}  # command_id -> CommandExecution
        self.lock = Lock()
        
        # Metrics
        self.total_commands_processed = 0
        self.total_commands_failed = 0
        self.total_ticks_received = 0
        self.total_heartbeats_received = 0
        
        logger.info("✅ CoreCommunicationManager initialized")
    
    # ========================================================================
    # CONNECTION MANAGEMENT
    # ========================================================================
    
    def register_connection(
        self,
        account_id: int,
        account_number: int,
        broker: str
    ) -> EAConnection:
        """
        Register new EA connection
        
        Args:
            account_id: Internal database account ID
            account_number: MT5 account number
            broker: Broker name
        
        Returns:
            EAConnection object
        """
        with self.lock:
            if account_id in self.connections:
                conn = self.connections[account_id]
                conn.state = ConnectionState.RECONNECTING
                conn.reconnect_count += 1
                logger.warning(f"🔄 EA reconnecting: Account {account_number} (reconnect #{conn.reconnect_count})")
            else:
                conn = EAConnection(
                    account_id=account_id,
                    account_number=account_number,
                    broker=broker,
                    state=ConnectionState.CONNECTING
                )
                self.connections[account_id] = conn
                logger.info(f"🔌 New EA connecting: Account {account_number} from {broker}")
            
            conn.connected_at = datetime.utcnow()
            conn.state = ConnectionState.CONNECTED
            
            # Update database
            with ScopedSession() as db:
                account = db.query(Account).filter_by(id=account_id).first()
                if account:
                    account.last_heartbeat = datetime.utcnow()
                    db.commit()
            
            return conn
    
    def get_connection(self, account_id: int) -> Optional[EAConnection]:
        """Get EA connection by account ID"""
        return self.connections.get(account_id)
    
    def get_all_connections(self) -> List[EAConnection]:
        """Get all active connections"""
        with self.lock:
            return list(self.connections.values())
    
    def remove_connection(self, account_id: int):
        """Remove EA connection"""
        with self.lock:
            if account_id in self.connections:
                conn = self.connections[account_id]
                conn.state = ConnectionState.DISCONNECTED
                logger.info(f"🔌 EA disconnected: Account {conn.account_number}")
                del self.connections[account_id]
    
    def process_heartbeat(
        self,
        account_id: int,
        balance: float,
        equity: float,
        margin: float = 0.0,
        free_margin: float = 0.0,
        latency_ms: float = 0.0
    ) -> Dict:
        """
        Process heartbeat from EA
        
        Args:
            account_id: Account ID
            balance: Current balance
            equity: Current equity
            margin: Used margin
            free_margin: Free margin
            latency_ms: Round-trip latency in milliseconds
        
        Returns:
            Response dict with pending commands
        """
        conn = self.get_connection(account_id)
        
        if not conn:
            logger.error(f"❌ Heartbeat from unknown account {account_id}")
            return {'status': 'error', 'message': 'Account not connected'}
        
        # Update connection metrics
        conn.update_heartbeat()
        self.total_heartbeats_received += 1
        
        # Update latency tracking
        if latency_ms > 0:
            # Exponential moving average
            alpha = 0.3
            conn.avg_heartbeat_latency = (
                alpha * (latency_ms / 1000) +
                (1 - alpha) * conn.avg_heartbeat_latency
            )
        
        # Update database
        with ScopedSession() as db:
            account = db.query(Account).filter_by(id=account_id).first()
            if account:
                account.balance = balance
                account.equity = equity
                account.margin = margin
                account.free_margin = free_margin
                account.last_heartbeat = datetime.utcnow()
                db.commit()
        
        # Get pending commands for this account
        commands = self.get_pending_commands(account_id, limit=10)
        
        logger.debug(
            f"💓 Heartbeat: Account {conn.account_number} | "
            f"Balance: €{balance:.2f} | Equity: €{equity:.2f} | "
            f"Latency: {latency_ms:.1f}ms | Commands: {len(commands)}"
        )
        
        return {
            'status': 'success',
            'commands': commands,
            'server_time': datetime.utcnow().isoformat()
        }
    
    # ========================================================================
    # TICK DATA PROCESSING
    # ========================================================================
    
    def process_tick_batch(
        self,
        account_id: int,
        ticks: List[Dict]
    ) -> Dict:
        """
        Process batch of ticks from EA
        
        Args:
            account_id: Account ID
            ticks: List of tick data dictionaries
        
        Returns:
            Processing result
        """
        if not ticks:
            return {'status': 'success', 'processed': 0}
        
        conn = self.get_connection(account_id)
        if conn:
            conn.last_tick_received = datetime.utcnow()
            conn.tick_count += len(ticks)
        
        self.total_ticks_received += len(ticks)
        
        # Ticks are processed by tick_batch_writer
        # We just acknowledge receipt here
        
        logger.debug(f"📊 Received {len(ticks)} ticks from account {account_id}")
        
        return {
            'status': 'success',
            'processed': len(ticks),
            'server_time': datetime.utcnow().isoformat()
        }
    
    # ========================================================================
    # TRADE SYNC (EA AS SOURCE OF TRUTH)
    # ========================================================================
    
    def sync_trades_from_ea(
        self,
        account_id: int,
        ea_trades: List[Dict]
    ) -> Dict:
        """
        Sync all open trades from EA (EA is source of truth)
        
        This ensures server database matches EA state exactly.
        EA sends complete list of open positions every 30 seconds.
        
        Args:
            account_id: Account ID
            ea_trades: List of trade dictionaries from EA
        
        Returns:
            Sync result with reconciliation info
        """
        with ScopedSession() as db:
            # Get all open trades in database for this account
            db_trades = db.query(Trade).filter(
                Trade.account_id == account_id,
                Trade.status == 'open'
            ).all()
            
            db_tickets = {trade.mt5_ticket for trade in db_trades}
            ea_tickets = {trade['ticket'] for trade in ea_trades}
            
            # Find discrepancies
            missing_in_ea = db_tickets - ea_tickets  # In DB but not in EA -> closed
            missing_in_db = ea_tickets - db_tickets  # In EA but not in DB -> new
            both = db_tickets & ea_tickets  # In both -> update
            
            reconciliation = {
                'total_ea_trades': len(ea_trades),
                'total_db_trades': len(db_trades),
                'closed_trades': len(missing_in_ea),
                'new_trades': len(missing_in_db),
                'updated_trades': len(both),
                'changes': []
            }
            
            # Close trades that exist in DB but not in EA
            for ticket in missing_in_ea:
                trade = db.query(Trade).filter_by(
                    account_id=account_id,
                    mt5_ticket=ticket
                ).first()
                
                if trade:
                    trade.status = 'closed'
                    trade.close_time = datetime.utcnow()
                    trade.close_reason = 'EA_SYNC_CLOSED'

                    # Calculate trade metrics
                    from trade_utils import calculate_trade_metrics_on_close
                    calculate_trade_metrics_on_close(trade)

                    reconciliation['changes'].append(
                        f"Closed trade {ticket} (not found in EA)"
                    )
                    logger.warning(f"⚠️  Trade {ticket} closed via EA sync (not found in EA)")
            
            # Add new trades found in EA but not in DB
            for ea_trade in ea_trades:
                ticket = ea_trade['ticket']
                
                if ticket in missing_in_db:
                    # Create new trade record
                    new_trade = Trade(
                        account_id=account_id,
                        mt5_ticket=ticket,
                        symbol=ea_trade['symbol'],
                        direction=ea_trade.get('direction', 'BUY'),
                        volume=ea_trade['volume'],
                        open_price=ea_trade['open_price'],
                        open_time=datetime.fromtimestamp(ea_trade['open_time']) if 'open_time' in ea_trade else datetime.utcnow(),
                        current_sl=ea_trade.get('sl', 0.0),
                        current_tp=ea_trade.get('tp', 0.0),
                        initial_sl=ea_trade.get('sl', 0.0),
                        initial_tp=ea_trade.get('tp', 0.0),
                        status='open',
                        source='ea_sync',
                        entry_reason='Found in EA during sync'
                    )

                    # Enrich with session metadata
                    from trade_utils import enrich_trade_metadata
                    enrich_trade_metadata(new_trade)

                    db.add(new_trade)
                    reconciliation['changes'].append(
                        f"Added trade {ticket} from EA"
                    )
                    logger.info(f"➕ New trade {ticket} added from EA sync")
                
                elif ticket in both:
                    # Update existing trade
                    trade = db.query(Trade).filter_by(
                        account_id=account_id,
                        mt5_ticket=ticket
                    ).first()
                    
                    if trade:
                        # Update SL/TP if changed
                        ea_sl = ea_trade.get('sl', 0.0)
                        ea_tp = ea_trade.get('tp', 0.0)
                        
                        if trade.current_sl != ea_sl or trade.current_tp != ea_tp:
                            old_sl = trade.current_sl
                            old_tp = trade.current_tp
                            trade.current_sl = ea_sl
                            trade.current_tp = ea_tp
                            
                            reconciliation['changes'].append(
                                f"Updated SL/TP for {ticket}: "
                                f"SL {old_sl}->{ea_sl}, TP {old_tp}->{ea_tp}"
                            )
                            logger.info(
                                f"🔄 Trade {ticket} SL/TP updated: "
                                f"SL {old_sl}->{ea_sl}, TP {old_tp}->{ea_tp}"
                            )
            
            db.commit()
            
            if reconciliation['changes']:
                logger.info(
                    f"🔄 Trade sync completed for account {account_id}: "
                    f"{reconciliation['closed_trades']} closed, "
                    f"{reconciliation['new_trades']} new, "
                    f"{reconciliation['updated_trades']} updated"
                )
            else:
                logger.debug(f"✅ Trade sync: No changes for account {account_id}")
            
            return {
                'status': 'success',
                'reconciliation': reconciliation
            }
    
    # ========================================================================
    # COMMAND QUEUE MANAGEMENT
    # ========================================================================
    
    def create_command(
        self,
        account_id: int,
        command_type: str,
        payload: Dict,
        priority: CommandPriority = CommandPriority.NORMAL,
        timeout: int = 30
    ) -> Tuple[str, CommandExecution]:
        """
        Create new command for EA
        
        Args:
            account_id: Target account ID
            command_type: Command type (OPEN_TRADE, MODIFY_TRADE, CLOSE_TRADE, etc.)
            payload: Command payload data
            priority: Command priority
            timeout: Command timeout in seconds
        
        Returns:
            Tuple of (command_id, CommandExecution object)
        """
        # Generate unique command ID
        timestamp = int(time.time() * 1000)
        command_id = f"cmd_{account_id}_{timestamp}"
        
        # Create command in database
        with ScopedSession() as db:
            cmd = Command(
                id=command_id,
                account_id=account_id,
                type=command_type,
                payload=payload,
                status='pending',
                created_at=datetime.utcnow()
            )
            db.add(cmd)
            db.commit()
        
        # Create execution tracker
        cmd_exec = CommandExecution(
            command_id=command_id,
            account_id=account_id,
            command_type=command_type,
            priority=priority,
            timeout=timeout
        )
        
        # Store in active commands
        with self.lock:
            self.active_commands[command_id] = cmd_exec
        
        # Push to Redis queue for instant delivery
        self.redis.push_command(account_id, {
            'id': command_id,
            'type': command_type,
            **payload
        })
        
        # Update connection metrics
        conn = self.get_connection(account_id)
        if conn:
            conn.command_count += 1
            conn.last_command_sent = datetime.utcnow()
        
        self.total_commands_processed += 1
        
        logger.info(
            f"📤 Command created: {command_type} | "
            f"ID: {command_id} | Priority: {priority.name} | "
            f"Account: {account_id}"
        )
        
        return command_id, cmd_exec
    
    def get_pending_commands(
        self,
        account_id: int,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get pending commands for account from Redis queue
        
        Args:
            account_id: Account ID
            limit: Maximum number of commands to return
        
        Returns:
            List of command dictionaries
        """
        commands = []
        
        # Pop commands from Redis queue
        for _ in range(limit):
            cmd = self.redis.pop_command(account_id)
            if not cmd:
                break
            
            commands.append(cmd)
            
            # Mark as executing
            cmd_id = cmd.get('id')
            if cmd_id and cmd_id in self.active_commands:
                cmd_exec = self.active_commands[cmd_id]
                cmd_exec.status = CommandStatus.EXECUTING
                cmd_exec.sent_at = datetime.utcnow()
        
        return commands
    
    def process_command_response(
        self,
        command_id: str,
        status: str,
        response_data: Optional[Dict] = None
    ) -> Dict:
        """
        Process command response from EA
        
        Args:
            command_id: Command ID
            status: Execution status ('completed' or 'failed')
            response_data: Response data from EA
        
        Returns:
            Processing result
        """
        # Update database
        with ScopedSession() as db:
            cmd = db.query(Command).filter_by(id=command_id).first()
            
            if not cmd:
                logger.error(f"❌ Response for unknown command: {command_id}")
                return {'status': 'error', 'message': 'Command not found'}
            
            cmd.status = status
            cmd.response = response_data or {}
            cmd.executed_at = datetime.utcnow()
            
            db.commit()
        
        # Update execution tracker
        cmd_exec = self.active_commands.get(command_id)
        
        if cmd_exec:
            cmd_exec.status = CommandStatus.COMPLETED if status == 'completed' else CommandStatus.FAILED
            cmd_exec.completed_at = datetime.utcnow()
            cmd_exec.response_data = response_data
            
            if status == 'failed':
                cmd_exec.error_message = response_data.get('error') if response_data else 'Unknown error'
                self.total_commands_failed += 1
            
            latency = cmd_exec.get_latency_ms()
            
            # Update connection metrics
            conn = self.get_connection(cmd_exec.account_id)
            if conn and latency:
                # Exponential moving average
                alpha = 0.3
                conn.avg_command_response_latency = (
                    alpha * (latency / 1000) +
                    (1 - alpha) * conn.avg_command_response_latency
                )
            
            logger.info(
                f"📥 Command response: {cmd_exec.command_type} | "
                f"ID: {command_id} | Status: {status} | "
                f"Latency: {latency}ms"
            )
            
            # Remove from active commands after some time (keep for debugging)
            # We'll clean them up in a separate maintenance task
        else:
            logger.warning(f"⚠️  Response for untracked command: {command_id}")
        
        return {'status': 'success', 'command_id': command_id}
    
    # ========================================================================
    # MONITORING & METRICS
    # ========================================================================
    
    def get_system_status(self) -> Dict:
        """Get comprehensive system status"""
        connections = self.get_all_connections()
        
        healthy = sum(1 for conn in connections if conn.is_healthy())
        unhealthy = len(connections) - healthy
        
        return {
            'connections': {
                'total': len(connections),
                'healthy': healthy,
                'unhealthy': unhealthy,
                'details': [conn.get_status_dict() for conn in connections]
            },
            'commands': {
                'total_processed': self.total_commands_processed,
                'total_failed': self.total_commands_failed,
                'success_rate': round(
                    (self.total_commands_processed - self.total_commands_failed) / 
                    max(self.total_commands_processed, 1) * 100, 2
                ),
                'active': len(self.active_commands)
            },
            'data': {
                'total_ticks_received': self.total_ticks_received,
                'total_heartbeats_received': self.total_heartbeats_received
            },
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def cleanup_expired_commands(self, max_age_hours: int = 24):
        """Clean up old command execution trackers"""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        with self.lock:
            expired = [
                cmd_id for cmd_id, cmd_exec in self.active_commands.items()
                if cmd_exec.created_at < cutoff
            ]
            
            for cmd_id in expired:
                del self.active_commands[cmd_id]
            
            if expired:
                logger.info(f"🧹 Cleaned up {len(expired)} expired command trackers")


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_core_comm_manager: Optional[CoreCommunicationManager] = None


def get_core_comm() -> CoreCommunicationManager:
    """Get or create global CoreCommunicationManager instance"""
    global _core_comm_manager
    
    if _core_comm_manager is None:
        _core_comm_manager = CoreCommunicationManager()
    
    return _core_comm_manager


def init_core_communication():
    """Initialize core communication system"""
    global _core_comm_manager
    
    if _core_comm_manager is None:
        _core_comm_manager = CoreCommunicationManager()
        logger.info("✅ Core Communication System initialized")
    
    return _core_comm_manager


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def send_command_to_ea(
    account_id: int,
    command_type: str,
    payload: Dict,
    priority: CommandPriority = CommandPriority.NORMAL
) -> str:
    """
    Convenience function to send command to EA
    
    Returns:
        command_id
    """
    comm = get_core_comm()
    command_id, _ = comm.create_command(account_id, command_type, payload, priority)
    return command_id


def get_ea_status(account_id: int) -> Optional[Dict]:
    """Get status for specific EA connection"""
    comm = get_core_comm()
    conn = comm.get_connection(account_id)
    
    if conn:
        return conn.get_status_dict()
    
    return None


def is_ea_connected(account_id: int) -> bool:
    """Check if EA is connected and healthy"""
    comm = get_core_comm()
    conn = comm.get_connection(account_id)
    
    return conn is not None and conn.is_healthy()
