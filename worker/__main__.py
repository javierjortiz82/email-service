"""Email worker package entry point.

Allows execution of the email worker via: python -m email_service.worker
"""

import asyncio

from email_service.worker.processor import main

if __name__ == "__main__":
    asyncio.run(main())
