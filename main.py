import discord
from discord.ext import commands
import os
import random
import datetime
from datetime import timedelta
from flask import Flask
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient

# --- 1. KEEP ALIVE (Render'da botun kapanmaması için) ---
app = Flask('')
@app.route('/')
def home(): return "Sistem 7/24 Aktif!"

def run(): app.run(host='0.0.0.0', port=10000)
def keep_alive():
    t = Thread(target=run)
    t.start()

# --- 2. MONGODB BAĞLANTISI ---
# Değişkenler: MONGO_URI
MONGO_URI = os.getenv("MONGO_URI")
cluster = AsyncIOMotorClient(MONGO_URI)
db = cluster["discord_bot"]
collection = db["ayarlar"]

# --- 3. BOT AYARLARI ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Bellek içi ayar tutucu (Performans için)
guild_settings = {}

async def get_settings(guild_id):
    if guild_id not in guild_settings:
        data = await collection.find_one({"_id": guild_id})
        if not data:
            default = {"_id": guild_id, "link_en": True, "etiket_en": True}
            await collection.insert_one(default)
            guild_settings[guild_id] = default
        else:
            guild_settings[guild_id] = data
    return guild_settings[guild_id]

# --- 4. OLAYLAR (Events) ---
@bot.event
async def on_ready():
    print(f'Giriş Yapıldı: {bot.user.name}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="!yardım"))

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    ayarlar = await get_settings(message.guild.id)
    
    # Link Engel
    if ayarlar.get("link_en") and "http" in message.content.lower():
        if not message.author.guild_permissions.manage_messages:
            await message.delete()
            return await message.channel.send(f"🚫 {message.author.mention}, link yasak!", delete_after=3)

    # Etiket Engel
    if ayarlar.get("etiket_en") and ("@everyone" in message.content or "@here" in message.content):
        if not message.author.guild_permissions.mention_everyone:
            await message.delete()
            return await message.channel.send(f"⚠️ {message.author.mention}, etiket yasak!", delete_after=3)

    await bot.process_commands(message)

# --- 5. KOMUTLAR ---
@bot.command()
@commands.has_permissions(administrator=True)
async def ayar(ctx, sistem: str = None, durum: str = None):
    s_map = {"link": "link_en", "etiket": "etiket_en"}
    if not sistem or sistem not in s_map:
        cur = await get_settings(ctx.guild.id)
        emb = discord.Embed(title="⚙️ Sunucu Ayarları", color=0x2ecc71)
        emb.add_field(name="Link Engel", value="✅" if cur["link_en"] else "❌")
        emb.add_field(name="Etiket Engel", value="✅" if cur["etiket_en"] else "❌")
        return await ctx.send(embed=emb)
    
    if durum in ["aç", "kapat"]:
        val = True if durum == "aç" else False
        await collection.update_one({"_id": ctx.guild.id}, {"$set": {s_map[sistem]: val}})
        guild_settings[ctx.guild.id][s_map[sistem]] = val
        await ctx.send(f"✅ {sistem.capitalize()} ayarı {durum}ıldı.")

@bot.command()
async def yardim(ctx):
    emb = discord.Embed(title="📜 Komut Menüsü", color=0x3498db)
    emb.add_field(name="⚙️ Ayar", value="`!ayar link aç/kapat`\n`!ayar etiket aç/kapat`", inline=False)
    emb.add_field(name="🛡️ Moderasyon", value="`!temizle`, `!kick`, `!ban`, `!mute` ", inline=False)
    emb.add_field(name="🎉 Eğlence", value="`!ask-olcer`, `!avatar`, `!ping` ", inline=False)
    await ctx.send(embed=emb)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def temizle(ctx, m: int = 10):
    await ctx.channel.purge(limit=m+1)
    await ctx.send(f"✅ {m} mesaj silindi.", delete_after=2)

@bot.command()
async def ping(ctx): await ctx.send(f'🏓 `{round(bot.latency * 1000)}ms`')

# --- 6. ÇALIŞTIRMA ---
if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv('TOKEN'))
