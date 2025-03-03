import json
import sqlite3
import aiohttp
from pyrogram import Client, filters
import sys, os
import asyncio
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
##############################################################################################
DB_FILE = "config.db"
API_KEY = "#########################"    #Ключ нейросети
MODEL = "deepseek/deepseek-r1"
###############################################################################################


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_channel TEXT UNIQUE,
                target_channel TEXT,
                auto_mode INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("PRAGMA table_info(channels)")
        columns = [col[1] for col in cursor.fetchall()]
        if "auto_mode" not in columns:
            cursor.execute("ALTER TABLE channels ADD COLUMN auto_mode INTEGER DEFAULT 0")
        cursor.execute("INSERT OR IGNORE INTO channels (id, donor_channel, target_channel, auto_mode) VALUES (1, '', '', 0)")
        conn.commit()

def set_target_channel(channel):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE channels SET target_channel = ? WHERE id = 1", (channel,))
        conn.commit()


def get_channel(column):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {column} FROM channels WHERE id = 1")
        result = cursor.fetchone()
    return result[0] if result else ""

def set_auto_mode(mode):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE channels SET auto_mode = ? WHERE id = 1", (mode,))
        conn.commit()

def get_auto_mode():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT auto_mode FROM channels WHERE id = 1")
        result = cursor.fetchone()
    return result[0] if result else 0

def add_donor_channel(channel):
    global donor_channels
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO channels (donor_channel) VALUES (?)", (channel,))
        conn.commit()
    donor_channels = get_donor_channels() 



def remove_donor_channel(channel):
    global donor_channels
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE donor_channel = ?", (channel,))
        conn.commit()
    donor_channels = get_donor_channels()  

def get_donor_channels():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT donor_channel FROM channels")
        return [row[0] for row in cursor.fetchall()]

init_db()
donor_channels = get_donor_channels()


donor_channel = get_channel("donor_channel")
target_channel = get_channel("target_channel")
auto_mode = get_auto_mode()
moderation_group_id = ##################
#######################################################################################################################
app = Client("my_session", api_id=########, api_hash="############")
#######################################################################################################################
async def chat_stream(prompt):
    if not prompt.strip():  
        logger.warning("⚠️ chat_stream() получил пустой prompt, обработка пропущена.")
        return ""

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": (
                "Перефразируй текст, удали ссылки и названия Telegram-каналов. "
                "Отправь только сам текст без заголовков, пометок или пояснений. "
                "Текст только на русском (не считая всяких названий). " + prompt
            )
        }],
        "stream": True
    }

    logger.info(f"🔄 Отправка запроса в OpenRouter: {data}")

    async with aiohttp.ClientSession() as session:
        async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data) as response:
            if response.status != 200:
                logger.error(f"❌ Ошибка API: {response.status}, текст ошибки: {await response.text()}")
                return ""

            full_response = []
            async for chunk in response.content.iter_any():
                if chunk:
                    try:
                        for line in chunk.decode('utf-8').split('\n'):
                            if line.startswith("data: "):
                                chunk_json = json.loads(line[6:])
                                content = chunk_json.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if content:
                                    full_response.append(content)
                    except Exception as e:
                        logger.error(f"❌ Ошибка при обработке ответа API: {e}")

            result = ''.join(full_response).strip()
            logger.info(f"✅ Ответ от OpenRouter: {result}")

            return result



@app.on_message(filters.command("set_target") & filters.chat(moderation_group_id))
async def set_target(client, message):
    if len(message.command) < 2:
        await message.reply("Использование: /set_target <channel_id>")
        return
    set_target_channel(message.command[1])
    await message.reply(f"Канал для публикации изменён на {message.command[1]}")


@app.on_message(filters.command("auto_start") & filters.chat(moderation_group_id))
async def auto_start(client, message):
    global auto_mode
    set_auto_mode(1)
    auto_mode = 1
    await message.reply("Автоматическое копирование сообщений БЕЗ согласия запущено.")

@app.on_message(filters.command("auto_stop") & filters.chat(moderation_group_id))
async def auto_stop(client, message):
    global auto_mode
    set_auto_mode(0)
    auto_mode = 0
    await message.reply("Автоматическое копирование остановлено. Теперь требуется одобрение перед публикацией.")



from pyrogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument
@app.on_message(filters.chat(donor_channels))
async def forward_from_donor(client, message):
    try:
        text_content = message.caption or ""  

        final_text = text_content
        if text_content.strip():
            logger.info(f"Исходный текст: {text_content}")
            rephrased_text = await chat_stream(text_content)
            logger.info(f"Перефразированный текст: {rephrased_text}")
            final_text = rephrased_text.strip() or text_content

        target = target_channel if auto_mode else moderation_group_id

        
        if message.media_group_id:
            media_group = []
            media_messages = await client.get_media_group(message.chat.id, message.id) 
            for msg in media_messages:
                if msg.photo:
                    media_group.append(InputMediaPhoto(msg.photo.file_id))
                elif msg.video:
                    media_group.append(InputMediaVideo(msg.video.file_id))

            if media_group:
                media_group[0].caption = final_text  
                await client.send_media_group(target, media_group)
            return  

        
        if message.photo:
            await client.send_photo(target, message.photo.file_id, caption=final_text)
        elif message.video:
            await client.send_video(target, message.video.file_id, caption=final_text)
        elif message.document:
            await client.send_document(target, message.document.file_id, caption=final_text)
        elif message.audio:
            await client.send_audio(target, message.audio.file_id, caption=final_text)
        elif message.voice:
            await client.send_voice(target, message.voice.file_id, caption=final_text)
        elif message.text:
            logger.info(f"Исходный текст: {message.text}")

           
            rephrased_text = await chat_stream(message.text)
            logger.info(f"Перефразированный текст: {rephrased_text}")

            
            final_text = rephrased_text.strip() or message.text  

            await client.send_message(target, final_text)  


    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения из канала-донора: {e}")




@app.on_message(filters.chat(moderation_group_id) & filters.text & filters.regex("одобрено"))
async def approve_message(client, message):
    replied_msg = message.reply_to_message
    if not replied_msg or not target_channel:
        return

    try:
        
        if replied_msg.media_group_id:
            media_group = []
            media_messages = await client.get_media_group(moderation_group_id, replied_msg.id)

            for msg in media_messages:
                if msg.photo:
                    media_group.append(InputMediaPhoto(msg.photo.file_id))
                elif msg.video:
                    media_group.append(InputMediaVideo(msg.video.file_id))
                elif msg.document:
                    media_group.append(InputMediaDocument(msg.document.file_id))

            if media_group:
                
                media_group[0].caption = replied_msg.caption if replied_msg.caption else ""
                await client.send_media_group(target_channel, media_group)
            return  

        
        await replied_msg.copy(target_channel)

    except Exception as e:
        logger.error(f"Ошибка при публикации сообщения: {e}")



@app.on_message(filters.command("show_donor") & filters.chat(moderation_group_id))
async def show_donor_channel(client, message):
    donors = get_donor_channels()  
    if donors:
        await message.reply("Донорские каналы:\n" + "\n".join(donors))
    else:
        await message.reply("Каналы-доноры не установлены.")


@app.on_message(filters.command("show_target") & filters.chat(moderation_group_id))
async def show_target_channel(client, message):
    target_channel = get_channel("target_channel")
    await message.reply(f"Текущий канал для публикации: {target_channel}" if target_channel else "Канал для публикации не установлен.")

@app.on_message(filters.command("add_donor") & filters.chat(moderation_group_id))
async def add_donor(client, message):
    if len(message.command) < 2:
        await message.reply("Использование: /add_donor <channel_id>")
        return
    donor_channel = message.command[1]
    donors = get_donor_channels()
    if len(donors) >= 8:
        await message.reply("Нельзя добавить больше 8 донорских каналов.")
        return
    add_donor_channel(donor_channel)
    await message.reply(f"Добавлен канал-донор: {donor_channel}")

@app.on_message(filters.command("remove_donor") & filters.chat(moderation_group_id))
async def remove_donor(client, message):
    if len(message.command) < 2:
        await message.reply("Использование: /remove_donor <channel_id>")
        return
    remove_donor_channel(message.command[1])
    await message.reply(f"Канал-донор удалён: {message.command[1]}")

@app.on_message(filters.command("list_donors") & filters.chat(moderation_group_id))
async def list_donors(client, message):
    donors = get_donor_channels()
    await message.reply("Донорские каналы:\n" + "\n".join(donors) if donors else "Нет добавленных доноров.")

@app.on_message(filters.command("restart") & filters.chat(moderation_group_id))
async def restart_bot(client, message):
    await message.reply("♻ Перезапуск бота...")
    logger.info("♻ Перезапуск бота...")

    asyncio.create_task(shutdown_and_restart(client))

async def shutdown_and_restart(client):
    await client.stop()  
    os.execl(sys.executable, sys.executable, *sys.argv) 


print("Бот запущен и слушает новые сообщения...")
app.run()