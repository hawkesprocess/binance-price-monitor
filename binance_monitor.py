import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Thread, Lock, Event
from typing import Dict, Set, Optional, Any, Deque
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from requests import Session

import requests
import websocket
from websocket import WebSocketApp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"
PRICE_CHANGE_THRESHOLD = 1.0  # 1% threshold
CHECK_INTERVAL = 5  # seconds
MONITORING_PERIOD = 30  # seconds to monitor after initial change
API_TIMEOUT = 5  # seconds
CACHE_DURATION = 60  # seconds
MAX_RETRIES = 3
PRICE_HISTORY_SIZE = 100

@dataclass
class MonitoringData:
    """Data class to store monitoring information for a trading pair."""
    initial_price: float
    current_price: float
    start_time: float
    last_update: float
    price_history: Deque[float]

class PriceMonitor:
    """Monitors Binance Futures pairs for significant price changes."""
    
    def __init__(self) -> None:
        """Initialize the PriceMonitor with default values."""
        self.last_prices: Dict[str, float] = {}
        self.webhook_url = DISCORD_WEBHOOK_URL
        self.monitored_pairs: Set[str] = set()
        self.pairs_lock = Lock()
        self.threads: Dict[str, Thread] = {}
        self.monitoring_periods: Dict[str, MonitoringData] = {}
        self._cached_pairs: Optional[Set[str]] = None
        self._last_pair_check = 0.0
        self.executor: Optional[ThreadPoolExecutor] = None
        self.current_workers = 0
        self.stop_event = Event()
        
        self.session = Session()
        retries = Retry(
            total=MAX_RETRIES,
            status_forcelist=[500, 502, 503, 504]
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.mount('http://', HTTPAdapter(max_retries=retries))

    def get_trading_pairs(self) -> Set[str]:
        """
        Fetch and cache the list of available trading pairs.
        
        Returns:
            Set[str]: Set of available trading pair symbols.
        """
        current_time = time.time()
        if self._cached_pairs is None or current_time - self._last_pair_check > CACHE_DURATION:
            try:
                response = self.session.get(
                    'https://fapi.binance.com/fapi/v1/exchangeInfo',
                    timeout=API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                self._cached_pairs = {
                    symbol['symbol'] for symbol in data['symbols']
                    if symbol['status'] == 'TRADING' and symbol['symbol'].endswith('USDT')
                }
                self._last_pair_check = current_time
                logger.info(f"Cached {len(self._cached_pairs)} trading pairs")
            except requests.RequestException as e:
                logger.error(f"Error fetching trading pairs: {e}")
                return self._cached_pairs or set()
        return self._cached_pairs   

    def update_executor(self, new_worker_count: int) -> None:
        """
        Update the ThreadPoolExecutor with a new worker count.
        
        Args:
            new_worker_count: The new number of workers to use.
        """
        if self.executor:
            self.executor.shutdown(wait=False)
        self.executor = ThreadPoolExecutor(max_workers=new_worker_count)
        self.current_workers = new_worker_count
        logger.info(f"Updated executor with {new_worker_count} workers")

    def send_discord_alert(
        self,
        symbol: str,
        initial_price: float,
        current_price: float,
        price_change: float,
        is_final: bool = False,
        monitoring_time: float = 0
    ) -> None:
        """
        Send a price alert to Discord.
        
        Args:
            symbol: The trading pair symbol.
            initial_price: The initial price when the change was detected.
            current_price: The current price.
            price_change: The percentage price change.
            is_final: Whether this is the final alert after monitoring period.
            monitoring_time: The duration of the monitoring period.
        """
        color = 0x00ff00 if price_change > 0 else 0xff0000
        sign = "+" if price_change > 0 else ""
        
        title = "Keefe's Binance Price Monitor"
        time_period = f"{monitoring_time:.1f} seconds" if is_final else "3 seconds"
        
        # Format prices to show exact values
        initial_price_str = f"${initial_price:.8f}"
        current_price_str = f"${current_price:.8f}"
        
        description = (
            f"{symbol} ({sign}{price_change:.2f}%) in the past {time_period}\n"
            f"Price: {initial_price_str} → {current_price_str}"
        )
        
        # Get current time in SGT (UTC+8) and format it
        sgt_time = datetime.utcnow().replace(tzinfo=None) + timedelta(hours=8)
        time_str = sgt_time.strftime('%I:%M:%S %p').lower()
        
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "footer": {
                "text": f"Today at {time_str}"
            }
        }

        payload = {"embeds": [embed]}

        try:
            response = self.session.post(
                self.webhook_url,
                json=payload,
                timeout=API_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending Discord alert: {e}")

    def on_message(self, ws: WebSocketApp, message: str) -> None:
        """
        Handle incoming WebSocket messages.
        
        Args:
            ws: The WebSocket connection.
            message: The received message.
        """
        try:
            data = json.loads(message)
            symbol = data['s']
            current_price = float(data['c'])
            current_time = time.time()
            
            if symbol in self.monitoring_periods:
                monitoring_data = self.monitoring_periods[symbol]
                monitoring_data.current_price = current_price
                monitoring_data.last_update = current_time
                monitoring_data.price_history.append(current_price)
                
                if current_time - monitoring_data.start_time >= MONITORING_PERIOD:
                    initial_price = monitoring_data.initial_price
                    price_change = ((current_price - initial_price) / initial_price) * 100
                    monitoring_time = current_time - monitoring_data.start_time
                    
                    self.send_discord_alert(
                        symbol,
                        initial_price,
                        current_price,
                        price_change,
                        is_final=True,
                        monitoring_time=monitoring_time
                    )
                    del self.monitoring_periods[symbol]
            
            elif symbol in self.last_prices:
                last_price = self.last_prices[symbol]
                price_change = ((current_price - last_price) / last_price) * 100
                
                if abs(price_change) >= PRICE_CHANGE_THRESHOLD:
                    self.send_discord_alert(symbol, last_price, current_price, price_change)
                    
                    self.monitoring_periods[symbol] = MonitoringData(
                        initial_price=last_price,
                        current_price=current_price,
                        start_time=current_time,
                        last_update=current_time,
                        price_history=deque(maxlen=PRICE_HISTORY_SIZE)
                    )
                    self.monitoring_periods[symbol].price_history.append(current_price)
                    logger.info(f"Started monitoring period for {symbol} after {price_change:+.2f}% change")
            
            self.last_prices[symbol] = current_price
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Error processing message: {e}")

    def on_error(self, ws: WebSocketApp, error: Exception) -> None:
        """
        Handle WebSocket errors.
        
        Args:
            ws: The WebSocket connection.
            error: The error that occurred.
        """
        logger.error(f"WebSocket error: {error}")

    def on_close(self, ws: WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """
        Handle WebSocket connection closure.
        
        Args:
            ws: The WebSocket connection.
            close_status_code: The status code of the closure.
            close_msg: The closure message.
        """
        logger.info(f"WebSocket connection closed with code {close_status_code}: {close_msg}")

    def on_open(self, ws: WebSocketApp) -> None:
        """
        Handle WebSocket connection opening.
        
        Args:
            ws: The WebSocket connection.
        """
        logger.info("WebSocket connection opened")

    def start_monitoring_pair(self, symbol: str) -> None:
        """
        Start monitoring a specific trading pair.
        
        Args:
            symbol: The trading pair symbol to monitor.
        """
        def run_websocket() -> None:
            while not self.stop_event.is_set():
                try:
                    ws = WebSocketApp(
                        f"wss://fstream.binance.com/ws/{symbol.lower()}@ticker",
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                        on_open=self.on_open
                    )
                    ws.run_forever()
                except Exception as e:
                    logger.error(f"WebSocket error for {symbol}: {e}")
                    time.sleep(1)

        thread = Thread(target=run_websocket)
        thread.daemon = True
        thread.start()
        self.threads[symbol] = thread

    def check_new_pairs(self) -> None:
        """Continuously check for new trading pairs."""
        while not self.stop_event.is_set():
            try:
                current_pairs = self.get_trading_pairs()
                with self.pairs_lock:
                    new_pairs = current_pairs - self.monitored_pairs
                    if new_pairs:
                        logger.info(f"Found {len(new_pairs)} new pairs: {', '.join(new_pairs)}")
                        
                        total_pairs = len(current_pairs)
                        if total_pairs > self.current_workers:
                            self.update_executor(total_pairs)
                        
                        for pair in new_pairs:
                            self.start_monitoring_pair(pair)
                            self.monitored_pairs.add(pair)
            except Exception as e:
                logger.error(f"Error checking for new pairs: {e}")
            time.sleep(CHECK_INTERVAL)

    def start_monitoring(self) -> None:
        """Start the price monitoring system."""
        initial_pairs = self.get_trading_pairs()
        num_pairs = len(initial_pairs)
        
        self.update_executor(num_pairs)
        
        with self.pairs_lock:
            self.monitored_pairs = set(initial_pairs)
            logger.info(f"Starting to monitor {num_pairs} futures pairs...")
            
            for symbol in initial_pairs:
                self.start_monitoring_pair(symbol)

        checker_thread = Thread(target=self.check_new_pairs)
        checker_thread.daemon = True
        checker_thread.start()

        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping monitor...")
            self.stop_event.set()
            if self.executor:
                self.executor.shutdown(wait=False)

def main() -> None:
    """Main entry point for the script."""
    monitor = PriceMonitor()
    monitor.start_monitoring()

if __name__ == "__main__":
    main() 