import discord
from discord.ext import commands
import os
import datetime
from flask import Flask
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient

# --- RENDER KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Yönetici Kilit Sistemi Aktif!"
def run(): app.run(host='0.0.0.0', port=10000)
def keep_alive():
    t = Thread(target=run)
    t.start()

# --- MONGODB & BOT AYARLARI ---
MONGO_URI = os.getenv("MONGO_URI")
cluster = AsyncIOMotorClient(MONGO_URI)
db = cluster["discord_bot"]
collection = db["ayarlar"]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Bellek içi ayarlar
guild_settings = {}

async def get_settings(guild_id):
    if guild_id not in guild_settings:
        data = await collection.find_one({"_id": guild_id})
        if not data:
            # YENİ: yonetici_serbest eklendi (Varsayılan False: Yöneticiler de kısıtlı)
            default = {"_id": guild_id, "link_en": True, "etiket_en": True, "yonetici_serbest": False}
            await collection.insert_one(default)
            guild_settings[guild_id] = default
        else:
            guild_settings[guild_id] = data
    return guild_settings[guild_id]

# --- OLAYLAR ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    ayarlar = await get_settings(message.guild.id)
    is_admin = message.author.guild_permissions.administrator
    serbest = ayarlar.get("yonetici_serbest", False)

    # LİNK ENGEL KONTROLÜ
    if ayarlar.get("link_en") and "http" in message.content.lower():
        # Eğer admin değilse VEYA (adminse ama serbest modu kapalıysa) SİL
        if not (is_admin and serbest):
            await message.delete()
            return await message.channel.send(f"🚫 {message.author.mention}, linkler yasak! (Yönetici Kilidi: {'KAPALI' if not serbest else 'AÇIK'})", delete_after=3)

    # ETİKET ENGEL KONTROLÜ
    if ayarlar.get("etiket_en") and ("@everyone" in message.content or "@here" in message.content):
        if not (is_admin and serbest):
            await message.delete()
            return await message.channel.send(f"⚠️ {message.author.mention}, etiket yasak!", delete_after=3)

    await bot.process_commands(message)

# --- YENİ YÖNETİCİ SERBEST KOMUTU ---
@bot.command(name="yönetici")
@commands.has_permissions(administrator=True)
async def yonetici_ayar(ctx, mod: str = None, durum: str = None):
    if mod == "serbest":
        val = True if durum == "aç" else False
        await collection.update_one({"_id": ctx.guild.id}, {"$set": {"yonetici_serbest": val}})
        guild_settings[ctx.guild.id]["yonetici_serbest"] = val
        status = "SERBEST ✅" if val else "KISITLI 🔒"
        await ctx.send(f"🛠️ Yönetici yetkileri şu an: **{status}**\n*(Not: Kapalıyken yöneticiler de link/etiket atamaz)*")
    else:
        await ctx.send("Kullanım: `!yönetici serbest aç` veya `!yönetici serbest kapat` ")

# --- GELİŞMİŞ YARDIM KOMUTU ---
@bot.command(name="yardım")
async def yardim(ctx):
    embed = discord.Embed(title="📜 Bot Komut Rehberi", color=0x2f3136, timestamp=datetime.datetime.now())
    embed.set_author(name=bot.user.name, icon_url=bot.user.avatar.url)
    
    embed.add_field(name="⚙️ Sistem Ayarları", value=(
        "`!ayar link aç/kapat` - Link engelini yönetir\n"
        "`!ayar etiket aç/kapat` - Etiket engelini yönetir\n"
        "`!yönetici serbest aç/kapat` - Yöneticilere izin verir/kaldırır"
    ), inline=False)

    embed.add_field(name="🛡️ Moderasyon", value=(
        "`!temizle [sayı]` - Mesajları süpürür\n"
        "`!kick/!ban/!mute` - Klasik cezalar"
    ), inline=False)

    embed.set_footer(text=f"Talep eden: {ctx.author.name}")
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def ayar(ctx, sistem: str = None, durum: str = None):
    s_map = {"link": "link_en", "etiket": "etiket_en"}
    if not sistem or sistem not in s_map:
        cur = await get_settings(ctx.guild.id)
        emb = discord.Embed(title="📊 Sistem Durumu", color=0x3498db)
        emb.add_field(name="Link Engel", value="✅" if cur["link_en"] else "❌")
        emb.add_field(name="Etiket Engel", value="✅" if cur["etiket_en"] else "❌")
        emb.add_field(name="Yönetici Serbest", value="🔓" if cur.get("yonetici_serbest") else "🔒")
        return await ctx.send(embed=emb)
    
    if durum in ["aç", "kapat"]:
        val = True if durum == "aç" else False
        await collection.update_one({"_id": ctx.guild.id}, {"$set": {s_map[sistem]: val}})
        guild_settings[ctx.guild.id][s_map[sistem]] = val
        await ctx.send(f"✅ {sistem.capitalize()} sistemi **{durum}ıldı**.")

# --- ÇALIŞTIRMA ---
if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv('TOKEN'))
