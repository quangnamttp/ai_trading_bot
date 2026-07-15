"""
Core module - Configuration, database, and main application
"""
from .config import *
from .database import db
from .signal_tracker import signal_tracker
from .statistics import statistics_manager
from .health_check import health_checker
from .reporting import reporting_manager
