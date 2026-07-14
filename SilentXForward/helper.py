import logging
from SilentXForward import database
from pyrogram import Client, filters, enums
from pyrogram.errors import RPCError
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STARTTEXT = """<b>👋 Hello! I am SilentXForward Bot.</b>

I Can Forward Videos And Documents From Multiple Channels To Multiple Other Channels, Filtering Out Unwanted Content.

<b>Maintained By:</b> <a href="https://t.me/SilentXBotz">SilentXBotz</a>
"""

HELPTEXT = """<b>ℹ️ Help Menu</b>

I Am An Auto-Forward Bot. I Forward Files From Source Channels To Target Channels.

<b>Commands:</b>
/start - Check If I Am Alive.
/help - Show This Help Message.
/about - Show Information About Me.
/set &lt;source_id&gt; &lt;target_id&gt; - Add Target To Source
/remove_target &lt;source_id&gt; &lt;target_id&gt; - Remove A Target From Source
/remove_source &lt;source_id&gt; - Remove Source
/list - View All Set Channels 
/clear - Clear All Mappings

<b>How to use:</b>
1. Add Me To Source Channels And Target Channels As Admin.
2. IMPORTANT: In the Target Channel, when adding me as admin, make sure the <b>"Post Messages"</b> permission is turned ON — otherwise I physically cannot send anything there.
3. Use /set command to link source to target channels.
4. I Will Automatically Forward Videos And Documents!

<b>Channel:</b> @SilentXBotz
"""

ABOUTTEXT = """<b>🤖 About SilentXForward</b>

<b>Name:</b> SilentXForward
<b>Version:</b> 2.1
<b>Channel:</b> <a href="https://t.me/SilentXBotz">SilentXBotz</a>
<b>Repository:</b> <a href="https://github.com/NBBotz/Auto-Forward-Bot">GitHub</a>

<b>Features:</b>
- Multi-Source to Multi-Target
- Video & Document Filter
- FloodWait Handling
- MongoDB Database
- Queue System
- Live Permission Verification On /set
"""

BUTTONS = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("📢 Channel", url="https://t.me/SilentXBotz"),
            InlineKeyboardButton("🐱 GitHub", url="https://github.com/NBBotz/Auto-Forward-Bot")
        ]
    ]
)


async def check_channel_access(client, chat_id, need_post=False):
    """
    Verifies the bot is actually an admin in chat_id, and (optionally)
    that it has the 'Post Messages' privilege there.
    Returns (ok: bool, reason: str | None)
    """
    try:
        member = await client.get_chat_member(chat_id, "me")
    except RPCError as e:
        return False, f"I couldn't check my own status there ({e}). Make sure I'm added to that chat at all."

    if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
        return False, "I'm in that chat, but I'm <b>not an admin</b> there."

    if need_post and member.status == enums.ChatMemberStatus.ADMINISTRATOR:
        privileges = member.privileges
        if privileges is not None and privileges.can_post_messages is False:
            return False, (
                "I'm an admin there, but the <b>\"Post Messages\"</b> permission is "
                "turned OFF. Edit my admin rights in that channel and enable it."
            )

    return True, None


@Client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    try:
        await message.reply(
            text=STARTTEXT,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=BUTTONS,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error In Start Function: {e}")

@Client.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    try:
        await message.reply(
            text=HELPTEXT,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=BUTTONS,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error In Help Function: {e}")

@Client.on_message(filters.command("about") & filters.private)
async def about_command(client, message):
    try:
        await message.reply(
            text=ABOUTTEXT,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=BUTTONS,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error In About Function: {e}")

@Client.on_message(filters.command("set") & filters.private)
async def set_channels(client, message: Message):
    user_id = message.from_user.id

    if len(message.command) < 3:
        await message.reply_text(
            "<b>❌ Usage:</b> <code>/set &lt;source_id&gt; &lt;target_id&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/set -1001234567890 -1009876543210</code>",
            parse_mode=enums.ParseMode.HTML
        )
        return

    source = message.command[1]
    target = message.command[2]

    status_msg = await message.reply_text("<b>🔎 Verifying channels...</b>", parse_mode=enums.ParseMode.HTML)

    try:
        source_chat = await client.get_chat(source)
        target_chat = await client.get_chat(target)

        source_id = source_chat.id
        target_id = target_chat.id

        # NEW: actually verify the bot can read the source and post in the target,
        # instead of silently trying (and silently failing) later.
        ok_source, err_source = await check_channel_access(client, source_id, need_post=False)
        if not ok_source:
            await status_msg.edit_text(
                f"<b>❌ Source Channel Problem</b>\n\n"
                f"<b>📥 {source_chat.title}</b>\n{err_source}",
                parse_mode=enums.ParseMode.HTML
            )
            return

        ok_target, err_target = await check_channel_access(client, target_id, need_post=True)
        if not ok_target:
            await status_msg.edit_text(
                f"<b>❌ Target Channel Problem</b>\n\n"
                f"<b>📤 {target_chat.title}</b>\n{err_target}",
                parse_mode=enums.ParseMode.HTML
            )
            return

        result = await database.add_target_to_source(
            user_id,
            source_id,
            target_id,
            source_chat.title,
            target_chat.title
        )

        if result == "created":
            await status_msg.edit_text(
                f"<b>✅ New Source Created:</b>\n\n"
                f"<b>📥 Source:</b> {source_chat.title}\n"
                f"   <code>{source_id}</code>\n\n"
                f"<b>📤 Target:</b> {target_chat.title}\n"
                f"   <code>{target_id}</code>\n\n"
                f"🎉 Messages Will Be Forwarded!",
                parse_mode=enums.ParseMode.HTML
            )
        elif result == "added":
            await status_msg.edit_text(
                f"<b>✅ Target Added:</b>\n\n"
                f"<b>📥 Source:</b> {source_chat.title}\n"
                f"   <code>{source_id}</code>\n\n"
                f"<b>📤 New Target:</b> {target_chat.title}\n"
                f"   <code>{target_id}</code>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await status_msg.edit_text(
                f"<b>⚠️ Already Exists:</b>\n\n"
                f"This Target Is Already Set For This Source!",
                parse_mode=enums.ParseMode.HTML
            )

    except Exception as e:
        await status_msg.edit_text(
            f"<b>❌ Error:</b> {e}\n\n"
            "Make sure:\n"
            "• Bot is admin in both channels\n"
            "• Bot has 'Post Messages' permission in the target\n"
            "• Channel IDs are correct",
            parse_mode=enums.ParseMode.HTML
        )

@Client.on_message(filters.command("remove_target") & filters.private)
async def remove_target_channel(client, message: Message):
    user_id = message.from_user.id

    if len(message.command) < 3:
        await message.reply_text(
            "<b>❌ Usage:</b> <code>/remove_target &lt;source_id&gt; &lt;target_id&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/remove_target -1001234567890 -1009876543210</code>",
            parse_mode=enums.ParseMode.HTML
        )
        return

    source_input = message.command[1]
    target_input = message.command[2]

    try:
        source_chat = await client.get_chat(source_input)
        source_id = source_chat.id
        source_title = source_chat.title

        target_chat = await client.get_chat(target_input)
        target_id = target_chat.id
        target_title = target_chat.title

        result = await database.remove_target_from_source(user_id, source_id, target_id)

        if result == "removed":
            await message.reply_text(
                f"<b>✅ Target Removed Successfully!</b>\n\n"
                f"<b>📥 Source:</b> {source_title}\n"
                f"   <code>{source_id}</code>\n\n"
                f"<b>🗑️ Target:</b> {target_title}\n"
                f"   <code>{target_id}</code>\n\n"
                f"Target Channel Has Been Removed From This Source Mapping.",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"<b>⚠️ Not Found:</b>\n\n"
                f"<b>📥 Source:</b> {source_title}\n"
                f"<b>🗑️ Target:</b> {target_title}\n\n"
                f"No Mapping Exists For This Source-target Pair.\n\n"
                f"Use <code>/list</code> To See Your Current Mappings.",
                parse_mode=enums.ParseMode.HTML
            )

    except Exception as e:
        await message.reply_text(
            f"<b>❌ Error:</b> {e}\n\n"
            f"Make sure both channel IDs are valid and accessible.",
            parse_mode=enums.ParseMode.HTML
        )

@Client.on_message(filters.command("remove_source") & filters.private)
async def remove_channel(client, message: Message):
    user_id = message.from_user.id

    if len(message.command) < 2:
        await message.reply_text(
            "<b>❌ Usage:</b> <code>/remove_source &lt;source_id&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/remove_source -1001234567890</code>",
            parse_mode=enums.ParseMode.HTML
        )
        return

    source = message.command[1]

    try:
        chat = await client.get_chat(source)
        source_id = chat.id

        removed = await database.remove_source(user_id, source_id)

        if removed:
            await message.reply_text(
                f"<b>✅ Removed:</b>\n\n"
                f"<b>📥 Source:</b> {chat.title}\n"
                f"   <code>{source_id}</code>\n\n"
                f"All Targets For This Source Have Been Removed.",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"<b>⚠️ Not Found:</b>\n\n"
                f"No Targets Exists For <b>{chat.title}</b>\n\n"
                f"Use /list To See Your Mappings.",
                parse_mode=enums.ParseMode.HTML
            )

    except Exception as e:
        await message.reply_text(
            f"<b>❌ Error:</b> {e}",
            parse_mode=enums.ParseMode.HTML
        )

@Client.on_message(filters.command("list") & filters.private)
async def list_mappings(client, message: Message):
    user_id = message.from_user.id

    mappings = await database.get_user_mappings(user_id)

    if not mappings:
        await message.reply_text(
            "<b>❌ No mappings found!</b>\n\n"
            "Use <code>/set &lt;source_id&gt; &lt;target_id&gt;</code> to create one.",
            parse_mode=enums.ParseMode.HTML
        )
        return

    text = "<b>📊 Your Channel Mappings:</b>\n\n"

    for idx, mapping in enumerate(mappings, 1):
        source_id = mapping['source_id']
        target_ids = mapping.get('target_ids', [])

        try:
            source_chat = await client.get_chat(source_id)
            text += f"<b>{idx}. 📥 {source_chat.title}</b>\n"
            text += f"   <code>{source_id}</code>\n"
            text += f"   ⤵️ <b>Targets ({len(target_ids)}):</b>\n"

            for target_id in target_ids:
                try:
                    target_chat = await client.get_chat(target_id)
                    text += f"   • {target_chat.title} (<code>{target_id}</code>)\n"
                except Exception:
                    text += f"   • <code>{target_id}</code> (Unable to fetch)\n"

            text += "\n"
        except Exception:
            text += f"<b>{idx}.</b> <code>{source_id}</code> (Unable to fetch)\n"
            text += f"   Targets: {len(target_ids)}\n\n"

    text += f"<b>Total Sources:</b> {len(mappings)}"

    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)

@Client.on_message(filters.command("clear") & filters.private)
async def clear_all(client, message: Message):
    user_id = message.from_user.id

    count = await database.clear_all_mappings(user_id)

    if count > 0:
        await message.reply_text(
            f"<b>✅ Cleared {count} source(s)!</b>\n\n"
            f"All Your Mappings Have Been Removed.",
            parse_mode=enums.ParseMode.HTML
        )
    else:
        await message.reply_text(
            "<b>❌ You Don't Have Any Mappings To Clear!</b>",
            parse_mode=enums.ParseMode.HTML
        )
