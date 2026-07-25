"""Telegram Bot service for remote control of the fichador."""
import logging
import asyncio
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DEBUG_DIR = DATA_DIR / "debug"
DEBUG_MANIFEST = DEBUG_DIR / "manifest.json"


class TelegramBotService:
    """Telegram bot using polling mode for remote fichador control."""

    def __init__(self):
        self.bot = None
        self.app = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._chat_id: Optional[str] = None
        self._token: Optional[str] = None
        self._screenshot_mode: str = "last"
        self._conversation_state: Dict[int, str] = {}
        self._fichador = None
        self._scheduler = None

    def _get_fichador(self):
        if self._fichador is None:
            from app.services.fichador import fichador
            self._fichador = fichador
        return self._fichador

    def _get_scheduler(self):
        if self._scheduler is None:
            from app.services.scheduler import scheduler
            self._scheduler = scheduler
        return self._scheduler

    def configure(self, token: str, chat_id: str, screenshot_mode: str = "last"):
        self._token = token
        self._chat_id = chat_id
        self._screenshot_mode = screenshot_mode
        logger.info(f"Telegram bot configured: chat_id={chat_id}, mode={screenshot_mode}")

    async def start(self):
        if self._running:
            logger.warning("Telegram bot already running")
            return

        if not self._token or not self._chat_id:
            logger.error("Telegram bot not configured (missing token or chat_id)")
            return

        try:
            from telegram import Update, BotCommand
            from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

            self.app = ApplicationBuilder().token(self._token).build()
            self.bot = self.app.bot

            async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                await update.message.reply_text(
                    "🤖 *Fichador Holded - Bot de Control*\n\n"
                    "Comandos disponibles:\n"
                    "/status - Estado del scheduler y fichaje\n"
                    "/play - Iniciar fichaje\n"
                    "/pause - Pausar fichaje\n"
                    "/stop - Finalizar fichaje\n"
                    "/fichar - Fichaje manual (pedira fecha)\n"
                    "/corregir - Corregir fichaje de hoy con horario activo\n"
                    "/start_scheduler - Iniciar scheduler\n"
                    "/stop_scheduler - Detener scheduler\n"
                    "/screenshots - Cambiar modo de capturas\n"
                    "/help - Esta ayuda",
                    parse_mode="Markdown"
                )

            async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                await cmd_start(update, context)

            async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                try:
                    sched = self._get_scheduler()
                    sched_status = sched.get_status()
                    sched_running = sched_status.get('is_running', False)
                    total_jobs = sched_status.get('total_jobs', 0)
                    next_fichaje = sched_status.get('next_fichaje', 'N/A')

                    fichador = self._get_fichador()
                    session_valid = fichador.is_session_valid()

                    from app.services.storage import get_attendance as storage_get_attendance
                    from datetime import date as date_cls
                    today = date_cls.today().isoformat()
                    today_logs = storage_get_attendance(start_date=today, end_date=today)
                    today_status = "sin registros"
                    if today_logs:
                        log = today_logs[-1]
                        today_status = log.get("status", "desconocido")

                    msg = (
                        f"📊 *Estado del Sistema*\n\n"
                        f"🔐 Sesión Holded: {'✅ Válida' if session_valid else '❌ Expirada'}\n"
                        f"⏰ Scheduler: {'✅ Activo' if sched_running else '❌ Parado'}\n"
                        f"📋 Trabajos: {total_jobs}\n"
                        f"⏭ Próximo fichaje: {next_fichaje}\n"
                        f"📝 Hoy: {today_status}"
                    )
                    await update.message.reply_text(msg, parse_mode="Markdown")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                await update.message.reply_text("▶️ Iniciando fichaje...")
                try:
                    fichador = self._get_fichador()
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: self._run_async(fichador.start_live_tracking()))
                    await self._send_action_result(update, result, "Fichaje iniciado")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                await update.message.reply_text("⏸ Pausando fichaje...")
                try:
                    fichador = self._get_fichador()
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: self._run_async(fichador.pause_live_tracking()))
                    await self._send_action_result(update, result, "Fichaje pausado")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                await update.message.reply_text("⏹ Finalizando fichaje...")
                try:
                    fichador = self._get_fichador()
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: self._run_async(fichador.stop_live_tracking()))
                    await self._send_action_result(update, result, "Fichaje finalizado")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_fichar(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                self._conversation_state[update.effective_user.id] = "waiting_fichar_date"
                await update.message.reply_text(
                    "📅 *Fichaje Manual*\n\n"
                    "Introduce la fecha (formato: DD/MM/YYYY, ej: 25/07/2026)\n"
                    "O envia /cancel para cancelar.",
                    parse_mode="Markdown"
                )

            async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                self._conversation_state.pop(update.effective_user.id, None)
                await update.message.reply_text("✖ Operación cancelada.")

            async def cmd_start_scheduler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                try:
                    sched = self._get_scheduler()
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, lambda: self._run_async(sched.start()))
                    await update.message.reply_text("✅ Scheduler iniciado")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_stop_scheduler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                try:
                    sched = self._get_scheduler()
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, lambda: self._run_async(sched.stop()))
                    await update.message.reply_text("✅ Scheduler detenido")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_corregir(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                await update.message.reply_text("🔧 Corrigiendo fichaje de hoy...")
                try:
                    from app.services.storage import get_schedules
                    from datetime import date as date_cls

                    schedules = get_schedules()
                    work_blocks = []
                    location = "ARCO C.B."
                    for s in schedules:
                        if s.get("is_active", True):
                            work_blocks = s.get("work_blocks", [])
                            location = s.get("location", "ARCO C.B.")
                            break

                    if not work_blocks:
                        await update.message.reply_text("❌ No hay horarios configurados")
                        return

                    fichador = self._get_fichador()
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None,
                        lambda: self._run_async(fichador.modificar_fichaje(
                            target_date=date_cls.today(),
                            work_blocks=work_blocks,
                            location=location
                        ))
                    )
                    await self._send_action_result(update, result, "Corregir fichaje de hoy")
                except Exception as e:
                    await update.message.reply_text(f"❌ Error: {e}")

            async def cmd_screenshots(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                args = context.args if context.args else []
                if args and args[0] in ("all", "last", "summary"):
                    self._screenshot_mode = args[0]
                    mode_names = {"all": "Todas las capturas", "last": "Solo la última", "summary": "Última + resumen"}
                    await update.message.reply_text(f"📸 Modo de capturas: {mode_names[args[0]]}")
                    # Save to config
                    try:
                        from app.services.storage import get_config, save_config
                        config = get_config()
                        config["telegram_screenshot_mode"] = args[0]
                        save_config(config)
                    except:
                        pass
                else:
                    await update.message.reply_text(
                        "📸 *Modo de Capturas*\n\n"
                        "Uso: /screenshots <modo>\n\n"
                        f"Modo actual: *{self._screenshot_mode}*\n\n"
                        "Modos disponibles:\n"
                        "`all` - Todas las capturas (4-6 imgs)\n"
                        "`last` - Solo la última captura\n"
                        "`summary` - Última + resumen",
                        parse_mode="Markdown"
                    )

            async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if not self._check_access(update):
                    return
                user_id = update.effective_user.id
                state = self._conversation_state.get(user_id)

                if state == "waiting_fichar_date":
                    text = update.message.text.strip()
                    self._conversation_state.pop(user_id, None)

                    try:
                        from datetime import date as date_cls
                        # Accept DD/MM/YYYY or YYYY-MM-DD
                        if "/" in text:
                            parts = text.split("/")
                            if len(parts) == 3:
                                target_date = date_cls(int(parts[2]), int(parts[1]), int(parts[0]))
                            else:
                                raise ValueError("Invalid format")
                        else:
                            target_date = date_cls.fromisoformat(text)
                    except ValueError:
                        await update.message.reply_text("❌ Formato de fecha inválido. Usa DD/MM/YYYY (ej: 25/07/2026)")
                        return

                    await update.message.reply_text(f"📅 Fichaje manual para {text}...")

                    try:
                        from app.services.storage import get_schedule, get_schedules
                        schedules = get_schedules()
                        work_blocks = []
                        location = "ARCO C.B."

                        for s in schedules:
                            if s.get("is_active", True):
                                work_blocks = s.get("work_blocks", [])
                                location = s.get("location", "ARCO C.B.")
                                break

                        if not work_blocks:
                            await update.message.reply_text("❌ No hay horarios configurados")
                            return

                        fichador = self._get_fichador()
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None,
                            lambda: self._run_async(fichador.fichar_manual(
                                work_blocks=work_blocks,
                                target_date=target_date,
                                location=location
                            ))
                        )
                        await self._send_action_result(update, result, f"Fichaje manual {text}")
                    except Exception as e:
                        await update.message.reply_text(f"❌ Error: {e}")

            self.app.add_handler(CommandHandler("start", cmd_start))
            self.app.add_handler(CommandHandler("help", cmd_help))
            self.app.add_handler(CommandHandler("status", cmd_status))
            self.app.add_handler(CommandHandler("play", cmd_play))
            self.app.add_handler(CommandHandler("pause", cmd_pause))
            self.app.add_handler(CommandHandler("stop", cmd_stop))
            self.app.add_handler(CommandHandler("fichar", cmd_fichar))
            self.app.add_handler(CommandHandler("cancel", cmd_cancel))
            self.app.add_handler(CommandHandler("start_scheduler", cmd_start_scheduler))
            self.app.add_handler(CommandHandler("stop_scheduler", cmd_stop_scheduler))
            self.app.add_handler(CommandHandler("corregir", cmd_corregir))
            self.app.add_handler(CommandHandler("screenshots", cmd_screenshots))
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            self._running = True
            logger.info("Telegram bot started")

            # Register bot commands for autocomplete
            try:
                from telegram import BotCommand
                commands = [
                    BotCommand("status", "Estado del scheduler y fichaje"),
                    BotCommand("play", "Iniciar fichaje"),
                    BotCommand("pause", "Pausar fichaje"),
                    BotCommand("stop", "Finalizar fichaje"),
                    BotCommand("fichar", "Fichaje manual (pedira fecha)"),
                    BotCommand("corregir", "Corregir fichaje de hoy con horario activo"),
                    BotCommand("start_scheduler", "Iniciar scheduler"),
                    BotCommand("stop_scheduler", "Detener scheduler"),
                    BotCommand("screenshots", "Cambiar modo de capturas"),
                    BotCommand("help", "Lista de comandos"),
                ]
                await self.app.bot.set_my_commands(commands)
                logger.info("Bot commands registered for autocomplete")
            except Exception as e:
                logger.error(f"Failed to set bot commands: {e}")

            # Notify the chat
            try:
                await self.app.bot.send_message(
                    chat_id=self._chat_id,
                    text="✅ *Fichador Holded conectado*\n\nEscribe /help para ver los comandos.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to send start message: {e}")

        except ImportError:
            logger.error("python-telegram-bot not installed")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")

    async def stop(self):
        if not self._running:
            return
        try:
            if self.app:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            self._running = False
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")

    def _check_access(self, update) -> bool:
        if not update.message:
            return False
        chat_id = str(update.effective_chat.id)
        if self._chat_id and chat_id != self._chat_id:
            logger.warning(f"Unauthorized Telegram access from chat_id={chat_id}")
            return False
        return True

    def _run_async(self, coro):
        """Run an async coroutine in a new event loop (for thread executor)."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error running async: {e}")
            return {"status": "error", "message": str(e)}

    async def _send_action_result(self, update, result: dict, action_name: str):
        """Send action result with screenshots to the chat."""
        status = result.get("status", "error")
        message = result.get("message", "Sin mensaje")

        if status == "success":
            text = f"✅ *{action_name}*\n\n{message}"
        else:
            text = f"❌ *{action_name}*\n\n{message}"

        # Get screenshots
        screenshots = self._get_latest_screenshots()

        if self._screenshot_mode == "all" and screenshots:
            for i, shot in enumerate(screenshots):
                caption = f"📸 {shot['step']}" if i < len(screenshots) - 1 else text
                try:
                    from telegram import InputFile
                    with open(shot["path"], "rb") as f:
                        await update.message.reply_photo(photo=InputFile(f), caption=caption)
                except Exception as e:
                    logger.error(f"Failed to send screenshot: {e}")
            if not screenshots:
                await update.message.reply_text(text, parse_mode="Markdown")

        elif self._screenshot_mode == "summary" and screenshots:
            last_shot = screenshots[-1]
            try:
                from telegram import InputFile
                with open(last_shot["path"], "rb") as f:
                    await update.message.reply_photo(
                        photo=InputFile(f),
                        caption=text,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Failed to send screenshot: {e}")
                await update.message.reply_text(text, parse_mode="Markdown")

        elif self._screenshot_mode == "last" and screenshots:
            last_shot = screenshots[-1]
            try:
                from telegram import InputFile
                with open(last_shot["path"], "rb") as f:
                    await update.message.reply_photo(
                        photo=InputFile(f),
                        caption=text,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Failed to send screenshot: {e}")
                await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

    async def send_notification(self, text: str, screenshot_path: Optional[str] = None):
        """Send a notification to the configured chat (used by scheduler)."""
        if not self._running or not self._chat_id or not self.bot:
            return

        try:
            if screenshot_path and Path(screenshot_path).exists():
                from telegram import InputFile
                with open(screenshot_path, "rb") as f:
                    await self.bot.send_photo(
                        chat_id=self._chat_id,
                        photo=InputFile(f),
                        caption=text,
                        parse_mode="Markdown"
                    )
            else:
                await self.bot.send_message(
                    chat_id=self._chat_id,
                    text=text,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    async def send_screenshots_from_steps(self, steps: list, action_name: str, result_status: str = "success"):
        """Send screenshots from debug steps list (called after fichaje actions)."""
        if not self._running or not self._chat_id or not self.bot:
            logger.info(f"send_screenshots skip: running={self._running}, chat_id={self._chat_id}, bot={bool(self.bot)}")
            return

        screenshots = []
        for step in steps:
            filename = step.get("filename", "")
            if filename:
                path = str(DEBUG_DIR / filename)
                if Path(path).exists():
                    screenshots.append({"step": step.get("step", ""), "path": path})

        logger.info(f"send_screenshots: {len(screenshots)} screenshots found, mode={self._screenshot_mode}")

        if not screenshots:
            return

        status_icon = "✅" if result_status == "success" else "❌"
        text = f"{status_icon} *{action_name}*"

        if self._screenshot_mode == "all":
            for i, shot in enumerate(screenshots):
                caption = f"📸 {shot['step']}" if i < len(screenshots) - 1 else text
                try:
                    from telegram import InputFile
                    with open(shot["path"], "rb") as f:
                        await self.bot.send_photo(
                            chat_id=self._chat_id,
                            photo=InputFile(f),
                            caption=caption
                        )
                except Exception as e:
                    logger.error(f"Failed to send screenshot: {e}")

        elif self._screenshot_mode == "summary" and screenshots:
            last_shot = screenshots[-1]
            try:
                from telegram import InputFile
                with open(last_shot["path"], "rb") as f:
                    await self.bot.send_photo(
                        chat_id=self._chat_id,
                        photo=InputFile(f),
                        caption=text,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Failed to send screenshot: {e}")

        elif self._screenshot_mode == "last" and screenshots:
            last_shot = screenshots[-1]
            try:
                from telegram import InputFile
                with open(last_shot["path"], "rb") as f:
                    await self.bot.send_photo(
                        chat_id=self._chat_id,
                        photo=InputFile(f),
                        caption=text,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Failed to send screenshot: {e}")

    def _get_latest_screenshots(self) -> list:
        """Get screenshots from the debug manifest."""
        import json
        try:
            if DEBUG_MANIFEST.exists():
                with open(DEBUG_MANIFEST) as f:
                    steps = json.load(f)
                result = []
                for step in steps:
                    path = DEBUG_DIR / step.get("filename", "")
                    if path.exists():
                        result.append({"step": step.get("step", ""), "path": str(path)})
                return result
        except Exception as e:
            logger.error(f"Failed to read debug manifest: {e}")
        return []

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "chat_id": self._chat_id,
            "token_configured": bool(self._token),
            "screenshot_mode": self._screenshot_mode
        }


telegram_bot = TelegramBotService()
