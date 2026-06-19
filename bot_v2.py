from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from PIL import Image
import requests
import random
import json
import os
import time

import os

TOKEN = os.getenv("TOKEN")

GROUP_ID = -1003655667215
TOPIC_ID = 6

pokemon_spawn_time = None
current_pokemon = None
current_pokemon_image = None
current_is_shiny = False
last_attempts = {}

POKEDEX_FILE = "pokedex.json"


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🐾 PA Catch Bot attivo!")


async def spawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_pokemon
    global current_pokemon_image
    global current_is_shiny
    global pokemon_spawn_time

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
pokemon_spawn_time = time.time()
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

    await update.message.reply_photo(
        photo=open("silhouette.png", "rb"),
        caption=caption
    )

async def auto_spawn(context: ContextTypes.DEFAULT_TYPE):

    global current_pokemon
    global pokemon_spawn_time

    ora = datetime.now().hour

    if ora < 6 or ora >= 24:
        return

    if current_pokemon is not None:

        if pokemon_spawn_time is not None:

            if time.time() - pokemon_spawn_time > 172800:

                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    message_thread_id=TOPIC_ID,
                    text="💨 Il Pokémon si è allontanato..."
                )

                current_pokemon = None
                pokemon_spawn_time = None

        return

    # per ora log di test
    print("SPAWN AUTOMATICO")

async def cattura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_pokemon
    global current_pokemon_image
    global current_is_shiny
    global last_attempts

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
    await update.message.reply_text(
        f"Chat ID: {update.effective_chat.id}"
    )

async def topicid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Topic ID: {update.message.message_thread_id}"
    )

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("spawn", spawn))
app.add_handler(CommandHandler("cattura", cattura))
app.add_handler(CommandHandler("pokedex", pokedex))
app.add_handler(CommandHandler("profilo", profilo))
app.add_handler(CommandHandler("chatid", chatid))
app.add_handler(CommandHandler("topicid", topicid))

print("BOT AVVIATO")
job_queue = app.job_queue

job_queue.run_repeating(
    auto_spawn,
    interval=10800,
    first=60
)
app.run_polling()
