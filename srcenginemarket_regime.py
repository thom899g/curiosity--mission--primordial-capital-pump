"""
Market Regime Detection for AERO/USD
Volatility filters, news monitoring, liquidity checks
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging
import requests
from typing import Tuple, Dict, List

logger = logging.getLogger(__name__)

class MarketRegimeDetector:
    def __init__(self, config_path: str = "config/circuit_breakers.json"):
        self.volatility_history = []
        self.spread_history = []
        self.news_alerts = []
        self.regime = "NORMAL"
        
        # Load config
        import json
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        # Initialize news monitoring (if configured)
        self.cryptopanic_api_key = None
        self._init_news_monitor()
    
    def _init_news_monitor(self):
        """Initialize news monitoring from environment"""
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        self.cryptopanic_api_key = os.getenv('CRYPTOPANIC_API_KEY')
        if self.cryptopanic_api_key:
            logger.info("CryptoPanic news monitoring initialized")
    
    def calculate_atr(self, prices: List[float], period: int = 5) -> float:
        """
        Calculate Average True Range for volatility
        Simplified version using high-low ranges
        """
        if len(prices) < period + 1:
            return 0.0
        
        # Using simple price changes as proxy for true range
        changes = np.abs(np.diff(prices[-period:]))
        return np.mean(changes) if len(changes) > 0 else 0.0
    
    def check_volatility(self, current_price: float, recent_prices: List[float]) -> Tuple[bool, float]:
        """
        Check if volatility exceeds threshold
        Returns: (is_volatile, atr_pct)
        """
        atr = self.calculate_atr(recent_prices, self.config['market']['atr_period_minutes'])
        atr_pct = (atr / current_price * 100) if current_price > 0 else 0
        
        threshold = self.config['market']['volatility_threshold_pct']
        is_volatile = atr_pct > threshold
        
        if is_volatile:
            logger.warning(f"High volatility detected: {atr_pct:.2f}% > {threshold}%")
        
        return is_volatile, atr_pct
    
    def check_spread(self, bid: float, ask: float, mid_price: float) -> Tuple[bool, float]:
        """
        Check if bid-ask spread is abnormally wide
        Returns: (is_wide, spread_pct)
        """
        if bid <= 0 or ask <= 0:
            return False, 0.0
        
        spread_pct = ((ask - bid) / mid_price * 100) if mid_price > 0 else 0
        baseline = self._get_baseline_spread()
        
        is_wide = spread_pct > (baseline * self.config['market']['max_spread_multiplier'])
        
        if is_wide:
            logger.warning(f"Wide spread detected: {spread_pct:.4f}%")
        
        return is_wide, spread_pct
    
    def _get_baseline_spread(self) -> float:
        """Calculate baseline spread from history"""
        if len(self.spread_history) < 10:
            return 0.1  # Default 0.1% baseline
        
        return np.percentile(self.spread_history, 50)  # Median spread
    
    def check_news(self, asset: str = "AERO") -> List[str]:
        """
        Check for recent news about asset
        Returns: List of alert headlines
        """
        alerts = []
        
        if not self.cryptopanic_api_key:
            return alerts
        
        try:
            url = f"https://cryptopanic.com/api/v1/posts/?auth_token={self.cryptopanic_api_key}&currencies={asset}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                for post in data.get('results', [])[:5]:  # Last 5 posts
                    if post.get('votes', {}).get('negative', 0) > 5:
                        alerts.append(post.get('title', ''))
                        logger.warning(f"Negative news detected: {post.get('title')}")
        except Exception as e:
            logger.error(f"News check failed: {e}")
        
        return alerts
    
    def determine_regime(self, market_data: Dict) -> str:
        """
        Determine overall market regime
        Returns: "NORMAL", "VOLATILE", or "HALTED"
        """
        current_price = market_data.get('price', 0)
        recent_prices = market_data.get('recent_prices', [])
        bid = market_data.get('bid', 0)
        ask = market_data.get('ask', 0)
        
        # Check volatility
        is_volatile, vol_pct = self.check_volatility(current_price, recent_prices)
        
        # Check spread
        mid_price = (bid + ask) / 2
        is_wide, spread_pct = self.check_spread(bid, ask, mid_price)
        
        # Check news
        news_alerts = self.check_news("AERO")
        
        # Update history
        self.spread_history.append(spread_pct)
        if len(self.spread_history) > 100:
            self.spread_history = self.spread_history[-100:]
        
        # Determine regime
        if is_volatile or is_wide or len(news_alerts) > 0:
            self.regime = "VOLATILE"
            logger.info(f"Market regime changed to VOLATILE. Vol: {vol_pct:.2f}%, Spread: {spread_pct:.4f}%, News: {len(news_alerts)} alerts")
        else:
            self.regime = "NORMAL"
        
        return self.regime