import os
import asyncio
import threading
import unicodedata
import re
from flask import Flask
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env se presente localmente
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# --- FLASK WEB SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# --- MAPPE DI CONVERSIONE UNICODE (Mathematical Italic) ---
ITALIC_UPPER = {
    'A': '𝐴', 'B': '𝐵', 'C': '𝐶', 'D': '𝐷', 'E': '𝐸', 'F': '𝐹', 'G': '𝐺', 'H': '𝐻', 'I': '𝐼', 'J': '𝐽',
    'K': '𝐾', 'L': '𝐿', 'M': '𝑀', 'N': '𝑁', 'O': '𝑂', 'P': '𝑃', 'Q': '𝑄', 'R': '𝑅', 'S': '𝑆', 'T': '𝑇',
    'U': '𝑈', 'V': '𝑉', 'W': '𝑊', 'X': '𝑋', 'Y': '𝑌', 'Z': '𝑍'
}

ITALIC_LOWER = {
    'a': '𝑎', 'b': '𝑏', 'c': '𝑐', 'd': '𝑑', 'e': '𝑒', 'f': '𝑓', 'g': '𝑔', 'h': 'ℎ', 'i': '𝑖', 'j': '𝑗',
    'k': '𝑘', 'l': '𝑙', 'm': '𝑚', 'n': '𝑛', 'o': '𝑜', 'p': '𝑝', 'q': '𝓆', 'r': '𝑟', 's': '𝑠', 't': '𝑡',
    'u': '𝑢', 'v': '𝑣', 'w': '𝑤', 'x': '𝑥', 'y': '𝑦', 'z': '𝑧'
}

def convert_to_italic(text: str) -> str:
    """Converte una stringa di testo normale in Mathematical Italic."""
    result = []
    for char in text:
        if char in ITALIC_UPPER:
            result.append(ITALIC_UPPER[char])
        elif char in ITALIC_LOWER:
            result.append(ITALIC_LOWER[char])
        else:
            result.append(char)
    return "".join(result)

def clean_to_normal_text(text: str) -> str:
    """Converte i caratteri unicode complessi in testo normale A-Z, a-z, 0-9."""
    normalized = unicodedata.normalize('NFKD', text)
    cleaned = "".join([c for c in normalized if c.isalnum() or c in " -_"])
    return cleaned

def is_emoji(char: str) -> bool:
    """Controlla se un carattere è un'emoji o un simbolo grafico."""
    if char in "∫´〃〴-":
        return False
        
    code = ord(char)
    return (
        0x1F600 <= code <= 0x1F64F or
        0x1F300 <= code <= 0x1F5FF or
        0x1F680 <= code <= 0x1F6FF or
        0x1F1E6 <= code <= 0x1F1FF or
        0x2600 <= code <= 0x27BF or
        0xFE00 <= code <= 0xFE0F or
        0x1F900 <= code <= 0x1F9FF or
        0x1FA70 <= code <= 0x1FAFF
    )

# --- TRASFORMAZIONE PER I CANALI (Nuovo Stile: 🦹‍♀️〴𝐶ℎ𝑎𝑡-𝐴𝑚𝑚𝑖𝑛𝑖𝑠𝑡𝑟𝑎𝑧𝑖𝑜𝑛𝑒) ---
def transform_channel_name(old_name: str) -> str:
    # 1. Isola le emoji custom di Discord
    discord_emoji_pattern = re.compile(r'(<a?:\w+:\d+>)')
    discord_emojis = discord_emoji_pattern.findall(old_name)
    text_without_custom = discord_emoji_pattern.sub('', old_name)
    
    # 2. Isola le emoji standard
    standard_emojis = []
    text_chars_only = []
    for char in text_without_custom:
        if is_emoji(char):
            standard_emojis.append(char)
        else:
            text_chars_only.append(char)
            
    all_emojis = "".join(discord_emojis + standard_emojis).strip()
    remaining_text = "".join(text_chars_only).strip()
    
    # Rimuove vecchi e nuovi separatori dal testo pulito per evitare pasticci
    remaining_text = remaining_text.replace('∫', '').replace('´', '').replace('〃', '').replace('〴', '')
    
    # 3. Pulisce e converte il testo in Italic
    normal_text = clean_to_normal_text(remaining_text)
    words_split = normal_text.replace('-', ' ').replace('_', ' ').split()
    
    if not words_split:
        return all_emojis if all_emojis else old_name
        
    # Capitalizza e rende italic ogni parola
    italic_words = [convert_to_italic(word.capitalize()) for word in words_split]
    
    # Unisce le parole con il trattino "-" come richiesto (es: 𝐶ℎ𝑎𝑡-𝐴𝑚𝑚𝑖𝑛𝑖𝑠𝑡𝑟𝑎𝑧𝑖𝑜𝑛𝑒)
    formatted_text = "-".join(italic_words)
    
    # 4. Ricompone con il nuovo separatore "〴"
    if all_emojis:
        new_name = f"{all_emojis}〴{formatted_text}"
    else:
        new_name = formatted_text
        
    return new_name


# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'🤖 Bot Discord connesso come {bot.user}')

# --- COMANDO CANALI (AGGIORNATO CON CONTROLLO ANTI-ROTTURA) ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def cambiafont(ctx):
    """Rinomina i canali in formato Italic: 🦹‍♀️〴𝐶ℎ𝑎𝑡-𝐴𝑚𝑚𝑖𝑛𝑖𝑠𝑡𝑟𝑎𝑧𝑖𝑜𝑛𝑒 (Salta i canali già convertiti)"""
    await ctx.send("🔄 Rilevamento canali e conversione in corso... I canali già formattati verranno saltati.")
    
    success_count = 0
    skipped_count = 0
    
    for channel in ctx.guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue  # Ignora le categorie
            
        old_name = channel.name
        
        # --- CONTROLLO DI SICUREZZA ---
        # Se il canale contiene già il carattere speciale '〴', significa che è già a posto. Lo saltiamo.
        if "〴" in old_name:
            skipped_count += 1
            continue
            
        new_name = transform_channel_name(old_name)
        
        if old_name != new_name:
            try:
                await channel.edit(name=new_name)
                success_count += 1
                await asyncio.sleep(1.5)  # Delay anti rate-limit
            except Exception as e:
                print(f"Errore canale {old_name}: {e}")
                
    await ctx.send(f"✅ Conversione canali completata!\n🔹 Modificati con successo: {success_count} canali.\n🔸 Saltati perché già protetti/configurati: {skipped_count} canali.")

# --- COMANDO RUOLI (FONT NORMALE - Lasciato intatto per comodità) ---
@bot.command()
@commands.has_permissions(manage_roles=True)
async def cambiaruoli(ctx):
    """Rinomina i ruoli ripristinando il font normale, lasciando intatti simboli ed emoji (Ignora '▰')"""
    # ... (Il codice dei ruoli che pulisce solo il font rimane integrato ed è identico a prima per sicurezza)
    await ctx.send("🔄 Avvio la conversione del font dei ruoli...")
    success_count = 0
    for role in ctx.guild.roles:
        if role.is_default() or "▰" in role.name or role >= ctx.guild.me.top_role:
            continue
            
        result = []
        for char in role.name:
            normalized = unicodedata.normalize('NFKD', char)
            result.append(normalized if normalized.isalnum() else char)
        new_name = "".join(result)
        
        if role.name != new_name:
            try:
                await role.edit(name=new_name)
                success_count += 1
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"Errore ruolo {role.name}: {e}")
    await ctx.send(f"✅ Conversione ruoli completata! Modificati: {success_count} ruoli.")


if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERRORE: DISCORD_TOKEN mancante.")
        exit(1)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Server Flask avviato sulla porta {PORT}")

    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Errore d'avvio del bot: {e}")
