#!/usr/bin/env python3
"""
Telegram Bot Handler for ngTradingBot
Handles incoming commands and button interactions
"""

import logging
import os
from flask import Flask, request, jsonify
from telegram_notifier import TelegramNotifier
from telegram_charts import TelegramChartsGenerator
from telegram_daily_report import TelegramDailyReporter
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram Bot command handler"""

    def __init__(self):
        self.notifier = TelegramNotifier()
        self.bot_token = self.notifier.bot_token
        self.chat_id = self.notifier.chat_id
        self.account_id = 3  # Default account

        if not self.notifier.enabled:
            logger.warning("Telegram bot disabled - missing credentials")
        else:
            logger.info(f"Telegram bot initialized for chat {self.chat_id}")

    def send_reply(self, text: str, reply_markup=None):
        """Send a reply message with optional keyboard"""
        if not self.notifier.enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            payload = {
                'chat_id': self.chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }

            if reply_markup:
                payload['reply_markup'] = reply_markup

            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200

        except Exception as e:
            logger.error(f"Error sending reply: {e}")
            return False

    def handle_command(self, command: str, message_id: int = None) -> bool:
        """
        Handle incoming Telegram bot commands

        Supported commands:
        - /start - Show welcome message with menu
        - /charts - Send P/L charts
        - /report - Send daily report
        - /help - Show available commands
        """
        command = command.lower().strip()

        logger.info(f"📥 Received command: {command}")

        if command == '/start' or command == '/help':
            return self._handle_start()

        elif command == '/charts':
            return self._handle_charts()

        elif command == '/report':
            return self._handle_report()

        else:
            self.send_reply(
                f"❓ Unbekannter Befehl: {command}\n\n"
                "Verfügbare Befehle:\n"
                "/charts - P/L Charts senden\n"
                "/report - Tagesbericht senden\n"
                "/help - Hilfe anzeigen"
            )
            return False

    def _handle_start(self) -> bool:
        """Handle /start command - show welcome with button menu"""

        # Create inline keyboard with buttons
        keyboard = {
            'inline_keyboard': [
                [
                    {'text': '📊 P/L Charts', 'callback_data': 'cmd_charts'},
                    {'text': '📈 Tagesbericht', 'callback_data': 'cmd_report'}
                ],
                [
                    {'text': '❓ Hilfe', 'callback_data': 'cmd_help'}
                ]
            ]
        }

        message = """
🤖 <b>ngTradingBot - Telegram Bot</b>

Willkommen! Nutze die Buttons unten oder diese Befehle:

<b>Verfügbare Funktionen:</b>
📊 <b>/charts</b> - P/L Charts senden
   Sendet alle 5 P/L Charts (1h, 12h, 24h, Woche, Jahr)

📈 <b>/report</b> - Tagesbericht
   24h Performance-Report mit Statistiken

❓ <b>/help</b> - Diese Hilfe

<i>Tipp: Nutze die Buttons für schnellen Zugriff!</i>
"""

        return self.send_reply(message, reply_markup=keyboard)

    def _handle_charts(self) -> bool:
        """Handle /charts command - send P/L charts"""

        # Send "processing" message
        self.send_reply("⏳ Generiere P/L Charts...")

        try:
            generator = TelegramChartsGenerator(account_id=self.account_id)
            success = generator.send_charts_to_telegram()

            if success:
                logger.info("✅ Charts sent successfully via bot command")
                return True
            else:
                self.send_reply("❌ Fehler beim Senden der Charts. Bitte später erneut versuchen.")
                return False

        except Exception as e:
            logger.error(f"Error handling /charts command: {e}", exc_info=True)
            self.send_reply(f"❌ Fehler beim Generieren der Charts: {str(e)}")
            return False

    def _handle_report(self) -> bool:
        """Handle /report command - send daily report"""

        self.send_reply("⏳ Generiere Tagesbericht...")

        try:
            reporter = TelegramDailyReporter(account_id=self.account_id)
            success = reporter.send_report()

            if success:
                logger.info("✅ Daily report sent successfully via bot command")
                return True
            else:
                self.send_reply("❌ Fehler beim Senden des Berichts.")
                return False

        except Exception as e:
            logger.error(f"Error handling /report command: {e}", exc_info=True)
            self.send_reply(f"❌ Fehler beim Generieren des Berichts: {str(e)}")
            return False

    def handle_callback(self, callback_data: str, callback_id: str) -> bool:
        """Handle inline keyboard button callbacks"""

        logger.info(f"📥 Received callback: {callback_data}")

        # Answer callback to remove loading state
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
            requests.post(url, json={'callback_query_id': callback_id}, timeout=5)
        except:
            pass

        # Map callback data to commands
        if callback_data == 'cmd_charts':
            return self._handle_charts()
        elif callback_data == 'cmd_report':
            return self._handle_report()
        elif callback_data == 'cmd_help':
            return self._handle_start()
        else:
            return False


# Flask app for webhook
app = Flask(__name__)
bot = TelegramBot()


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Telegram webhook endpoint
    Receives updates from Telegram Bot API
    """
    try:
        update = request.get_json()

        # Handle text commands
        if 'message' in update and 'text' in update['message']:
            text = update['message']['text']
            message_id = update['message']['message_id']

            # Only process commands (starting with /)
            if text.startswith('/'):
                bot.handle_command(text, message_id)

        # Handle inline keyboard button clicks
        elif 'callback_query' in update:
            callback_data = update['callback_query']['data']
            callback_id = update['callback_query']['id']
            bot.handle_callback(callback_data, callback_id)

        return jsonify({'ok': True})

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'bot_enabled': bot.notifier.enabled,
        'chat_id': bot.chat_id
    })


def set_webhook(webhook_url: str) -> bool:
    """
    Set the webhook URL for the bot

    Args:
        webhook_url: Public URL where Telegram should send updates
                    e.g. https://yourdomain.com/webhook

    Returns:
        True if webhook was set successfully
    """
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return False

    try:
        url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        response = requests.post(url, json={'url': webhook_url}, timeout=10)

        if response.status_code == 200:
            logger.info(f"✅ Webhook set to: {webhook_url}")
            return True
        else:
            logger.error(f"Failed to set webhook: {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return False


def get_webhook_info() -> dict:
    """Get current webhook status"""
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not bot_token:
        return {'error': 'TELEGRAM_BOT_TOKEN not set'}

    try:
        url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            return response.json()
        else:
            return {'error': response.text}

    except Exception as e:
        return {'error': str(e)}


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == 'webhook':
            # Set webhook
            if len(sys.argv) < 3:
                print("Usage: python telegram_bot.py webhook <URL>")
                print("Example: python telegram_bot.py webhook https://yourdomain.com/webhook")
                sys.exit(1)

            webhook_url = sys.argv[2]
            if set_webhook(webhook_url):
                print(f"✅ Webhook set to: {webhook_url}")
            else:
                print("❌ Failed to set webhook")
                sys.exit(1)

        elif sys.argv[1] == 'info':
            # Show webhook info
            info = get_webhook_info()
            print("📋 Webhook Info:")
            print(info)

        elif sys.argv[1] == 'test':
            # Test bot commands locally
            print("🧪 Testing bot commands...")
            bot = TelegramBot()

            print("\n1. Testing /start...")
            bot.handle_command('/start')

            print("\n2. Testing /charts...")
            bot.handle_command('/charts')

            print("\n✅ Tests completed!")

    else:
        # Run Flask webhook server
        print("🚀 Starting Telegram Bot webhook server on port 9907...")
        print("Set webhook with: python telegram_bot.py webhook <YOUR_PUBLIC_URL>")
        app.run(host='0.0.0.0', port=9907, debug=False)
