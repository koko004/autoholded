"""Scheduler service for automated fichajes."""
import logging
import asyncio
from datetime import datetime, date, time
from typing import Optional, List, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.storage import (
    get_schedules, get_schedule, get_config, get_schedule_assignment,
    get_calendar_events, get_default_schedule
)

logger = logging.getLogger(__name__)


class FichadorScheduler:
    """Manages scheduled fichaje tasks using live tracking controls."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=settings.TZ)
        self.is_running = False
        self.last_fichaje: Optional[datetime] = None
        self.next_fichaje: Optional[datetime] = None
        self._fichador = None

    def _get_fichador(self):
        """Lazy load fichador to avoid circular imports."""
        if self._fichador is None:
            from app.services.fichador import fichador
            self._fichador = fichador
        return self._fichador

    async def start(self):
        """Start the scheduler and load all schedules."""
        try:
            if not self.is_running:
                self.scheduler.start()
                self.is_running = True
                self._load_all_schedules()
                logger.info("Scheduler started")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise

    async def stop(self):
        """Stop the scheduler."""
        try:
            if self.is_running:
                self.scheduler.shutdown()
                self.is_running = False
                logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Failed to stop scheduler: {e}")
            raise

    def _load_all_schedules(self):
        """Load all active schedules and create jobs based on schedule source mode."""
        config = get_config()
        schedule_source = config.get("schedule_source", "schedules")
        logger.info(f"Schedule source mode: {schedule_source}")

        # Clear existing jobs first
        for job in self.scheduler.get_jobs():
            self.scheduler.remove_job(job.id)
            logger.info(f"Removed existing job: {job.id}")

        if schedule_source == "calendar":
            self._load_calendar_schedule()
            return

        # Schedules mode: create cron jobs from active schedules (original behavior)
        schedules = get_schedules()
        logger.info(f"Loading schedules: {len(schedules)} total")

        for schedule in schedules:
            if schedule.get("is_active", True):
                logger.info(f"Loading active schedule: {schedule.get('name')} (id={schedule.get('id')})")
                self._add_schedule_jobs(schedule)
            else:
                logger.info(f"Skipping inactive schedule: {schedule.get('name')}")

        jobs = self.scheduler.get_jobs()
        logger.info(f"Total jobs scheduled: {len(jobs)}")
        for job in jobs:
            logger.info(f"  Job: {job.id} -> next run: {job.next_run_time}")

    def _load_calendar_schedule(self):
        """In calendar mode, determine today's schedule and create jobs for it."""
        from datetime import date as date_cls
        today = date_cls.today()
        today_str = today.isoformat()
        weekday = today.weekday()

        # Check if today is a holiday or vacation
        if self._is_holiday_or_vacation(today_str):
            logger.info(f"Calendar mode: Today ({today_str}) is holiday/vacation, no jobs created")
            self._add_midnight_reload_job()
            return

        # Check calendar assignment for today
        assignment = get_schedule_assignment(today_str)
        effective_schedule_id = None

        if assignment:
            effective_schedule_id = assignment.get("schedule_id")
            logger.info(f"Calendar mode: Found assignment for today: {effective_schedule_id} ({assignment.get('description')})")

        # Fallback to default schedule
        if not effective_schedule_id:
            default_schedule = get_default_schedule()
            if default_schedule:
                effective_schedule_id = default_schedule.get("id")
                logger.info(f"Calendar mode: No assignment, using default schedule: {default_schedule.get('name')}")
            else:
                logger.warning("Calendar mode: No assignment and no default schedule")
                self._add_midnight_reload_job()
                return

        # Get the schedule
        schedule = get_schedule(effective_schedule_id)
        if not schedule:
            logger.error(f"Calendar mode: Schedule {effective_schedule_id} not found")
            self._add_midnight_reload_job()
            return

        # Check if today is a workday for this schedule
        if not self._is_workday(schedule):
            logger.info("Calendar mode: Today is not a workday for this schedule")
            self._add_midnight_reload_job()
            return

        # Create jobs for today's schedule (no day_of_week filter - one-shot for today)
        logger.info(f"Calendar mode: Creating jobs for schedule '{schedule.get('name')}'")
        self._add_schedule_jobs_today(schedule)

        # Add midnight reload job for tomorrow
        self._add_midnight_reload_job()

        jobs = self.scheduler.get_jobs()
        logger.info(f"Total jobs scheduled: {len(jobs)}")
        for job in jobs:
            logger.info(f"  Job: {job.id} -> next run: {job.next_run_time}")

    def _add_midnight_reload_job(self):
        """Add a one-shot job at 00:05 to reload the calendar schedule for the next day."""
        from datetime import date as date_cls, timedelta
        tomorrow = date_cls.today() + timedelta(days=1)
        reload_date = tomorrow.isoformat()

        # Only add if not already scheduled
        existing = [j.id for j in self.scheduler.get_jobs() if j.id == "calendar_daily_reload"]
        if existing:
            return

        self.scheduler.add_job(
            self._reload_calendar_schedule,
            CronTrigger(hour=0, minute=5),
            id="calendar_daily_reload",
            replace_existing=True,
            next_run_time=datetime.combine(tomorrow, time(0, 5))
        )
        logger.info(f"Calendar mode: Scheduled daily reload at 00:05 for {reload_date}")

    def _reload_calendar_schedule(self):
        """Reload schedule jobs for the new day (called at midnight)."""
        logger.info("=== Calendar daily reload triggered ===")
        self._load_calendar_schedule()

    def _add_schedule_jobs(self, schedule: Dict[str, Any]):
        """
        Add jobs for a schedule using live tracking controls.

        For a schedule with work_blocks [{entry, exit}, ...], we create:
        - Job at block[0].entry -> start_live_tracking (play)
        - Job at block[i].exit -> pause_live_tracking (for intermediate Trabajado blocks)
        - Job at block[i].entry -> start_live_tracking (resume, for intermediate Trabajado blocks)
        - Job at block[-1].exit -> stop_live_tracking (stop)
        """
        schedule_id = schedule.get("id")
        work_blocks = schedule.get("work_blocks", [])
        work_days = schedule.get("work_days", [])

        if not work_blocks:
            logger.warning(f"Schedule {schedule_id} has no work blocks")
            return

        logger.info(f"Schedule {schedule_id} has {len(work_blocks)} work blocks")

        # Convert work_days to cron day format
        day_numbers = [d.get("day_of_week") for d in work_days if d.get("is_workday")]
        if not day_numbers:
            day_numbers = [0, 1, 2, 3, 4]  # Default: Mon-Fri

        cron_days = ",".join(str(d) for d in day_numbers)
        logger.info(f"Schedule {schedule_id} work days: {cron_days}")

        # Job 1: Start tracking at first block entry
        first_block = work_blocks[0]
        first_entry = self._parse_time(first_block.get("entry"))
        if first_entry:
            job_id = f"schedule_{schedule_id}_start"
            self.scheduler.add_job(
                self._execute_live_tracking,
                CronTrigger(
                    hour=first_entry.hour,
                    minute=first_entry.minute,
                    day_of_week=cron_days
                ),
                id=job_id,
                kwargs={'action': 'start', 'schedule_id': schedule_id},
                replace_existing=True
            )
            logger.info(f"Added START job: {schedule_id} at {first_entry}")

        # Intermediate jobs: pause at block exits, resume at next block entries
        for i in range(len(work_blocks) - 1):
            block_exit = self._parse_time(work_blocks[i].get("exit"))
            next_block = work_blocks[i + 1]
            next_entry = self._parse_time(next_block.get("entry"))
            next_type = next_block.get("type", "Trabajado")

            if block_exit:
                job_id = f"schedule_{schedule_id}_block{i}_pause"
                self.scheduler.add_job(
                    self._execute_live_tracking,
                    CronTrigger(
                        hour=block_exit.hour,
                        minute=block_exit.minute,
                        day_of_week=cron_days
                    ),
                    id=job_id,
                    kwargs={'action': 'pause', 'schedule_id': schedule_id},
                    replace_existing=True
                )
                logger.info(f"Added PAUSE job: {schedule_id} block {i} at {block_exit}")

            if next_entry and next_type != "Pausa":
                job_id = f"schedule_{schedule_id}_block{i+1}_resume"
                self.scheduler.add_job(
                    self._execute_live_tracking,
                    CronTrigger(
                        hour=next_entry.hour,
                        minute=next_entry.minute,
                        day_of_week=cron_days
                    ),
                    id=job_id,
                    kwargs={'action': 'start', 'schedule_id': schedule_id},
                    replace_existing=True
                )
                logger.info(f"Added RESUME job: {schedule_id} block {i+1} at {next_entry}")
            elif next_entry:
                logger.info(f"Skipped RESUME job: {schedule_id} block {i+1} is Pausa type, no resume needed")

        # Final job: Stop tracking at last block exit
        last_block = work_blocks[-1]
        last_exit = self._parse_time(last_block.get("exit"))
        if last_exit:
            job_id = f"schedule_{schedule_id}_stop"
            self.scheduler.add_job(
                self._execute_live_tracking,
                CronTrigger(
                    hour=last_exit.hour,
                    minute=last_exit.minute,
                    day_of_week=cron_days
                ),
                id=job_id,
                kwargs={'action': 'stop', 'schedule_id': schedule_id},
                replace_existing=True
            )
            logger.info(f"Added STOP job: {schedule_id} at {last_exit}")

    def _add_schedule_jobs_today(self, schedule: Dict[str, Any]):
        """Add jobs for a schedule for today only (no day_of_week filter).
        
        Used in calendar mode to schedule today's assignment.
        """
        schedule_id = schedule.get("id")
        work_blocks = schedule.get("work_blocks", [])

        if not work_blocks:
            logger.warning(f"Schedule {schedule_id} has no work blocks")
            return

        logger.info(f"Adding today-only jobs for schedule {schedule_id} ({len(work_blocks)} blocks)")

        from datetime import date as date_cls
        today = date_cls.today()

        # Job 1: Start tracking at first block entry
        first_block = work_blocks[0]
        first_entry = self._parse_time(first_block.get("entry"))
        if first_entry:
            job_id = f"cal_{schedule_id}_start"
            run_dt = datetime.combine(today, first_entry)
            if run_dt > datetime.now():
                self.scheduler.add_job(
                    self._execute_live_tracking,
                    'date',
                    run_date=run_dt,
                    id=job_id,
                    kwargs={'action': 'start', 'schedule_id': schedule_id},
                    replace_existing=True
                )
                logger.info(f"  START: {run_dt}")

        # Intermediate jobs
        for i in range(len(work_blocks) - 1):
            block_exit = self._parse_time(work_blocks[i].get("exit"))
            next_block = work_blocks[i + 1]
            next_entry = self._parse_time(next_block.get("entry"))
            next_type = next_block.get("type", "Trabajado")

            if block_exit:
                job_id = f"cal_{schedule_id}_block{i}_pause"
                run_dt = datetime.combine(today, block_exit)
                if run_dt > datetime.now():
                    self.scheduler.add_job(
                        self._execute_live_tracking,
                        'date',
                        run_date=run_dt,
                        id=job_id,
                        kwargs={'action': 'pause', 'schedule_id': schedule_id},
                        replace_existing=True
                    )
                    logger.info(f"  PAUSE: {run_dt}")

            if next_entry and next_type != "Pausa":
                job_id = f"cal_{schedule_id}_block{i+1}_resume"
                run_dt = datetime.combine(today, next_entry)
                if run_dt > datetime.now():
                    self.scheduler.add_job(
                        self._execute_live_tracking,
                        'date',
                        run_date=run_dt,
                        id=job_id,
                        kwargs={'action': 'start', 'schedule_id': schedule_id},
                        replace_existing=True
                    )
                    logger.info(f"  RESUME: {run_dt}")

        # Final job: Stop tracking at last block exit
        last_block = work_blocks[-1]
        last_exit = self._parse_time(last_block.get("exit"))
        if last_exit:
            job_id = f"cal_{schedule_id}_stop"
            run_dt = datetime.combine(today, last_exit)
            if run_dt > datetime.now():
                self.scheduler.add_job(
                    self._execute_live_tracking,
                    'date',
                    run_date=run_dt,
                    id=job_id,
                    kwargs={'action': 'stop', 'schedule_id': schedule_id},
                    replace_existing=True
                )
                logger.info(f"  STOP: {run_dt}")

    def _parse_time(self, time_str) -> Optional[time]:
        """Parse time string like '08:00' or '13:00'."""
        if not time_str:
            return None
        try:
            if isinstance(time_str, str):
                parts = time_str.split(":")
                return time(int(parts[0]), int(parts[1]))
            return time_str
        except (ValueError, TypeError):
            return None

    def _execute_live_tracking(self, action: str = 'start', schedule_id: str = None):
        """Execute a live tracking action (start/pause/stop).

        This runs in a thread executor (from APScheduler). We create a new
        event loop for the async Playwright operations.
        
        Schedule resolution order:
        1. Check calendar for schedule_assignment for today
        2. If found, use that schedule
        3. If not found, use the default schedule (if set)
        4. If no default, use the schedule_id passed as parameter
        """
        logger.info(f"=== SCHEDULER JOB FIRED: action={action}, schedule_id={schedule_id} ===")

        MAX_RETRIES = 2
        RETRY_DELAY = 5

        try:
            # First, check if today is a holiday or vacation - these always override
            today_str = date.today().isoformat()
            if self._is_holiday_or_vacation(today_str):
                logger.info(f"Today ({today_str}) is a holiday or vacation, skipping fichaje")
                try:
                    from app.services.telegram_bot import telegram_bot
                    if telegram_bot.is_running:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                telegram_bot.send_notification("ℹ️ *Scheduler*\n\nHoy es festivo/vacaciones, fichaje omitido.")
                            )
                        finally:
                            loop.close()
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")
                return

            # Check if there's a calendar assignment for today
            assignment = get_schedule_assignment(today_str)
            
            effective_schedule_id = schedule_id
            if assignment:
                assigned_id = assignment.get("schedule_id")
                if assigned_id:
                    effective_schedule_id = assigned_id
                    logger.info(f"Using schedule from calendar assignment: {assigned_id} ({assignment.get('description')})")
            else:
                # No assignment found, try the default schedule
                default_schedule = get_default_schedule()
                if default_schedule:
                    effective_schedule_id = default_schedule.get("id")
                    logger.info(f"No calendar assignment, using default schedule: {default_schedule.get('name')}")
                elif effective_schedule_id:
                    logger.info(f"No calendar assignment or default, using passed schedule_id: {effective_schedule_id}")
                else:
                    logger.warning("No calendar assignment, no default schedule, and no schedule_id passed")
            
            schedule = None
            if effective_schedule_id:
                schedule = get_schedule(effective_schedule_id)
                logger.info(f"Schedule loaded: {schedule.get('name') if schedule else 'NOT FOUND'}")

            if not self._is_workday(schedule):
                logger.info("Today is not a workday, skipping")
                try:
                    from app.services.telegram_bot import telegram_bot
                    if telegram_bot.is_running:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                telegram_bot.send_notification("ℹ️ *Scheduler*\n\nHoy no es dia laborable, fichaje omitido.")
                            )
                        finally:
                            loop.close()
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")
                return

            # Check session validity before starting browser
            fichador = self._get_fichador()
            logger.info(f"Fichador headless mode: {fichador.headless}")
            logger.info(f"Session valid: {fichador.is_session_valid()}")

            if not fichador.is_session_valid():
                logger.error("Session file is missing or expired. Cannot execute fichaje.")
                try:
                    from app.services.telegram_bot import telegram_bot
                    if telegram_bot.is_running:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                telegram_bot.send_notification(
                                    "⚠️ *Sesion expirada*\n\n"
                                    "No se puede ejecutar el fichaje porque la sesion de Holded ha expirado. "
                                    "Inicia sesion manualmente para reactivar."
                                )
                            )
                        finally:
                            loop.close()
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")
                return

            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                result = None
                last_exception = None
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        logger.info(f"Running {action} live tracking (attempt {attempt}/{MAX_RETRIES})...")
                        if action == 'start':
                            result = loop.run_until_complete(fichador.start_live_tracking())
                        elif action == 'pause':
                            result = loop.run_until_complete(fichador.pause_live_tracking())
                        elif action == 'stop':
                            result = loop.run_until_complete(fichador.stop_live_tracking())
                        else:
                            logger.error(f"Unknown action: {action}")
                            return

                        if result.get("status") in ("success", "session_expired"):
                            break

                        logger.warning(f"Attempt {attempt} failed: {result.get('message')}")
                        last_exception = None
                        if attempt < MAX_RETRIES:
                            logger.info(f"Retrying in {RETRY_DELAY}s...")
                            import time as time_mod
                            time_mod.sleep(RETRY_DELAY)
                    except Exception as e:
                        last_exception = e
                        logger.warning(f"Attempt {attempt} raised exception: {e}")
                        if attempt < MAX_RETRIES:
                            logger.info(f"Retrying in {RETRY_DELAY}s...")
                            import time as time_mod
                            time_mod.sleep(RETRY_DELAY)

                if result is None and last_exception is not None:
                    raise last_exception

                logger.info(f"Result: {result}")

                if result.get("status") == "success":
                    self.last_fichaje = datetime.now()
                    logger.info(f"Live tracking {action} completed successfully")

                    # Send Telegram screenshots
                    try:
                        from app.services.telegram_bot import telegram_bot
                        if telegram_bot.is_running:
                            action_names = {"start": "Fichaje iniciado", "pause": "Fichaje pausado", "stop": "Fichaje finalizado"}
                            steps = fichador.get_debug_steps()
                            loop.run_until_complete(
                                telegram_bot.send_screenshots_from_steps(
                                    steps, action_names.get(action, action), "success"
                                )
                            )
                    except Exception as e:
                        logger.error(f"Failed to send Telegram notification: {e}")

                    # Save attendance record
                    try:
                        from app.services.storage import save_attendance
                        from datetime import date as date_cls
                        today = date_cls.today().isoformat()
                        now = datetime.now()

                        if action == 'start':
                            save_attendance({
                                "date": today,
                                "entry_time": now.isoformat(),
                                "status": "in_progress",
                                "source": "scheduler"
                            })
                        elif action == 'stop':
                            save_attendance({
                                "date": today,
                                "exit_time": now.isoformat(),
                                "status": "completed",
                                "source": "scheduler"
                            })
                        elif action == 'pause':
                            save_attendance({
                                "date": today,
                                "status": "paused",
                                "source": "scheduler"
                            })
                    except Exception as e:
                        logger.error(f"Failed to save attendance: {e}")
                elif result.get("status") == "session_expired":
                    logger.warning("Session expired during fichaje - may need re-login")
                    try:
                        from app.services.telegram_bot import telegram_bot
                        if telegram_bot.is_running:
                            action_names = {"start": "Fichaje", "pause": "Pausa", "stop": "Finalizar"}
                            loop.run_until_complete(
                                telegram_bot.send_notification(
                                    f"⚠️ *Sesion expirada*\n\n"
                                    f"{action_names.get(action, action)} no completado. "
                                    f"Se necesita re-login en Holded."
                                )
                            )
                    except Exception:
                        pass
                else:
                    logger.error(f"Live tracking {action} failed after {MAX_RETRIES} attempts: {result.get('message')}")
                    try:
                        from app.services.telegram_bot import telegram_bot
                        if telegram_bot.is_running:
                            loop.run_until_complete(
                                telegram_bot.send_notification(
                                    f"❌ *Error en {action}* (tras {MAX_RETRIES} intentos)\n\n{result.get('message', 'Error desconocido')}"
                                )
                            )
                    except Exception:
                        pass
            finally:
                loop.close()

        except Exception as e:
            logger.error(f"Error executing live tracking {action}: {e}", exc_info=True)
            try:
                from app.services.telegram_bot import telegram_bot
                if telegram_bot.is_running:
                    loop_n = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop_n)
                    try:
                        loop_n.run_until_complete(
                            telegram_bot.send_notification(
                                f"❌ *Error critico en {action}*\n\n{str(e)}"
                            )
                        )
                    finally:
                        loop_n.close()
            except Exception:
                pass

    def _execute_fichaje(self, fichaje_type: str = 'entry', entry_time: time = None, exit_time: time = None):
        """Execute a fichaje (legacy method, kept for compatibility)."""
        try:
            logger.info(f"Executing scheduled fichaje: {fichaje_type}")

            if not self._is_workday():
                logger.info("Today is not a workday, skipping fichaje")
                return

            config = get_config()
            email = config.get("holded_email") or settings.HOLDED_EMAIL
            password = config.get("holded_password") or settings.HOLDED_PASSWORD

            if not email or not password:
                logger.error("Holded credentials not configured")
                return

            fichador = self._get_fichador()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                result = loop.run_until_complete(
                    fichador.fichar(
                        email=email,
                        password=password,
                        entry_time=entry_time,
                        exit_time=exit_time,
                        target_date=date.today()
                    )
                )

                if result.get("status") == "success":
                    self.last_fichaje = datetime.now()
                    logger.info(f"Fichaje {fichaje_type} completed successfully")
                elif result.get("status") == "session_expired":
                    logger.warning("Session expired, may need re-login")
                else:
                    logger.error(f"Fichaje {fichaje_type} failed: {result.get('message')}")
            finally:
                loop.close()

        except Exception as e:
            logger.error(f"Error executing fichaje: {e}")

    def _is_workday(self, schedule: Optional[Dict[str, Any]] = None) -> bool:
        """Check if today is a workday, optionally checking against a schedule's work_days."""
        today = date.today()
        if schedule:
            work_days = schedule.get("work_days", [])
            if work_days:
                is_workday = any(d.get("day_of_week") == today.weekday() and d.get("is_workday") for d in work_days)
                logger.info(f"Today is weekday {today.weekday()}, schedule work_days check: {is_workday}")
                return is_workday
        # Default: Mon-Fri
        is_weekday = today.weekday() < 5
        logger.info(f"Today is weekday {today.weekday()}, default check: {is_weekday}")
        return is_weekday

    def _is_holiday_or_vacation(self, target_date: str) -> bool:
        """Check if a date is marked as holiday or vacation in the calendar.
        
        Holidays and vacations always override any schedule assignment.
        """
        year = int(target_date[:4])
        month = int(target_date[5:7])
        events = get_calendar_events(year=year, month=month)
        for event in events:
            if event.get("event_date") == target_date:
                event_type = event.get("event_type")
                if event_type in ("holiday", "vacation"):
                    logger.info(f"Date {target_date} is {event_type}: {event.get('description', '')}")
                    return True
        return False

    def get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        jobs = self.scheduler.get_jobs()
        if jobs:
            next_times = [job.next_run_time for job in jobs if job.next_run_time]
            if next_times:
                return min(next_times)
        return None

    def get_schedule_source(self) -> str:
        """Get the current schedule source mode."""
        config = get_config()
        return config.get("schedule_source", "schedules")

    def get_status(self) -> dict:
        """Get scheduler status."""
        jobs = self.scheduler.get_jobs()
        job_ids = [job.id for job in jobs]

        return {
            'is_running': self.is_running,
            'last_fichaje': self.last_fichaje.isoformat() if self.last_fichaje else None,
            'next_fichaje': self.get_next_run_time().isoformat() if self.get_next_run_time() else None,
            'active_jobs': job_ids,
            'total_jobs': len(jobs),
            'schedule_source': self.get_schedule_source()
        }

    def reload_schedules(self):
        """Reload all schedules (call after config changes)."""
        logger.info("Reloading schedules...")
        self._load_all_schedules()


# Singleton instance
scheduler = FichadorScheduler()
