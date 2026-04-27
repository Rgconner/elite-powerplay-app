#!/usr/bin/env python3
"""
Simple email sender script using Gmail SMTP
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import getpass

def send_email(to_email, subject, body, from_email=None, password=None):
    """
    Send an email using Gmail SMTP server
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body text
        from_email: Sender email (will prompt if not provided)
        password: App password (will prompt if not provided)
    """
    # Get credentials if not provided
    if from_email is None:
        from_email = input("Enter your Gmail address: ")
    
    if password is None:
        password = getpass.getpass("Enter your Gmail App Password: ")
    
    # Create message
    message = MIMEMultipart()
    message['From'] = from_email
    message['To'] = to_email
    message['Subject'] = subject
    
    # Add body to email
    message.attach(MIMEText(body, 'plain'))
    
    try:
        # Create SMTP session
        print(f"Connecting to Gmail SMTP server...")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Enable security
        
        # Login
        print(f"Logging in as {from_email}...")
        server.login(from_email, password)
        
        # Send email
        print(f"Sending email to {to_email}...")
        text = message.as_string()
        server.sendmail(from_email, to_email, text)
        
        print("✓ Email sent successfully!")
        
        # Close connection
        server.quit()
        return True
        
    except Exception as e:
        print(f"✗ Failed to send email: {str(e)}")
        return False

if __name__ == "__main__":
    # Email details
    recipient = "dom.tovani@Ibm.com"
    subject = "See, Bob can send you an email."
    body = """Hello,

This email was sent by Bob to demonstrate email sending capability.

Best regards,
Bob"""
    
    print("=" * 60)
    print("Bob's Email Sender")
    print("=" * 60)
    print(f"\nRecipient: {recipient}")
    print(f"Subject: {subject}")
    print("\nNote: You'll need a Gmail account and an App Password.")
    print("To create an App Password:")
    print("1. Go to your Google Account settings")
    print("2. Security > 2-Step Verification > App passwords")
    print("3. Generate a new app password for 'Mail'")
    print("=" * 60)
    print()
    
    send_email(recipient, subject, body)

# Made with Bob
