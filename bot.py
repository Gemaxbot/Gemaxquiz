import os
import json
import sqlite3
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import google.generativeai as genai

# --- CONFIGURACIÓN DE FLASK PARA CUMPLIR CON EL PUERTO DE RENDER ---
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "¡El bot de trivia de Telegram está activo y funcionando! 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)
# ------------------------------------------------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Faltan variables de entorno (TELEGRAM_BOT_TOKEN o GEMINI_API_KEY).")

genai.configure(api_key=GEMINI_API_KEY)

# Configuración del modelo estable de Gemini
model = genai.GenerativeModel('gemini-1.5-flash')

def init_db():
    conn = sqlite3.connect("trivia_mensual.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            points INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

trivia_activa = False
pregunta_actual = {}

async def iniciar_trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global trivia_activa, pregunta_actual
    
    mensaje_espera = await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="🤖 *Generando una pregunta cripto con IA...* ⏳", 
        parse_mode="Markdown"
    )

    try:
        prompt = """
        Genera una pregunta de trivia sobre criptomonedas, blockchain, DeFi o análisis técnico en español.
        Debe tener exactamente 3 opciones de respuesta y una de ellas debe ser la correcta.
        Devuelve la respuesta ÚNICAMENTE en formato JSON válido, sin texto adicional, con esta estructura exacta:
        {
          "pregunta": "Texto de la pregunta aquí",
          "opciones": ["Opción 1", "Opción 2", "Opción 3"],
          "correcta": 1
        }
        Donde 'correcta' es el índice numérico de la opción correcta (0, 1 o 2).
        """

        response = model.generate_content(prompt)
        
        texto_respuesta = response.text.strip()
        if "```json" in texto_respuesta:
            texto_respuesta = texto_respuesta.split("```json")[1].split("```")[0].strip()
        elif "```" in texto_respuesta:
            texto_respuesta = texto_respuesta.split("```")[1].split("```")[0].strip()
            
        pregunta_actual = json.loads(texto_respuesta)
        trivia_activa = True

        texto = f"🧠 **¡TRIVIA CRIPTO IA DEL DÍA!** 🧠\n\n{pregunta_actual['pregunta']}\n\n"
        for i, opcion in enumerate(pregunta_actual['opciones']):
            texto += f"{i+1}️⃣ {opcion}\n"
        
        texto += "\n💡 *Responde enviando el número de tu opción (1, 2 o 3).* ¡El primero en acertar gana 1 punto!"
        
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=mensaje_espera.message_id)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=texto, parse_mode="Markdown")

    except Exception as e:
        print(f"ERROR DETALLADO DE GEMINI: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=mensaje_espera.message_id,
            text=f"⚠️ Ups, hubo un error generando la trivia con IA. Revisa los logs."
        )

async def manejar_respuesta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global trivia_activa, pregunta_actual
    
    if not trivia_activa:
        return

    texto_usuario = update.message.text.strip()
    
    if texto_usuario.isdigit():
        opcion_elegida = int(texto_usuario) - 1
        
        if opcion_elegida == pregunta_actual.get("correcta"):
            trivia_activa = False 
            
            user = update.effective_user
            user_id = user.id
            username = user.username or user.first_name
            
            conn = sqlite3.connect("trivia_mensual.db")
            cursor = conn.cursor()
            cursor.execute("SELECT points FROM scores WHERE user_id = ?", (user_id,))
            resultado = cursor.fetchone()
            
            if resultado:
                nuevos_puntos = resultado[0] + 1
                cursor.execute("UPDATE scores SET points = ?, username = ? WHERE user_id = ?", (nuevos_puntos, username, user_id))
            else:
                cursor.execute("INSERT INTO scores (user_id, username, points) VALUES (?, ?, 1)", (user_id, username))
                
            conn.commit()
            conn.close()
            
            await update.message.reply_text(
                f"🎉 ¡Correcto, @{username}! La respuesta era la opción {pregunta_actual['correcta'] + 1}. Sumas 1 punto para la liga mensual. 🚀"
            )

async def ver_ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("trivia_mensual.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, points FROM scores ORDER BY points DESC LIMIT 10")
    ranking = cursor.fetchall()
    conn.close()
    
    if not ranking:
        await update.message.reply_text("📊 Aún no hay registros en la tabla de clasificación este mes.")
        return
        
    texto = "🏆 **TABLA DE CLASIFICACIÓN - LIGA MENSUAL** 🏆\n\n"
    for i, (username, points) in enumerate(ranking, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        texto += f"{medal} @{username} — *{points} aciertos*\n"
        
    texto += "\n¡Sigan participando para llevarse el premio a fin de mes! 🔥"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def reiniciar_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("trivia_mensual.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scores")
    conn.commit()
    conn.close()
    await update.message.reply_text("🔄 ¡La tabla mensual ha sido reiniciada! Comienza una nueva batalla cripto.")

def main():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("trivia", iniciar_trivia))
    app.add_handler(CommandHandler("ranking", ver_ranking))
    app.add_handler(CommandHandler("resetmes", reiniciar_mes))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_respuesta))

    print("🤖 Bot de Trivia Cripto con Gemini y Flask iniciado correctamente...")
    app.run_polling()

if __name__ == "__main__":
    main()
