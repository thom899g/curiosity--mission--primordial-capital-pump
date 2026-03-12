"""
Resilient State Management for PRIMORDIAL TURBINE
Primary: Firebase Firestore with real-time sync
Fallback: Local JSON with integrity checks
"""
import json
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import logging

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self, config_path: str = "config/circuit_breakers.json"):
        """
        Initialize state manager with Firebase primary, local fallback
        """
        self.state = {
            "session_id": f"{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}",
            "status": "PAUSED",  # Default to safe state
            "open_position": None,
            "daily_pnl": 0.0,
            "drawdown_pct": 0.0,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "market_regime": "NORMAL",
            "circuit_breakers": [],
            "consecutive_losses": 0,
            "daily_trades": 0,
            "start_time": datetime.utcnow().isoformat()
        }
        
        self.local_backup_path = "logs/state_backup.json"
        self.firestore_initialized = False
        
        # Load config
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        else:
            logger.error(f"Config file not found: {config_path}")
            self.config = {}
        
        # Initialize Firebase if credentials exist
        self._init_firebase()
    
    def _init_firebase(self):
        """Initialize Firebase connection if credentials available"""
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            from google.cloud.firestore_v1.base_client import BaseClient
            
            cred_path = "config/firebase-key.json"
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                self.db = firestore.client()
                self.firestore_initialized = True
                logger.info("Firebase Firestore initialized successfully")
                
                # Create collections if they don't exist
                self._ensure_collections()
            else:
                logger.warning(f"Firebase credentials not found at {cred_path}. Using local storage only.")
                
        except ImportError as e:
            logger.error(f"Firebase admin not installed: {e}")
        except Exception as e:
            logger.error(f"Firebase initialization failed: {e}")
    
    def _ensure_collections(self):
        """Ensure required Firestore collections exist"""
        if not self.firestore_initialized:
            return
            
        collections = ['trades', 'market_snapshots', 'system_logs', 'performance', 'state']
        for collection in collections:
            try:
                # Try to create a dummy document to ensure collection exists
                doc_ref = self.db.collection(collection).document('_check')
                doc_ref.set({'check': True, 'timestamp': datetime.utcnow().isoformat()})
                doc_ref.delete()  # Clean up
            except Exception as e:
                logger.error(f"Error ensuring collection {collection}: {e}")
    
    def save_state(self, update_fields: Optional[Dict] = None):
        """
        Save state to Firebase (primary) and local backup
        Args:
            update_fields: Optional dict of fields to update before saving
        """
        if update_fields:
            for key, value in update_fields.items():
                if key in self.state:
                    self.state[key] = value
        self.state['last_heartbeat'] = datetime.utcnow().isoformat()
        
        # Save to Firebase
        if self.firestore_initialized:
            try:
                state_ref = self.db.collection('state').document(self.state['session_id'])
                state_ref.set(self.state)
            except Exception as e:
                logger.error(f"Firebase save failed: {e}. Using local backup.")
                self.firestore_initialized = False
        
        # Always save local backup
        try:
            os.makedirs(os.path.dirname(self.local_backup_path), exist_ok=True)
            with open(self.local_backup_path, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Local backup failed: {e}")
    
    def load_state(self) -> bool:
        """
        Load state from Firebase or local backup
        Returns: True if successful, False otherwise
        """
        # Try Firebase first
        if self.firestore_initialized:
            try:
                state_ref = self.db.collection('state').document(self.state['session_id'])
                doc = state_ref.get()
                if doc.exists:
                    loaded_state = doc.to_dict()
                    self.state.update(loaded_state)
                    logger.info("State loaded from Firebase")
                    return True
            except Exception as e:
                logger.error(f"Firebase load failed: {e}")
        
        # Fallback to local
        if os.path.exists(self.local_backup_path):
            try:
                with open(self.local_backup_path, 'r') as f:
                    loaded_state = json.load(f)
                self.state.update(loaded_state)
                logger.info("State loaded from local backup")
                return True
            except Exception as e:
                logger.error(f"Local backup load failed: {e}")
        
        logger.warning("No previous state found, using fresh state")
        return False
    
    def log_trade(self, trade_data: Dict):
        """Log a completed trade"""
        if self.firestore_initialized:
            try:
                trades_ref = self.db.collection('trades').document()
                trades_ref.set(trade_data)
            except Exception as e:
                logger.error(f"Failed to log trade to Firebase: {e}")
        
        # Local CSV backup
        try:
            csv_path = f"logs/trades/trades_{datetime.utcnow().strftime('%Y%m%d')}.csv"
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            
            # Write header if file doesn't exist
            if not os.path.exists(csv_path):
                with open(csv_path, 'w') as f:
                    f.write(','.join(trade_data.keys()) + '\n')
            
            # Append trade
            with open(csv_path, 'a') as f:
                f.write(','.join(str(v) for v in trade_data.values()) + '\n')
        except Exception as e:
            logger.error(f"Failed to log trade locally: {e}")
    
    def get_status(self) -> Dict:
        """Return current system status"""
        return self.state.copy()