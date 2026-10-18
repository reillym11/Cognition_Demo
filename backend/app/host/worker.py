from app.foundation import jobs
from app.foundation.logging_setup import configure
from app.foundation.settings import get_settings


def main() -> None:
    configure()
    s = get_settings()
    jobs.worker_loop(s.worker_poll_seconds, scheduler=not s.disable_scheduler)


if __name__ == "__main__":
    main()
