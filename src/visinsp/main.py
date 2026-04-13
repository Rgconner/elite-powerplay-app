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


def setup_gpio() -> bool:
    """
    Initialize GPIO pins for button input and alarm output.
    
    Returns:
        True if GPIO setup successful, False otherwise
    """
    if not GPIO_AVAILABLE:
        print("GPIO not available - skipping GPIO setup")
        return False
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(HARDWARE_CONFIG['BUTTON_PIN'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(HARDWARE_CONFIG['ALARM_PIN'], GPIO.OUT)
        GPIO.output(HARDWARE_CONFIG['ALARM_PIN'], GPIO.LOW)
        print(f"GPIO initialized: Button={HARDWARE_CONFIG['BUTTON_PIN']}, Alarm={HARDWARE_CONFIG['ALARM_PIN']}")
        return True
    except Exception as e:
        print(f"Error setting up GPIO: {e}")
        return False


def capture_image(camera_index: int = 0) -> Optional[np.ndarray]:
    """
    Capture a grayscale image from the specified camera.
    
    Args:
        camera_index: Camera device index (default: 0)
        
    Returns:
        Grayscale image as numpy array, or None if capture fails
    """
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"Error: Could not open camera {camera_index}")
            return None
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            print("Error: Could not read frame from camera")
            return None
        
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        print(f"Image captured: {gray.shape[1]}x{gray.shape[0]} grayscale")
        return gray
    except Exception as e:
        print(f"Error capturing image: {e}")
        return None


def match_template(image: np.ndarray, template: np.ndarray, threshold: float) -> bool:
    """
    Perform template matching and check if match exceeds threshold.
    
    Args:
        image: Input grayscale image
        template: Template grayscale image to match
        threshold: Confidence threshold (0.0 to 1.0)
        
    Returns:
        True if template found with confidence >= threshold, False otherwise
    """
    try:
        if image is None or template is None:
            print("Error: Invalid image or template")
            return False
        
        # Perform template matching
        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        print(f"Template matching: max confidence = {max_val:.3f}, threshold = {threshold:.3f}")
        
        # Check if best match exceeds threshold
        if max_val >= threshold:
            print(f"✓ Template detected at position {max_loc} with confidence {max_val:.3f}")
            return True
        else:
            print(f"✗ Template NOT detected (confidence {max_val:.3f} < threshold {threshold:.3f})")
            return False
    except Exception as e:
        print(f"Error in template matching: {e}")
        return False


def trigger_alarm(message: str) -> None:
    """
    Trigger alarm by setting alarm pin and displaying message.
    Waits for spacebar press to clear alarm.
    
    Args:
        message: Alarm message to display
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Set alarm pin HIGH
    if GPIO_AVAILABLE:
        try:
            GPIO.output(HARDWARE_CONFIG['ALARM_PIN'], GPIO.HIGH)
            print(f"\n{'='*60}")
            print(f"🚨 ALARM TRIGGERED at {timestamp}")
            print(f"{'='*60}")
        except Exception as e:
            print(f"Error setting alarm pin: {e}")
    else:
        print(f"\n{'='*60}")
        print(f"⚠️  ALARM (GPIO disabled) at {timestamp}")
        print(f"{'='*60}")
    
    print(f"MESSAGE: {message}")
    print(f"{'='*60}")
    print("\nPress SPACEBAR to acknowledge and clear alarm...")
    
    # Wait for spacebar press
    while True:
        key = input().strip()
        if key == '' or key == ' ':
            break
        print("Please press SPACEBAR to continue...")
    
    # Clear alarm pin
    if GPIO_AVAILABLE:
        try:
            GPIO.output(HARDWARE_CONFIG['ALARM_PIN'], GPIO.LOW)
            print("✓ Alarm cleared")
        except Exception as e:
            print(f"Error clearing alarm pin: {e}")
    else:
        print("✓ Alarm acknowledged")
    
    print(f"{'='*60}\n")


def wait_for_button_press() -> bool:
    """
    Wait for button press on BUTTON_PIN.
    
    Returns:
        True if button pressed, False if GPIO not available
    """
    if not GPIO_AVAILABLE:
        print("GPIO not available - simulating button press")
        time.sleep(1)
        return True
    
    try:
        print(f"Waiting for button press on GPIO {HARDWARE_CONFIG['BUTTON_PIN']}...")
        GPIO.wait_for_edge(HARDWARE_CONFIG['BUTTON_PIN'], GPIO.FALLING)
        print("✓ Button pressed!")
        time.sleep(0.2)  # Debounce delay
        return True
    except Exception as e:
        print(f"Error waiting for button: {e}")
        return False


def inspection_loop(template_path: Optional[str] = None) -> None:
    """
    Main inspection loop: wait for button, capture image, match template, trigger alarm if needed.
    
    Args:
        template_path: Path to template image file. If None, uses HARDWARE_CONFIG['TEMPLATE']
    """
    # Load template image
    template = None
    if template_path:
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is not None:
            HARDWARE_CONFIG['TEMPLATE'] = template
            print(f"Template loaded: {template_path} ({template.shape[1]}x{template.shape[0]})")
        else:
            print(f"Error: Could not load template from {template_path}")
            return
    elif HARDWARE_CONFIG['TEMPLATE'] is not None:
        template = HARDWARE_CONFIG['TEMPLATE']
    else:
        print("Error: No template image specified")
        return
    
    # Setup GPIO
    gpio_ready = setup_gpio()
    
    print("\n" + "="*60)
    print("INSPECTION SYSTEM READY")
    print("="*60)
    print(f"Camera: {HARDWARE_CONFIG['CAMERA']}")
    print(f"Threshold: {HARDWARE_CONFIG['THRESHOLD']}")
    print(f"Button Pin: GPIO {HARDWARE_CONFIG['BUTTON_PIN']}")
    print(f"Alarm Pin: GPIO {HARDWARE_CONFIG['ALARM_PIN']}")
    print("="*60 + "\n")
    
    try:
        while True:
            # Wait for button press
            if not wait_for_button_press():
                break
            
            # Capture image
            print(f"\nCapturing image from camera {HARDWARE_CONFIG['CAMERA']}...")
            image = capture_image(HARDWARE_CONFIG['CAMERA'])
            
            if image is None:
                print("Failed to capture image - skipping inspection")
                continue
            
            # Perform template matching
            print("Performing template matching...")
            detected = match_template(image, template, HARDWARE_CONFIG['THRESHOLD'])
            
            # Trigger alarm if template not detected
            if not detected:
                trigger_alarm(HARDWARE_CONFIG['ALARM_MESSAGE'])
            else:
                print("✓ Inspection passed - template detected\n")
            
    except KeyboardInterrupt:
        print("\n\nInspection loop interrupted by user")
    finally:
        # Cleanup GPIO
        if gpio_ready:
            try:
                GPIO.cleanup()
                print("GPIO cleanup complete")
            except Exception as e:
                print(f"Error during GPIO cleanup: {e}")


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
