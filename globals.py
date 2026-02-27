# Stores active Telethon clients: {user_id: client_object}
user_clients = {}

# Stores user settings & stats: {user_id: { 'list': [], 'stats': {}, ... }}
user_configs = {}

# Stores temporary data for the Telegram OTP web login process
# Format: { phone_number: { 'client': TelegramClient, 'hash': str } }
otp_flows = {}
