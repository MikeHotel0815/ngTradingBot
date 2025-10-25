#!/usr/bin/env python3
"""
Telegram Chat-ID herausfinden

Usage:
    python get_telegram_chat_id.py YOUR_BOT_TOKEN
"""

import sys
import requests

if len(sys.argv) < 2:
    print("❌ Usage: python get_telegram_chat_id.py YOUR_BOT_TOKEN")
    sys.exit(1)

bot_token = sys.argv[1]

try:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    response = requests.get(url)
    data = response.json()

    if not data.get('ok'):
        print(f"❌ Error: {data.get('description', 'Unknown error')}")
        sys.exit(1)

    updates = data.get('result', [])

    if not updates:
        print("❌ Keine Nachrichten gefunden!")
        print("   → Sende zuerst eine Nachricht an deinen Bot in Telegram")
        print("   → Dann führe dieses Script erneut aus")
        sys.exit(1)

    print("✅ Telegram-Konfiguration gefunden!\n")

    for update in updates:
        if 'message' in update:
            chat = update['message']['chat']
            chat_id = chat['id']
            username = chat.get('username', 'N/A')
            first_name = chat.get('first_name', 'N/A')

            print(f"Chat-ID: {chat_id}")
            print(f"Username: @{username}")
            print(f"Name: {first_name}")
            print()

    # Zeige den ersten Chat als Empfehlung
    first_chat_id = updates[0]['message']['chat']['id']
    print("=" * 60)
    print("📋 KOPIERE DIESE WERTE:")
    print("=" * 60)
    print(f"TELEGRAM_BOT_TOKEN = '{bot_token}'")
    print(f"TELEGRAM_CHAT_ID = '{first_chat_id}'")
    print("=" * 60)

except Exception as e:
    print(f"❌ Fehler: {e}")
    sys.exit(1)
