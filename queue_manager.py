import os
import redis
from rq import Queue, Worker
import logging
from dotenv import load_dotenv
import asyncio
from threading import Thread
import signal
import sys
from typing import Optional
import inspect

load_dotenv()

logger = logging.getLogger(__name__)

class QueueManager:
    def __init__(self):
        # Read Redis configuration from environment variables
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD")
        self.redis_ssl = os.getenv("REDIS_SSL", "False").lower() == "true"
        
        self.redis_conn = None
        self.queue = None
        self.worker = None
        self.worker_thread = None
        self.should_stop = False
        
    def connect(self):
        """Connect to Redis"""
        try:
            # Connect to Redis with configuration from env
            redis_config = {
                "host": self.redis_host,
                "port": self.redis_port,
                "decode_responses": True,
                "socket_connect_timeout": 30,
                "socket_timeout": 30,
                "retry_on_timeout": True,
                "health_check_interval": 30
            }
            
            # Add password if provided
            if self.redis_password:
                redis_config["password"] = self.redis_password
            
            # Add SSL configuration if enabled
            if self.redis_ssl:
                redis_config.update({
                    "ssl": True,
                    "ssl_cert_reqs": None
                })
            
            self.redis_conn = redis.Redis(**redis_config)
            
            # Test the connection
            self.redis_conn.ping()
            
            self.queue = Queue('scraping_tasks', connection=self.redis_conn)
            logger.info(f"Connected to Redis at {self.redis_host}:{self.redis_port} successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False
    
    def start_worker(self):
        """Start RQ worker in background thread"""
        if not self.redis_conn:
            if not self.connect():
                return False
        
        def run_worker():
            try:
                self.worker = Worker(['scraping_tasks'], connection=self.redis_conn)
                logger.info("Starting RQ worker...")
                
                # Check if the work method supports install_signal_handlers parameter
                work_signature = inspect.signature(self.worker.work)
                
                if 'install_signal_handlers' in work_signature.parameters:
                    # Newer versions of RQ
                    self.worker.work(install_signal_handlers=False)
                else:
                    # Older versions of RQ - temporarily override signal handlers
                    original_handlers = {}
                    try:
                        # Save original signal handlers
                        for sig in [signal.SIGINT, signal.SIGTERM]:
                            try:
                                original_handlers[sig] = signal.signal(sig, signal.SIG_IGN)
                            except (OSError, ValueError):
                                # Signal handling might not be available in thread
                                pass
                        
                        # Start worker
                        self.worker.work()
                        
                    finally:
                        # Restore original signal handlers
                        for sig, handler in original_handlers.items():
                            try:
                                signal.signal(sig, handler)
                            except (OSError, ValueError):
                                pass
                                
            except Exception as e:
                logger.error(f"Worker error: {e}")
        
        self.worker_thread = Thread(target=run_worker, daemon=True)
        self.worker_thread.start()
        logger.info("RQ worker started in background")
        return True
    
    def enqueue_job(self, func, *args, **kwargs):
        """Enqueue a job"""
        if not self.queue:
            if not self.connect():
                raise Exception("Failed to connect to Redis")
        
        job = self.queue.enqueue(func, *args, **kwargs, job_timeout='30m')
        return job.id
    
    def get_job_status(self, job_id):
        """Get job status"""
        if not self.redis_conn:
            return None
        
        try:
            job = self.queue.fetch_job(job_id)
            if job:
                return {
                    'id': job.id,
                    'status': job.get_status(),
                    'result': job.result,
                    'exc_info': job.exc_info
                }
        except Exception as e:
            logger.error(f"Error fetching job status: {e}")
        return None
    
    def shutdown(self):
        """Shutdown worker and connections"""
        try:
            self.should_stop = True
            if self.worker:
                # Send shutdown signal to worker
                try:
                    self.worker.request_stop()
                except AttributeError:
                    # Older versions might not have request_stop
                    logger.info("Worker stop requested (method not available)")
                    
            if self.worker_thread and self.worker_thread.is_alive():
                logger.info("Waiting for worker thread to finish...")
                # Don't wait indefinitely
                
            if self.redis_conn:
                self.redis_conn.close()
            logger.info("Queue manager shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

# Global queue manager instance
queue_manager = QueueManager()

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown - ONLY in main thread"""
    def signal_handler(signum, frame):
        logger.info("Received shutdown signal, stopping worker...")
        queue_manager.shutdown()
        sys.exit(0)
    
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        logger.info("Signal handlers registered successfully")
    except ValueError as e:
        logger.warning(f"Could not register signal handlers: {e}")