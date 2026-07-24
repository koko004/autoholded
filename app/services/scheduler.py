"""Scheduler service for automated fichajes."""
import logging
import asyncio
from datetime import datetime, date, time
from typing import Optional, List, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.storage import get_schedules, get_schedule, get_config

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
        """Load all active schedules and create jobs."""
        schedules = get_schedules()
        logger.info(f"Loading schedules: {len(schedules)} total")

        # Clear existing jobs first
        for job in self.scheduler.get_jobs():
            self.scheduler.remove_job(job.id)
            logger.info(f"Removed existing job: {job.id}")

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

    def _add_schedule_jobs(self, schedule: Dict[str, Any]):
        """
        Add jobs for a schedule using live tracking controls.

        For a schedule with work_blocks [{entry, exit}, ...], we create:
        - Job at block[0].entry -> start_live_tracking (play)
        - Job at block[i].exit -> pause_live_tracking (for intermediate blocks)
        - Job at block[i].entry -> start_live_tracking (resume, for intermediate blocks)
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
            next_entry = self._parse_time(work_blocks[i + 1].get("entry"))

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

            if next_entry:
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

    def _parse_time(self, time_str) -> Optional[time]:
        """Parse time string like '08:00' or '13:00'."""
        if not time_str:
            return None
        try:
            if isinstance(time_str, str):
                parts = time_str.split(":")
                return time(int(parts[0]), int(parts[1]))
            return time_str
        except:
            return None

    def _execute_live_tracking(self, action: str = 'start', schedule_id: str = None):
        """Execute a live tracking action (start/pause/stop).

        This runs in a thread executor (from APScheduler). We create a new
        event loop for the async Playwright operations.
        """
        logger.info(f"=== SCHEDULER JOB FIRED: action={action}, schedule_id={schedule_id} ===")

        try:
            schedule = None
            if schedule_id:
                schedule = get_schedule(schedule_id)
                logger.info(f"Schedule loaded: {schedule.get('name') if schedule else 'NOT FOUND'}")

            if not self._is_workday(schedule):
                logger.info("Today is not a workday, skipping")
                return

            config = get_config()
            email = config.get("holded_email") or settings.HOLDED_EMAIL
            password = config.get("holded_password") or settings.HOLDED_PASSWORD

            if not email or not password:
                logger.error("Holded credentials not configured in config.json or .env")
                return

            logger.info(f"Credentials found for: {email}")

            # Check session validity before starting browser
            fichador = self._get_fichador()
            logger.info(f"Fichador headless mode: {fichador.headless}")
            logger.info(f"Session valid: {fichador.is_session_valid()}")

            if not fichador.is_session_valid():
                logger.error("Session file is missing or expired. Cannot execute fichaje.")
                return

            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                logger.info(f"Running {action} live tracking...")
                if action == 'start':
                    result = loop.run_until_complete(fichador.start_live_tracking())
                elif action == 'pause':
                    result = loop.run_until_complete(fichador.pause_live_tracking())
                elif action == 'stop':
                    result = loop.run_until_complete(fichador.stop_live_tracking())
                else:
                    logger.error(f"Unknown action: {action}")
                    return

                logger.info(f"Result: {result}")

                if result.get("status") == "success":
                    self.last_fichaje = datetime.now()
                    logger.info(f"Live tracking {action} completed successfully")
                elif result.get("status") == "session_expired":
                    logger.warning("Session expired during fichaje - may need re-login")
                else:
                    logger.error(f"Live tracking {action} failed: {result.get('message')}")
            finally:
                loop.close()

        except Exception as e:
            logger.error(f"Error executing live tracking {action}: {e}", exc_info=True)

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

    def get_next_run_time(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        jobs = self.scheduler.get_jobs()
        if jobs:
            next_times = [job.next_run_time for job in jobs if job.next_run_time]
            if next_times:
                return min(next_times)
        return None

    def get_status(self) -> dict:
        """Get scheduler status."""
        jobs = self.scheduler.get_jobs()
        job_ids = [job.id for job in jobs]

        return {
            'is_running': self.is_running,
            'last_fichaje': self.last_fichaje.isoformat() if self.last_fichaje else None,
            'next_fichaje': self.get_next_run_time().isoformat() if self.get_next_run_time() else None,
            'active_jobs': job_ids,
            'total_jobs': len(jobs)
        }


# Singleton instance
scheduler = FichadorScheduler()
