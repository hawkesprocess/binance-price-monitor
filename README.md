# Binance Futures Price Monitor

A real-time price monitoring system for Binance Futures trading pairs that sends alerts to Discord when significant price changes are detected.

## Features

- Real-time price monitoring using WebSocket connections
- Immediate alerts for price changes ≥ 1%
- Extended monitoring period (30 seconds) after initial alert
- Dynamic scaling of WebSocket connections based on number of pairs
- Automatic detection of new trading pairs
- Discord alerts with exact prices
- Automatic reconnection on WebSocket errors

## Requirements

- Python 3.7+
- Required packages:
  - `websocket-client`
  - `requests`
  - `urllib3`

## Installation

1. Clone the repository:
```bash
git clone https://github.com/hawkesprocess/binance-price-monitor.git
cd binance-price-monitor
```

2. Install the required packages:
```bash
pip install -r requirements.txt
```

3. Configure your Discord webhook URL:
   - Open `binance_monitor.py`
   - Replace `DISCORD_WEBHOOK_URL` with your Discord webhook URL

## Configuration

The following parameters can be adjusted in `binance_monitor.py`:

- `PRICE_CHANGE_THRESHOLD`: Minimum percentage change to trigger alerts (default: 1.0%)
- `CHECK_INTERVAL`: Interval to check for new trading pairs (default: 5 seconds)
- `MONITORING_PERIOD`: Duration to monitor after initial alert (default: 30 seconds)
- `API_TIMEOUT`: Timeout for API requests (default: 5 seconds)
- `CACHE_DURATION`: Duration to cache trading pairs list (default: 60 seconds)
- `MAX_RETRIES`: Maximum number of retries for failed requests (default: 3)
- `PRICE_HISTORY_SIZE`: Number of price points to keep in history for each pair 

## Usage

Run the monitor:
```bash
python binance_monitor.py
```

The script will:
1. Connect to Binance Futures WebSocket API
2. Start monitoring all USDT trading pairs
3. Send alerts to Discord when significant price changes are detected
4. Automatically detect and monitor new trading pairs
5. Maintain price history for each monitored pair (if enabled)
6. Scale WebSocket connections dynamically with the number of pairs (I think)

## Discord Alert Format

Alerts are sent in the following format:

```
Keefe's Binance Price Monitor
BTCUSDT (+1.50%) in the past 3 seconds
Price: $42123.45678901 → $42750.67890123
Today at 12:01:46 am
```


