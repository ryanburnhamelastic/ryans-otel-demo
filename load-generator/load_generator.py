import os
import time
import random
import logging
import requests
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Get configuration from environment variables
APP_URL = os.getenv('APP_URL', 'http://otel-demo-app:8080')
REQUESTS_PER_SECOND = int(os.getenv('REQUESTS_PER_SECOND', '10'))
NUM_WORKERS = int(os.getenv('NUM_WORKERS', '5'))

def make_request():
    """Make a single request to the application"""
    # Select a random endpoint
    endpoints = [
        "/",
        "/api/data"
    ]
    endpoint = random.choice(endpoints)
    
    url = f"{APP_URL}{endpoint}"
    try:
        logger.info(f"Sending request to {url}")
        response = requests.get(url, timeout=5)
        logger.info(f"Response from {url}: {response.status_code}")
        return response.status_code
    except Exception as e:
        logger.error(f"Error sending request to {url}: {str(e)}")
        return 0

def worker():
    """Worker function to continuously make requests"""
    while True:
        make_request()
        # Add random sleep time around 1/REQUESTS_PER_SECOND to achieve desired RPS
        time.sleep(random.uniform(0.5, 1.5) * (1.0 / REQUESTS_PER_SECOND))

def main():
    """Main function to start the load generator"""
    logger.info(f"Starting load generator targeting {APP_URL}")
    logger.info(f"Target: {REQUESTS_PER_SECOND} requests per second with {NUM_WORKERS} workers")
    
    # Try to make a test request to the app
    try:
        requests.get(f"{APP_URL}/health", timeout=5)
        logger.info("Successfully connected to the application")
    except Exception as e:
        logger.warning(f"Could not connect to the application: {str(e)}")
        logger.info("Will keep trying to connect...")
    
    # Start worker threads
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        for _ in range(NUM_WORKERS):
            executor.submit(worker)

if __name__ == "__main__":
    main() 