"""
Main module for VisInsp

This module contains the main functionality for the VisInsp project.
"""

import sys
from typing import Optional
import cv2
import numpy as np


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


def run() -> None:
    """
    Main entry point for the VisInsp application.
    
    This function demonstrates basic functionality and can be extended
    with your specific visual inspection logic.
    """
    print("=" * 50)
    print("VisInsp - Visual Inspection Module")
    print("=" * 50)
    print()
    
    # Get user name if provided as command line argument
    name = sys.argv[1] if len(sys.argv) > 1 else None
    
    # Display greeting
    greeting = hello_visinsp(name)
    print(greeting)
    print()
    
    # Display OpenCV version
    print(f"OpenCV version: {cv2.__version__}")
    print(f"NumPy version: {np.__version__}")
    print()
    
    # Add your visual inspection logic here
    print("Ready for visual inspection tasks!")
    print()
    print("To get started:")
    print("1. Add your inspection logic to this module")
    print("2. Import and use functions from other modules")
    print("3. Extend functionality as needed")
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
