import requests
from bs4 import BeautifulSoup
import re

# URLs for the first two pages
URL_PAGE_1 = "https://www.gunsinternational.com/adv-results.cfm?the_order=6&saved_search_id=&keyword=smith&exclude_term=&type_cat=Revolvers&price_low=&price_high=&manufacturer=&screenname=&screenname_omit=&seller_sku=&area_code=&age=&start_row=1"
URL_PAGE_2 = "https://www.gunsinternational.com/adv-results.cfm?the_order=6&saved_search_id=&keyword=smith&exclude_term=&type_cat=Revolvers&price_low=&price_high=&manufacturer=&screenname=&screenname_omit=&seller_sku=&area_code=&age=&start_row=26" # Assuming 25 items per page

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# We might need to handle the age verification. Let's start without it and add if necessary.
# Using a session object to persist cookies, which might help with the age verification.
session = requests.Session()
session.headers.update(HEADERS)

listings = []
processed_gi_numbers = set()
TARGET_COUNT = 50

def process_page(url, session, listings, processed_gi_numbers):
    """Fetches a page, parses it, and extracts listing data."""
    global TARGET_COUNT
    print(f"Processing page: {url}")
    try:
        response = session.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # --- Age Verification Check (Simplified - may need adjustment) ---
        if url == URL_PAGE_1:
             age_verification_button = soup.find('button', string=re.compile(r'I am 18\+'))
             if age_verification_button:
                 print("Age verification likely present. Attempting reload within session...")
                 response = session.get(url) # Re-request within session
                 response.raise_for_status()
                 soup = BeautifulSoup(response.text, 'html.parser')
        # --- End Age Verification ---

        # Find listing containers: Look for divs containing the text "GI#:"
        # This seems more robust than assuming specific classes or table structures.
        listing_divs = soup.find_all(lambda tag: tag.name == 'div' and 'GI#:' in tag.get_text())

        print(f"Found {len(listing_divs)} potential listing divs.")

        for item_div in listing_divs:
            if len(listings) >= TARGET_COUNT:
                break

            # --- Extract Name ---
            # Look for the link, then prioritize the strong tag inside it.
            name_tag = item_div.find('a', href=re.compile(r'guns-for-sale-online/'))
            name = "Name not found"
            if name_tag:
                strong_tag = name_tag.find('strong')
                if strong_tag and strong_tag.get_text(strip=True):
                    name = strong_tag.get_text(strip=True)
                else:
                    # Fallback to the whole link text if no strong tag or it's empty
                    link_text = name_tag.get_text(strip=True)
                    if link_text: # Use link text only if it's not empty
                         name = link_text
                    # If both strong and link text are empty/missing, keep "Name not found"

            # --- Extract GI Number ---
            gi_number = "GI# not found"
            # Search for the GI number pattern within the div's text content
            div_text = item_div.get_text()
            match = re.search(r'GI#:\s*(\d+)', div_text)
            if match:
                gi_number = match.group(1)

            # --- Validate and Store ---
            if name != "Name not found" and gi_number != "GI# not found":
                 if gi_number not in processed_gi_numbers:
                     listings.append({'name': name, 'gi_number': gi_number})
                     processed_gi_numbers.add(gi_number)
                     # print(f"Added: {name} (GI#: {gi_number})") # Optional: print progress
                 # else:
                     # print(f"Skipping duplicate GI#: {gi_number}") # Optional: print skips

            if len(listings) >= TARGET_COUNT:
                print(f"Reached target count of {TARGET_COUNT}.")
                break # Stop processing divs if we have enough

    except requests.exceptions.RequestException as e:
        print(f"Error fetching or processing {url}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while processing {url}: {e}")


# Process Page 1
process_page(URL_PAGE_1, session, listings, processed_gi_numbers)

# Process Page 2 if we still need more listings
if len(listings) < TARGET_COUNT:
    process_page(URL_PAGE_2, session, listings, processed_gi_numbers)


print("\n--- Final Results ---")
print(f"Found {len(listings)} unique listings:")
for i, listing in enumerate(listings):
    print(f"  {i+1}. Name: {listing['name']}, GI#: {listing['gi_number']}")
    print() # Add a blank line after each listing

# Note: Selectors and logic refined based on previous outputs.
# Further adjustments might be needed depending on subtle variations in HTML structure.
