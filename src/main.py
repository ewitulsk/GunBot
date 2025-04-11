import requests
from bs4 import BeautifulSoup
import re
import toml
import schedule
import time
import sys
import os
import smtplib
from email.message import EmailMessage
import argparse

# Define a simple class to hold listing data
class Listing:
    def __init__(self, name, gi, price):
        self.name = name
        self.gi = gi
        self.price = price

    def __repr__(self):
        return f"Listing(name='{self.name}', gi='{self.gi}', price='{self.price}')"

# --- Configuration Loading ---
CONFIG_FILE = "config.toml"
PREVIOUS_LISTINGS_FILE = "previous_listings.txt"

try:
    config = toml.load(CONFIG_FILE)
    # Schedule Config
    RUN_INTERVAL_SECONDS = config.get('schedule', {}).get('run_seconds', 3600)
    if not isinstance(RUN_INTERVAL_SECONDS, int) or RUN_INTERVAL_SECONDS <= 0:
        print(f"Error: {CONFIG_FILE} [schedule] run_seconds must be a positive integer.")
        sys.exit(1)

    # Email Config
    email_config = config.get('email', {})
    SMTP_SERVER = email_config.get('smtp_server')
    SMTP_PORT = email_config.get('smtp_port')
    USE_SSL = email_config.get('use_ssl', False)
    SENDER_EMAIL = email_config.get('sender_email')
    SENDER_PASSWORD = email_config.get('sender_password')
    RECIPIENT_EMAIL = email_config.get('recipient_email')

    # Basic validation for Email config
    if not all([SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL]):
        print(f"Warning: Email configuration in {CONFIG_FILE} is incomplete. Email notifications will be disabled.")
        SEND_EMAIL = False
    elif "your_smtp_server" in SMTP_SERVER or "your_email" in SENDER_EMAIL or "your_app_password" in SENDER_PASSWORD:
        print(f"Warning: Email configuration in {CONFIG_FILE} seems to contain placeholders. Email notifications might fail.")
        SEND_EMAIL = True # Attempt anyway
    else:
        SEND_EMAIL = True

except FileNotFoundError:
    print(f"Error: {CONFIG_FILE} not found. Please create it.")
    sys.exit(1)
except toml.TomlDecodeError as e:
    print(f"Error parsing {CONFIG_FILE}: {e}")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred loading config: {e}")
    sys.exit(1)

# --- Constants and Session ---
URL_PAGE_1 = "https://www.gunsinternational.com/adv-results.cfm?the_order=6&saved_search_id=&keyword=smith&exclude_term=&type_cat=Revolvers&price_low=&price_high=&manufacturer=&screenname=&screenname_omit=&seller_sku=&area_code=&age=&start_row=1"
URL_PAGE_2 = "https://www.gunsinternational.com/adv-results.cfm?the_order=6&saved_search_id=&keyword=smith&exclude_term=&type_cat=Revolvers&price_low=&price_high=&manufacturer=&screenname=&screenname_omit=&seller_sku=&area_code=&age=&start_row=26"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
TARGET_COUNT = 50
session = requests.Session()
session.headers.update(HEADERS)

# --- Helper Functions ---
def load_previous_listings(filename):
    """Loads the set of GI numbers from the previous run."""
    if not os.path.exists(filename):
        return set()
    try:
        with open(filename, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    except IOError as e:
        print(f"Warning: Could not read previous listings file {filename}: {e}. Starting fresh.")
        return set()

def save_current_listings(filename, gi_numbers_set):
    """Saves the current set of GI numbers for the next run."""
    try:
        with open(filename, 'w') as f:
            for gi_number in gi_numbers_set:
                f.write(f"{gi_number}\n")
    except IOError as e:
        print(f"Warning: Could not write listings file {filename}: {e}")

def send_email_notification(new_listings):
    """Sends an email notification using smtplib."""
    if not SEND_EMAIL:
        print("Email notifications disabled due to incomplete config.")
        return

    subject = f"GunSniperBot: {len(new_listings)} New Listings Found"
    body_html = "<html><body>"
    body_html += f"<h2>Found {len(new_listings)} new listings:</h2><hr>"
    body_html += "<ul>"
    for listing in new_listings:
        # Basic escaping for HTML safety
        name_esc = listing.name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        price_esc = listing.price.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        body_html += f"<li><b>{name_esc}</b><br>GI#: {listing.gi}<br>Price: {price_esc}</li><br>"
    body_html += "</ul></body></html>"

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg.set_content("Please enable HTML emails to view listings.") # Fallback for non-HTML clients
    msg.add_alternative(body_html, subtype='html')

    server = None # Initialize server variable
    try:
        print(f"Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        if USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls() # Upgrade connection to secure

        print("Logging into SMTP server...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        print("Sending email notification...")
        server.send_message(msg)
        print("Email notification sent successfully.")

    except smtplib.SMTPAuthenticationError:
        print("Error: SMTP Authentication failed. Check sender_email and sender_password in config.")
    except smtplib.SMTPConnectError as e:
        print(f"Error: Could not connect to SMTP server {SMTP_SERVER}:{SMTP_PORT}. {e}")
    except smtplib.SMTPServerDisconnected:
        print("Error: SMTP server disconnected unexpectedly.")
    except Exception as e:
        print(f"An unexpected error occurred during email sending: {e}")
    finally:
        if server:
            try:
                server.quit()
                print("SMTP connection closed.")
            except Exception:
                pass # Ignore errors during quit

def send_test_email():
    """Sends a simple test email notification using smtplib."""
    if not SEND_EMAIL:
        print("Cannot send test email: Notifications disabled due to incomplete config.")
        return False

    subject = "GunSniperBot: Test Email Notification"
    body_html = "<html><body><p>This is a test email from GunSniperBot.</p></body></html>"

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECIPIENT_EMAIL
    msg.set_content("GunSniperBot: Test Email Notification.") # Fallback
    msg.add_alternative(body_html, subtype='html')

    server = None
    try:
        print(f"Attempting to send test email to {RECIPIENT_EMAIL}...")
        print(f"Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        if USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()

        print("Logging into SMTP server...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        print("Sending test email...")
        server.send_message(msg)
        print("Test email sent successfully.")
        return True

    except smtplib.SMTPAuthenticationError:
        print("Error: SMTP Authentication failed. Check sender_email and sender_password in config.")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"Error: Could not connect to SMTP server {SMTP_SERVER}:{SMTP_PORT}. {e}")
        return False
    except smtplib.SMTPServerDisconnected:
         print("Error: SMTP server disconnected unexpectedly.")
         return False
    except Exception as e:
        print(f"An unexpected error occurred during test email sending: {e}")
        return False
    finally:
        if server:
            try:
                server.quit()
                print("SMTP connection closed.")
            except Exception:
                 pass

def process_page(url, session, listings_list, processed_gi_numbers_set):
    """Fetches a page, parses it, and extracts listing data into Listing objects."""
    print(f"Processing page: {url}")
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # --- Age Verification Check ---
        if url == URL_PAGE_1:
             age_verification_button = soup.find('button', string=re.compile(r'I am 18\+'))
             if age_verification_button:
                 print("Age verification likely present. Attempting reload within session...")
                 response = session.get(url)
                 response.raise_for_status()
                 soup = BeautifulSoup(response.text, 'html.parser')
        # --- End Age Verification ---

        listing_divs = soup.find_all(lambda tag: tag.name == 'div' and 'GI#:' in tag.get_text())
        print(f"Found {len(listing_divs)} potential listing divs.")

        for item_div in listing_divs:
            if len(listings_list) >= TARGET_COUNT:
                break

            # --- Extract Name ---
            name_tag = item_div.find('a', href=re.compile(r'guns-for-sale-online/'))
            name = "Name not found"
            if name_tag:
                strong_tag = name_tag.find('strong')
                if strong_tag and strong_tag.get_text(strip=True):
                    name = strong_tag.get_text(strip=True)
                else:
                    link_text = name_tag.get_text(strip=True)
                    if link_text:
                        name = link_text

            # --- Extract GI Number ---
            gi_number = "GI# not found"
            div_text_gi = item_div.get_text()
            gi_match = re.search(r'GI#:\s*(\d+)', div_text_gi)
            if gi_match:
                gi_number = gi_match.group(1)

            # --- Extract Price ---
            price = "Price not found"
            div_text_price = item_div.get_text(separator=' ')
            price_match = re.search(r'\$\s*([\d,]+\.?\d*)', div_text_price)
            if price_match:
                price = f"${price_match.group(1)}"

            # --- Validate and Store ---
            if name != "Name not found" and gi_number != "GI# not found":
                 if gi_number not in processed_gi_numbers_set:
                     listing_obj = Listing(name=name, gi=gi_number, price=price)
                     listings_list.append(listing_obj)
                     processed_gi_numbers_set.add(gi_number)

            if len(listings_list) >= TARGET_COUNT:
                print(f"Reached target count of {TARGET_COUNT}.")
                break

    except requests.exceptions.RequestException as e:
        print(f"Error fetching or processing {url}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while processing {url}: {e}")

def run_scrape_job():
    """Main function to perform one round of scraping, comparing, and notifying."""
    print(f"\n--- Running scrape job at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")

    previous_gi_numbers = load_previous_listings(PREVIOUS_LISTINGS_FILE)
    print(f"Loaded {len(previous_gi_numbers)} listings from previous run.")

    current_listings = []
    current_gi_numbers = set()

    process_page(URL_PAGE_1, session, current_listings, current_gi_numbers)
    if len(current_listings) < TARGET_COUNT:
        process_page(URL_PAGE_2, session, current_listings, current_gi_numbers)

    print("\n--- Scrape Results ---")
    print(f"Found {len(current_listings)} unique listings in current run.")

    new_gi_numbers = current_gi_numbers - previous_gi_numbers
    if new_gi_numbers:
        print(f"Found {len(new_gi_numbers)} new listings since last run.")
        new_listings_details = [lst for lst in current_listings if lst.gi in new_gi_numbers]
        print("--- New Listings Details ---")
        for listing in new_listings_details:
             print(f"  Name: {listing.name}\n     GI#: {listing.gi}\n     Price: {listing.price}")
             print()
        # Call the email notification function
        send_email_notification(new_listings_details)
    else:
        print("No new listings found since last run.")

    save_current_listings(PREVIOUS_LISTINGS_FILE, current_gi_numbers)
    print(f"--- Scrape job finished at {time.strftime('%Y-%m-%d %H:%M:%S')} --- \n")

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description='GunSniperBot: Scrape listings and send notifications.')
parser.add_argument(
    '--test-email', 
    action='store_true', 
    help='Send a test email notification to the configured recipient and exit.'
)
args = parser.parse_args()

# --- Handle Test Email Flag ---
if args.test_email:
    print("\n--- Test Email Mode ---")
    if SEND_EMAIL:
        send_test_email()
    else:
        print("Email notifications are disabled in config.toml. Cannot send test.")
    print("Exiting after test email attempt.")
    sys.exit(0) # Exit after handling the test flag

# --- Scheduling Setup ---
schedule.every(RUN_INTERVAL_SECONDS).seconds.do(run_scrape_job)

print(f"Script started. Scheduling job to run every {RUN_INTERVAL_SECONDS} seconds.")
print(f"Notifications configured: SEND_EMAIL={SEND_EMAIL}")
if SEND_EMAIL:
    print(f"Notifications will be sent from {SENDER_EMAIL} to {RECIPIENT_EMAIL}")
print(f"Persistence file: {PREVIOUS_LISTINGS_FILE}")
print(f"First run will be at approximately {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + RUN_INTERVAL_SECONDS))}")

# Run the job once immediately at startup
run_scrape_job()

# Keep the script running
while True:
    schedule.run_pending()
    time.sleep(1)
