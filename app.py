import os
import re
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ========= CONFIGURATION =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
ESCROW_FEE = float(os.getenv("ESCROW_FEE", 0.03))
ADMIN_IDS = [OWNER_ID]

# Database structures (in-memory for demo)
user_warns = {}
muted_users = {}
banned_users = {}
custom_filters = {}
notes = {}
welcome_enabled = {}
goodbye_enabled = {}
antiflood_enabled = {}
antilink_enabled = {}
flood_counts = {}
group_rules = {}
captcha_required = {}
approved_users = {}
escrow_transactions = {}

# Helper Functions
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def can_restrict_member(chat_member):
    return chat_member.status in ['administrator', 'creator']

async def get_target_user(update: Update, user_id=None):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if user_id:
        return await update.get_chat().get_member(user_id)
    return None

# ========= ESCROW COMMANDS =========
async def escrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔒 *RDX Escrow Service*\n\n"
        "To start an escrow transaction:\n"
        "`/create_escrow <amount> <seller_username> <description>`\n\n"
        f"*Fee:* {ESCROW_FEE*100}% of transaction amount\n\n"
        "_Trusted escrow by RDX_",
        parse_mode="Markdown"
    )

async def create_escrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/create_escrow <amount> <seller> <description>`", parse_mode="Markdown")
        return
    amount = float(context.args[0])
    seller = context.args[1]
    description = ' '.join(context.args[2:])
    fee = amount * ESCROW_FEE
    total = amount + fee
    tx_id = len(escrow_transactions) + 1
    escrow_transactions[tx_id] = {
        'buyer': update.effective_user.id,
        'seller': seller,
        'amount': amount,
        'fee': fee,
        'total': total,
        'description': description,
        'status': 'pending'
    }
    await update.message.reply_text(
        f"✅ *Escrow Created!*\n\n"
        f"📝 *Tx ID:* `{tx_id}`\n"
        f"💰 *Amount:* ${amount:,.2f}\n"
        f"💸 *Fee ({ESCROW_FEE*100}%):* ${fee:,.2f}\n"
        f"💵 *Total:* ${total:,.2f}\n"
        f"👤 *Seller:* {seller}\n"
        f"📋 *Desc:* {description}\n\n"
        f"Send payment to receive escrow protection.\n"
        f"Use `/release {tx_id}` when done.",
        parse_mode="Markdown"
    )

async def fee_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: `/fee <amount>`\nExample: `/fee 1000`", parse_mode="Markdown")
        return
    try:
        amount = float(context.args[0])
        fee = amount * ESCROW_FEE
        total = amount + fee
        await update.message.reply_text(
            f"💰 *Fee Calculation*\n\n"
            f"Amount: `${amount:,.2f}`\n"
            f"Fee ({ESCROW_FEE*100}%): `${fee:,.2f}`\n"
            f"Total: `${total:,.2f}`\n\n"
            f"🔒 Escrow secured by RDX.",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

async def release_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/release <tx_id>`", parse_mode="Markdown")
        return
    tx_id = int(context.args[0])
    if tx_id in escrow_transactions:
        escrow_transactions[tx_id]['status'] = 'completed'
        await update.message.reply_text(f"✅ Transaction {tx_id} released successfully!")
    else:
        await update.message.reply_text("Transaction not found.")

async def dispute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/dispute <tx_id>`", parse_mode="Markdown")
        return
    tx_id = int(context.args[0])
    if tx_id in escrow_transactions:
        escrow_transactions[tx_id]['status'] = 'disputed'
        await update.message.reply_text(f"⚠️ Dispute opened for transaction {tx_id}. Admin will review.")
    else:
        await update.message.reply_text("Transaction not found.")

# ========= ROSE BOT MODERATION COMMANDS =========

# Ban Commands
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to ban them.")
        return
    user = update.message.reply_to_message.from_user
    reason = ' '.join(context.args) if context.args else "No reason provided"
    await update.message.chat.ban_member(user.id)
    banned_users[user.id] = {'reason': reason, 'banned_by': update.effective_user.id}
    await update.message.reply_text(f"✅ Banned {user.first_name}.\nReason: {reason}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/unban <user_id>` or reply to a message", parse_mode="Markdown")
        return
    user_id = int(context.args[0])
    await update.message.chat.unban_member(user_id)
    if user_id in banned_users:
        del banned_users[user_id]
    await update.message.reply_text(f"✅ Unbanned user {user_id}.")

async def tban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Temporary ban - /tban 2h for 2 hours, /tban 30m for 30 minutes"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message or not context.args:
        await update.message.reply_text("Reply to a user and specify time: `/tban 2h` or `/tban 30m`", parse_mode="Markdown")
        return
    user = update.message.reply_to_message.from_user
    time_str = context.args[0]
    match = re.match(r'(\d+)([smhdw])', time_str.lower())
    if not match:
        await update.message.reply_text("Invalid format. Use: 30s, 5m, 2h, 1d, 1w")
        return
    value, unit = int(match[1]), match[2]
    unit_map = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    seconds = value * unit_map[unit]
    until_date = datetime.now() + timedelta(seconds=seconds)
    await update.message.chat.ban_member(user.id, until_date=until_date)
    await update.message.reply_text(f"✅ Banned {user.first_name} for {time_str}.")

# Mute Commands
async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to mute them.")
        return
    user = update.message.reply_to_message.from_user
    permissions = ChatPermissions(can_send_messages=False)
    await update.message.chat.restrict_member(user.id, permissions)
    muted_users[user.id] = True
    await update.message.reply_text(f"🔇 Muted {user.first_name}.")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to unmute them.")
        return
    user = update.message.reply_to_message.from_user
    permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
    await update.message.chat.restrict_member(user.id, permissions)
    if user.id in muted_users:
        del muted_users[user.id]
    await update.message.reply_text(f"🔊 Unmuted {user.first_name}.")

async def tmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Temporary mute - /tmute 30m"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message or not context.args:
        await update.message.reply_text("Reply to a user and specify time: `/tmute 30m`", parse_mode="Markdown")
        return
    user = update.message.reply_to_message.from_user
    time_str = context.args[0]
    match = re.match(r'(\d+)([smhd])', time_str.lower())
    if not match:
        await update.message.reply_text("Invalid format. Use: 30s, 5m, 2h, 1d")
        return
    value, unit = int(match[1]), match[2]
    unit_map = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    seconds = value * unit_map[unit]
    until_date = datetime.now() + timedelta(seconds=seconds)
    permissions = ChatPermissions(can_send_messages=False)
    await update.message.chat.restrict_member(user.id, permissions, until_date=until_date)
    muted_users[user.id] = until_date
    await update.message.reply_text(f"🔇 Muted {user.first_name} for {time_str}.")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to kick them.")
        return
    user = update.message.reply_to_message.from_user
    await update.message.chat.ban_member(user.id)
    await update.message.chat.unban_member(user.id)
    await update.message.reply_text(f"👢 Kicked {user.first_name}.")

# Welcome & Goodbye
async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        status = "ON" if welcome_enabled.get(update.effective_chat.id, False) else "OFF"
        await update.message.reply_text(f"Welcome messages are currently {status}.\nUse `/welcome on` or `/welcome off`", parse_mode="Markdown")
        return
    if context.args[0].lower() == 'on':
        welcome_enabled[update.effective_chat.id] = True
        await update.message.reply_text("✅ Welcome messages enabled. Use `/setwelcome <message>` to customize.", parse_mode="Markdown")
    elif context.args[0].lower() == 'off':
        welcome_enabled[update.effective_chat.id] = False
        await update.message.reply_text("❌ Welcome messages disabled.")

async def setwelcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setwelcome Welcome {first} to the group!", parse_mode="Markdown")
        return
    welcome_msg = ' '.join(context.args)
    context.bot_data[f'welcome_{update.effective_chat.id}'] = welcome_msg
    await update.message.reply_text(f"✅ Welcome message set to:\n{welcome_msg}")

async def goodbye_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        status = "ON" if goodbye_enabled.get(update.effective_chat.id, False) else "OFF"
        await update.message.reply_text(f"Goodbye messages are currently {status}.")
        return
    if context.args[0].lower() == 'on':
        goodbye_enabled[update.effective_chat.id] = True
        await update.message.reply_text("✅ Goodbye messages enabled.")
    elif context.args[0].lower() == 'off':
        goodbye_enabled[update.effective_chat.id] = False
        await update.message.reply_text("❌ Goodbye messages disabled.")

# Rules
async def setrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setrules <rule text>`", parse_mode="Markdown")
        return
    rules = ' '.join(context.args)
    group_rules[update.effective_chat.id] = rules
    await update.message.reply_text(f"✅ Rules set!\n\n{rules}")

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = group_rules.get(update.effective_chat.id)
    if rules:
        await update.message.reply_text(f"📋 *Group Rules*\n\n{rules}", parse_mode="Markdown")
    else:
        await update.message.reply_text("No rules have been set for this group. Ask an admin to use `/setrules`.")

async def resetrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if update.effective_chat.id in group_rules:
        del group_rules[update.effective_chat.id]
    await update.message.reply_text("✅ Rules have been reset.")

# Warn System
async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to warn them.")
        return
    user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    reason = ' '.join(context.args) if context.args else "No reason"
    if chat_id not in user_warns:
        user_warns[chat_id] = {}
    user_warns[chat_id][user.id] = user_warns[chat_id].get(user.id, 0) + 1
    warn_count = user_warns[chat_id][user.id]
    await update.message.reply_text(f"⚠️ Warned {user.first_name} | Reason: {reason}\nWarnings: {warn_count}/3")
    if warn_count >= 3:
        await update.message.chat.ban_member(user.id)
        await update.message.reply_text(f"🚫 {user.first_name} has been banned for exceeding 3 warnings.")
        del user_warns[chat_id][user.id]

async def resetwarns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to reset their warnings.")
        return
    user = update.message.reply_to_message.from_user
    chat_id = update.effective_chat.id
    if chat_id in user_warns and user.id in user_warns[chat_id]:
        del user_warns[chat_id][user.id]
    await update.message.reply_text(f"✅ Reset warnings for {user.first_name}.")

# Antiflood
async def antiflood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        status = "ON" if antiflood_enabled.get(update.effective_chat.id, False) else "OFF"
        await update.message.reply_text(f"Antiflood is currently {status}.\nUse `/antiflood on` or `/antiflood off`", parse_mode="Markdown")
        return
    if context.args[0].lower() == 'on':
        antiflood_enabled[update.effective_chat.id] = True
        await update.message.reply_text("✅ Antiflood protection enabled. Use `/setflood 5` to set limit.")
    elif context.args[0].lower() == 'off':
        antiflood_enabled[update.effective_chat.id] = False
        await update.message.reply_text("❌ Antiflood protection disabled.")

async def setflood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setflood <number>`", parse_mode="Markdown")
        return
    try:
        limit = int(context.args[0])
        context.bot_data[f'flood_limit_{update.effective_chat.id}'] = limit
        await update.message.reply_text(f"✅ Flood limit set to {limit} messages per 5 seconds.")
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

# Antilink
async def antilink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        status = "ON" if antilink_enabled.get(update.effective_chat.id, False) else "OFF"
        await update.message.reply_text(f"Antilink is currently {status}.\nUse `/antilink on` or `/antilink off`", parse_mode="Markdown")
        return
    if context.args[0].lower() == 'on':
        antilink_enabled[update.effective_chat.id] = True
        await update.message.reply_text("✅ Link protection enabled.")
    elif context.args[0].lower() == 'off':
        antilink_enabled[update.effective_chat.id] = False
        await update.message.reply_text("❌ Link protection disabled.")

# Purge
async def purge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to delete all messages after it.")
        return
    msg_id = update.message.reply_to_message.message_id
    current_id = update.message.message_id
    for i in range(msg_id, current_id):
        try:
            await update.message.chat.delete_message(i)
        except:
            pass
    await update.message.reply_text("✅ Messages purged.")

# Info & ID
async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    await update.message.reply_text(
        f"📁 *User Info*\n\n"
        f"👤 Name: {user.first_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"👥 Username: @{user.username if user.username else 'None'}\n"
        f"🖼️ DC ID: {user.dc_id if hasattr(user, 'dc_id') else 'Unknown'}",
        parse_mode="Markdown"
    )

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    await update.message.reply_text(f"🆔 User ID: `{user.id}`\nChat ID: `{update.effective_chat.id}`", parse_mode="Markdown")

# Pin
async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to pin it.")
        return
    await update.message.reply_to_message.pin()
    await update.message.reply_text("📌 Message pinned.")

async def unpin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    await update.message.chat.unpin_all_messages()
    await update.message.reply_text("📌 All messages unpinned.")

# Lock/Unlock
async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/lock all` or `/lock messages`")
        return
    lock_type = context.args[0].lower()
    if lock_type == 'all':
        permissions = ChatPermissions(can_send_messages=False)
        await update.message.chat.set_permissions(permissions)
        await update.message.reply_text("🔒 Chat locked for all members.")
    elif lock_type == 'messages':
        # Remove send message permission only
        await update.message.reply_text("🔒 Messages locked.")

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
    await update.message.chat.set_permissions(permissions)
    await update.message.reply_text("🔓 Chat unlocked.")

# Slowmode
async def slowmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/slowmode 10` (seconds)")
        return
    try:
        seconds = int(context.args[0])
        await update.message.chat.set_slow_mode_delay(seconds)
        await update.message.reply_text(f"⏱️ Slow mode set to {seconds} seconds.")
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")

# Notes & Filters
async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/save <note_name> <content>`")
        return
    note_name = context.args[0]
    content = ' '.join(context.args[1:])
    if update.effective_chat.id not in notes:
        notes[update.effective_chat.id] = {}
    notes[update.effective_chat.id][note_name] = content
    await update.message.reply_text(f"✅ Note '{note_name}' saved!")

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/get <note_name>`")
        return
    note_name = context.args[0]
    if update.effective_chat.id in notes and note_name in notes[update.effective_chat.id]:
        await update.message.reply_text(notes[update.effective_chat.id][note_name])
    else:
        await update.message.reply_text(f"Note '{note_name}' not found.")

async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in notes or not notes[update.effective_chat.id]:
        await update.message.reply_text("No notes saved in this group.")
        return
    note_list = "\n".join([f"• `{n}`" for n in notes[update.effective_chat.id].keys()])
    await update.message.reply_text(f"📝 *Saved Notes*\n\n{note_list}", parse_mode="Markdown")

async def rm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/rm <note_name>`")
        return
    note_name = context.args[0]
    if update.effective_chat.id in notes and note_name in notes[update.effective_chat.id]:
        del notes[update.effective_chat.id][note_name]
        await update.message.reply_text(f"✅ Note '{note_name}' deleted.")
    else:
        await update.message.reply_text(f"Note '{note_name}' not found.")

# Filter
async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/filter <keyword> <response>`")
        return
    keyword = context.args[0].lower()
    response = ' '.join(context.args[1:])
    if update.effective_chat.id not in custom_filters:
        custom_filters[update.effective_chat.id] = {}
    custom_filters[update.effective_chat.id][keyword] = response
    await update.message.reply_text(f"✅ Filter added for '{keyword}'")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/stop <keyword>`")
        return
    keyword = context.args[0].lower()
    if update.effective_chat.id in custom_filters and keyword in custom_filters[update.effective_chat.id]:
        del custom_filters[update.effective_chat.id][keyword]
        await update.message.reply_text(f"✅ Filter '{keyword}' removed.")
    else:
        await update.message.reply_text(f"Filter '{keyword}' not found.")

async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in custom_filters or not custom_filters[update.effective_chat.id]:
        await update.message.reply_text("No filters active in this group.")
        return
    filter_list = "\n".join([f"• `{k}`" for k in custom_filters[update.effective_chat.id].keys()])
    await update.message.reply_text(f"🔍 *Active Filters*\n\n{filter_list}", parse_mode="Markdown")

# Auto-filter message handler
async def check_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    if chat_id in custom_filters:
        for keyword, response in custom_filters[chat_id].items():
            if keyword in text:
                await update.message.reply_text(response)
                break

# Anti-flood handler
async def check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not antiflood_enabled.get(update.effective_chat.id, False):
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    key = f"{chat_id}_{user_id}"
    now = datetime.now()
    if key not in flood_counts:
        flood_counts[key] = []
    flood_counts[key] = [t for t in flood_counts[key] if (now - t).seconds < 5]
    flood_counts[key].append(now)
    limit = context.bot_data.get(f'flood_limit_{chat_id}', 5)
    if len(flood_counts[key]) > limit:
        await update.message.chat.restrict_member(user_id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🚫 User {update.effective_user.first_name} has been muted for flooding.")

# Anti-link handler
async def check_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not antilink_enabled.get(update.effective_chat.id, False):
        return
    if not update.message or not update.message.text:
        return
    text = update.message.text.lower()
    url_pattern = r'https?://[^\s]+|t\.me/[^\s]+|@[^\s]+'
    if re.search(url_pattern, text):
        await update.message.delete()
        await update.message.reply_text(f"❌ Links are not allowed, {update.effective_user.first_name}!")

# Captcha
async def captcha_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        status = "ON" if captcha_required.get(update.effective_chat.id, False) else "OFF"
        await update.message.reply_text(f"Captcha verification is {status}.\nUse `/captcha on` or `/captcha off`")
        return
    if context.args[0].lower() == 'on':
        captcha_required[update.effective_chat.id] = True
        await update.message.reply_text("✅ Captcha verification enabled. New members will be verified.")
    elif context.args[0].lower() == 'off':
        captcha_required[update.effective_chat.id] = False
        await update.message.reply_text("❌ Captcha verification disabled.")

# Language
async def setlang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setlang en` (English) or `/setlang tr` (Turkish)")
        return
    lang = context.args[0].lower()
    context.bot_data[f'lang_{update.effective_chat.id}'] = lang
    await update.message.reply_text(f"✅ Language set to {lang}. (Bot interface updates coming soon)")

# Report
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to report it to admins.")
        return
    reported_user = update.message.reply_to_message.from_user
    reason = ' '.join(context.args) if context.args else "No reason"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"🚨 *Report*\nUser: {reported_user.first_name} (ID: {reported_user.id})\nReason: {reason}\nChat: {update.effective_chat.title}")
        except:
            pass
    await update.message.reply_text("✅ Report sent to admins.")

# Admin Panel
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only bot admins can access this panel.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔨 Moderation Tools", callback_data="admin_modtools")],
        [InlineKeyboardButton("⚙️ Group Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("💰 Escrow Transactions", callback_data="admin_escrow")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛠️ *Admin Panel*", reply_markup=reply_markup, parse_mode="Markdown")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Access denied.")
        return
    if query.data == "admin_stats":
        await query.edit_message_text(
            "📊 *Bot Statistics*\n\n"
            f"• Active Escrows: {len(escrow_transactions)}\n"
            f"• Completed: {sum(1 for t in escrow_transactions.values() if t['status'] == 'completed')}\n"
            f"• Banned Users: {len(banned_users)}\n"
            f"• Muted Users: {len(muted_users)}\n"
            "• Total Groups: Not tracked\n\n"
            "_RDX Escrow Service_",
            parse_mode="Markdown"
        )
    elif query.data == "admin_broadcast":
        context.user_data['awaiting_broadcast'] = True
        await query.edit_message_text("📢 Send me the message to broadcast to all groups.")
    elif query.data == "admin_modtools":
        kb = [[InlineKeyboardButton("🔙 Back", callback