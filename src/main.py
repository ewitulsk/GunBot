import requests
from bs4 import BeautifulSoup, Tag
import re
import toml
import schedule
import time
import sys
import os
import smtplib
from email.message import EmailMessage
import argparse
import urllib.parse

# Define a simple class to hold listing data
class Listing:
    def __init__(self, title, description, gi, price, listing_url):
        self.title = title
        self.description = description
        self.gi = gi
        self.price = price
        self.listing_url = listing_url

    def __repr__(self):
        return f"Listing(title='{self.title}', description='{self.description[:50]}...', gi='{self.gi}', price='{self.price}', listing_url='{self.listing_url}')"

# --- Configuration Loading ---
CONFIG_FILE = "config.toml"
PREVIOUS_LISTINGS_FILE = "previous_listings.txt"

try:
    config = toml.load(CONFIG_FILE)
    # Schedule Config
    schedule_config = config.get('schedule', {})
    RUN_INTERVAL_SECONDS = schedule_config.get('run_seconds', 3600)
    TARGET_COUNT = schedule_config.get('target_listings_count', 50)
    if not isinstance(RUN_INTERVAL_SECONDS, int) or RUN_INTERVAL_SECONDS <= 0:
        print(f"Error: {CONFIG_FILE} [schedule] run_seconds must be a positive integer.")
        sys.exit(1)
    if not isinstance(TARGET_COUNT, int) or TARGET_COUNT <= 0:
        print(f"Error: {CONFIG_FILE} [schedule] target_listings_count must be a positive integer.")
        sys.exit(1)

    # Search Config (New)
    search_config = config.get('search', {})
    SEARCH_KEYWORD = search_config.get('search_keyword', "smith") # Default to "smith"
    SEARCH_TYPE_CATEGORY = search_config.get('search_type_category', "Revolvers") # Default to "Revolvers"

    # URL Encode the keyword
    ENCODED_KEYWORD = urllib.parse.quote_plus(SEARCH_KEYWORD)

    # Email Config
    email_config = config.get('email', {})
    SMTP_SERVER = email_config.get('smtp_server')
    SMTP_PORT = email_config.get('smtp_port')
    USE_SSL = email_config.get('use_ssl', False)
    SENDER_EMAIL = email_config.get('sender_email')
    SENDER_PASSWORD = email_config.get('sender_password')
    RECIPIENT_EMAILS = email_config.get('recipient_emails')

    # Updated validation for Email config
    if not all([SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD]):
        print(f"Warning: Basic SMTP server/sender configuration in {CONFIG_FILE} is incomplete. Email notifications will be disabled.")
        SEND_EMAIL = False
        RECIPIENT_EMAILS = []
    elif not RECIPIENT_EMAILS or not isinstance(RECIPIENT_EMAILS, list) or not all(isinstance(email, str) and '@' in email for email in RECIPIENT_EMAILS):
        print(f"Warning: 'recipient_emails' in {CONFIG_FILE} is missing, empty, or not a valid list of email addresses. Email notifications will be disabled.")
        SEND_EMAIL = False
        RECIPIENT_EMAILS = []
    elif "your_smtp_server" in SMTP_SERVER or "your_email" in SENDER_EMAIL or "your_app_password" in SENDER_PASSWORD:
         print(f"Warning: SMTP/sender configuration in {CONFIG_FILE} seems to contain placeholders. Email notifications might fail.")
         SEND_EMAIL = True
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
# Construct Base URL dynamically
BASE_URL = f"https://www.gunsinternational.com/adv-results.cfm?the_order=6&saved_search_id=&keyword={ENCODED_KEYWORD}&exclude_term=&type_cat={SEARCH_TYPE_CATEGORY}&price_low=&price_high=&manufacturer=&screenname=&screenname_omit=&seller_sku=&area_code=&age="
ITEMS_PER_PAGE = 25

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
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
    """Sends an email notification using smtplib to each recipient."""
    if not SEND_EMAIL:
        print("Email notifications disabled due to incomplete config.")
        return
    if not RECIPIENT_EMAILS:
        print("No recipient emails configured. Skipping email notification.")
        return

    subject = f"GunSniperBot: {len(new_listings)} New Listings Found"
    body_html = "<html><body>"
    body_html += f"<h2>Found {len(new_listings)} new listings:</h2><hr>"
    body_html += "<ul>"
    for listing in new_listings:
        # Basic escaping for HTML safety
        title_esc = listing.title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        desc_esc = listing.description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        price_esc = listing.price.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        body_html += f"<li>"
        body_html += f"<b>{title_esc}</b><br>"
        body_html += f"GI#: {listing.gi}<br>"
        body_html += f"Price: {price_esc}<br>"
        body_html += f"Description: {desc_esc[:200]}...<br>"
        body_html += f"Link: <a href='{listing.listing_url}'>View Listing</a>"
        body_html += f"</li><br>"
    body_html += "</ul></body></html>"

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

        success_count = 0
        fail_count = 0
        for recipient in RECIPIENT_EMAILS:
            try:
                print(f"Sending email notification to {recipient}...")
                msg = EmailMessage()
                msg['Subject'] = subject
                msg['From'] = SENDER_EMAIL
                msg['To'] = recipient # Send to individual recipient
                msg.set_content("Please enable HTML emails to view listings.") # Fallback
                msg.add_alternative(body_html, subtype='html')

                server.send_message(msg)
                print(f"Email notification sent successfully to {recipient}.")
                success_count += 1
            except Exception as e:
                print(f"Failed to send email to {recipient}: {e}")
                fail_count += 1

        print(f"Email sending complete. Success: {success_count}, Failed: {fail_count}")

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
    """Sends a simple test email notification using smtplib to each recipient."""
    if not SEND_EMAIL:
        print("Cannot send test email: Notifications disabled due to incomplete config.")
        return False
    if not RECIPIENT_EMAILS:
        print("No recipient emails configured. Cannot send test email.")
        return False

    subject = "GunSniperBot: Test Email Notification"
    body_html = "<html><body><p>This is a test email from GunSniperBot.</p></body></html>"

    server = None
    overall_success = True
    try:
        print(f"Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        if USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()

        print("Logging into SMTP server...")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)

        success_count = 0
        fail_count = 0
        print(f"Attempting to send test emails to: {', '.join(RECIPIENT_EMAILS)}...")
        for recipient in RECIPIENT_EMAILS:
            try:
                print(f"Sending test email to {recipient}...")
                msg = EmailMessage()
                msg['Subject'] = subject
                msg['From'] = SENDER_EMAIL
                msg['To'] = recipient # Send to individual recipient
                msg.set_content("GunSniperBot: Test Email Notification.") # Fallback
                msg.add_alternative(body_html, subtype='html')

                server.send_message(msg)
                print(f"Test email sent successfully to {recipient}.")
                success_count += 1
            except Exception as e:
                print(f"Failed to send test email to {recipient}: {e}")
                fail_count += 1
                overall_success = False

        print(f"Test email sending complete. Success: {success_count}, Failed: {fail_count}")
        return overall_success

    except smtplib.SMTPAuthenticationError:
        print("Error: SMTP Authentication failed. Check sender_email and sender_password in config.")
    except smtplib.SMTPConnectError as e:
        print(f"Error: Could not connect to SMTP server {SMTP_SERVER}:{SMTP_PORT}. {e}")
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

def process_page(url, session, listings_list, processed_gi_numbers_set, page_number):
    """Fetches a page, parses it, and extracts listing data into Listing objects."""
    print(f"Processing page {page_number}: {url}")
    listings_added_on_this_page = 0
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # --- Age Verification Check (Only on first page of a job) ---
        if page_number == 1:
             age_verification_button = soup.find('button', string=re.compile(r'I am 18\+'))
             if age_verification_button:
                 print("Age verification likely present. Attempting reload within session...")
                 # Re-request within the session, hoping the cookie/state persists
                 response = session.get(url)
                 response.raise_for_status()
                 soup = BeautifulSoup(response.text, 'html.parser')
        # --- End Age Verification ---

        # Use a more specific selector for the listing containers
        listing_divs = soup.find_all('div', class_='listing_guts')
        # print(f"Found {len(listing_divs)} potential listing divs on page {page_number}.") # Optional debug print

        if not listing_divs and page_number > 1: # Check if we got an empty results page (beyond page 1)
             print(f"No listing divs found on page {page_number}. Assuming end of results.")
             return 0 # Signal that no listings were added

        for item_div in listing_divs:
            if len(listings_list) >= TARGET_COUNT:
                break # Stop processing divs if global target is met

            # --- Extract Title, URL, Description, GI, Price ---
            title = "Title not found"
            listing_url = "URL not found"
            description = "Description not found"
            gi_number = "GI# not found"
            price = "Price not found"

            # Find the main title link more reliably
            title_link_tag = item_div.find('div', class_='title_link')
            if title_link_tag:
                actual_link = title_link_tag.find('a', href=re.compile(r'guns-for-sale-online/'))
                if actual_link:
                    title = actual_link.get_text(strip=True)
                    href = actual_link.get('href')
                    if href:
                        # Ensure the URL is absolute
                        listing_url = urllib.parse.urljoin("https://www.gunsinternational.com/", href)

            # Find the description container reliably
            # The description is typically in a div following the image and title divs
            desc_container = item_div.find('div', class_='col-md-12') # This might need adjustment if structure varies
            if desc_container:
                # Attempt to extract text before the "...Click for more info" link
                desc_parts = []
                more_info_link_found = False
                for content in desc_container.contents:
                    if isinstance(content, str):
                        cleaned_content = content.strip()
                        if cleaned_content:
                             desc_parts.append(cleaned_content)
                    elif isinstance(content, Tag) and content.name == 'a' and '...Click for more info' in content.get_text(strip=True):
                        more_info_link_found = True
                        break # Stop collecting text once the link is found
                    elif isinstance(content, Tag):
                        # Include text from other tags like <b>, <i> etc if needed
                        # For now, we only take direct text nodes before the link
                        pass

                if desc_parts:
                     description = ' '.join(desc_parts)
                elif not more_info_link_found and desc_container.get_text(strip=True):
                     # Fallback: If no link found, take all text, but this might include seller info
                     # Let's try a more targeted approach for the text node directly inside col-md-12
                     direct_text = ''.join(desc_container.find_all(string=True, recursive=False)).strip()
                     if direct_text:
                         description = direct_text
                     else:
                         # Last resort: grab all text and remove the link text if possible
                         all_text = desc_container.get_text(separator=' ', strip=True)
                         click_link_text = item_div.find('a', string=re.compile(r'\.\.\.Click for more info'))
                         if click_link_text:
                             description = all_text.replace(click_link_text.get_text(strip=True), '').strip()
                         else:
                             description = all_text # Might still contain seller info

            # --- Extract GI (Use existing logic, but scope it to item_div) ---
            div_text_gi = item_div.get_text()
            gi_match = re.search(r'GI#:\s*(\d+)', div_text_gi)
            if gi_match:
                gi_number = gi_match.group(1)

            # --- Extract Price (Use existing logic, but scope it to item_div) ---
            div_text_price = item_div.get_text(separator=' ')
            price_match = re.search(r'\$\s*([\d,]+\.?\d*)', div_text_price)
            if price_match:
                price = f"${price_match.group(1)}"

            # --- Validate and Store ---
            # Validate based on finding GI number and a valid URL
            if gi_number != "GI# not found" and listing_url != "URL not found" and not listing_url.endswith("gunsinternational.com/"):
                 if gi_number not in processed_gi_numbers_set:
                     # Create Listing object with title and description
                     listing_obj = Listing(
                         title=title,
                         description=description,
                         gi=gi_number,
                         price=price,
                         listing_url=listing_url
                     )
                     listings_list.append(listing_obj)
                     processed_gi_numbers_set.add(gi_number)
                     listings_added_on_this_page += 1

            # Inner loop break if target met
            if len(listings_list) >= TARGET_COUNT:
                print(f"Reached target count of {TARGET_COUNT} during page {page_number}.")
                break

    except requests.exceptions.RequestException as e:
        print(f"Error fetching or processing {url}: {e}")
        return 0 # Indicate failure/no listings added
    except Exception as e:
        print(f"An unexpected error occurred while processing {url}: {e}")
        return 0 # Indicate failure/no listings added

    return listings_added_on_this_page

def run_scrape_job():
    """Main function to perform one round of scraping, comparing, and notifying."""
    print(f"\n--- Running scrape job at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    print(f"Targeting {TARGET_COUNT} listings.")

    previous_gi_numbers = load_previous_listings(PREVIOUS_LISTINGS_FILE)
    print(f"Loaded {len(previous_gi_numbers)} listings from previous run.")

    current_listings = []
    current_gi_numbers = set()
    page_number = 1

    # Loop through pages until target is met or no new listings are found
    while len(current_listings) < TARGET_COUNT:
        start_row = (page_number - 1) * ITEMS_PER_PAGE + 1
        current_page_url = f"{BASE_URL}&start_row={start_row}"

        listings_added = process_page(
            current_page_url, 
            session, 
            current_listings, 
            current_gi_numbers, 
            page_number # Pass page number for age check logic
        )

        # If a page adds no new listings (or errors out), stop pagination
        if listings_added == 0 and page_number > 1: # Check page_number > 1 to allow first page errors/empty results
            print(f"No new listings added from page {page_number}. Stopping pagination.")
            break
        
        page_number += 1

        # Optional safety break to prevent excessive page requests
        if page_number > (TARGET_COUNT // ITEMS_PER_PAGE) + 5: # e.g., Target 100 -> max ~9 pages
            print(f"Warning: Reached page limit ({page_number-1}). Stopping pagination.")
            break

    print("\n--- Scrape Results ---")
    print(f"Scraping finished. Found {len(current_listings)} unique listings in current run.")

    # --- Comparison and Notification (Logic remains the same) ---
    new_gi_numbers = current_gi_numbers - previous_gi_numbers
    if new_gi_numbers:
        print(f"Found {len(new_gi_numbers)} new listings since last run.")
        new_listings_details = [lst for lst in current_listings if lst.gi in new_gi_numbers]
        print("--- New Listings Details ---")
        for listing in new_listings_details:
             print(f"  Title: {listing.title}")
             print(f"     GI#: {listing.gi}")
             print(f"     Price: {listing.price}")
             print(f"     Desc: {listing.description[:100]}...")
             print(f"     URL: {listing.listing_url}")
             print()
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
    print(f"Notifications will be sent from {SENDER_EMAIL} to: {', '.join(RECIPIENT_EMAILS)}")
print(f"Persistence file: {PREVIOUS_LISTINGS_FILE}")
print(f"First run will be at approximately {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + RUN_INTERVAL_SECONDS))}")

# Run the job once immediately at startup
run_scrape_job()

# Keep the script running
while True:
    schedule.run_pending()
    time.sleep(1)
