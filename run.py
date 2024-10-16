#!/usr/bin/env python3
import asyncio
import logging
import math
import os
import time

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
STOP_LOSS = float(os.environ.get('STOP_LOSS', '30.0'))
TAKE_PROFIT = float(os.environ.get('TAKE_PROFIT', '200.0'))
INDEX = os.environ.get('INDEX', 'AUS200.cash')

# Enables logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# possibles states for conversation handler
CALCULATE, TRADE, DECISION = range(3)

# allowed FX symbols
SYMBOLS = ['FRA40.cash']

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
        logger.info(f"Symbol received: {trade['Symbol']}")
    
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
    
    # calculates the stop loss in pips
    if(trade['Symbol'] == 'XAUUSD'):
        multiplier = 0.1

    elif(trade['Symbol'] == 'XAGUSD'):
        multiplier = 0.001

    elif(str(trade['Entry']).index('.') >= 2):
        multiplier = 0.01

    else:
        multiplier = 0.0001

    # calculates the stop loss in pips
    # update.effective_message.reply_text(f"Entry: {trade['Entry']}, StopLoss: {trade['StopLoss']}, TP: {trade['TP']}")
    stopLossPips = abs(round((trade['StopLoss'] - trade['Entry']) / multiplier))

    # calculates the position size using stop loss and RISK FACTOR
    trade['PositionSize'] = LOT_SIZE # COMMENTMIKA math.floor(((balance * trade['RiskFactor']) / stopLossPips) / 10 * 100) / 100
    # update.effective_message.reply_text(f"PositionSize: {trade['PositionSize']}, StopLoss: {trade['StopLoss']}, TP: {trade['TP']}")
    
    # calculates the take profit(s) in pips
    takeProfitPips = []
    # update.effective_message.reply_text(f"TP values: {trade['TP']}")
    for takeProfit in trade['TP']:
        takeProfitPips.append(abs(round((takeProfit - trade['Entry']) / multiplier)))

    # creates table with trade information
    table = CreateTable(trade, balance, stopLossPips, takeProfitPips, update)
    
    # sends user trade information and calcualted risk
    update.effective_message.reply_text(f'<pre>{table}</pre>', parse_mode=ParseMode.HTML)
    # update.effective_message.reply_text("Cooking... 👀😏")

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
    
    # creates prettytable object
    table = PrettyTable()
    
    table.title = "Trade Information"
    table.field_names = ["Key", "Value"]
    table.align["Key"] = "l"  
    table.align["Value"] = "l" 

    table.add_row([trade["OrderType"] , trade["Symbol"]])
    table.add_row(['Entry\n', trade['Entry']])

    table.add_row(['Stop Loss', trade['StopLoss']])

    # for count, takeProfit in enumerate(takeProfitPips):
        # table.add_row([f'TP {count + 1}', f'{takeProfit} pips'])

    # table.add_row(['\nRisk Factor', '\n{:,.0f} %'.format(trade['RiskFactor'] * 100)])
    table.add_row(['Position Size', trade['PositionSize']])
    
    table.add_row(['\nCurrent Balance', '\n$ {:,.2f}'.format(balance)])
    # table.add_row(['Potential Loss', '$ {:,.2f}'.format(round((trade['PositionSize'] * 10) * stopLossPips, 2))])

    # total potential profit from trade
    totalProfit = 0

    # for count, takeProfit in enumerate(takeProfitPips):
        # profit = round((trade['PositionSize'] * 10 * (1 / len(takeProfitPips))) * takeProfit, 2)
        # table.add_row([f'TP {count + 1} Profit', '$ {:,.2f}'.format(profit)])
        
        # sums potential profit from each take profit target
        # totalProfit += profit

    # table.add_row(['\nTotal Profit', '\n$ {:,.2f}'.format(totalProfit)])

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
            price = await connection.get_symbol_price(symbol=trade['Symbol'])

            # uses bid price if the order type is a buy
            if(trade['OrderType'] == 'Buy'):
                trade['Entry'] = float(price['bid'])
                trade['StopLoss'] = float(price['bid']) - STOP_LOSS # COMMENTMIKA UPDATE 20.0 WITH ENV VAR
                trade['TP'] = [float(price['bid']) + 200] # COMMENTMIKA UPDATE 200.0 WITH ENV VAR
                logger.info(f"DEBUG: Entry={price['bid']}")
                logger.info(f"DEBUG: STOP_LOSS={STOP_LOSS}")
                logger.info(f"DEBUG: CALCULATION={float(price['bid'])} - {STOP_LOSS} = {float(price['bid']) - STOP_LOSS}")
                logger.info(f"DEBUG: SL={trade['StopLoss']}")

            # uses ask price if the order type is a sell
            if(trade['OrderType'] == 'Sell'):
                trade['Entry'] = float(price['ask'])
                trade['StopLoss'] = float(price['ask']) + STOP_LOSS # COMMENTMIKA UPDATE 20.0 WITH ENV VAR
                trade['TP'] = [float(price['bid']) - 200] # COMMENTMIKA UPDATE 200.0 WITH ENV VAR
                logger.info(f"DEBUG: Entry={price['ask']}")
                logger.info(f"DEBUG: STOP_LOSS={STOP_LOSS}")
                logger.info(f"DEBUG: CALCULATION={float(price['ask'])} + {STOP_LOSS} = {float(price['bid']) + STOP_LOSS}")
                logger.info(f"DEBUG: SL={trade['StopLoss']}")

        # produces a table with trade information
        GetTradeInformation(update, trade, account_information['balance'])
            
        # checks if the user has indicated to enter trade
        if(enterTrade == True):

            # enters trade on to MetaTrader account
            # update.effective_message.reply_text("Entering trade on MetaTrader Account ... 👨🏾‍💻")

            try:
                # executes buy market execution order
                if(trade['OrderType'] == 'Buy'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_buy_order(trade['Symbol'], trade['PositionSize'], trade['StopLoss'], takeProfit)

                # executes buy limit order
                elif(trade['OrderType'] == 'Buy Limit'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_limit_buy_order(trade['Symbol'], trade['PositionSize'], trade['Entry'], trade['StopLoss'], takeProfit)

                # executes buy stop order
                elif(trade['OrderType'] == 'Buy Stop'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_stop_buy_order(trade['Symbol'], trade['PositionSize'], trade['Entry'], trade['StopLoss'], takeProfit)

                # executes sell market execution order
                elif(trade['OrderType'] == 'Sell'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_market_sell_order(trade['Symbol'], trade['PositionSize'], trade['StopLoss'], takeProfit)

                # executes sell limit order
                elif(trade['OrderType'] == 'Sell Limit'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_limit_sell_order(trade['Symbol'], trade['PositionSize'], trade['Entry'], trade['StopLoss'], takeProfit)

                # executes sell stop order
                elif(trade['OrderType'] == 'Sell Stop'):
                    for takeProfit in trade['TP']:
                        result = await connection.create_stop_sell_order(trade['Symbol'], trade['PositionSize'], trade['Entry'], trade['StopLoss'], takeProfit)
                
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
    """Parses trade and places on MetaTrader account."""
    
    # Add debug logging
    logger.info(f"Processing trade from chat ID: {update.effective_message.chat.id}")
    logger.info(f"Message content: {update.effective_message.text}")
    
    # Check if the trade has already been parsed
    if context.user_data.get('trade') is None:
        try: 
            # Parse signal from Telegram message
            trade = ParseSignal(update.effective_message.text)
            
            if not trade:
                raise Exception('Invalid Trade')

            context.user_data['trade'] = trade
            # update.effective_message.reply_text("Trade Successfully Parsed! 🥳\nConnecting to MetaTrader ... 👀")
        
        except Exception as error:
            logger.error(f'Error parsing trade: {error}')
            errorMessage = (
                f"There was an error parsing this trade 😕\n\n"
                f"Error: {error}\n\n"
                f"Please re-enter trade with this format:\n"
                f"BUY/SELL SYMBOL\nEntry \nSL \nTP \n\n"
                f"Or use the /cancel to command to cancel this action."
            )
            update.effective_message.reply_text(errorMessage)
            return TRADE
    
    # Attempt to connect to MetaTrader and place trade
    asyncio.run(ConnectMetaTrader(update, context.user_data['trade'], True))
    
    # Clean up
    context.user_data['trade'] = None

    logger.info(f"New trade request: Symbol={trade['Symbol']}, Size={trade['PositionSize']}, SL={trade['StopLoss']}")
    
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
    update.effective_message.reply_text(update.effective_message.chat.username)
    update.effective_message.reply_text("-4-")
    update.effective_message.reply_text(TELEGRAM_USER)
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

    welcome_message = "Welcome my old friends 💻💸\n\nInchbuddah une session bien rentable 🚀\n\Faites la commande /help si vous êtes perdus"
    
    # sends messages to user
    update.effective_message.reply_text(welcome_message)

    return

async def ping_server(api_key, account_id):
    logger.info("Démarrage de la fonction ping_server")
    start_time = time.time()
    try:
        logger.info("Initialisation de l'API MetaApi")
        api = MetaApi(api_key)
        
        logger.info("Récupération du compte")
        account = await api.metatrader_account_api.get_account(account_id)
        
        end_time = time.time()
        logger.info("Ping réussi")
        return True, round((end_time - start_time) * 1000, 2)
    except Exception as e:
        logger.error(f"Erreur lors du ping: {str(e)}", exc_info=True)
        return False, str(e)

def ping(update: Update, context: CallbackContext) -> None:
    """Pings the MetaAPI server and reports the result."""
    logger.info("Commande /ping reçue")
    message = update.effective_message.reply_text("Pinging server...")
    try:
        success, result = asyncio.run(ping_server(API_KEY, ACCOUNT_ID))
        if success:
            logger.info(f"Ping réussi en {result}ms")
            message.edit_text(f"Pong! 🏓\nLe serveur est accessible.\nTemps de réponse: {result}ms")
        else:
            logger.warning(f"Échec du ping: {result}")
            message.edit_text(f"Échec du ping! ❌\nErreur: {result}")
    except Exception as e:
        logger.error(f"Erreur inattendue lors du ping: {str(e)}", exc_info=True)
        message.edit_text(f"Erreur inattendue lors du ping. Veuillez vérifier les logs.")
    return

def help(update: Update, context: CallbackContext) -> None:
    """Sends a help message when the command /help is issued

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    help_message = "Toujours bien commencer la session avec la commande /start"
    commands = "List des commandes:\n/start : à faire au début de chaque session\n/help : liste des commandes\n/trade : à faire avant de placer un trade\n/cancel : à faire après un /trade pour cancel\n/ping : vérifier si le bot est en ligne"
    trade_example = "Exemples de trades possibles 💴:\n\n"
    market_execution_example = "Market Execution:\nBUY GBPUSD\nEntry NOW\nSL 1.14336\nTP 1.28930\nTP 1.29845\n\n"
    limit_example = "buy\nsell\nexit buy\nexit sell"
    
    update.effective_message.reply_text(help_message)
    update.effective_message.reply_text(commands)
    update.effective_message.reply_text(trade_example + limit_example)

    return

def exit_trade_handler(update: Update, context: CallbackContext) -> None:
    """Handles exit trade commands.
    
    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """
    # Add debug logging
    logger.info(f"Exit command received from chat ID: {update.effective_message.chat.id}")
    logger.info(f"Message from user: {update.effective_message.from_user.username}")
    logger.info(f"Chat type: {update.effective_message.chat.type}")
    
    # Check if it's a group chat
    is_group = update.effective_message.chat.type in ['group', 'supergroup']
    
    # Authorization check for group chats
    if is_group:
        if update.effective_message.from_user.username != TELEGRAM_USER:
            update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
            return
    else:
        # Original check for private chats
        if not(update.effective_message.chat.username == TELEGRAM_USER):
            update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
            return

    message = update.effective_message.text.lower()
    if message not in ['exit buy', 'exit sell', 'Exit buy', 'Exit sell']:
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
    """Asks user to enter the trade they would like to place."""
    
    # Add debug logging
    logger.info(f"Trade command received from chat ID: {update.effective_message.chat.id}")
    logger.info(f"Message from user: {update.effective_message.from_user.username}")
    logger.info(f"Chat type: {update.effective_message.chat.type}")
    
    # Check if it's a group chat
    is_group = update.effective_message.chat.type in ['group', 'supergroup']
    
    # Modify the authorization check to handle group chats
    if is_group:
        # Check if the message is from an authorized user
        if update.effective_message.from_user.username != TELEGRAM_USER:
            update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
            return ConversationHandler.END
    else:
        # Original check for private chats
        if not(update.effective_message.chat.username == TELEGRAM_USER):
            update.effective_message.reply_text("You are not authorized to use this bot! 🙅🏽‍♂️")
            return ConversationHandler.END
    
    # Initialize the trade
    context.user_data['trade'] = None
    
    # Ask user to enter the trade
    update.effective_message.reply_text("Please enter the trade that you would like to place.")

    return TRADE

def Calculation_Command(update: Update, context: CallbackContext) -> int:
    """Asks user to enter the trade they would like to calculate trade information for.

    Arguments:
        update: update from Telegram
        context: CallbackContext object that stores commonly used objects in handler callbacks
    """

    update.effective_message.reply_text(update.effective_message.chat.username)
    update.effective_message.reply_text("-1-")
    update.effective_message.reply_text(TELEGRAM_USER)
    
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

    dp.add_handler(CommandHandler("start", welcome))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("ping", ping))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("trade", Trade_Command, filters=Filters.chat_type.groups | Filters.chat_type.private)],
        states={
            TRADE: [
                MessageHandler(
                    Filters.text & ~Filters.command & (Filters.chat_type.groups | Filters.chat_type.private), 
                    PlaceTrade
                )
            ],
            CALCULATE: [
                MessageHandler(
                    Filters.text & ~Filters.command & (Filters.chat_type.groups | Filters.chat_type.private), 
                    CalculateTrade
                )
            ],
            DECISION: [
                CommandHandler("yes", PlaceTrade), 
                CommandHandler("no", cancel)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    # conversation handler for entering trade or calculating trade information
    dp.add_handler(conv_handler)

    def detailed_error_handler(update: Update, context: CallbackContext):
        """Log Errors caused by Updates with detailed information."""
        logger.warning('Update "%s" caused error "%s"', update.to_dict(), context.error)
        logger.warning('Error details:', exc_info=context.error)
        
        # Check if the message is from mika or vitaly
        if update.effective_message and update.effective_message.from_user:
            username = update.effective_message.from_user.username
            if username in ["msprs01", "drosee92", "Vitaliy_YOUNOX"]:
                logger.info(f"Message sent")
            else:
                update.effective_message.reply_text("Sorry, an error occurred. The administrator has been notified.")


    dp.add_error_handler(detailed_error_handler)

    # Add the exit trade handler with updated filters
    dp.add_handler(MessageHandler(
        Filters.regex('^exit (buy|sell)$') & (Filters.chat_type.groups | Filters.chat_type.private), 
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
