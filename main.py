import discord
from discord.ext import commands
import os, requests, datetime
from flask import Flask, render_template, request, redirect, session, url_for
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# --- 1. AYARLAR VE ÇEVRE DEĞİŞKENLERİ ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

# Bot Tanımlamaları
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# MongoDB Bağlantısı
cluster = AsyncIOMotorClient(MONGO_URI)
db = cluster["panel_db"]
collection = db["ayarlar"]

# --- 2. YARDIMCI FONKSİYONLAR ---
async def get_db_settings(guild_id):
    """Veritabanından sunucu ayarlarını çeker veya varsayılan oluşturur."""
    data = await collection.find_one({"_id": str(guild_id)})
    if not data:
        default = {"_id": str(guild_id), "link_en": True, "yonetici_serbest": False}
        await collection.insert_one(default)
        return default
    return data

# --- 3. BOT KOMUTLARI (MODERASYON) ---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def temizle(ctx, miktar: int = 10):
    await ctx.channel.purge(limit=miktar + 1)
    await ctx.send(f"🧹 **{miktar}** mesaj temizlendi!", delete_after=3)

@bot.command()
@commands.has_permissions(administrator=True)
async def ban(ctx, member: discord.Member, *, sebep="Belirtilmedi"):
    await member.ban(reason=sebep)
    await ctx.send(f"🚫 **{member.name}** yasaklandı. Sebep: {sebep}")

# --- 4. BOT OLAYLARI (KORUMA SİSTEMİ) ---
@bot.event
async def on_ready():
    print(f"✅ Bot Giriş Yaptı: {bot.user.name}")

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    # MongoDB'den ayarları çek
    setts = await get_db_settings(message.guild.id)
    is_admin = message.author.guild_permissions.administrator
    serbest = setts.get("yonetici_serbest", False)

    # Link Engel Kontrolü
    if setts.get("link_en") and "http" in message.content.lower():
        if not (is_admin and serbest):
            await message.delete()
            return await message.channel.send(f"⚠️ {message.author.mention}, linkler kapalı!", delete_after=3)

    await bot.process_commands(message)

# --- 5. WEB PANEL (FLASK) ---
app = Flask(__name__)
app.secret_key = os.urandom(32)

@app.route('/')
def index():
    try:
        if 'token' in session:
            headers = {'Authorization': f"Bearer {session['token']}"}
            user_r = requests.get("https://discord.com/api/users/@me", headers=headers)
            guilds_r = requests.get("https://discord.com/api/users/@me/guilds", headers=headers)
            
            if user_r.status_code != 200:
                session.clear()
                return redirect('/')

            user = user_r.json()
            guilds = guilds_r.json()
            
            # Sadece yönetici (0x8) olan sunucuları ayıkla
            admin_guilds = [g for g in guilds if (int(g['permissions']) & 0x8) == 0x8]
            for g in admin_guilds:
                g['bot_in'] = bot.get_guild(int(g['id'])) is not None
            
            return render_template('index.html', user=user, guilds=admin_guilds)
        return render_template('login.html')
    except Exception as e:
        return f"Ana Sayfa Hatası: {str(e)}"

@app.route('/login')
def login():
    # Güvenli URL formatı
    url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds"
    return redirect(url)

@app.route('/callback')
def callback():
    try:
        code = request.args.get('code')
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI
        }
        r = requests.post("https://discord.com/api/oauth2/token", data=data)
        if r.status_code == 200:
            session['token'] = r.json().get('access_token')
            return redirect('/')
        return f"Discord Hatası: {r.text}"
    except Exception as e:
        return f"Bağlantı Hatası: {str(e)}"

@app.route('/manage/<guild_id>', methods=['GET', 'POST'])
async def manage(guild_id):
    if 'token' not in session: return redirect('/login')
    
    try:
        guild_obj = bot.get_guild(int(guild_id))
        if not guild_obj: return "Hata: Bot bu sunucuda değil!"

        if request.method == 'POST':
            l_en = True if request.form.get('link_en') else False
            y_s = True if request.form.get('yonetici_s') else False
            await collection.update_one(
                {"_id": str(guild_id)}, 
                {"$set": {"link_en": l_en, "yonetici_serbest": y_s}}, 
                upsert=True
            )
            return redirect(f'/manage/{guild_id}?success=1')
        
        settings = await get_db_settings(guild_id)
        return render_template('manage.html', settings=settings, guild=guild_obj)
    except Exception as e:
        return f"Yönetim Hatası: {str(e)}"

# --- 6. ÇALIŞTIRMA ---
def run_web():
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    Thread(target=run_web).start()
    bot.run(TOKEN)
