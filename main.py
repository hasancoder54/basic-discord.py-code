import discord
from discord.ext import commands
import os, requests, datetime
from flask import Flask, render_template, request, redirect, session, url_for
from threading import Thread
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# --- 1. AYARLAR VE ÇEVRE DEĞİŞKENLERİ ---
TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

# Discord Bot Tanımı
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
    """Veritabanından ayarları çeker, yoksa varsayılan oluşturur."""
    try:
        data = await collection.find_one({"_id": str(guild_id)})
        if not data:
            default = {"_id": str(guild_id), "link_en": True, "yonetici_serbest": False}
            await collection.insert_one(default)
            return default
        return data
    except Exception as e:
        print(f"MongoDB Hatası: {e}")
        return {"link_en": True, "yonetici_serbest": False}

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
    await ctx.send(f"🚫 **{member.name}** yasaklandı.")

# --- 4. BOT OLAYLARI (KORUMA FİLTRESİ) ---
@bot.event
async def on_ready():
    print(f"✅ Bot Giriş Yaptı: {bot.user.name}")

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    
    setts = await get_db_settings(message.guild.id)
    is_admin = message.author.guild_permissions.administrator
    serbest = setts.get("yonetici_serbest", False)

    if setts.get("link_en") and "http" in message.content.lower():
        if not (is_admin and serbest):
            await message.delete()
            return await message.channel.send(f"⚠️ {message.author.mention}, linkler yasak!", delete_after=3)

    await bot.process_commands(message)

# --- 5. WEB PANEL (FLASK) ---
app = Flask(__name__)
app.secret_key = os.urandom(32)

@app.route('/')
def index():
    if 'token' in session:
        headers = {'Authorization': f"Bearer {session['token']}"}
        try:
            user = requests.get("https://discord.com/api/users/@me", headers=headers).json()
            guilds = requests.get("https://discord.com/api/users/@me/guilds", headers=headers).json()
            
            # GÜVENLİK: Sadece yönetici yetkisi (0x8) olanları listele
            admin_guilds = [g for g in guilds if (int(g['permissions']) & 0x8) == 0x8]
            for g in admin_guilds:
                g['bot_in'] = bot.get_guild(int(g['id'])) is not None
            
            return render_template('index.html', user=user, guilds=admin_guilds)
        except:
            session.clear()
            return redirect('/')
    return render_template('login.html')

@app.route('/login')
def login():
    url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify+guilds"
    return redirect(url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    data = {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
    r = requests.post("https://discord.com/api/oauth2/token", data=data)
    if r.status_code == 200:
        session['token'] = r.json().get('access_token')
        return redirect('/')
    return "Giriş başarısız, lütfen tekrar deneyin."

@app.route('/manage/<guild_id>', methods=['GET', 'POST'])
async def manage(guild_id):
    # GÜVENLİK ADIMI: Kullanıcı giriş yapmış mı?
    if 'token' not in session: return redirect('/login')
    
    try:
        headers = {'Authorization': f"Bearer {session['token']}"}
        guilds_r = requests.get("https://discord.com/api/users/@me/guilds", headers=headers).json()
        
        # GÜVENLİK ADIMI: URL'den elle girmeye çalışan kişi bu sunucuda YÖNETİCİ mi?
        is_admin = any(g['id'] == str(guild_id) and (int(g['permissions']) & 0x8) == 0x8 for g in guilds_r)
        
        if not is_admin:
            return "⛔ YETKİSİZ ERİŞİM: Bu sunucuyu yönetmek için yönetici yetkiniz olmalı!"

        guild_obj = bot.get_guild(int(guild_id))
        if not guild_obj: 
            return "🤖 Bot bu sunucuda ekli değil. Lütfen önce botu davet edin."

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
        # settings verisi None ise boş dict göndererek HTML'in çökmesini engelle
        return render_template('manage.html', settings=(settings or {}), guild=guild_obj)
        
    except Exception as e:
        print(f"HATA DETAYI (/manage): {e}")
        return f"Yönetim Paneli Hatası: {str(e)}"

# --- 6. ÇALIŞTIRMA ---
def run_web():
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    # Web sunucusunu ayrı bir kolda (Thread) başlat
    Thread(target=run_web).start()
    # Botu ana kolda başlat
    bot.run(TOKEN)
