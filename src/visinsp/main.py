"""
Main module for VisInsp

This module contains the main functionality for the VisInsp project.
"""

import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any
import cv2
import numpy as np
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not available. GPIO functionality will be disabled.")

from .config import load_config, Config


# Hardware configuration array
HARDWARE_CONFIG: Dict[str, Any] = {
    'BUTTON_PIN': 17,      # GPIO pin for button input
    'ALARM_PIN': 27,       # GPIO pin for alarm output
    'ALARM_MESSAGE': 'Inspection Alert: Threshold exceeded!',
    'THRESHOLD': 0.85,     # Detection confidence threshold
    'TEMPLATE': None,      # Template image for matching (loaded at runtime)
    'CAMERA': 0,           # Camera device index (0 for default camera)
}


def hello_visinsp(name: Optional[str] = None) -> str:
    """
    Generate a greeting message.
    
    Args:
        name: Optional name to include in the greeting
        
    Returns:
        A greeting string
    """
    if name:
        return f"Hello from VisInsp, {name}!"
    return "Hello from VisInsp!"


def run(config: Optional[Config] = None) -> None:
    """
    Main entry point for the VisInsp application.
    
    Args:
        config: Optional Config object. If None, will attempt to load from default location.
    
    This function demonstrates basic functionality and can be extended
    with your specific visual inspection logic.
    """
    # Load configuration
    if config is None:
        try:
            config = load_config()
        except FileNotFoundError:
            print("Warning: No configuration file found. Using defaults.")
            config = Config()
    
    print("=" * 50)
    app_name = config.get('app.name', 'VisInsp')
    print(f"{app_name} - Visual Inspection Module")
    print("=" * 50)
    print()
    
    # Get user name if provided as command line argument
    name = sys.argv[1] if len(sys.argv) > 1 else None
    
    # Display greeting
    greeting = hello_visinsp(name)
    print(greeting)
    print()
    
    # Display version information
    print(f"App version: {config.get('app.version', 'unknown')}")
    print(f"OpenCV version: {cv2.__version__}")
    print(f"NumPy version: {np.__version__}")
    print()
    
    # Display configuration info
    print("Configuration:")
    print(f"  Debug mode: {config.get('app.debug', False)}")
    print(f"  Image path: {config.get('inspection.image_path', 'images/')}")
    print(f"  Output path: {config.get('inspection.output_path', 'output/')}")
    print()
    
    # Add your visual inspection logic here
    print("Ready for visual inspection tasks!")
    print()
    print("To get started:")
    print("1. Add your inspection logic to this module")
    print("2. Modify config.json to customize settings")
    print("3. Use config.get() to access configuration values")
    print()
    print("=" * 50)


def main() -> int:
    """
    Main function that can be called from command line.
    
    Returns:
        Exit code (0 for success)
    """
    try:
        run()
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
