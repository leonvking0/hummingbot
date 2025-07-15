#!/usr/bin/env python
"""
Simplified version that uses REST API polling only - suitable for exchanges 
with incomplete WebSocket implementation like Backpack.
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict

# Add hummingbot to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hummingbot import data_path
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.backpack import backpack_web_utils as web_utils
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.connections.data_types import RESTMethod

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RestOnlyOrderBookDownloader:
    def __init__(self, exchange_name: str, trading_pairs: list, depth: int = 50, 
                 poll_interval: float = 1.0, dump_interval: int = 10):
        self.exchange_name = exchange_name
        self.trading_pairs = trading_pairs
        self.depth = depth
        self.poll_interval = poll_interval
        self.dump_interval = dump_interval
        
        self.api_factory = None
        self.last_dump_timestamp = 0
        self.current_date = None
        
        self.ob_temp_storage = {trading_pair: [] for trading_pair in trading_pairs}
        self.trades_temp_storage = {trading_pair: [] for trading_pair in trading_pairs}
        self.ob_file_paths = {}
        self.trades_file_paths = {}
        
        self._main_task = None
        
    async def initialize(self):
        """Initialize the API factory"""
        try:
            # Create API factory for REST requests
            self.api_factory = web_utils.build_api_factory()
            logger.info(f"Initialized {self.exchange_name} REST API client")
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise
            
    def create_files(self):
        """Create files for storing orderbook and trade data"""
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Close existing files if any
        for file in self.ob_file_paths.values():
            file.close()
        for file in self.trades_file_paths.values():
            file.close()
            
        # Create new files
        self.ob_file_paths = {
            trading_pair: self.get_file(self.exchange_name, trading_pair, "order_book_snapshots", self.current_date) 
            for trading_pair in self.trading_pairs
        }
        self.trades_file_paths = {
            trading_pair: self.get_file(self.exchange_name, trading_pair, "trades", self.current_date) 
            for trading_pair in self.trading_pairs
        }
        
        logger.info(f"Created data files for date: {self.current_date}")
        
    @staticmethod
    def get_file(exchange: str, trading_pair: str, source_type: str, current_date: str):
        """Get file handle for data storage"""
        file_path = os.path.join(data_path(), f"{exchange}_{trading_pair}_{source_type}_{current_date}.txt")
        logger.info(f"Opening file: {file_path}")
        return open(file_path, "a")
        
    async def fetch_order_book(self, trading_pair: str) -> Dict:
        """Fetch order book data via REST API"""
        try:
            rest_assistant = await self.api_factory.get_rest_assistant()
            # Convert trading pair format
            symbol = trading_pair.replace("-", "_")
            url = web_utils.get_order_book_url(symbol)
            
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id="/api/v1/depth",
                method=RESTMethod.GET
            )
            
            timestamp = datetime.now().timestamp()
            
            # Format the response
            return {
                "ts": timestamp,
                "bids": [[float(price), float(amount)] for price, amount in response.get("bids", [])[:self.depth]],
                "asks": [[float(price), float(amount)] for price, amount in response.get("asks", [])[:self.depth]],
            }
        except Exception as e:
            logger.error(f"Error fetching orderbook for {trading_pair}: {e}")
            return {
                "ts": datetime.now().timestamp(),
                "bids": [],
                "asks": [],
            }
            
    async def fetch_recent_trades(self, trading_pair: str) -> list:
        """Fetch recent trades via REST API"""
        try:
            rest_assistant = await self.api_factory.get_rest_assistant()
            # Convert trading pair format
            symbol = trading_pair.replace("-", "_")
            url = web_utils.get_trades_url(symbol)
            
            response = await rest_assistant.execute_request(
                url=url,
                throttler_limit_id="/api/v1/trades",
                method=RESTMethod.GET
            )
            
            trades = []
            for trade in response:
                trades.append({
                    "ts": float(trade.get("timestamp", 0)) / 1000,  # Convert from ms to seconds
                    "price": float(trade.get("price", 0)),
                    "q_base": float(trade.get("quantity", 0)),
                    "side": "buy" if trade.get("isBuyerMaker", False) else "sell"
                })
            
            return trades
        except Exception as e:
            logger.error(f"Error fetching trades for {trading_pair}: {e}")
            return []
            
    def dump_and_clean_temp_storage(self):
        """Dump temporary storage to files"""
        # Dump orderbook data
        for trading_pair, order_book_info in self.ob_temp_storage.items():
            if order_book_info:
                file = self.ob_file_paths[trading_pair]
                json_strings = [json.dumps(obj) for obj in order_book_info]
                json_data = '\n'.join(json_strings)
                file.write(json_data + "\n")
                file.flush()
                self.ob_temp_storage[trading_pair] = []
                
        # Dump trade data
        for trading_pair, trades_info in self.trades_temp_storage.items():
            if trades_info:
                file = self.trades_file_paths[trading_pair]
                # Deduplicate trades by timestamp
                seen = set()
                unique_trades = []
                for trade in trades_info:
                    trade_id = (trade['ts'], trade['price'], trade['q_base'])
                    if trade_id not in seen:
                        seen.add(trade_id)
                        unique_trades.append(trade)
                
                json_strings = [json.dumps(obj) for obj in unique_trades]
                json_data = '\n'.join(json_strings)
                file.write(json_data + "\n")
                file.flush()
                self.trades_temp_storage[trading_pair] = []
                
        logger.info("Dumped data to files")
        
    def check_and_replace_files(self):
        """Check if date has changed and create new files if needed"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        if current_date != self.current_date:
            self.create_files()
            
    async def collect_data(self):
        """Main data collection loop"""
        while True:
            try:
                # Check if files need to be replaced
                self.check_and_replace_files()
                
                # Collect data for all trading pairs
                for trading_pair in self.trading_pairs:
                    # Fetch orderbook
                    order_book_data = await self.fetch_order_book(trading_pair)
                    self.ob_temp_storage[trading_pair].append(order_book_data)
                    
                    # Fetch recent trades
                    trades = await self.fetch_recent_trades(trading_pair)
                    self.trades_temp_storage[trading_pair].extend(trades)
                
                # Dump data if interval has passed
                current_time = datetime.now().timestamp()
                if self.last_dump_timestamp + self.dump_interval < current_time:
                    self.dump_and_clean_temp_storage()
                    self.last_dump_timestamp = current_time
                    
                # Wait before next poll
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Error in data collection loop: {e}")
                await asyncio.sleep(self.poll_interval)
                
    async def start(self):
        """Start the data collection"""
        try:
            # Initialize
            await self.initialize()
            
            # Create initial files
            self.create_files()
            
            logger.info(f"Started collecting data for {self.exchange_name} - {self.trading_pairs}")
            logger.info(f"Data will be saved to: {data_path()}")
            logger.info(f"Polling interval: {self.poll_interval}s, Dump interval: {self.dump_interval}s")
            logger.info("Press Ctrl+C to stop...")
            
            # Start collection
            await self.collect_data()
            
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            raise
        finally:
            await self.stop()
            
    async def stop(self):
        """Stop the data collection"""
        logger.info("Stopping data collection...")
        
        # Final data dump
        if self.ob_temp_storage or self.trades_temp_storage:
            self.dump_and_clean_temp_storage()
            
        # Close files
        for file in self.ob_file_paths.values():
            file.close()
        for file in self.trades_file_paths.values():
            file.close()
            
        logger.info("Data collection stopped")


async def main():
    # Get configuration from environment variables or use defaults
    exchange = os.getenv("EXCHANGE", "backpack")
    trading_pairs = os.getenv("TRADING_PAIRS", "SOL-USDC,BTC-USDC")
    depth = int(os.getenv("DEPTH", "50"))
    poll_interval = float(os.getenv("POLL_INTERVAL", "1.0"))
    dump_interval = int(os.getenv("DUMP_INTERVAL", "10"))
    
    # Parse trading pairs
    trading_pairs = [pair.strip() for pair in trading_pairs.split(",")]
    
    logger.info(f"Starting REST-only orderbook and trades downloader")
    logger.info(f"Exchange: {exchange}")
    logger.info(f"Trading pairs: {trading_pairs}")
    logger.info(f"Depth: {depth}")
    logger.info(f"Poll interval: {poll_interval}s")
    logger.info(f"Dump interval: {dump_interval}s")
    
    # Create and start downloader
    downloader = RestOnlyOrderBookDownloader(
        exchange_name=exchange,
        trading_pairs=trading_pairs,
        depth=depth,
        poll_interval=poll_interval,
        dump_interval=dump_interval
    )
    
    await downloader.start()


if __name__ == "__main__":
    asyncio.run(main())