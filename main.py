import discord
from discord.ext import commands
import os
from flask import Flask
from threading import Thread

# 1. Render için Web Sunucusu (Keep Alive)
app = Flask('')

@app.route('/')
def home():
    return "Bot Cevap Veriyor: Sistem Ayakta!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# 2. Discord Bot Ayarları
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Giriş Yapıldı: {bot.user.name}')

@bot.command()
async def ping(ctx):
    await ctx.send(f'Pong! Gecikme: {round(bot.latency * 1000)}ms')

# 3. Çalıştırma
if __name__ == "__main__":
    keep_alive() # Web sunucusunu başlat
    token = os.getenv('TOKEN') # Render panelinden 'TOKEN' adıyla ekle
    if token:
        bot.run(token)
    else:
        print("HATA: TOKEN bulunamadı!")
