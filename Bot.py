import threading
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands, tasks

# --- CONFIGURAZIONE SERVER FLASK (Per mantenere il bot attivo) ---
app = Flask("")


@app.route("/")
def home():
  return "Il bot Discord dello staff è online e attivo!"


def run_flask():
  app.run(host="0.0.0.0", port=8080)


def keep_alive():
  t = threading.Thread(target=run_flask)
  t.daemon = True
  t.start()


# --- CONFIGURAZIONE BOT DISCORD ---
intents = discord.Intents.default()
intents.members = True  # Necessario per leggere i membri e i ruoli del server

bot = commands.Bot(command_prefix="!", intents=intents)

# Lista degli ID dei ruoli dello staff forniti
STAFF_ROLE_IDS = [
    1455297914455986408,
    1455297915726598370,
    1500051309808582778,
    1531229874046631947,
    1500051544551456861,
    1500051724877168680,
    1455297916708192373,
    1531247431814217828,
    1455297933196001411,
]

# Variabili globali per memorizzare canale e messaggio da aggiornare in tempo reale
TARGET_CHANNEL_ID = 0
TARGET_MESSAGE_ID = 0


async def genera_embed_staff(guild: discord.Guild) -> discord.Embed:
  """Funzione che calcola la gerarchia prendendo per ogni utente

  esclusivamente il ruolo staff più alto che possiede.
  """
  # 1. Otteniamo gli oggetti ruolo reali e li ordiniamo per posizione (dal più alto al più basso)
  roles = [guild.get_role(r_id) for r_id in STAFF_ROLE_IDS]
  roles = [r for r in roles if r is not None]
  roles.sort(key=lambda r: r.position, reverse=True)

  # 2. Inizializziamo il dizionario per raccogliere i membri per ciascun ID ruolo
  role_members = {r.id: [] for r in roles}

  # 3. Scansioniamo tutti i membri del server
  async for member in guild.fetch_members(limit=None):
    if member.bot:
      continue

    # Troviamo quali ruoli della lista possiede questo utente
    user_staff_roles = [r for r in member.roles if r.id in STAFF_ROLE_IDS]

    if user_staff_roles:
      # Ordiniamo i suoi ruoli staff per posizione (dal più alto al più basso)
      user_staff_roles.sort(key=lambda r: r.position, reverse=True)
      # Prendiamo SOLO il ruolo più alto
      highest_role = user_staff_roles[0]

      # Aggiungiamo il membro alla lista del suo ruolo più alto
      if highest_role.id in role_members:
        role_members[highest_role.id].append(member.mention)

  # 4. Creazione dell'Embed finale
  embed = discord.Embed(
      title="👑 Gerarchia dello Staff",
      description=(
          "Elenco aggiornato in tempo reale dello staff suddiviso per ruolo"
          " principale."
      ),
      color=discord.Color.blue(),
      timestamp=discord.utils.utcnow(),  # Mostra l'orario dell'ultimo aggiornamento
  )

  for role in roles:
    members = role_members.get(role.id, [])
    value_text = ", ".join(members) if members else "*Nessun membro*"
    # Utilizziamo role.mention per taggare direttamente il ruolo nel titolo
    embed.add_field(name=f"➤ {role.mention}", value=value_text, inline=False)

  return embed


# --- TASK DI AGGIORNAMENTO AUTOMATICO IN TEMPO REALE ---
@tasks.loop(minutes=10)
async def aggiorna_messaggio_automatico():
  if not bot.is_ready():
    return

  if TARGET_CHANNEL_ID == 0 or TARGET_MESSAGE_ID == 0:
    return

  for guild in bot.guilds:
    try:
      channel = guild.get_channel(TARGET_CHANNEL_ID)
      if channel:
        message = await channel.fetch_message(TARGET_MESSAGE_ID)
        new_embed = await genera_embed_staff(guild)
        await message.edit(embed=new_embed)
        print(f"[{discord.utils.utcnow()}] Embed staff aggiornato con successo!")
    except discord.NotFound:
      print("Impossibile trovare il messaggio o il canale da aggiornare.")
    except Exception as e:
      print(f"Errore durante l'aggiornamento automatico: {e}")


@bot.event
async def on_ready():
  print(f"Bot connesso come {bot.user}")
  try:
    synced = await bot.tree.sync()
    print(f"Sincronizzati {len(synced)} comandi slash.")
  except Exception as e:
    print(e)

  # Avvia il task di aggiornamento automatico
  if not aggiorna_messaggio_automatico.is_running():
    aggiorna_messaggio_automatico.start()


# --- COMANDO SLASH PER GENERARE IL MESSAGGIO ---
@bot.tree.command(
    name="staff",
    description=(
        "Invia la gerarchia dello staff e avvia l'aggiornamento in tempo reale."
    ),
)
@app_commands.default_permissions(administrator=True)
async def staff_command(interaction: discord.Interaction):
  await interaction.response.defer(thinking=True)

  guild = interaction.guild
  embed = await genera_embed_staff(guild)

  # Invia l'embed nel canale in cui è stato eseguito il comando
  msg = await interaction.followup.send(embed=embed)

  # Imposta dinamicamente i riferimenti per l'aggiornamento automatico
  global TARGET_CHANNEL_ID, TARGET_MESSAGE_ID
  TARGET_CHANNEL_ID = interaction.channel.id
  TARGET_MESSAGE_ID = msg.id

  await interaction.followup.send(
      "✅ Gerarchia generata con successo! Questo messaggio si aggiornerà"
      " automaticamente in tempo reale.",
      ephemeral=True,
  )


# --- AVVIO DEL BOT E DEL SERVER FLASK ---
if __name__ == "__main__":
  # Avvia Flask in background
  keep_alive()
  # Avvia il bot Discord (inserisci qui il tuo token)
  bot.run("IL_TUO_TOKEN_DEL_BOT")
