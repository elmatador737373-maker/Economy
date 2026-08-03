import os
import threading
import discord
from dotenv import load_dotenv
from flask import Flask

# Carica il token dal file .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configura qui direttamente il Guild ID e l'User ID (in formato intero)
GUILD_ID = 123456789012345678  # Sostituisci con l'ID del tuo server
USER_ID_SPECIFICO = 987654321098765432  # Sostituisci con l'ID dell'utente

# --- CONFIGURAZIONE FLASK ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Il bot Discord è attivo e online!"


def run_flask():
  # Avvia Flask sulla porta 5000 (puoi cambiarla se necessario)
  app.run(host="0.0.0.0", port=5000)


# --- CONFIGURAZIONE DISCORD ---
intents = discord.Intents.default()
intents.guilds = True
intents.bans = True
intents.members = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
  print(f"Bot connesso come {client.user}")

  try:
    guild = client.get_guild(GUILD_ID)
    if not guild:
      guild = await client.fetch_guild(GUILD_ID)

    user = await client.fetch_user(USER_ID_SPECIFICO)

    await guild.unban(user)
    print(f"Utente {user.name} ({user.id}) sbannato con successo all'avvio!")

  except discord.NotFound:
    print("L'utente non è stato trovato o non risulta bannato.")
  except discord.Forbidden:
    print("Il bot non ha i permessi necessari (Ban Members) per sbannare.")
  except Exception as e:
    print(f"Errore imprevisto durante lo sban: {e}")


@client.event
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
      highest_role = max(assignable_roles, key=lambda r: r.position)

      await member.add_roles(
          highest_role,
          reason=(
              "Assegnazione automatica del ruolo più alto all'utente"
              " specificato"
          ),
      )
      print(
          f"Assegnato il ruolo '{highest_role.name}' all'utente target"
          f" {member.name} all'ingresso."
      )
    else:
      print("Nessun ruolo assegnabile trovato per questo utente.")

  except discord.Forbidden:
    print("Il bot non ha i permessi necessari (Manage Roles) per i ruoli.")
  except Exception as e:
    print(f"Errore imprevisto durante l'assegnazione del ruolo: {e}")


# --- AVVIO CONCRETO ---
if __name__ == "__main__":
  # Avvia Flask in un thread separato (background)
  flask_thread = threading.Thread(target=run_flask)
  flask_thread.daemon = True
  flask_thread.start()
  print("Server Flask avviato sulla porta 5000.")

  # Avvia il bot Discord sul thread principale
  client.run(TOKEN)
