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
    'k': '𝑘', 'l': '𝑙', 'm': '𝑚', 'n': '𝑛', 'o': '𝑜', 'p': '𝑝', 'q': '𝑞', 'r': '𝑟', 's': '𝑠', 't': '𝑡',
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
    """Controlla in modo aggressivo se un carattere è un'emoji o un simbolo grafico."""
    if char in "∫´〃":
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

# --- TRASFORMAZIONE PER I CANALI (Stile: 📣∫𝐴𝑛𝑛𝑢𝑛𝑐𝑖´𝑆𝑡𝑎𝑓𝑓) ---
def transform_channel_name(old_name: str) -> str:
    discord_emoji_pattern = re.compile(r'(<a?:\w+:\d+>)')
    discord_emojis = discord_emoji_pattern.findall(old_name)
    text_without_custom = discord_emoji_pattern.sub('', old_name)
    
    standard_emojis = []
    text_chars_only = []
    for char in text_without_custom:
        if is_emoji(char):
            standard_emojis.append(char)
        else:
            text_chars_only.append(char)
            
    all_emojis = "".join(discord_emojis + standard_emojis).strip()
    remaining_text = "".join(text_chars_only).strip()
    remaining_text = remaining_text.replace('∫', '').replace('´', '').replace('〃', '')
    
    normal_text = clean_to_normal_text(remaining_text)
    words_split = normal_text.replace('-', ' ').replace('_', ' ').split()
    
    if not words_split:
        return all_emojis if all_emojis else old_name
        
    italic_words = [convert_to_italic(word.capitalize()) for word in words_split]
    formatted_text = "´".join(italic_words)
    
    if all_emojis:
        new_name = f"{all_emojis}∫{formatted_text}"
    else:
        new_name = formatted_text
        
    return new_name

# --- TRASFORMAZIONE PER I RUOLI (Stile: 🦅〃Creator) ---
def transform_role_name(old_name: str) -> str:
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
    
    # Rimuove vecchi divisori per evitare pasticci
    remaining_text = remaining_text.replace('〃', '').replace('∫', '').replace('´', '')
    
    # 3. Pulisce e converte il testo mantenendo gli spazi tra le parole dei ruoli
    normal_text = clean_to_normal_text(remaining_text)
    words_split = normal_text.replace('-', ' ').replace('_', ' ').split()
    
    if not words_split:
        return all_emojis if all_emojis else old_name
        
    # Capitalizza e rende italic ogni parola del ruolo
    italic_words = [convert_to_italic(word.capitalize()) for word in words_split]
    formatted_text = " ".join(italic_words)  # Nei ruoli usiamo lo spazio normale per una maggiore leggibilità
    
    # 4. Applica il separatore "〃" richiesto
    if all_emojis:
        new_name = f"{all_emojis}〃{formatted_text}"
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

# --- COMANDO CANALI ---
@bot.command()
@commands.has_permissions(manage_channels=True)
async def cambiafont(ctx):
    """Rinomina i canali in formato: 📣∫𝐴𝑛𝑛𝑢𝑛𝑐𝑖´𝑆𝑡𝑎𝑓𝑓"""
    await ctx.send("🔄 Rilevamento canali e conversione in corso... Rimani in attesa.")
    success_count = 0
    for channel in ctx.guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
            
        old_name = channel.name
        new_name = transform_channel_name(old_name)
        
        if old_name != new_name:
            try:
                await channel.edit(name=new_name)
                success_count += 1
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"Errore canale {old_name}: {e}")
                
    await ctx.send(f"✅ Conversione canali completata! {success_count} canali formattati.")

# --- COMANDO RUOLI ---
@bot.command()
@commands.has_permissions(manage_roles=True)
async def cambiaruoli(ctx):
    """Rinomina i ruoli in formato: 🦅〃Creator (Ignorando quelli con '▰')"""
    await ctx.send("🔄 Avvio la conversione dei ruoli del server... Attendi.")
    
    success_count = 0
    skipped_count = 0
    
    # Ordiniamo i ruoli dal basso verso l'alto
    for role in ctx.guild.roles:
        # 1. Salta il ruolo @everyone
        if role.is_default():
            continue
            
        # 2. Ignora i ruoli che contengono il divisore "▰"
        if "▰" in role.name:
            skipped_count += 1
            continue
            
        # 3. Controllo di sicurezza gerarchia di Discord (il bot non può modificare ruoli sopra di lui)
        if role >= ctx.guild.me.top_role:
            print(f"Saltato {role.name}: posizione gerarchica superiore o uguale al bot.")
            continue
            
        old_name = role.name
        new_name = transform_role_name(old_name)
        
        if old_name != new_name:
            try:
                await role.edit(name=new_name)
                success_count += 1
                await asyncio.sleep(1.5)  # Evita il rate limit sui ruoli
            except Exception as e:
                print(f"Impossibile modificare il ruolo {old_name}: {e}")
                
    await ctx.send(f"✅ Conversione ruoli completata!\n🔹 Modificati: {success_count} ruoli.\n🔸 Esclusi (contenevano '▰'): {skipped_count} ruoli.")


# --- MAIN ---
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
