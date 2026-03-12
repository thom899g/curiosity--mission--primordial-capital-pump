"""
Execution Engine for AERO/USD micro-trading
CCXT integration with graceful degradation
"""
import ccxt
import time
from datetime import datetime
from typing import Optional, Dict, Tuple
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self, exchange_id: str = "coinbase"):
        """
        Initialize CCXT exchange connection
        """
        load_dotenv()
        
        self.exchange_id = exchange_id
        self.exchange = None
        self.api_errors = 0
        self.last_order_time = None
        
        self._init_exchange()
    
    def _init_exchange(self):
        """Initialize CCXT exchange with API credentials"""
        try:
            # Get API credentials from environment
            api_key = os.getenv('CEX_API_KEY')
            api_secret = os.getenv('CEX_API_SECRET')
            
            if not api_key or not api_secret:
                logger.error("CEX API credentials not found in environment")
                return
            
            # Initialize exchange
            exchange_class = getattr(ccxt, self.exchange_id)
            self.exchange = exchange_class({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                    'adjustForTimeDifference': True
                }
            })
            
            # Test connection
            self.exchange.fetch_balance()
            logger.info(f"Connected to {self.exchange_id} successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize exchange {self.exchange_id}: {e}")
            self.exchange = None
    
    def fetch_order_book(self, symbol: str = "AERO/USD") -> Optional[Dict]:
        """
        Fetch order book with exponential backoff
        Returns: Order book dict or None on failure
        """
        if not self.exchange:
            logger.error("Exchange not initialized")
            return None
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                order_book = self.exchange.fetch_order_book(symbol)
                
                # Reset error counter on success
                self.api_errors = 0
                return order_book
                
            except ccxt.RateLimitExceeded as e:
                wait_time = 2 ** attempt
                logger.warning(f"Rate limit hit, waiting {wait_time}s: {e}")
                time.sleep(wait_time)
            except ccxt.NetworkError as e:
                self.api_errors += 1
                logger.error(f"Network error (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
            except Exception as e:
                self.api_errors += 1
                logger.error(f"Unexpected error fetching order book: {e}")
                return None
        
        logger.error(f