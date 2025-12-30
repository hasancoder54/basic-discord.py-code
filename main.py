import discord
from discord.ext import commands
import os, requests, datetime
from flask import Flask, render_template, request, redirect, session, url_for
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import timedelta

# --- 1. AYARLAR VE BAĞLANTILAR ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

db = AsyncIOMotorClient(MONGO_URI)["panel_db"]
collection = db["ayarlar"]

# --- 2. YARDIMCI FONKSİYONLAR ---
async def get_db_settings(guild_id):
    data = await collection.find_one({"_id": str(guild_id)})
    if not data:
        default = {"_id": str(guild_id), "link_en": True, "yonetici_serbest": False}
        await collection.insert_one(default)
        return default
    return data

def parse_time(time_str: str):
    unit = time_str[-1]
    amount = int(time_str[:-1])
    if unit == "m": return timedelta(minutes=amount)
    if unit == "h": return timedelta(hours=amount)
    if unit == "d": return timedelta(days=amount)
    return None

# --- 3. BOT KOMUTLARI (MODERASYON & EĞLENCE) ---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def temizle(ctx, miktar: int = 10):
    await ctx.channel.purge(limit=miktar + 1)
    await ctx.send(f"✅ {miktar} mesaj süpürüldü.", delete_after=2)

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, sebep="Yok"):
    await member.kick(reason=sebep)
    await ctx.send(f"👢 {member.name} sunucudan atıldı.")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, sebep="Yok"):
    await member.ban(reason=sebep)
    await ctx.send(f"🚫 {member.name} yasaklandı.")

@bot.command()
async def yardim(ctx):
    emb = discord.Embed(title="📜 Komut Menüsü", color=0x7289da)
    emb.add_field(name="🛡️ Moderasyon", value="`!temizle`, `!kick`, `!ban`", inline=False)
    emb.add_field(name="🌐 Panel", value=f"[Web Paneli]({REDIRECT_URI.replace('/callback','')})", inline=False)
    await ctx.send(embed=emb)

# --- 4. BOT OLAYLARI (FİLTRE SİSTEMİ) ---
@bot.event
async def on_ready():
    print(f"Bot Aktif: {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    setts = await get_db_settings(message.guild.id)
    is_admin = message.author.guild_permissions.administrator
    serbest = setts.get("yonetici_serbest", False)

    if setts.get("link_en") and "http" in message.content.lower():
        if not (is_admin and serbest):
            await message.delete()
            return await message.channel.send(f"🚫 {message.author.mention}, linkler kapalı!", delete_after=3)

    await bot.process_commands(message)

# --- 5. WEB PANEL (FLASK) ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/')
def index():
    if 'token' in session:
        headers = {'Authorization': f"Bearer {session['token']}"}
        user = requests.get("https://discord.com/api/users/@me", headers=headers).json()
        guilds = requests.get("https://discord.com/api/users/@me/guilds", headers=headers).json()
        admin_guilds = [g for g in guilds if (int(g['permissions']) & 0x8) == 0x8]
        for g in admin_guilds: g['bot_in'] = bot.get_guild(int(g['id'])) is not None
        return render_template('index.html', user=user, guilds=admin_guilds)
    return '<center><h1>Hasan Bot Panel</h1><a href="/login">Giriş Yap</a></center>'

@app.route('/login')
def login():
    url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI.replace(':', '%3A').replace('/', '%2F')}&response_type=code&scope=identify+guilds"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    data = {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
    r = requests.post("https://discord.com/api/oauth2/token", data=data)
    session['token'] = r.json().get('access_token')
    return redirect('/')

@app.route('/manage/<guild_id>', methods=['GET', 'POST'])
async def manage(guild_id):
    if 'token' not in session: return redirect('/')
    try:
        guild_obj = bot.get_guild(int(guild_id))
        if request.method == 'POST':
            link_en = True if request.form.get('link_en') else False
            yonetici_s = True if request.form.get('yonetici_s') else False
            await collection.update_one({"_id": str(guild_id)}, {"$set": {"link_en": link_en, "yonetici_serbest": yonetici_s}}, upsert=True)
            return redirect(f'/manage/{guild_id}')
        settings = await get_db_settings(guild_id)
        return render_template('manage.html', settings=settings, guild=guild_obj)
    except Exception as e: return str(e)

# --- 6. ÇALIŞTIRMA ---
def run_web(): app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    Thread(target=run_web).start()
    bot.run(TOKEN)
