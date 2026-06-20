from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from PIL import Image
import requests
import random
import json
import os
import time
import datetime

TOKEN = os.getenv("TOKEN")

CHAT_ID = -1003655667215
TOPIC_ID = 6

# Orario spawn automatico (ora italiana)
SPAWN_ORA_INIZIO = 6   # 06:00
SPAWN_ORA_FINE = 24    # 24:00 (mezzanotte)

# Intervallo base in secondi (3 ore) con variazione ±1 ora
SPAWN_BASE_SECONDI = 3 * 3600
SPAWN_VARIAZIONE_SECONDI = 1 * 3600

current_pokemon = None
current_pokemon_image = None
current_is_shiny = False
last_attempts = {}

POKEDEX_FILE = "pokedex.json"


# ─── Pokedex helpers ──────────────────────────────────────────────────────────

def carica_pokedex():
    if not os.path.exists(POKEDEX_FILE):
        return {}
    with open(POKEDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salva_pokedex(dati):
    with open(POKEDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=4, ensure_ascii=False)


def crea_utente_se_manca(dati, user_id):
    user_id = str(user_id)
    if user_id not in dati:
        dati[user_id] = {
            "pokemon": [],
            "catture_totali": 0,
            "shiny": 0
        }
    return user_id


def registra_cattura(user_id, pokemon, shiny=False):
    dati = carica_pokedex()
    user_id = crea_utente_se_manca(dati, user_id)

    chiave = pokemon + "_shiny" if shiny else pokemon
    nuovo = chiave not in dati[user_id]["pokemon"]

    if nuovo:
        dati[user_id]["pokemon"].append(chiave)

    dati[user_id]["catture_totali"] += 1

    if shiny:
        dati[user_id]["shiny"] += 1

    salva_pokedex(dati)
    return nuovo


def ottieni_profilo(user_id):
    dati = carica_pokedex()
    return dati.get(str(user_id), {
        "pokemon": [],
        "catture_totali": 0,
        "shiny": 0
    })


def genera_shiny():
    return random.randint(1, 10) == 1


# ─── Logica spawn (condivisa tra comando manuale e automatico) ────────────────

async def esegui_spawn(bot, chat_id, topic_id):
    """Genera un Pokémon e lo manda nella chat/topic indicati."""
    global current_pokemon, current_pokemon_image, current_is_shiny

    pokemon_id = random.randint(1, 151)
    current_is_shiny = genera_shiny()

    if current_is_shiny:
        artwork = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/shiny/{pokemon_id}.png"
    else:
        artwork = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pokemon_id}.png"

    img_data = requests.get(artwork).content
    with open("pokemon.png", "wb") as h:
        h.write(img_data)

    pokemon_data = requests.get(
        f"https://pokeapi.co/api/v2/pokemon/{pokemon_id}"
    ).json()

    current_pokemon = pokemon_data["name"].lower()
    current_pokemon_image = "pokemon.png"

    img = Image.open("pokemon.png").convert("RGBA")
    pixels = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pixels[x, y]
            if a > 0:
                pixels[x, y] = (0, 0, 0, 255)
    img.save("silhouette.png")

    if current_is_shiny:
        caption = "✨ Un Pokémon misterioso scintilla nell'oscurità... ✨\n\nScrivi /cattura NomePokemon"
    else:
        caption = "🐾 Un Pokémon selvatico è apparso!\n\nScrivi /cattura NomePokemon"

    await bot.send_photo(
        chat_id=chat_id,
        message_thread_id=topic_id,
        photo=open("silhouette.png", "rb"),
        caption=caption
    )


def calcola_prossimo_spawn():
    """
    Restituisce i secondi da attendere prima del prossimo spawn automatico.
    Se siamo fuori dalla fascia oraria, aspetta fino alle 06:00 del giorno
    giusto, poi aggiunge un offset random in [0, SPAWN_VARIAZIONE_SECONDI].
    """
    now = datetime.datetime.now()
    ora_attuale = now.hour + now.minute / 60

    # Siamo nell'orario attivo → prossimo spawn tra (base ± variazione)
    if SPAWN_ORA_INIZIO <= ora_attuale < SPAWN_ORA_FINE:
        variazione = random.randint(-SPAWN_VARIAZIONE_SECONDI, SPAWN_VARIAZIONE_SECONDI)
        delay = max(60, SPAWN_BASE_SECONDI + variazione)  # minimo 1 minuto
        return delay

    # Fuori orario → calcola secondi fino alle 06:00 di domani (o oggi)
    if ora_attuale >= SPAWN_ORA_FINE:
        # Mezzanotte passata: riprendiamo domani mattina
        prossima_apertura = now.replace(hour=SPAWN_ORA_INIZIO, minute=0, second=0, microsecond=0)
        prossima_apertura += datetime.timedelta(days=1)
    else:
        # Siamo tra mezzanotte e le 06:00: riprendiamo stamattina
        prossima_apertura = now.replace(hour=SPAWN_ORA_INIZIO, minute=0, second=0, microsecond=0)

    secondi_attesa = (prossima_apertura - now).total_seconds()
    # Aggiungiamo un offset random (0‑1 h) così non è sempre esattamente alle 06:00
    secondi_attesa += random.randint(0, SPAWN_VARIAZIONE_SECONDI)
    return secondi_attesa


# ─── Job per spawn automatico ─────────────────────────────────────────────────

async def job_spawn_automatico(context: ContextTypes.DEFAULT_TYPE):
    """Eseguito dal JobQueue: spawna e ripianifica se stesso."""
    await esegui_spawn(context.bot, CHAT_ID, TOPIC_ID)
    pianifica_prossimo_spawn(context.application)


def pianifica_prossimo_spawn(app):
    """Calcola il delay e aggiunge il job one-shot al JobQueue."""
    delay = calcola_prossimo_spawn()
    ore = delay / 3600
    print(f"[Spawn] Prossimo spawn automatico tra {ore:.1f} ore")
    app.job_queue.run_once(job_spawn_automatico, when=delay)


# ─── Handlers comandi Telegram ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🐾 PA Catch Bot attivo!")


async def spawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Spawn manuale (comando /spawn)."""
    await esegui_spawn(
        context.bot,
        update.effective_chat.id,
        update.message.message_thread_id
    )


async def cattura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_pokemon, current_pokemon_image, current_is_shiny, last_attempts

    user_id = update.effective_user.id
    now = time.time()

    if user_id in last_attempts and now - last_attempts[user_id] < 10:
        await update.message.reply_text("⏳ Attendi 10 secondi tra un tentativo e l'altro.")
        return

    last_attempts[user_id] = now

    if current_pokemon is None:
        await update.message.reply_text("❌ Non ci sono Pokémon da catturare.")
        return

    if len(context.args) == 0:
        await update.message.reply_text("Usa: /cattura NomePokemon")
        return

    tentativo = " ".join(context.args).lower()

    if tentativo != current_pokemon:
        await update.message.reply_text("❌ Pokémon errato!")
        return

    utente = update.effective_user.first_name
    nuovo = registra_cattura(user_id, current_pokemon, current_is_shiny)

    info = requests.get(
        f"https://pokeapi.co/api/v2/pokemon/{current_pokemon}"
    ).json()
    numero = str(info["id"]).zfill(3)

    if current_is_shiny:
        testo = f"✨ {utente} ha catturato uno SHINY {current_pokemon.capitalize()}! ✨\n\n🌟 Evento rarissimo (1/500)"
    elif nuovo:
        testo = f"🎉 {utente} ha catturato {current_pokemon.capitalize()}!\n\n📖 #{numero} registrato nel Pokédex!"
    else:
        testo = f"🎉 {utente} ha catturato {current_pokemon.capitalize()}!\n\n📖 Pokémon già presente nel Pokédex."

    await update.message.reply_photo(
        photo=open(current_pokemon_image, "rb"),
        caption=testo
    )

    current_pokemon = None
    current_pokemon_image = None
    current_is_shiny = False


async def pokedex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profilo = ottieni_profilo(update.effective_user.id)

    if not profilo["pokemon"]:
        await update.message.reply_text("📖 Il tuo Pokédex è vuoto.")
        return

    testo = f"📖 Pokédex di {update.effective_user.first_name}\n\n"
    testo += f"Completamento: {len(profilo['pokemon'])}/151\n\n"

    for voce in sorted(profilo["pokemon"]):
        shiny = voce.endswith("_shiny")
        nome = voce.replace("_shiny", "")
        info = requests.get(f"https://pokeapi.co/api/v2/pokemon/{nome}").json()
        numero = str(info["id"]).zfill(3)
        testo += f"#{numero} {nome.capitalize()}"
        if shiny:
            testo += " ✨"
        testo += "\n"

    await update.message.reply_text(testo[:4000])


async def profilo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = ottieni_profilo(update.effective_user.id)
    completamento = round((len(p["pokemon"]) / 151) * 100, 2)
    testo = (
        f"👤 {update.effective_user.first_name}\n\n"
        f"📖 Pokémon unici: {len(p['pokemon'])}\n"
        f"🎯 Catture totali: {p['catture_totali']}\n"
        f"✨ Shiny: {p['shiny']}\n"
        f"📊 Completamento: {completamento}%"
    )
    await update.message.reply_text(testo)


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def topicid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Topic ID: {update.message.message_thread_id}")


# ─── Avvio ────────────────────────────────────────────────────────────────────

async def post_init(app):
    """Chiamato dopo l'inizializzazione: pianifica il primo spawn automatico."""
    pianifica_prossimo_spawn(app)


app = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("spawn", spawn))
app.add_handler(CommandHandler("cattura", cattura))
app.add_handler(CommandHandler("pokedex", pokedex))
app.add_handler(CommandHandler("profilo", profilo))
app.add_handler(CommandHandler("chatid", chatid))
app.add_handler(CommandHandler("topicid", topicid))

print("BOT AVVIATO")
app.run_polling()
