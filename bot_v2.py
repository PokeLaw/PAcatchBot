from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from PIL import Image
import requests
import random
import json
import os
import time
import datetime
from zoneinfo import ZoneInfo

TOKEN = os.getenv("TOKEN")

CHAT_ID = -1003655667215
TOPIC_ID = 6

TIMEZONE = ZoneInfo("Europe/Rome")

# Orario spawn automatico (ora italiana)
SPAWN_ORA_INIZIO = 9   # 09:00
SPAWN_ORA_FINE = 22    # 22:00

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


# ─── Job per spawn automatico ─────────────────────────────────────────────────

def genera_orari_giornalieri():
    """
    Genera 6 orari casuali nella fascia SPAWN_ORA_INIZIO–SPAWN_ORA_FINE,
    ordinati cronologicamente. Ritorna una lista di datetime aware (Europe/Rome).
    """
    oggi = datetime.datetime.now(TIMEZONE).date()
    inizio = SPAWN_ORA_INIZIO * 3600
    fine   = SPAWN_ORA_FINE   * 3600

    campioni = sorted(random.sample(range(inizio, fine), 6))

    orari = []
    for secondi in campioni:
        h = secondi // 3600
        m = (secondi % 3600) // 60
        orari.append(datetime.datetime.combine(oggi, datetime.time(h, m), tzinfo=TIMEZONE))

    return orari


async def job_spawn_automatico(context: ContextTypes.DEFAULT_TYPE):
    """Eseguito dal JobQueue per ogni spawn della giornata."""
    await esegui_spawn(context.bot, CHAT_ID, TOPIC_ID)


async def job_pianifica_giornata(context: ContextTypes.DEFAULT_TYPE):
    """
    Eseguito ogni mattina (o all'avvio): genera gli orari del giorno
    e registra un job one-shot per ciascuno.
    """
    app = context.application
    orari = genera_orari_giornalieri()

    print(f"[Spawn] Orari di oggi: {[o.strftime('%H:%M') for o in orari]}")

    now = datetime.datetime.now(TIMEZONE)
    for orario in orari:
        if orario > now:   # salta orari già passati (utile se Railway riavvia a metà giornata)
            app.job_queue.run_once(job_spawn_automatico, when=orario)


def pianifica_prossimo_spawn(app):
    """
    Chiamata all'avvio:
    - pianifica subito gli spawn di oggi (quelli futuri)
    - pianifica un job ricorrente ogni notte alle 00:01 (ora italiana) per i giorni seguenti
    """
    app.job_queue.run_once(job_pianifica_giornata, when=0)

    app.job_queue.run_daily(
        job_pianifica_giornata,
        time=datetime.time(0, 1, tzinfo=TIMEZONE)
    )


# ─── Handlers comandi Telegram ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🐾 PA Catch Bot attivo!")


async def spawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Spawn manuale (comando /spawn), riservato agli admin."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = {a.user.id for a in admins}

    if user_id not in admin_ids:
        await update.message.reply_text("⛔ Solo gli admin possono usare questo comando.")
        return

    await esegui_spawn(
        context.bot,
        chat_id,
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
    """Chiamato dopo l'inizializzazione: pianifica gli spawn automatici."""
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
