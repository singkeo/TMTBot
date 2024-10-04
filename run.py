#!/usr/bin/env python3
import asyncio
import logging
import math
import os

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
LOT_SIZE = float(os.environ.get('LOT_SIZE', '6.0'))  # Default to 0.01 if not set
STOP_LOSS = float(os.environ.get('STOP_LOSS', '20.0'))
TAKE_PROFIT = float(os.environ.get('TAKE_PROFIT', '200.0'))
INDEX = os.environ.get('INDEX', 'AUS200.cash')

# Enables logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# possibles states for conversation handler
CALCULATE, TRADE, DECISION = range(3)

# allowed FX symbols
SYMBOLS = ['AUDCAD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD', 'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD', 'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD', 'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD', 'GBPUSD', 'NOW', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD', 'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD']

# RISK FACTOR
RISK_FACTOR = float(os.environ.get("RISK_FACTOR"))


# Helper Functions
def ParseSignal(signal: str) -> dict:
    """Starts process of parsing signal and entering trade on MetaTrader account.

    Arguments:
        signal: trading signal

    Returns:
        a dictionary that contains trade signal information
    """

    # converts message to list of strings for parsing
    signal = signal.splitlines()
    signal = [line.rstrip() for line in signal]

    trade = {}
    
    # determines the order type of the trade
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
    
    # returns an empty dictionary if an invalid order type was given
    else:
        return {}

    # extracts symbol from trade signal
    trade['Symbol'] = (signal[0].split())[-1].upper()
    
    # checks if the symbol is valid, if not, returns an empty dictionary
    if(trade['Symbol'] not in SYMBOLS):
        trade['Symbol'] = INDEX  # COMMENTMIKA ASX200 index
    
    # checks wheter or not to convert entry to float because of market exectution option ("NOW")
    if(trade['OrderType'] == 'Buy' or trade['OrderType'] == 'Sell'):
        # COMMENTMIKA trade['Entry'] = (signal[1].split())[-1]
        # If it's a Buy/Sell signal, it's going to be "NOW" anyway
        trade['Entry'] = 'NOW'
    
    else:
        trade['Entry'] = float((signal[1].split())[-1])
        trade['StopLoss'] = float((signal[2].split())[-1])
        trade['TP'] = [float((signal[3].split())[-1])]

    # checks if there's a fourth line and parses it for TP2
    if(len(signal) > 4):
        trade['TP'].append(float(signal[4].split()[-1]))
    
    # adds risk factor to trade
    trade['RiskFactor'] = RISK_FACTOR

    return trade

def GetTradeInformation(update: Update, trade: dict, balance: float) -> None:
    """Calculates information from given trade including stop loss and take profit in pips, posiition size, and potential loss/profit.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
    """

    update.effective_message.reply_text("B1")

    # calculates the stop loss in pips
    if(trade['Symbol'] == 'XAUUSD'):
        multiplier = 0.1
        update.effective_message.reply_text("B1.2")

    elif(trade['Symbol'] == 'XAGUSD'):
        multiplier = 0.001
        update.effective_message.reply_text("B1.3")

    elif(str(trade['Entry']).index('.') >= 2):
        multiplier = 0.01
        update.effective_message.reply_text("B1.4")

    else:
        multiplier = 0.0001
        update.effective_message.reply_text("B2")

    # calculates the stop loss in pips
    update.effective_message.reply_text(f"Entry: {trade['Entry']}, StopLoss: {trade['StopLoss']}, TP: {trade['TP']}")
    update.effective_message.reply_text("B3")
    stopLossPips = abs(round((trade['StopLoss'] - trade['Entry']) / multiplier))

    # calculates the position size using stop loss and RISK FACTOR
    update.effective_message.reply_text("B4")
    trade['PositionSize'] = LOT_SIZE # COMMENTMIKA math.floor(((balance * trade['RiskFactor']) / stopLossPips) / 10 * 100) / 100
    update.effective_message.reply_text(f"PositionSize: {trade['PositionSize']}, StopLoss: {trade['StopLoss']}, TP: {trade['TP']}")
    update.effective_message.reply_text("B4.2")
    
    # calculates the take profit(s) in pips
    takeProfitPips = []
    update.effective_message.reply_text("B4.3")
    update.effective_message.reply_text(f"TP values: {trade['TP']}")
    for takeProfit in trade['TP']:
        update.effective_message.reply_text("B5")
        takeProfitPips.append(abs(round((takeProfit - trade['Entry']) / multiplier)))

    # creates table with trade information
    update.effective_message.reply_text("B6")
    table = CreateTable(trade, balance, stopLossPips, takeProfitPips, update)
    
    # sends user trade information and calcualted risk
    update.effective_message.reply_text(f'<pre>{table}</pre>', parse_mode=ParseMode.HTML)
    update.effective_message.reply_text("Cooking... 👀😏")

    return

def CreateTable(trade: dict, balance: float, stopLossPips: int, takeProfitPips: int, update: Update) -> PrettyTable:
    """Creates PrettyTable object to display trade information to user.

    Arguments:
        trade: dictionary that stores trade information
        balance: current balance of the MetaTrader account
        stopLossPips: the difference in pips from stop loss price to entry price

    Returns:
        a Pretty Table object that contains trade information
    """

    update.effective_message.reply_text("C1")

    # creates prettytable object
    table = PrettyTable()

    update.effective_message.reply_text("C2")
    
    table.title = "Trade Information"
    table.field_names = ["Key", "Value"]
    table.align["Key"] = "l"  
    table.align["Value"] = "l" 

    update.effective_message.reply_text("C3")

    table.add_row([trade["OrderType"] , trade["Symbol"]])
    update.effective_message.reply_text("C4")
    table.add_row(['Entry\n', trade['Entry']])
    update.effective_message.reply_text("C5")

    table.add_row(['Stop Loss', '{} pips'.format(stopLossPips)])
    update.effective_message.reply_text("C6")

    for count, takeProfit in enumerate(takeProfitPips):
        update.effective_message.reply_text("C7")
        table.add_row([f'TP {count + 1}', f'{takeProfit} pips'])

    update.effective_message.reply_text("C8")
    table.add_row(['\nRisk Factor', '\n{:,.0f} %'.format(trade['RiskFactor'] * 100)])
    update.effective_message.reply_text("C9")
    table.add_row(['Position Size', trade['PositionSize']])
    
    table.add_row(['\nCurrent Balance', '\n$ {:,.2f}'.format(balance)])
    update.effective_message.reply_text("C10")
    table.add_row(['Potential Loss', '$ {:,.2f}'.format(round((trade['PositionSize'] * 10) * stopLossPips, 2))])
    update.effective_message.reply_text("C11")

    # total potential profit from trade
    totalProfit = 0

    for count, takeProfit in enumerate(takeProfitPips):
        update.effective_message.reply_text("C12")
        profit = round((trade['PositionSize'] * 10 * (1 / len(takeProfitPips))) * takeProfit, 2)
        update.effective_message.reply_text("C13")
        table.add_row([f'TP {count + 1} Profit', '$ {:,.2f}'.format(profit)])
        update.effective_message.reply_text("C4")
        
        # sums potential profit from each take profit target
        totalProfit += profit
        update.effective_message.reply_text("C15")

    table.add_row(['\nTotal Profit', '\n$ {:,.2f}'.format(totalProfit)])

    return table

async def ConnectMetaTrader(update: Update, trade: dict, enterTrade: bool):
    """Attempts connection to MetaAPI and MetaTrader to place trade.

    Arguments:
        update: update from Telegram
        trade: dictionary that stores trade information

    Returns:
        A coroutine that confirms that the connection to MetaAPI/MetaTrader and trade placement were successful
    """

    # creates connection to MetaAPI
    api = MetaApi(API_KEY)
    
    try:
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ['DEPLOYING', 'DEPLOYED']

        if initial_state not in deployed_states:
            #  wait until account is deployed and connected to broker
            logger.info('Deploying account')
            await account.deploy()

        logger.info('Waiting for API server to connect to broker ...')
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()

        # wait until terminal state synchronized to the local state
        logger.info('Waiting for SDK to synchronize to terminal state ...')
        await connection.wait_synchronized()

        # obtains account information from MetaTrader server
        account_information = await connection.get_account_information()

        # COMMENTMIKA update.effective_message.reply_text("Successfully connected to MetaTrader!\nCalculating trade risk ... 🤔")
        update.effective_message.reply_text("Successfully connected to MetaTrader! 👌🏼")

        # checks if the order is a market execution to get the current price of symbol
        if(trade['Entry'] == 'NOW'):
            update.effective_message.reply_text("A1")
            price = await connection.get_symbol_price(symbol=trade['Symbol'])

            # uses bid price if the order type is a buy
            if(trade['OrderType'] == 'Buy'):
                update.effective_message.reply_text("A2")
                trade['Entry'] = float(price['bid'])
                trade['StopLoss'] = float(price['bid']) - STOP_LOSS # COMMENTMIKA UPDATE 20.0 WITH ENV VAR
                trade['TP'] = [float(price['bid']) + 200] # COMMENTMIKA UPDATE 200.0 WITH ENV VAR

            # uses ask price if the order type is a sell
            if(trade['OrderType'] == 'Sell'):
                update.effective_message.reply_text("A3")
                trade['Entry'] = float(price['ask'])
                trade['StopLoss'] = float(price['ask']) + STOP_LOSS # COMMENTMIKA UPDATE 20.0 WITH ENV VAR
                trade['TP'] = [float(price['bid']) - 200] # COMMENTMIKA UPDATE 200.0 WITH ENV VAR

        # produces a table with trade information
        GetTradeInformation(update, trade, account_information['balance'])
            
        # checks if the user has indicated to enter trade
        if(enterTrade == True):

            # enters trade on to MetaTrader account
            update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                # executes buy market execution order
                if(trade['OrderType'] == 'Buy'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['StopLoss'], takeProfit)

                # executes buy limit order
                elif(trade['OrderType'] == 'Buy Limit'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_limit_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)

                # executes buy stop order
                elif(trade['OrderType'] == 'Buy Stop'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_stop_buy_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)

                # executes sell market execution order
                elif(trade['OrderType'] == 'Sell'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['StopLoss'], takeProfit)

                # executes sell limit order
                elif(trade['OrderType'] == 'Sell Limit'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_limit_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)

                # executes sell stop order
                elif(trade['OrderType'] == 'Sell Stop'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_stop_sell_order(trade['Symbol'], trade['PositionSize'] / len(trade['TP']), trade['Entry'], trade['StopLoss'], takeProfit)
                
                # sends success message to user
                update.effective_message.reply_text("Trade entered successfully! 💰")
                
                # prints success message to console
                logger.info('\nTrade entered successfully!')
                logger.info('Result Code: {}\n'.format(result['stringCode']))
            
            except Exception as error:
                logger.info(f"\nTrade failed with error: {error}\n")
                update.effective_message.reply_text(f"There was an issue 😕\n\nError Message:\n{error}")
    
    except Exception as error:
        logger.error(f'Error: {error}')
        update.effective_message.reply_text(f"There was an issue with the connection 😕\n\nError Message:\n{error}")
    
    return


# Handler Functions
def PlaceTrade(update: Update, context: CallbackContext) -> int:
    """Parses trade and places on MetaTrader account.   
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    # checks if the trade has already been parsed or not
    if(context.user_data['trade'] == None):

        try: 
            # parses signal from Telegram message
            trade = ParseSignal(update.effective_message.text)
            
            # checks if there was an issue with parsing the trade
            if(not(trade)):
                raise Exception('Invalid Trade')

            # sets the user context trade equal to the parsed trade
            context.user_data['trade'] = trade
            # COMMENTMIKA update.effective_message.reply_text("Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... \n(May take a while) ⏰")
            update.effective_message.reply_text("Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... 👀")
        
        except Exception as error:
            logger.error(f'Error: {error}')
            errorMessage = f"There was an error parsing this trade 😕\n\nError: {error}\n\nPlease re-enter trade with this format:\n\nBUY/SELL SYMBOL\nEntry \nSL \nTP \n\nOr use the /cancel to command to cancel this action."
            update.effective_message.reply_text(errorMessage)

            # returns to TRADE state to reattempt trade parsing
            return TRADE
    
    # attempts connection to MetaTrader and places trade
    asyncio.run(ConnectMetaTrader(update, context.user_data['trade'], True))
    
    # removes trade from user context data
    context.user_data['trade'] = None

    return ConversationHandler.END

def CalculateTrade(update: Update, context: CallbackContext) -> int:
    """Parses trade and places on MetaTrader account.   
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    # checks if the trade has already been parsed or not
    if(context.user_data['trade'] == None):

        try: 
            # parses signal from Telegram message
            trade = ParseSignal(update.effective_message.text)
            
            # checks if there was an issue with parsing the trade
            if(not(trade)):
                raise Exception('Invalid Trade')

            # sets the user context trade equal to the parsed trade
            context.user_data['trade'] = trade
            # COMMENTMIKA update.effective_message.reply_text("Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... (May take a while) ⏰")
            update.effective_message.reply_text("Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... 👀")
        
        except Exception as error:
            logger.error(f'Error: {error}')
            errorMessage = f"There was an error parsing this trade 😕\n\nError: {error}\n\nPlease re-enter trade with this format:\n\nBUY/SELL SYMBOL\nEntry \nSL \nTP \n\nOr use the /cancel to command to cancel this action."
            update.effective_message.reply_text(errorMessage)

            # returns to CALCULATE to reattempt trade parsing
            return CALCULATE
    
    # attempts connection to MetaTrader and calculates trade information
    asyncio.run(ConnectMetaTrader(update, context.user_data['trade'], False))

    # asks if user if they would like to enter or decline trade
    update.effective_message.reply_text("Would you like to enter this trade?\nTo enter, select: /yes\nTo decline, select: /no")

    return DECISION

async def ExitTrades(update: Update, context: CallbackContext, exit_type: str) -> None:
    """Exits all trades of specified type (buy/sell) from MetaTrader account.
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
        exit_type: string specifying which type of trades to exit ('buy' or 'sell')
    """
    
    # creates connection to MetaAPI
    api = MetaApi(API_KEY)
    
    try:
        account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
        initial_state = account.state
        deployed_states = ['DEPLOYING', 'DEPLOYED']

        if initial_state not in deployed_states:
            logger.info('Deploying account')
            await account.deploy()

        logger.info('Waiting for API server to connect to broker ...')
        await account.wait_connected()

        # connect to MetaApi API
        connection = account.get_rpc_connection()
        await connection.connect()

        # wait until terminal state synchronized to the local state
        logger.info('Waiting for SDK to synchronize to terminal state ...')
        await connection.wait_synchronized()

        # Get all positions
        positions = await connection.get_positions()
        
        # Counter for closed positions
        closed_count = 0
        
        # Exit positions based on type
        for position in positions:
            try:
                # Check if position matches the exit type
                should_close = (exit_type.lower() == 'exit buy' and position['type'] == 'POSITION_TYPE_BUY') or \
                              (exit_type.lower() == 'exit sell' and position['type'] == 'POSITION_TYPE_SELL')
                
                if should_close:
                    # Close the position using market order
                    try:
                        result = await connection.close_position(position['id'])
                        if result.get('orderId'):
                            closed_count += 1
                            logger.info(f"Successfully closed position {position['id']}")
                        else:
                            logger.error(f"Failed to close position {position['id']}")
                            
                    except Exception as error:
                        error_details = getattr(error, 'details', None)
                        error_message = f"Error closing position {position['id']}"
                        
                        if error_details:
                            logger.error(f"{error_message}: {str(error)}, Details: {error_details}")
                            update.effective_message.reply_text(
                                f"{error_message}:\n{str(error)}\nDetails: {error_details}"
                            )
                        else:
                            logger.error(f"{error_message}: {str(error)}")
                            update.effective_message.reply_text(
                                f"{error_message}:\n{str(error)}"
                            )
                        
            except Exception as position_error:
                logger.error(f"Error processing position: {str(position_error)}")
                continue
        
        # Send summary message
        if closed_count > 0:
            update.effective_message.reply_text(f"Successfully closed {closed_count} {exit_type.split()[1].upper()} positions 👍")
        else:
            update.effective_message.reply_text(f"No {exit_type.split()[1].upper()} positions found to close 🤷‍♂️")
            
    except Exception as error:
        error_details = getattr(error, 'details', None)
        if error_details:
            logger.error(f'Error: {error}, Details: {error_details}')
            update.effective_message.reply_text(
                f"There was an issue with the connection 😕\n\n"
                f"Error Message: {error}\n"
                f"Details: {error_details}"
            )
        else:
            logger.error(f'Error: {error}')
            update.effective_message.reply_text(
                f"There was an issue with the connection 😕\n\n"
                f"Error Message: {error}"
            )

def unknown_command(update: Update, context: CallbackContext) -> None:
    """Checks if the user is authorized to use this bot or shares to use /help command for instructions.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    if(not(update.effective_message.chat.username == TELEGRAM_USER)):
        update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
        return

    update.effective_message.reply_text("Unknown command. Use /trade to place a trade or /calculate to find information for a trade. You can also use the /help command to view instructions for this bot.")

    return

# Command Handlers
def welcome(update: Update, context: CallbackContext) -> None:
    """Sends welcome message to user.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    welcome_message = "Welcome to the FX Signal Copier Telegram Bot! 💻💸\n\nYou can use this bot to enter trades directly from Telegram and get a detailed look at your risk to reward ratio with profit, loss, and calculated lot size. You are able to change specific settings such as allowed symbols, risk factor, and more from your personalized Python script and environment variables.\n\nUse the /help command to view instructions and example trades."
    
    # sends messages to user
    update.effective_message.reply_text(welcome_message)

    return

def help(update: Update, context: CallbackContext) -> None:
    """Sends a help message when the command /help is issued

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    help_message = "This bot is used to automatically enter trades onto your MetaTrader account directly from Telegram. To begin, ensure that you are authorized to use this bot by adjusting your Python script or environment variables.\n\nThis bot supports all trade order types (Market Execution, Limit, and Stop)\n\nAfter an extended period away from the bot, please be sure to re-enter the start command to restart the connection to your MetaTrader account."
    commands = "List of commands:\n/start : displays welcome message\n/help : displays list of commands and example trades\n/trade : takes in user inputted trade for parsing and placement\n/calculate : calculates trade information for a user inputted trade"
    trade_example = "Example Trades 💴:\n\n"
    market_execution_example = "Market Execution:\nBUY GBPUSD\nEntry NOW\nSL 1.14336\nTP 1.28930\nTP 1.29845\n\n"
    limit_example = "Limit Execution:\nBUY LIMIT GBPUSD\nEntry 1.14480\nSL 1.14336\nTP 1.28930\n\n"
    note = "You are able to enter up to two take profits. If two are entered, both trades will use half of the position size, and one will use TP1 while the other uses TP2.\n\nNote: Use 'NOW' as the entry to enter a market execution trade."

    # sends messages to user
    update.effective_message.reply_text(help_message)
    update.effective_message.reply_text(commands)
    update.effective_message.reply_text(trade_example + market_execution_example + limit_example + note)

    return

def exit_trade_handler(update: Update, context: CallbackContext) -> None:
    """Handles exit trade commands.
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    if not(update.effective_message.chat.username == TELEGRAM_USER):
        update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
        return

    message = update.effective_message.text.lower()
    if message not in ['exit buy', 'exit sell']:
        update.effective_message.reply_text("Invalid exit command. Please use 'exit buy' or 'exit sell'.")
        return
        
    update.effective_message.reply_text(f"Processing {message} command... 🔄")
    asyncio.run(ExitTrades(update, context, message))

def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels and ends the conversation.   
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    update.effective_message.reply_text("Command has been canceled.")

    # removes trade from user context data
    context.user_data['trade'] = None

    return ConversationHandler.END

def error(update: Update, context: CallbackContext) -> None:
    """Logs Errors caused by updates.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    logger.warning('Update "%s" caused error "%s"', update, context.error)

    return

def Trade_Command(update: Update, context: CallbackContext) -> int:
    """Asks user to enter the trade they would like to place.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    if(not(update.effective_message.chat.username == TELEGRAM_USER)):
        update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
        return ConversationHandler.END
    
    # initializes the user's trade as empty prior to input and parsing
    context.user_data['trade'] = None
    
    # asks user to enter the trade
    update.effective_message.reply_text("Please enter the trade that you would like to place.")

    return TRADE

def Calculation_Command(update: Update, context: CallbackContext) -> int:
    """Asks user to enter the trade they would like to calculate trade information for.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    if(not(update.effective_message.chat.username == TELEGRAM_USER)):
        update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
        return ConversationHandler.END

    # initializes the user's trade as empty prior to input and parsing
    context.user_data['trade'] = None

    # asks user to enter the trade
    update.effective_message.reply_text("Please enter the trade that you would like to calculate.")

    return CALCULATE


def main() -> None:
    """Runs the Telegram bot."""

    updater = Updater(TOKEN, use_context=True)

    # get the dispatcher to register handlers
    dp = updater.dispatcher

    # message handler
    dp.add_handler(CommandHandler("start", welcome))

    # help command handler
    dp.add_handler(CommandHandler("help", help))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", Trade_Command), CommandHandler("calculate", Calculation_Command)],
        states={
            TRADE: [MessageHandler(Filters.text & ~Filters.command, PlaceTrade)],
            CALCULATE: [MessageHandler(Filters.text & ~Filters.command, CalculateTrade)],
            DECISION: [CommandHandler("yes", PlaceTrade), CommandHandler("no", cancel)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # conversation handler for entering trade or calculating trade information
    dp.add_handler(conv_handler)

    # Exit trade handler
    dp.add_handler(MessageHandler(
        Filters.regex('^exit (buy|sell)$'), 
        exit_trade_handler
    ))
    
    # message handler for all messages that are not included in conversation handler
    dp.add_handler(MessageHandler(Filters.text, unknown_command))

    # log all errors
    dp.add_error_handler(error)
    
    # listens for incoming updates from Telegram
    updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=APP_URL + TOKEN)
    updater.idle()

    return


if __name__ == '__main__':
    main()
