#!/usr/bin/env python
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Set

# Add hummingbot to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hummingbot import data_path
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.clock import Clock
from hummingbot.core.event.event_forwarder import SourceInfoEventForwarder
from hummingbot.core.event.events import OrderBookEvent, OrderBookTradeEvent
from hummingbot.core.utils.async_utils import safe_ensure_future

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StandaloneOrderBookDownloader:
    def __init__(self, exchange_name: str, trading_pairs: list, depth: int = 50, dump_interval: int = 10):
        self.exchange_name = exchange_name
        self.trading_pairs = trading_pairs
        self.depth = depth
        self.dump_interval = dump_interval
        
        self.connector = None
        self.clock = None
        self.last_dump_timestamp = 0
        self.current_date = None
        
        self.ob_temp_storage = {trading_pair: [] for trading_pair in trading_pairs}
        self.trades_temp_storage = {trading_pair: [] for trading_pair in trading_pairs}
        self.ob_file_paths = {}
        self.trades_file_paths = {}
        
        self.subscribed_to_order_book_trade_event = False
        self.order_book_trade_event = SourceInfoEventForwarder(self._process_public_trade)
        
        self._main_task = None
        self._clock_task = None
        
    async def initialize_connector(self):
        """Initialize the exchange connector"""
        try:
            # Import the appropriate exchange module
            if self.exchange_name == "binance":
                from hummingbot.connector.exchange.binance.binance_exchange import BinanceExchange
                exchange_class = BinanceExchange
            elif self.exchange_name == "binance_paper_trade":
                from hummingbot.connector.exchange.paper_trade import create_paper_trade_market
            elif self.exchange_name == "backpack":
                from hummingbot.connector.exchange.backpack.backpack_exchange import BackpackExchange
                exchange_class = BackpackExchange
            else:
                raise ValueError(f"Unsupported exchange: {self.exchange_name}")
            
            # Create client config
            client_config = ClientConfigAdapter(ClientConfigMap())
            
            # Create connector
            if self.exchange_name == "binance_paper_trade":
                self.connector = create_paper_trade_market(
                    exchange_name="binance",
                    client_config_map=client_config,
                    trading_pairs=self.trading_pairs
                )
            else:
                # Map generic parameters to exchange-specific ones
                if self.exchange_name == "binance":
                    self.connector = exchange_class(
                        client_config_map=client_config,
                        binance_api_key=os.getenv("BINANCE_API_KEY", ""),
                        binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
                        trading_pairs=self.trading_pairs,
                        trading_required=False
                    )
                elif self.exchange_name == "backpack":
                    self.connector = exchange_class(
                        client_config_map=client_config,
                        api_key=os.getenv("BACKPACK_API_KEY", ""),
                        api_secret=os.getenv("BACKPACK_API_SECRET", ""),
                        trading_pairs=self.trading_pairs,
                        trading_required=False
                    )
                else:
                    raise ValueError(f"Exchange {self.exchange_name} parameter mapping not implemented")
            
            # Initialize the connector
            logger.info(f"Initializing {self.exchange_name} connector...")
            
            # Update trading rules only for real exchanges
            if hasattr(self.connector, '_update_trading_rules'):
                await self.connector._update_trading_rules()
            
            # Start network
            await self.connector.start_network()
            
            # Initialize clock
            from hummingbot.core.clock import Clock, ClockMode
            self.clock = Clock(ClockMode.REALTIME, tick_size=1.0)
            self.clock.add_iterator(self.connector)
            
            logger.info(f"Successfully initialized {self.exchange_name} connector")
            
        except Exception as e:
            logger.error(f"Failed to initialize connector: {e}")
            raise
            
    def create_order_book_and_trade_files(self):
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
        
    def get_order_book_dict(self, trading_pair: str):
        """Get orderbook snapshot as dictionary"""
        try:
            order_book = self.connector.get_order_book(trading_pair)
            snapshot = order_book.snapshot
            return {
                "ts": self.clock.current_timestamp,
                "bids": snapshot[0].loc[:(self.depth - 1), ["price", "amount"]].values.tolist() if not snapshot[0].empty else [],
                "asks": snapshot[1].loc[:(self.depth - 1), ["price", "amount"]].values.tolist() if not snapshot[1].empty else [],
            }
        except Exception:
            # Return empty order book if not ready yet
            return {
                "ts": self.clock.current_timestamp,
                "bids": [],
                "asks": [],
            }
        
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
                json_strings = [json.dumps(obj) for obj in trades_info]
                json_data = '\n'.join(json_strings)
                file.write(json_data + "\n")
                file.flush()
                self.trades_temp_storage[trading_pair] = []
                
        if self.clock:
            self.last_dump_timestamp = self.clock.current_timestamp + self.dump_interval
        logger.info("Dumped data to files")
        
    def check_and_replace_files(self):
        """Check if date has changed and create new files if needed"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        if current_date != self.current_date:
            self.create_order_book_and_trade_files()
            
    def _process_public_trade(self, event_tag: int, market: ConnectorBase, event: OrderBookTradeEvent):
        """Process incoming trade events"""
        self.trades_temp_storage[event.trading_pair].append({
            "ts": event.timestamp,
            "price": float(event.price),
            "q_base": float(event.amount),
            "side": event.type.name.lower(),
        })
        
    def subscribe_to_order_book_trade_event(self):
        """Subscribe to orderbook trade events"""
        if not self.subscribed_to_order_book_trade_event:
            for order_book in self.connector.order_books.values():
                order_book.add_listener(OrderBookEvent.TradeEvent, self.order_book_trade_event)
            self.subscribed_to_order_book_trade_event = True
            logger.info("Subscribed to order book trade events")
            
    async def on_tick(self):
        """Main tick function called periodically"""
        # Subscribe to trade events
        if not self.subscribed_to_order_book_trade_event:
            self.subscribe_to_order_book_trade_event()
            
        # Check if files need to be replaced
        self.check_and_replace_files()
        
        # Collect orderbook snapshots
        for trading_pair in self.trading_pairs:
            try:
                order_book_data = self.get_order_book_dict(trading_pair)
                self.ob_temp_storage[trading_pair].append(order_book_data)
            except Exception as e:
                logger.error(f"Error getting orderbook for {trading_pair}: {e}")
                
        # Dump data if interval has passed
        if self.last_dump_timestamp < self.clock.current_timestamp:
            self.dump_and_clean_temp_storage()
            
    async def _clock_loop(self):
        """Clock loop to drive periodic updates"""
        while True:
            await asyncio.sleep(1.0)
            # Use backtest tick for manual clock advancement
            self.clock.backtest_til(self.clock.current_timestamp + 1)
            
    async def _main_loop(self):
        """Main loop for data collection"""
        while True:
            await self.on_tick()
            await asyncio.sleep(1.0)
            
    async def start(self):
        """Start the data collection"""
        try:
            # Initialize connector
            await self.initialize_connector()
            
            # Create initial files
            self.create_order_book_and_trade_files()
            
            # Wait for order books to initialize
            logger.info("Waiting for order books to initialize...")
            await asyncio.sleep(5.0)
            
            # Start clock and main loops
            self._clock_task = safe_ensure_future(self._clock_loop())
            self._main_task = safe_ensure_future(self._main_loop())
            
            logger.info(f"Started collecting data for {self.exchange_name} - {self.trading_pairs}")
            logger.info(f"Data will be saved to: {data_path()}")
            logger.info("Press Ctrl+C to stop...")
            
            # Wait for tasks
            await asyncio.gather(self._clock_task, self._main_task)
            
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
        
        # Cancel tasks
        if self._main_task:
            self._main_task.cancel()
        if self._clock_task:
            self._clock_task.cancel()
            
        # Final data dump
        if self.ob_temp_storage or self.trades_temp_storage:
            self.dump_and_clean_temp_storage()
            
        # Close files
        for file in self.ob_file_paths.values():
            file.close()
        for file in self.trades_file_paths.values():
            file.close()
            
        # Stop connector
        if self.connector:
            await self.connector.stop_network()
            
        logger.info("Data collection stopped")


async def main():
    # Get configuration from environment variables or use defaults
    exchange = os.getenv("EXCHANGE", "backpack")
    trading_pairs = os.getenv("TRADING_PAIRS", "ETH-USDC,BTC-USDC, SOL-USDC")
    depth = int(os.getenv("DEPTH", "50"))
    dump_interval = int(os.getenv("DUMP_INTERVAL", "10"))
    
    # Parse trading pairs
    trading_pairs = [pair.strip() for pair in trading_pairs.split(",")]
    
    logger.info(f"Starting orderbook and trades downloader")
    logger.info(f"Exchange: {exchange}")
    logger.info(f"Trading pairs: {trading_pairs}")
    logger.info(f"Depth: {depth}")
    logger.info(f"Dump interval: {dump_interval}s")
    
    # Create and start downloader
    downloader = StandaloneOrderBookDownloader(
        exchange_name=exchange,
        trading_pairs=trading_pairs,
        depth=depth,
        dump_interval=dump_interval
    )
    
    await downloader.start()


if __name__ == "__main__":
    asyncio.run(main())