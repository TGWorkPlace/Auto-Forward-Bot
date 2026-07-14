import asyncio
import logging
import time
from collections import defaultdict
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError
from SilentXForward import database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

message_queue = asyncio.Queue()
message_buffer = defaultdict(list)
buffer_tasks = {}

BUFFER_DELAY = 4

# NEW: cooldown so a persistently-broken mapping doesn't spam the owner's DMs
_last_notify = {}
NOTIFY_COOLDOWN = 600  # seconds


async def notify_owner(client, user_id, text):
    now = time.time()
    key = (user_id, text)
    if now - _last_notify.get(key, 0) < NOTIFY_COOLDOWN:
        return
    _last_notify[key] = now
    try:
        await client.send_message(user_id, text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Could not DM user {user_id} about a forwarding failure: {e}")


async def handle_flood(func, **kwargs):
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            return await func(**kwargs)
        except FloodWait as e:
            logger.warning(f"FloodWait detected. Sleeping for {e.value} seconds.")
            await asyncio.sleep(e.value + 1)
        except RPCError as e:
            logger.error(f"RPCError: {e}")
            retry_count += 1
            if retry_count >= max_retries:
                raise e
            await asyncio.sleep(2 ** retry_count)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            retry_count += 1
            if retry_count >= max_retries:
                raise e
            await asyncio.sleep(2 ** retry_count)

    raise Exception(f"Failed after {max_retries} retries")

async def forward_single_message(client, message, chat_id):
    try:
        kwargs = {
            "chat_id": chat_id,
            "from_chat_id": message.chat.id,
            "message_id": message.id,
        }

        if message.caption:
            kwargs["caption"] = message.caption
            if message.caption_entities:
                kwargs["caption_entities"] = message.caption_entities

        await handle_flood(client.copy_message, **kwargs)
        logger.info(f"Forwarded message {message.id} from {message.chat.id} to {chat_id}")
        return True, None
    except Exception as e:
        logger.error(f"Error forwarding message {message.id} to {chat_id}: {e}")
        return False, str(e)

async def forward_buffered_messages(client, messages, chat_id):
    try:
        sorted_messages = sorted(messages, key=lambda m: m.id)
        success_count = 0
        last_error = None

        for msg in sorted_messages:
            ok, err = await forward_single_message(client, msg, chat_id)
            if ok:
                success_count += 1
                await asyncio.sleep(0.3)
            else:
                last_error = err

        logger.info(f"Forwarded {success_count}/{len(messages)} buffered messages to {chat_id}")
        return success_count > 0, last_error

    except Exception as e:
        logger.error(f"Error forwarding buffered messages to {chat_id}: {e}")
        return False, str(e)

async def process_queue(client):
    while True:
        try:
            data = await message_queue.get()
            if not data:
                message_queue.task_done()
                continue

            message_or_list, target_ids, user_id = data
            failed_targets = []
            last_error = None

            for chat_id in target_ids:
                try:
                    success, err = await forward_buffered_messages(client, message_or_list, chat_id)

                    if not success:
                        failed_targets.append(chat_id)
                        last_error = err

                    await asyncio.sleep(0.5)

                except FloodWait as e:
                    logger.warning(f"FloodWait for chat {chat_id}. Waiting {e.value}s")
                    await asyncio.sleep(e.value + 1)
                    failed_targets.append(chat_id)
                except Exception as e:
                    logger.error(f"Error forwarding to {chat_id}: {e}")
                    failed_targets.append(chat_id)
                    last_error = str(e)

            if failed_targets:
                logger.info(f"Re-queuing for {len(failed_targets)} failed target(s)")
                # NEW: tell the owner why, instead of just retrying silently forever
                if user_id and last_error:
                    await notify_owner(
                        client,
                        user_id,
                        f"⚠️ I couldn't forward a message to {failed_targets}.\n"
                        f"Reason: {last_error}\n\n"
                        f"Most common cause: I'm not an admin there, or I'm missing "
                        f"the 'Post Messages' permission. Re-check with /set."
                    )
                await message_queue.put((message_or_list, failed_targets, user_id))

            message_queue.task_done()

        except Exception as e:
            logger.error(f"Queue processing error: {e}")
            message_queue.task_done()
            await asyncio.sleep(1)

async def start_processor(client):
    task = asyncio.create_task(process_queue(client))
    logger.info("Message processor started")
    return {'main_processor': task}

async def process_buffered_messages(source_chat_id):
    await asyncio.sleep(BUFFER_DELAY)

    buffer_key = source_chat_id
    if buffer_key not in message_buffer:
        return

    messages = message_buffer[buffer_key]
    if not messages:
        del message_buffer[buffer_key]
        if buffer_key in buffer_tasks:
            del buffer_tasks[buffer_key]
        return

    try:
        mappings = await database.get_all_targets_for_source(source_chat_id)
        if not mappings:
            del message_buffer[buffer_key]
            if buffer_key in buffer_tasks:
                del buffer_tasks[buffer_key]
            return

        message_count = len(messages)
        for mapping in mappings:
            target_ids = mapping.get('target_ids', [])
            user_id = mapping.get('user_id')
            if target_ids:
                await message_queue.put((messages.copy(), target_ids, user_id))
                logger.info(f"Queued buffered group ({message_count} files) from {source_chat_id} for {len(target_ids)} target(s)")

    except Exception as e:
        logger.error(f"Error processing buffered messages: {e}")
    finally:
        if buffer_key in message_buffer:
            del message_buffer[buffer_key]
        if buffer_key in buffer_tasks:
            del buffer_tasks[buffer_key]

@Client.on_message(
    filters.channel &
    (filters.video | filters.document | filters.photo | filters.audio) &
    ~filters.sticker &
    ~filters.animation,
    group=0
)
async def forward_content(client, message):
    try:
        source_chat_id = message.chat.id

        buffer_key = source_chat_id
        message_buffer[buffer_key].append(message)

        if buffer_key in buffer_tasks:
            buffer_tasks[buffer_key].cancel()

        buffer_tasks[buffer_key] = asyncio.create_task(
            process_buffered_messages(source_chat_id)
        )

    except Exception as e:
        logger.error(f"Error in forward_content handler: {e}", exc_info=True)
