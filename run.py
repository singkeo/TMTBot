#!/usr/bin/env python3
import asyncio
import logging
import math
import os
import time
from typing import Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from metaapi_cloud_sdk import MetaApi
from prettytable import PrettyTable
from telegram import ParseMode, Update
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater, ConversationHandler, CallbackContext

# MetaAPI Credentials
API_KEY = os.environ.get("API_KEY")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID")

# Telegram Credentials
TOKEN = os.environ.get("TOKEN")
TELEGRAM_USER = os.environ.get("TELEGRAM_USER")

# Heroku Credentials
APP_URL = os.environ.get("APP_URL")

# Port number for Telegram bot web hook
PORT = int(os.environ.get('PORT', '8443'))

# ENV Variables
LOT_SIZE = float(os.environ.get('LOT_SIZE', '6.0'))
STOP_LOSS = float(os.environ.get('STOP_LOSS', '20.0'))
TAKE_PROFIT = float(os.environ.get('TAKE_PROFIT', '200.0'))
INDEX = os.environ.get('INDEX', 'AUS200.cash')

# Connection timeouts
CONNECTION_TIMEOUT = 30  # seconds
SYNC_TIMEOUT = 20  # seconds

# Enables logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# possibles states for conversation handler
CALCULATE, TRADE, DECISION = range(3)

# allowed FX symbols
SYMBOLS = ['AUDCAD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

# RISK FACTOR
RISK_FACTOR = float(os.environ.get("RISK_FACTOR"))

class MetaApiConnection:
    _instance = None
    _connection = None
    _last_health_check = 0
    _health_check_interval = 60  # seconds
    
    @classmethod
    async def get_connection(cls):
        current_time = time.time()
        
        # Check if we need to verify connection health
        if cls._connection is not None and (current_time - cls._last_health_check) > cls._health_check_interval:
            if not await cls.is_connection_healthy():
                cls._connection = None
                logger.info("Connection health check failed, creating new connection")
        
        if cls._connection is None:
            try:
                async with asyncio.timeout(CONNECTION_TIMEOUT):
                    api = MetaApi(API_KEY)
                    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
                    
                    if account.state not in ['DEPLOYING', 'DEPLOYED']:
                        await account.deploy()
                    
                    await account.wait_connected()
                    cls._connection = account.get_rpc_connection()
                    await cls._connection.connect()
                    await cls._connection.wait_synchronized()
                    cls._last_health_check = current_time
                    logger.info("Created new MetaAPI connection")
            except asyncio.TimeoutError:
                logger.error("Connection timeout exceeded")
                raise
            except Exception as error:
                logger.error(f"Error establishing connection: {error}")
                raise
        
        return cls._connection

    @classmethod
    async def is_connection_healthy(cls):
        try:
            if cls._connection is None:
                return False
            await cls._connection.get_account_information()
            cls._last_health_check = time.time()
            return True
        except Exception as error:
            logger.error(f"Health check failed: {error}")
            return False

async def execute_trades(connection, trade: dict):
    """Execute multiple trades in parallel for different take profits"""
    tasks = []
    for tp in trade['TP']:
        if trade['OrderType'] == 'Buy':
            task = connection.create_market_buy_order(
                trade['Symbol'],
                trade['PositionSize'] / len(trade['TP']),
                trade['StopLoss'],
                tp
            )
        elif trade['OrderType'] == 'Sell':
            task = connection.create_market_sell_order(
                trade['Symbol'],
                trade['PositionSize'] / len(trade['TP']),
                trade['StopLoss'],
                tp
            )
        tasks.append(task)
    return await asyncio.gather(*tasks)

def validate_trade_parameters(trade: dict) -> bool:
    """Validate trade parameters before execution"""
    try:
        validations = [
            ('Symbol', lambda x: x in SYMBOLS or x == INDEX),
            ('OrderType', lambda x: x in ['Buy', 'Sell', 'Buy Limit', 'Sell Limit', 'Buy Stop', 'Sell Stop']),
            ('PositionSize', lambda x: 0.01 <= x <= 50.0),
            ('StopLoss', lambda x: x > 0),
            ('TP', lambda x: all(tp > 0 for tp in x))
        ]
        return all(validator(trade[param]) for param, validator in validations)
    except Exception as error:
        logger.error(f"Trade validation error: {error}")
        return False

def ParseSignal(signal: str) -> dict:
    """Starts process of parsing signal and entering trade on MetaTrader account."""
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]

    trade = {}
    
    if('Buy Limit'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Buy Limit'
    elif('Sell Limit'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Sell Limit'
    elif('Buy Stop'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Buy Stop'
    elif('Sell Stop'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Sell Stop'
    elif('Buy'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Buy'
    elif('Sell'.lower() in signal[0].lower()):
        trade['OrderType'] = 'Sell'
    else:
        return {}

    trade['Symbol'] = (signal[0].split())[-1].upper()
    
    if(trade['Symbol'] not in SYMBOLS):
        trade['Symbol'] = INDEX
        logger.info(f"Symbol received: {trade['Symbol']}")
    
    if(trade['OrderType'] == 'Buy' or trade['OrderType'] == 'Sell'):
        trade['Entry'] = 'NOW'
    else:
        trade['Entry'] = float((signal[1].split())[-1])
        trade['StopLoss'] = float((signal[2].split())[-1])
        trade['TP'] = [float((signal[3].split())[-1])]

    if(len(signal) > 4):
        trade['TP'].append(float(signal[4].split()[-1]))
    
    trade['RiskFactor'] = RISK_FACTOR
    
    return trade

async def ConnectMetaTrader(update: Update, trade: dict, enterTrade: bool):
    """Attempts connection to MetaAPI and MetaTrader to place trade."""
    start_time = time.time()
    
    try:
        # Get connection from pool
        connection = await MetaApiConnection.get_connection()
        
        # Validate trade parameters
        if not validate_trade_parameters(trade):
            raise ValueError("Invalid trade parameters")
        
        account_information = await connection.get_account_information()
        update.effective_message.reply_text("Successfully connected to MetaTrader! 👌🏼")
        
        if(trade['Entry'] == 'NOW'):
            price = await connection.get_symbol_price(symbol=trade['Symbol'])
            
            if(trade['OrderType'] == 'Buy'):
                trade['Entry'] = float(price['bid'])
                trade['StopLoss'] = float(price['bid']) - STOP_LOSS
                trade['TP'] = [float(price['bid']) + TAKE_PROFIT]
            
            if(trade['OrderType'] == 'Sell'):
                trade['Entry'] = float(price['ask'])
                trade['StopLoss'] = float(price['ask']) + STOP_LOSS
                trade['TP'] = [float(price['bid']) - TAKE_PROFIT]

        GetTradeInformation(update, trade, account_information['balance'])
            
        if(enterTrade):
            update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                if(trade['OrderType'] in ['Buy', 'Sell']):
                    results = await execute_trades(connection, trade)
                else:
                    # Handle limit and stop orders
                    result = await connection.create_limit_buy_order(trade['Symbol'], 
                                                                   trade['PositionSize'],
                                                                   trade['Entry'],
                                                                   trade['StopLoss'],
                                                                   trade['TP'][0])
                
                update.effective_message.reply_text("Trade entered successfully! 💰")
                logger.info('\nTrade entered successfully!')
                
            except Exception as error:
                logger.error(f"\nTrade failed with error: {error}\n")
                update.effective_message.reply_text(f"There was an issue 😕\n\nError Message:\n{error}")
    
    except Exception as error:
        logger.error(f'Error: {error}')
        update.effective_message.reply_text(f"There was an issue with the connection 😕\n\nError Message:\n{error}")
    
    finally:
        duration = time.time() - start_time
        logger.info(f"Trade execution took {duration:.2f} seconds")

# [Rest of the existing functions remain the same...]

def main() -> None:
    """Runs the Telegram bot."""
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", welcome))
    dp.add_handler(CommandHandler("help", help))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", Trade_Command, filters=Filters.chat_type.groups | Filters.chat_type.private)],
        states={
            TRADE: [MessageHandler(Filters.text & ~Filters.command & (Filters.chat_type.groups | Filters.chat_type.private), PlaceTrade)],
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command & (Filters.chat_type.groups | Filters.chat_type.private), CalculateTrade)],
            DECISION: [CommandHandler("yes", PlaceTrade), CommandHandler("no", cancel)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    dp.add_handler(conv_handler)
    dp.add_handler(MessageHandler(Filters.regex('^exit (buy|sell)$') & (Filters.chat_type.groups | Filters.chat_type.private), exit_trade_handler))
    dp.add_handler(MessageHandler(Filters.text, unknown_command))
    dp.add_error_handler(error)
    
    updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=APP_URL + TOKEN)
    updater.idle()

if __name__ == '__main__':
    main()
